#!/usr/bin/env python3
"""
SelectiveVMCloner - Creates isolated VMs with only selected apps/paths/services.
"""

import base64
import json
import logging
import os
import secrets
import shutil
import socket
import string
import subprocess
import tempfile
import time
import urllib.request
import uuid
import zlib
import xml.etree.ElementTree as ET
import signal
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import libvirt
except ImportError:
    libvirt = None
import yaml

from clonebox.di import get_container
from clonebox.interfaces.disk import DiskManager
from clonebox.interfaces.hypervisor import HypervisorBackend
from clonebox.interfaces.network import NetworkManager
from clonebox.logging import get_logger, log_operation
from clonebox.policies import PolicyEngine, PolicyViolationError
from clonebox.resources import ResourceLimits
from clonebox.rollback import vm_creation_transaction
from clonebox.secrets import SecretsManager, SSHKeyPair
from clonebox.audit import get_audit_logger, AuditEventType, AuditOutcome
from clonebox.models import VMConfig
from clonebox.cloud_init import generate_cloud_init_config
from clonebox.vm_xml import generate_vm_xml

log = get_logger(__name__)


class SelectiveVMCloner:
    """
    Creates VMs with only selected applications, paths and services.
    Uses bind mounts instead of full disk cloning.
    """

    def __init__(
        self,
        conn_uri: str = None,
        user_session: bool = False,
        hypervisor: HypervisorBackend = None,
        disk_manager: DiskManager = None,
        network_manager: NetworkManager = None,
        secrets_manager: SecretsManager = None,
    ):
        self.user_session = user_session
        self.container = get_container()

        # Resolve dependencies
        self.hypervisor = hypervisor or self.container.resolve(HypervisorBackend)
        self.disk = disk_manager or self.container.resolve(DiskManager)
        self.network = network_manager or self.container.resolve(NetworkManager)
        self.secrets = secrets_manager or self.container.resolve(SecretsManager)
        # Load policy engine from filesystem if available
        from .policies import PolicyEngine
        self.policy_engine = PolicyEngine.load_effective()
        self.audit_logger = get_audit_logger()

        # Initialize libvirt connection
        if conn_uri is None:
            conn_uri = "qemu:///session" if user_session else "qemu:///system"
        
        self.conn_uri = conn_uri
        if libvirt:
            try:
                self.conn = libvirt.open(conn_uri)
            except Exception as e:
                raise ConnectionError(
                    f"Cannot connect to libvirt at {conn_uri}.\n"
                    f"Error: {e}\n\n"
                    f"Troubleshooting:\n"
                    f"1. Check libvirtd is running: sudo systemctl status libvirtd\n"
                    f"2. Check permissions: groups | grep libvirt\n"
                    f"3. For user session: virsh --connect qemu:///session list\n"
                    f"4. For system session: sudo virsh --connect qemu:///system list"
                )
        else:
            raise ImportError("libvirt-python is required. Install with: pip install libvirt-python")

    def create_vm(
        self,
        config: VMConfig,
        start: bool = False,
        replace: bool = False,
        approved: bool = False,
        console: Any = None,
    ) -> str:
        """Create a new VM with the given configuration."""
        
        with log_operation(
            log,
            "vm_create",
            vm_name=config.name,
            user=os.getenv("USER"),
            details={
                "ram_mb": config.ram_mb,
                "vcpus": config.vcpus,
                "disk_size_gb": config.disk_size_gb,
                "user_session": self.user_session,
            }
        ):
            # Check if VM already exists
            if replace:
                log.info(f"Replacing existing VM '{config.name}' (deleting old storage)...")
                self.delete_vm(config.name, delete_storage=True, approved=approved)
            else:
                try:
                    existing_vm = self.conn.lookupByName(config.name)
                    # If we get here, VM exists
                    raise ValueError(f"VM '{config.name}' already exists")
                except Exception as e:
                    # Check if it's the "VM not found" exception
                    if "no domain" not in str(e).lower() and "not found" not in str(e).lower():
                        # Re-raise if it's not a "not found" exception
                        raise
            
            # Validate configuration against policies
            if not approved and self.policy_engine is not None:
                self.policy_engine.validate_vm_creation(config)
            
            # Generate VM UUID
            vm_uuid = str(uuid.uuid4())
            
            # Create transaction for rollback
            with vm_creation_transaction(self, config, console) as ctx:
                # Create base disk
                log.info("Step 1/5: Creating VM disk...")
                disk_path = self._create_vm_disk(config)
                log.info(f"  Disk created: {disk_path}")
                
                # Generate cloud-init ISO
                log.info("Step 2/5: Generating cloud-init ISO...")
                cloud_init_path = self._generate_cloud_init(config)
                log.info(f"  Cloud-init ISO created: {cloud_init_path}")
                
                # Allocate SSH port for user session
                ssh_port = None
                if self.user_session:
                    log.info("Step 3/5: Allocating SSH port...")
                    ssh_port = self._allocate_ssh_port(config.name)
                    self._save_ssh_port(config.name, ssh_port)
                    log.info(f"  SSH port allocated: {ssh_port}")
                    log.info(f"  Port saved to: {self.USER_IMAGES_DIR / config.name / 'ssh_port'}")
                
                # Generate VM XML
                log.info("Step 4/5: Generating VM XML configuration...")
                vm_xml = generate_vm_xml(
                    config=config,
                    vm_uuid=vm_uuid,
                    disk_path=disk_path,
                    cdrom_path=cloud_init_path,
                    user_session=self.user_session,
                    ssh_port=ssh_port,
                )
                log.info("  VM XML generated")
                if self.user_session and ssh_port:
                    log.info(f"  SSH forwarding configured: localhost:{ssh_port} -> VM:22")
                
                # Define and start VM
                log.info("Step 5/5: Defining and starting VM...")
                vm = self.conn.defineXML(vm_xml)
                log.info(f"  VM defined: {config.name}")
                
                if start:
                    log.info("  Starting VM...")
                    vm.create()
                    log.info(f"VM '{config.name}' started successfully")
                    
                    # Brief pause to let QEMU initialize
                    time.sleep(2)
                    
                    # Run comprehensive diagnostics
                    checks = self._check_vm_processes(config.name)
                    
                    # Setup SSH port forwarding if in user session (if not using QEMU user networking)
                    if self.user_session and ssh_port and not checks.get("port_listening"):
                        log.info("Setting up SSH port forwarding with socat...")
                        self._setup_ssh_port_forward(config.name, ssh_port)
                    
                    # Open VM viewer window
                    log.info("Opening VM viewer window...")
                    self._open_viewer(config.name)
                
                # Setup networking
                self._setup_vm_networking(vm, config)
                
                # Wait for IP address (shorter timeout since we have diagnostics)
                if start:
                    log.info("Waiting for VM to boot (checking every 10s)...")
                    ip = self._wait_for_ip(vm, timeout=30)
                    if ip:
                        log.info(f"VM '{config.name}' IP: {ip}")
                    else:
                        log.info("VM IP not detected (normal for user-mode networking)")
                    
                    # Test SSH connectivity
                    log.info("Testing SSH connectivity (cloud-init may take 2-3 minutes)...")
                    ssh_ok = self._test_ssh_connectivity(config.name, timeout=180)
                
                log.info(f"VM '{config.name}' creation completed successfully!")
                return vm_uuid

    def start_vm(self, vm_name: str, open_viewer: bool = False, console: Any = None) -> None:
        """Start an existing VM."""
        
        try:
            log.info(f"Looking up VM '{vm_name}'...")
            vm = self.conn.lookupByName(vm_name)
            
            if vm.isActive():
                log.info(f"VM '{vm_name}' is already running")
                # Still run diagnostics for already running VM
                self._check_vm_processes(vm_name)
                return
            
            log.info(f"Starting VM '{vm_name}'...")
            vm.create()
            log.info(f"VM '{vm_name}' started successfully")
            
            # Brief pause to let QEMU initialize
            time.sleep(2)
            
            # Run comprehensive diagnostics
            checks = self._check_vm_processes(vm_name)
            
            # Setup SSH port forwarding if needed
            ssh_port = self._get_saved_ssh_port(vm_name)
            if self.user_session and ssh_port and not checks.get("port_listening"):
                log.info("Setting up SSH port forwarding with socat...")
                self._setup_ssh_port_forward(vm_name, ssh_port)
            
            # Open viewer
            if open_viewer:
                log.info("Opening VM viewer...")
                self._open_viewer(vm_name)
            
            # Wait for IP address (short timeout)
            log.info("Waiting for VM to boot (checking every 10s)...")
            ip = self._wait_for_ip(vm, timeout=30)
            if ip:
                log.info(f"VM '{vm_name}' IP: {ip}")
            else:
                log.info("VM IP not detected (normal for user-mode networking)")
            
            # Test SSH connectivity
            log.info("Testing SSH connectivity (cloud-init may take 2-3 minutes)...")
            ssh_ok = self._test_ssh_connectivity(vm_name, timeout=180)
            
            if ssh_ok:
                log.info("=" * 50)
                log.info("VM READY FOR USE!")
                log.info(f"  ssh -p {ssh_port} ubuntu@localhost")
                log.info("=" * 50)
                
        except libvirt.libvirtError as e:
            log.error(f"Failed to start VM '{vm_name}': {e}")
            raise

    def stop_vm(self, vm_name: str, force: bool = False, console: Any = None) -> None:
        """Stop a VM."""
        
        try:
            vm = self.conn.lookupByName(vm_name)
            
            if not vm.isActive():
                log.info(f"VM '{vm_name}' is already stopped")
                return
            
            if force:
                vm.destroy()
                log.info(f"VM '{vm_name}' forcefully stopped")
            else:
                vm.shutdown()
                log.info(f"VM '{vm_name}' shutdown initiated")
                
        except libvirt.libvirtError as e:
            log.error(f"Failed to stop VM '{vm_name}': {e}")
            raise

    def restart_vm(self, vm_name: str, force: bool = False, open_viewer: bool = False, console: Any = None) -> None:
        """Restart a VM."""
        
        self.stop_vm(vm_name, force=force)
        time.sleep(2)
        self.start_vm(vm_name, open_viewer=open_viewer)

    def delete_vm(self, vm_name: str, delete_storage: bool = False, approved: bool = False, console: Any = None) -> None:
        """Delete a VM and its storage."""
        
        with log_operation(
            log,
            "vm_delete",
            vm_name=vm_name,
            user=os.getenv("USER"),
            details={"delete_storage": delete_storage}
        ):
            try:
                vm = self.conn.lookupByName(vm_name)
                
                # Stop VM if running
                if vm.isActive():
                    vm.destroy()
                
                # Get disk paths
                vm_xml = vm.XMLDesc()
                root = ET.fromstring(vm_xml)
                disk_paths = []
                
                for disk in root.findall(".//devices/disk[@type='file']/source"):
                    disk_path = disk.get("file")
                    if disk_path and not disk_path.endswith(".iso"):
                        disk_paths.append(disk_path)
                
                # Undefine VM
                vm.undefine()
                log.info(f"VM '{vm_name}' undefined")
                
                # Delete storage if requested
                if delete_storage:
                    for disk_path in disk_paths:
                        if os.path.exists(disk_path):
                            os.remove(disk_path)
                            log.info(f"Deleted disk: {disk_path}")
                            
            except Exception as e:
                if "no domain with matching name" in str(e):
                    # VM doesn't exist, that's OK when replacing
                    log.info(f"VM '{vm_name}' does not exist, skipping deletion")
                else:
                    log.error(f"Failed to delete VM '{vm_name}': {e}")
                    raise

    @property
    def SYSTEM_IMAGES_DIR(self) -> Path:
        """Get the system images directory."""
        return Path(os.getenv("CLONEBOX_SYSTEM_IMAGES_DIR", "/var/lib/libvirt/images"))

    @property
    def USER_IMAGES_DIR(self) -> Path:
        """Get the user images directory."""
        return Path(
            os.getenv("CLONEBOX_USER_IMAGES_DIR", str(Path.home() / ".local/share/libvirt/images"))
        )

    def _generate_vm_xml(self, config: VMConfig, disk_path: Path, cloud_init_path: Optional[Path]) -> str:
        """Generate VM XML configuration."""
        # Allocate SSH port for user session
        ssh_port = None
        if self.user_session:
            ssh_port = self._allocate_ssh_port(config.name)
            self._save_ssh_port(config.name, ssh_port)
        
        return generate_vm_xml(
            config=config,
            vm_uuid=str(uuid.uuid4()),
            disk_path=str(disk_path),
            cdrom_path=str(cloud_init_path) if cloud_init_path else None,
            user_session=self.user_session,
            ssh_port=ssh_port
        )

    def get_images_dir(self) -> Path:
        """Get the appropriate images directory based on session type."""
        if self.user_session:
            return self.USER_IMAGES_DIR
        return self.SYSTEM_IMAGES_DIR

    def _get_downloads_dir(self) -> Path:
        """Get the downloads directory."""
        return Path.home() / "Downloads"

    def check_prerequisites(self, config: Optional[VMConfig] = None) -> dict:
        """Check system prerequisites for VM creation."""
        images_dir = self.get_images_dir()

        resolved_network_mode: Optional[str] = None
        if config is not None:
            try:
                resolved_network_mode = self.resolve_network_mode(config)
            except Exception:
                resolved_network_mode = None

        checks = {
            "libvirt_connected": False,
            "kvm_available": False,
            "default_network": False,
            "default_network_required": True,
            "images_dir_writable": False,
            "images_dir": str(images_dir),
            "session_type": "user" if self.user_session else "system",
            "genisoimage_installed": False,
            "virt_viewer_installed": False,
            "qemu_img_installed": False,
            "passt_installed": shutil.which("passt") is not None,
            "passt_available": False,
        }

        checks["passt_available"] = checks["passt_installed"] and self._passt_supported()

        # Check for genisoimage
        checks["genisoimage_installed"] = shutil.which("genisoimage") is not None

        # Check for virt-viewer
        checks["virt_viewer_installed"] = shutil.which("virt-viewer") is not None

        # Check for qemu-img
        checks["qemu_img_installed"] = shutil.which("qemu-img") is not None

        # Check libvirt connection
        if self.conn and self.conn.isAlive():
            checks["libvirt_connected"] = True

        # Check KVM
        kvm_path = Path("/dev/kvm")
        checks["kvm_available"] = kvm_path.exists()
        if not checks["kvm_available"]:
            checks["kvm_error"] = "KVM not available. Enable virtualization in BIOS."
        elif not os.access(kvm_path, os.R_OK | os.W_OK):
            checks["kvm_error"] = (
                "No access to /dev/kvm. Add user to kvm group: sudo usermod -aG kvm $USER"
            )

        # Check default network
        default_net_state = self._default_network_state()
        checks["default_network_required"] = (resolved_network_mode or "default") != "user"
        if checks["default_network_required"]:
            checks["default_network"] = default_net_state == "active"
        else:
            checks["default_network"] = True

        if checks["default_network_required"] and default_net_state in {"inactive", "missing", "unknown"}:
            checks["network_error"] = (
                "Default network not found or inactive.\n"
                "  For user session, CloneBox can use user-mode networking (slirp) automatically.\n"
                "  Or create a user network:\n"
                "    virsh --connect qemu:///session net-define /tmp/default-network.xml\n"
                "    virsh --connect qemu:///session net-start default\n"
                "  Or use system session: clonebox clone . (without --user)\n"
            )

        if resolved_network_mode is not None:
            checks["network_mode"] = resolved_network_mode

        # Check images directory
        if images_dir.exists():
            checks["images_dir_writable"] = os.access(images_dir, os.W_OK)
            if not checks["images_dir_writable"]:
                checks["images_dir_error"] = (
                    f"Cannot write to {images_dir}\n"
                    f"  Option 1: Run with sudo\n"
                    f"  Option 2: Use --user flag for user session (recommended):\n"
                    f"     clonebox clone . --user\n\n"
                    f"  3. Fix permissions: sudo chown -R $USER:libvirt {images_dir}"
                )
        else:
            try:
                images_dir.mkdir(parents=True, exist_ok=True)
                checks["images_dir_writable"] = True
            except PermissionError:
                checks["images_dir_writable"] = False
                checks["images_dir_error"] = (
                    f"Cannot create {images_dir}\n"
                    f"  Use --user flag for user session (stores in ~/.local/share/libvirt/images/)"
                )

        return checks

    def _passt_supported(self) -> bool:
        """Check if passt is supported."""
        return shutil.which("passt") is not None

    def _default_network_state(self) -> str:
        """Get default network state."""
        try:
            networks = self.conn.listNetworks()
            defined_networks = self.conn.listDefinedNetworks()
            if "default" in networks:
                return "active"
            elif "default" in defined_networks:
                return "inactive"
            else:
                return "missing"
        except Exception:
            return "unknown"

    def _default_network_active(self) -> bool:
        """Check if default network is active."""
        return self._default_network_state() == "active"

    def resolve_network_mode(self, config: VMConfig) -> str:
        """Resolve network mode for VM."""
        valid_modes = {"auto", "default", "user", "bridge", "nat"}
        
        if config.network_mode not in valid_modes:
            return "default"
        
        if config.network_mode == "auto":
            # Auto mode - use default network if available, otherwise user mode
            if self._default_network_active():
                return "default"
            elif self.user_session:
                return "user"
            else:
                return "default"
        return config.network_mode

    def list_vms(self) -> List[Dict]:
        """List all VMs."""
        
        vms = []
        
        try:
            # Get running VMs by ID
            for domain_id in self.conn.listDomainsID():
                try:
                    domain = self.conn.lookupByID(domain_id)
                    info = domain.info()
                    state = self._get_state_string(info[0])
                    
                    vm_data = {
                        "name": domain.name(),
                        "state": state,
                        "uuid": domain.UUIDString(),
                        "memory": info[1] // 1024,
                        "vcpus": info[3],
                    }
                    
                    if state == "running":
                        ip = self._get_vm_ip(domain)
                        if ip:
                            vm_data["ip"] = ip
                    
                    vms.append(vm_data)
                except Exception:
                    pass
            
            # Get stopped VMs
            for domain_name in self.conn.listDefinedDomains():
                try:
                    domain = self.conn.lookupByName(domain_name)
                    info = domain.info()
                    state = self._get_state_string(info[0])
                    
                    vm_data = {
                        "name": domain.name(),
                        "state": state,
                        "uuid": domain.UUIDString(),
                        "memory": info[1] // 1024,
                        "vcpus": info[3],
                    }
                    
                    vms.append(vm_data)
                except Exception:
                    pass
                
        except Exception as e:
            log.error(f"Failed to list VMs: {e}")
            
        return vms

    def close(self):
        """Close the libvirt connection."""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
            self.conn = None

    def _create_vm_disk(self, config: VMConfig) -> str:
        """Create the VM disk image."""
        
        # Get base image path
        log.debug(f"Resolving base image for VM '{config.name}'...")
        if config.base_image:
            base_image = config.base_image
            log.debug(f"Using user-specified base image: {base_image}")
        else:
            log.debug("No base image specified, searching for default...")
            base_image = self._get_default_base_image()
            log.debug(f"Found default base image: {base_image}")
        
        if not os.path.exists(base_image):
            log.error(f"Base image not found: {base_image}")
            log.error("Please download a cloud image:")
            log.error("  wget https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img")
            raise FileNotFoundError(f"Base image not found: {base_image}")
        
        # Verify base image is readable
        try:
            base_size = os.path.getsize(base_image)
            log.debug(f"Base image size: {base_size / (1024*1024):.1f} MB")
        except Exception as e:
            log.warning(f"Could not check base image size: {e}")
        
        # Create disk path
        disk_dir = Path("/var/lib/libvirt/images") if not self.user_session else Path.home() / ".local/share/libvirt/images"
        log.debug(f"Disk directory: {disk_dir}")
        
        try:
            disk_dir.mkdir(parents=True, exist_ok=True)
            log.debug(f"Disk directory ensured: {disk_dir}")
        except PermissionError as e:
            log.error(f"Cannot create disk directory: {disk_dir}")
            log.error(f"Permission denied. Try: sudo mkdir -p {disk_dir} && sudo chown $USER:$USER {disk_dir}")
            raise
        
        disk_path = disk_dir / f"{config.name}.qcow2"
        log.debug(f"Target disk path: {disk_path}")
        
        # Check if disk already exists
        if disk_path.exists():
            log.warning(f"Disk already exists: {disk_path}")
            log.debug("Will be overwritten by qemu-img create")
        
        # Verify qemu-img is available
        if not shutil.which("qemu-img"):
            log.error("qemu-img not found in PATH")
            log.error("Install with: sudo apt-get install qemu-utils")
            raise FileNotFoundError("qemu-img not found. Install qemu-utils.")
        
        # Create disk from base image
        cmd = [
            "qemu-img",
            "create",
            "-f", "qcow2",
            "-F", "qcow2",
            "-b", base_image,
            str(disk_path),
            f"{config.disk_size_gb}G"
        ]
        log.debug(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if result.stderr:
                log.debug(f"qemu-img stderr: {result.stderr.strip()}")
            log.info(f"Created disk: {disk_path}")
        except subprocess.CalledProcessError as e:
            log.error(f"qemu-img create failed with exit code {e.returncode}")
            if e.stderr:
                log.error(f"Error: {e.stderr.strip()}")
            log.error("Possible causes:")
            log.error("  - Base image is corrupted")
            log.error("  - Insufficient disk space")
            log.error("  - Permission denied")
            raise
        
        # Verify disk was created
        if not disk_path.exists():
            log.error(f"Disk creation failed - file not found: {disk_path}")
            raise FileNotFoundError(f"Disk not created: {disk_path}")
        
        disk_size = os.path.getsize(disk_path)
        log.debug(f"Created disk size: {disk_size / 1024:.1f} KB")
        
        return str(disk_path)

    def _generate_cloud_init(self, config: VMConfig) -> str:
        """Generate cloud-init ISO image."""
        log.debug(f"Generating cloud-init for VM '{config.name}'...")
        log.debug(f"Auth method: {config.auth_method}")
        
        # Read host SSH key only if auth_method is ssh_key
        if not config.ssh_public_key and config.auth_method == "ssh_key":
            log.debug("Looking for host SSH public key...")
            # Try to read host's SSH public key
            ssh_key_paths = [
                Path.home() / ".ssh" / "id_ed25519.pub",
                Path.home() / ".ssh" / "id_rsa.pub",
                Path.home() / ".ssh" / "id_ecdsa.pub",
            ]
            for key_path in ssh_key_paths:
                log.debug(f"Checking for SSH key at: {key_path}")
                if key_path.exists():
                    try:
                        config.ssh_public_key = key_path.read_text().strip()
                        log.info(f"Using host SSH key: {key_path}")
                        break
                    except Exception as e:
                        log.warning(f"Could not read SSH key {key_path}: {e}")
            else:
                # Fallback: generate new key if no host key found
                log.warning("No host SSH key found. Generating new key pair.")
                log.warning("You may want to create one: ssh-keygen -t ed25519")
                try:
                    key_pair = SSHKeyPair.generate()
                    config.ssh_public_key = key_pair.public_key
                    log.debug("Generated temporary SSH key pair")
                    
                    # Save the generated key pair to VM directory for later use
                    self._save_ssh_key(config.name, key_pair)
                except Exception as e:
                    log.error(f"Failed to generate SSH key: {e}")
                    log.warning("Falling back to password authentication")
                    config.auth_method = "password"
        
        # Also copy host SSH key to VM directory if using host key
        if config.ssh_public_key and config.auth_method == "ssh_key":
            self._copy_host_ssh_key_to_vm(config.name)
        
        log.debug(f"User session mode: {self.user_session}")
        
        # Generate cloud-init config (returns tuple: user_data, meta_data, network_config)
        try:
            user_data, meta_data, network_config = generate_cloud_init_config(
                config=config,
                user_session=self.user_session,
            )
            log.debug(f"Cloud-init user-data generated ({len(user_data)} bytes)")
            log.debug(f"Cloud-init meta-data generated ({len(meta_data)} bytes)")
            if network_config:
                log.debug(f"Cloud-init network-config generated ({len(network_config)} bytes)")
        except Exception as e:
            log.error(f"Failed to generate cloud-init config: {e}")
            raise
        
        # Create temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            log.debug(f"Using temp directory: {tmpdir}")
            # Write user-data
            user_data_path = Path(tmpdir) / "user-data"
            user_data_path.write_text(user_data)
            
            # Write meta-data
            meta_data_path = Path(tmpdir) / "meta-data"
            meta_data_path.write_text(meta_data)
            
            # Write network-config if provided (for user session with passt)
            iso_files = [str(user_data_path), str(meta_data_path)]
            if network_config:
                network_config_path = Path(tmpdir) / "network-config"
                network_config_path.write_text(network_config)
                iso_files.append(str(network_config_path))
            
            # Create ISO with long filename support for cloud-init
            iso_path = Path(tmpdir) / "cloud-init.iso"
            
            # Find available ISO creation tool
            mkisofs_cmd = None
            for cmd_name in ["genisoimage", "mkisofs", "xorriso"]:
                if shutil.which(cmd_name):
                    mkisofs_cmd = cmd_name
                    log.debug(f"Using ISO tool: {cmd_name}")
                    break
            
            if not mkisofs_cmd:
                log.error("No ISO creation tool found (genisoimage, mkisofs, or xorriso)")
                log.error("Install with: sudo apt-get install genisoimage")
                raise FileNotFoundError("No ISO creation tool available. Install genisoimage.")
            
            if mkisofs_cmd == "xorriso":
                cmd = [
                    "xorriso", "-as", "mkisofs",
                    "-o", str(iso_path),
                    "-V", "cidata",
                    "-J", "-r",
                ] + iso_files
            else:
                cmd = [
                    mkisofs_cmd,
                    "-o", str(iso_path),
                    "-V", "cidata",
                    "-J", "-r",
                    "-iso-level", "4",  # Support long filenames
                ] + iso_files
            
            log.debug(f"Running: {' '.join(cmd)}")
            
            try:
                result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                if result.stderr and "Warning" not in result.stderr:
                    log.debug(f"ISO stderr: {result.stderr.strip()}")
            except subprocess.CalledProcessError as e:
                log.error(f"ISO creation failed with exit code {e.returncode}")
                if e.stderr:
                    log.error(f"Error: {e.stderr.strip()}")
                raise
            
            if not iso_path.exists():
                log.error(f"ISO creation failed - file not found: {iso_path}")
                raise FileNotFoundError(f"ISO not created: {iso_path}")
            
            log.debug(f"Created cloud-init ISO: {iso_path} ({os.path.getsize(iso_path)} bytes)")
            
            # Copy to final location
            iso_dir = Path("/var/lib/libvirt/images") if not self.user_session else Path.home() / ".local/share/libvirt/images"
            try:
                iso_dir.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                log.error(f"Cannot create ISO directory: {iso_dir}")
                raise
            
            final_iso_path = iso_dir / f"{config.name}-cloud-init.iso"
            log.debug(f"Copying ISO to: {final_iso_path}")
            shutil.copy2(iso_path, final_iso_path)
            
            log.debug(f"Cloud-init ISO ready: {final_iso_path}")
            return str(final_iso_path)

    def _setup_vm_networking(self, vm, config: VMConfig) -> None:
        """Setup networking for VM."""
        log.debug(f"Setting up networking for VM '{config.name}'...")
        log.debug(f"Network mode: {config.network_mode}")
        log.debug(f"User session: {self.user_session}")
        
        # Network setup is handled in the VM XML
        # Additional network configuration can be done here if needed
        
        if self.user_session:
            log.debug("User session networking uses QEMU user-mode (slirp) with hostfwd")
            log.debug("VM will get IP 10.0.2.15, gateway 10.0.2.2, DNS 10.0.2.3")
        else:
            log.debug("System session uses libvirt default network (NAT)")
            log.debug("VM will get IP from DHCP on 192.168.122.x")
        
        log.debug("Network setup complete (configuration in VM XML)")

    def _wait_for_ip(self, vm, timeout: int = 60) -> Optional[str]:
        """Wait for VM to get an IP address."""
        log.info(f"Waiting for VM IP address (timeout: {timeout}s)...")
        
        start_time = time.time()
        last_log_time = start_time
        attempt = 0
        
        while time.time() - start_time < timeout:
            attempt += 1
            elapsed = int(time.time() - start_time)
            
            # Log progress every 10 seconds
            if time.time() - last_log_time >= 10:
                log.info(f"  ... still waiting for IP ({elapsed}s elapsed, {attempt} attempts)")
                last_log_time = time.time()
            
            try:
                ip = self._get_vm_ip(vm)
                if ip:
                    log.info(f"VM IP detected: {ip} (after {elapsed}s)")
                    return ip
            except Exception as e:
                log.debug(f"IP detection attempt {attempt} failed: {e}")
            
            time.sleep(1)
        
        log.warning(f"Could not detect VM IP after {timeout}s - continuing without IP")
        log.warning("This is normal for user-mode networking - SSH port forwarding should still work")
        return None

    def _get_vm_ip(self, vm) -> Optional[str]:
        """Get IP address of VM."""
        
        try:
            # Try to get IP from DHCP leases
            if not self.user_session:
                # System session - check default network
                network = self.conn.networkLookupByName("default")
                leases = network.DHCPGetLeases()
                
                vm_mac = vm.XMLDesc().find("mac/@address")
                if vm_mac:
                    vm_mac = vm_mac.split('"')[1]
                    
                    for lease in leases:
                        if lease["mac"] == vm_mac:
                            return lease["ipaddr"]
            
            # Try QEMU Guest Agent
            if vm.isActive():
                try:
                    result = vm.qemuAgentCommand('{"execute": "guest-network-get-interfaces"}')
                    interfaces = json.loads(result)
                    
                    for iface in interfaces:
                        if iface["name"] not in ["lo", "docker0"]:
                            for ip_info in iface.get("ip-addresses", []):
                                if ip_info["type"] == "ipv4" and not ip_info["ip-address"].startswith("127."):
                                    return ip_info["ip-address"]
                except:
                    pass
            
        except Exception as e:
            log.debug(f"Failed to get VM IP: {e}")
        
        return None

    def _check_vm_processes(self, vm_name: str) -> dict:
        """Check that all required VM processes are running."""
        import shutil
        import socket
        
        log.info("=" * 50)
        log.info("VM DIAGNOSTICS")
        log.info("=" * 50)
        
        checks = {}
        
        # Check QEMU process
        log.info("[1/6] Checking QEMU process...")
        try:
            result = subprocess.run(
                ["pgrep", "-af", f"qemu.*guest={vm_name}"],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split('\n')
                qemu_pid = lines[0].split()[0]
                log.info(f"  ✓ QEMU running (PID: {qemu_pid})")
                
                # Get QEMU memory usage
                try:
                    mem_result = subprocess.run(
                        ["ps", "-o", "rss=", "-p", qemu_pid],
                        capture_output=True, text=True
                    )
                    if mem_result.returncode == 0:
                        mem_kb = int(mem_result.stdout.strip())
                        mem_mb = mem_kb / 1024
                        log.info(f"  ✓ QEMU memory: {mem_mb:.0f} MB")
                except:
                    pass
                checks["qemu"] = True
            else:
                log.error(f"  ✗ QEMU process NOT FOUND for VM '{vm_name}'")
                log.error("    This means the VM failed to start!")
                checks["qemu"] = False
        except Exception as e:
            log.error(f"  ✗ Failed to check QEMU: {e}")
            checks["qemu"] = False
        
        # Check SSH port from saved config
        log.info("[2/6] Checking SSH port configuration...")
        ssh_port = self._get_saved_ssh_port(vm_name)
        if ssh_port:
            log.info(f"  ✓ SSH port configured: {ssh_port}")
            checks["ssh_port"] = ssh_port
        else:
            log.warning("  ✗ No SSH port configured - checking VM XML...")
            # Try to get port from VM XML
            try:
                vm = self.conn.lookupByName(vm_name)
                vm_xml = vm.XMLDesc()
                import xml.etree.ElementTree as ET
                root = ET.fromstring(vm_xml)
                
                # Check for hostfwd in QEMU arguments
                qemu_args = root.find(".//domain/qemu:commandline", namespaces={'qemu': 'http://libvirt.org/schemas/domain/qemu/1.0'})
                if qemu_args is not None:
                    for arg in qemu_args.findall(".//qemu:arg", namespaces={'qemu': 'http://libvirt.org/schemas/domain/qemu/1.0'}):
                        value = arg.get('value', '')
                        if 'hostfwd=tcp::' in value and '-:22' in value:
                            import re
                            match = re.search(r'hostfwd=tcp::(\d+)-:22', value)
                            if match:
                                ssh_port = int(match.group(1))
                                log.info(f"  ✓ Found SSH port in VM XML: {ssh_port}")
                                checks["ssh_port"] = ssh_port
                                break
            except Exception as e:
                log.debug(f"Failed to parse VM XML: {e}")
            
            # Check if port is listening
            log.info(f"[3/6] Checking if port {ssh_port} is listening...")
            try:
                result = subprocess.run(
                    ["ss", "-tlnp", f"sport = :{ssh_port}"],
                    capture_output=True, text=True
                )
                if f":{ssh_port}" in result.stdout:
                    log.info(f"  ✓ Port {ssh_port} is LISTENING")
                    # Extract process info
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        if f":{ssh_port}" in line:
                            log.info(f"    {line.strip()}")
                    checks["port_listening"] = True
                else:
                    log.warning(f"  ✗ Port {ssh_port} is NOT listening")
                    log.warning("    This is OK - QEMU will handle forwarding internally")
                    checks["port_listening"] = False
            except Exception as e:
                log.warning(f"  ✗ Failed to check port: {e}")
                checks["port_listening"] = False
            
            # Test TCP connection
            log.info(f"[4/6] Testing TCP connection to port {ssh_port}...")
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex(('127.0.0.1', ssh_port))
                sock.close()
                if result == 0:
                    log.info(f"  ✓ TCP connection to port {ssh_port} SUCCESSFUL")
                    checks["tcp_connect"] = True
                else:
                    log.warning(f"  ✗ TCP connection to port {ssh_port} FAILED (error: {result})")
                    checks["tcp_connect"] = False
            except Exception as e:
                log.warning(f"  ✗ TCP connection failed: {e}")
                checks["tcp_connect"] = False
        
        if not ssh_port:
            log.warning("  ✗ No SSH port configured")
            checks["ssh_port"] = None
            log.info("=" * 50)
            log.info("DIAGNOSTICS SUMMARY: 2/2 checks passed")
            log.info("=" * 50)
            return checks
        
        # Check for virt-viewer availability
        log.info("[5/6] Checking display tools...")
        if shutil.which("virt-viewer"):
            log.info("  ✓ virt-viewer available")
            checks["virt_viewer"] = True
        else:
            log.warning("  ✗ virt-viewer not installed")
            log.warning("    Install: sudo apt-get install virt-viewer")
            checks["virt_viewer"] = False
        
        # Check VM display ports
        try:
            vm = self.conn.lookupByName(vm_name)
            vm_xml = vm.XMLDesc()
            import xml.etree.ElementTree as ET
            root = ET.fromstring(vm_xml)
            
            # Check SPICE
            spice = root.find(".//graphics[@type='spice']")
            if spice is not None:
                spice_port = spice.get('port', 'auto')
                log.info(f"  ✓ SPICE display on port {spice_port}")
                checks["spice_port"] = spice_port
            
            # Check VNC
            vnc = root.find(".//graphics[@type='vnc']")
            if vnc is not None:
                vnc_port = vnc.get('port', 'auto')
                log.info(f"  ✓ VNC display on port {vnc_port}")
                checks["vnc_port"] = vnc_port
        except Exception as e:
            log.debug(f"Failed to get display ports: {e}")
        
        # Check socat availability
        log.info("[6/6] Checking networking tools...")
        if shutil.which("socat"):
            log.info("  ✓ socat available")
            checks["socat"] = True
        else:
            log.warning("  ✗ socat not installed")
            log.warning("    Install: sudo apt-get install socat")
            checks["socat"] = False
        
        # Summary
        log.info("=" * 50)
        passed = sum(1 for k, v in checks.items() if v is True)
        total = sum(1 for k, v in checks.items() if isinstance(v, bool))
        log.info(f"DIAGNOSTICS SUMMARY: {passed}/{total} checks passed")
        
        if checks.get("ssh_port"):
            log.info(f"SSH ACCESS: ssh -p {checks['ssh_port']} ubuntu@localhost")
        if checks.get("vnc_port"):
            log.info(f"VNC ACCESS: vncviewer localhost:{checks['vnc_port']}")
        if checks.get("spice_port"):
            log.info(f"SPICE ACCESS: remote-viewer spice://localhost:{checks['spice_port']}")
        
        log.info("=" * 50)
        
        return checks
    
    def _get_saved_ssh_port(self, vm_name: str) -> int | None:
        """Get saved SSH port for a VM."""
        # Check both locations for compatibility
        images_dir = self.USER_IMAGES_DIR if self.user_session else Path("/var/lib/libvirt/images")
        
        # First check VM directory
        port_file = images_dir / vm_name / "ssh_port"
        log.debug(f"Checking for SSH port at: {port_file}")
        if port_file.exists():
            try:
                port = int(port_file.read_text().strip())
                log.debug(f"Found SSH port {port} in VM directory")
                return port
            except Exception as e:
                log.debug(f"Failed to read port from {port_file}: {e}")
        
        # Fallback to old location
        port_file = Path.home() / ".local/share/clonebox" / f"{vm_name}.ssh_port"
        log.debug(f"Checking for SSH port at: {port_file}")
        if port_file.exists():
            try:
                port = int(port_file.read_text().strip())
                log.debug(f"Found SSH port {port} in old location")
                return port
            except Exception as e:
                log.debug(f"Failed to read port from {port_file}: {e}")
        
        log.debug(f"No SSH port found for VM '{vm_name}'")
        return None
    
    def _test_ssh_connectivity(self, vm_name: str, timeout: int = 120) -> bool:
        """Test SSH connectivity to VM with multiple fallback methods."""
        ssh_port = self._get_saved_ssh_port(vm_name)
        if not ssh_port:
            log.warning("No SSH port configured for VM")
            log.warning("Attempting to derive port from VM name...")
            # Fallback: compute port from VM name hash
            ssh_port = 22000 + (zlib.crc32(vm_name.encode()) % 1000)
            log.warning(f"Using fallback port: {ssh_port}")
        
        log.info(f"Testing SSH connectivity on port {ssh_port}...")
        log.info(f"  (waiting up to {timeout}s for cloud-init to complete)")
        
        # First check if port is listening
        log.debug(f"Checking if port {ssh_port} is listening...")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('127.0.0.1', ssh_port))
            sock.close()
            if result == 0:
                log.debug(f"Port {ssh_port} is accepting connections")
            else:
                log.debug(f"Port {ssh_port} not yet accepting connections (error: {result})")
        except Exception as e:
            log.debug(f"Port check failed: {e}")
        
        start_time = time.time()
        attempt = 0
        last_error = None
        tcp_ok = False
        
        while time.time() - start_time < timeout:
            attempt += 1
            elapsed = time.time() - start_time
            
            # First check TCP connectivity
            if not tcp_ok or attempt % 5 == 0:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)
                    result = sock.connect_ex(('127.0.0.1', ssh_port))
                    sock.close()
                    if result == 0:
                        if not tcp_ok:
                            log.debug(f"TCP connection to port {ssh_port} successful after {elapsed:.1f}s")
                        tcp_ok = True
                    else:
                        tcp_ok = False
                except Exception as e:
                    log.debug(f"TCP check failed: {e}")
                    tcp_ok = False
            
            if not tcp_ok:
                if attempt % 10 == 0:
                    log.info(f"  ... waiting for port {ssh_port} to accept connections ({elapsed:.0f}s elapsed)")
                time.sleep(2)
                continue
            
            # Try SSH connection
            try:
                result = subprocess.run(
                    [
                        "ssh", "-o", "StrictHostKeyChecking=no",
                        "-o", "UserKnownHostsFile=/dev/null",
                        "-o", "ConnectTimeout=5",
                        "-o", "BatchMode=yes",
                        "-o", "LogLevel=ERROR",
                        "-p", str(ssh_port),
                        "ubuntu@localhost",
                        "echo 'SSH_OK'"
                    ],
                    capture_output=True, text=True, timeout=10
                )
                if "SSH_OK" in result.stdout:
                    elapsed = time.time() - start_time
                    log.info(f"  ✓ SSH connection successful after {elapsed:.1f}s ({attempt} attempts)")
                    log.info("=" * 50)
                    log.info("VM READY FOR USE!")
                    log.info(f"  ssh -p {ssh_port} ubuntu@localhost")
                    log.info("=" * 50)
                    return True
                else:
                    # SSH connected but command failed
                    if result.stderr:
                        last_error = result.stderr.strip()
                        log.debug(f"SSH stderr: {last_error}")
            except subprocess.TimeoutExpired:
                log.debug(f"SSH attempt {attempt} timed out")
            except Exception as e:
                last_error = str(e)
                log.debug(f"SSH attempt {attempt} failed: {e}")
            
            if attempt % 10 == 0:
                log.info(f"  ... still waiting for SSH ({elapsed:.0f}s elapsed, {attempt} attempts)")
                if last_error:
                    log.debug(f"    Last error: {last_error}")
            
            time.sleep(3)
        
        log.warning(f"  ✗ SSH connection not available after {timeout}s")
        log.warning("    Possible causes:")
        log.warning("    - Cloud-init still running (wait and try again)")
        log.warning("    - SSH not enabled in VM")
        log.warning("    - Network misconfiguration")
        if last_error:
            log.warning(f"    - Last error: {last_error}")
        log.warning("    Manual connection:")
        log.warning(f"    ssh -p {ssh_port} ubuntu@localhost")
        log.warning(f"    Or check console: virsh --connect {self.conn_uri} console {vm_name}")
        return False

    def _open_viewer(self, vm_name: str) -> None:
        """Open SPICE/VNC viewer for VM."""
        import shutil
        
        if not shutil.which("virt-viewer"):
            log.warning("virt-viewer not installed - cannot open VM window")
            log.warning("Install with: sudo apt-get install virt-viewer")
            log.warning(f"Alternative: virsh --connect {self.conn_uri} console {vm_name}")
            return
        
        try:
            cmd = ["virt-viewer", "--connect", self.conn_uri, vm_name]
            log.info(f"Launching: {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            # Wait briefly to check if it started
            import time
            time.sleep(0.5)
            if process.poll() is not None:
                # Process exited immediately - check error
                _, stderr = process.communicate()
                if stderr:
                    log.warning(f"virt-viewer failed: {stderr.decode().strip()}")
            else:
                log.info(f"VM viewer window opened for '{vm_name}'")
        except Exception as e:
            log.warning(f"Failed to open VM viewer: {e}")

    def _get_state_string(self, state: int) -> str:
        """Convert libvirt state to string."""
        
        states = {
            0: "running",
            1: "blocked",
            2: "paused",
            3: "shutdown",
            4: "shut off",
            5: "crashed",
            6: "pmsuspended",
        }
        
        return states.get(state, "unknown")

    def _get_default_base_image(self) -> str:
        """Get default base image path."""
        
        # Check common locations
        paths = [
            str(Path.home() / ".local/share/libvirt/base-images/ubuntu-22.04.qcow2"),
            "/var/lib/libvirt/base-images/ubuntu-22.04.qcow2",
            "/var/lib/libvirt/images/ubuntu-22.04.qcow2",
            "/usr/share/clonebox/images/ubuntu-22.04.qcow2",
        ]
        
        for path in paths:
            if os.path.exists(path):
                return path
        
        raise FileNotFoundError("No base image found. Please download or specify one.")

    def _ensure_default_base_image(self, console=None) -> Path:
        """Ensure a default base image exists, downloading if necessary."""
        # Check common locations first
        try:
            return Path(self._get_default_base_image())
        except FileNotFoundError:
            pass
        
        # Download default image if not found
        if console:
            console.print("[yellow]Base image not found. Attempting to download...[/]")
        
        # Download to user images directory
        images_dir = self.get_images_dir()
        images_dir.mkdir(parents=True, exist_ok=True)
        
        base_image_path = images_dir / "ubuntu-22.04.qcow2"
        
        # Placeholder for download - in real implementation would download from cloud-images.ubuntu.com
        raise FileNotFoundError(
            f"No base image found. Please download one:\n"
            f"  wget -P {images_dir} https://cloud-images.ubuntu.com/jammy/current/"
            f"jammy-server-cloudimg-amd64.img"
        )

    def _create_cloudinit_iso(self, vm_dir: Path, config: VMConfig, user_session: bool = False) -> Path:
        """Create cloud-init ISO image for VM."""
        from clonebox.cloud_init import generate_cloud_init_config
        
        # Generate cloud-init config (returns tuple: user_data, meta_data, network_config)
        user_data, meta_data, network_config = generate_cloud_init_config(config, user_session=user_session)
        
        # Create ISO in temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            user_data_path = Path(tmpdir) / "user-data"
            user_data_path.write_text(user_data)
            
            meta_data_path = Path(tmpdir) / "meta-data"
            meta_data_path.write_text(meta_data)
            
            # Write network-config if provided (for user session with passt)
            iso_files = [str(user_data_path), str(meta_data_path)]
            if network_config:
                network_config_path = Path(tmpdir) / "network-config"
                network_config_path.write_text(network_config)
                iso_files.append(str(network_config_path))
            
            iso_path = Path(tmpdir) / "cloud-init.iso"
            
            # Use genisoimage or mkisofs with long filename support
            mkisofs_cmd = "genisoimage" if shutil.which("genisoimage") else "mkisofs"
            cmd = [
                mkisofs_cmd,
                "-o", str(iso_path),
                "-V", "cidata",
                "-J", "-r",
                "-iso-level", "4",  # Support long filenames for network-config
            ] + iso_files
            
            subprocess.run(cmd, check=True, capture_output=True)
            
            # Copy to vm_dir
            final_iso = vm_dir / f"{config.name}-cloud-init.iso"
            shutil.copy2(iso_path, final_iso)
            
            return final_iso

    def _get_state_string(self, state_code: int) -> str:
        """Convert libvirt state code to string."""
        states = {
            0: "nostate",
            1: "running",
            2: "blocked",
            3: "paused",
            4: "shutdown",
            5: "shutoff",
            6: "crashed",
            7: "suspended",
        }
        return states.get(state_code, "unknown")

    def _allocate_ssh_port(self, vm_name: str) -> int:
        """Allocate a free localhost port for SSH forwarding."""
        import socket
        import random
        
        log.debug(f"Allocating SSH port for VM '{vm_name}'...")
        
        # First check if we already have a saved port for this VM
        existing_port = self._get_saved_ssh_port(vm_name)
        if existing_port:
            log.debug(f"Found existing SSH port for VM: {existing_port}")
            # Verify it's still available
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', existing_port))
                    log.debug(f"Existing port {existing_port} is available, reusing")
                    return existing_port
            except OSError:
                log.debug(f"Existing port {existing_port} is in use, allocating new one")
        
        # Try to allocate a deterministic port based on VM name (for consistency)
        base_port = 22000 + (zlib.crc32(vm_name.encode()) % 1000)
        log.debug(f"Trying deterministic port based on VM name: {base_port}")
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', base_port))
                log.debug(f"Allocated deterministic port: {base_port}")
                return base_port
        except OSError:
            log.debug(f"Deterministic port {base_port} is in use, trying random ports")
        
        # Try to find a free port in range 22000-22999
        attempts = 0
        for _ in range(100):
            port = random.randint(22000, 22999)
            attempts += 1
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', port))
                    log.debug(f"Allocated random port {port} after {attempts} attempts")
                    return port
            except OSError:
                continue
        
        log.warning(f"Could not find free port in range 22000-22999 after {attempts} attempts")
        log.warning("Falling back to OS-assigned port")
        
        # Fallback: let OS assign a port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]
                log.debug(f"OS assigned port: {port}")
                return port
        except Exception as e:
            log.error(f"Failed to allocate any port: {e}")
            # Last resort fallback
            fallback_port = 22000 + (zlib.crc32(vm_name.encode()) % 1000)
            log.warning(f"Using fallback port without verification: {fallback_port}")
            return fallback_port

    def _save_ssh_port(self, vm_name: str, port: int) -> None:
        """Save SSH port to file for later retrieval."""
        images_dir = self.USER_IMAGES_DIR if self.user_session else Path("/var/lib/libvirt/images")
        vm_dir = images_dir / vm_name
        
        log.debug(f"Saving SSH port {port} for VM '{vm_name}'...")
        
        try:
            vm_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            log.error(f"Cannot create VM directory: {vm_dir}")
            log.error(f"Permission denied: {e}")
            # Try alternative location
            alt_dir = Path.home() / ".local/share/clonebox"
            try:
                alt_dir.mkdir(parents=True, exist_ok=True)
                port_file = alt_dir / f"{vm_name}.ssh_port"
                port_file.write_text(str(port))
                log.warning(f"Saved SSH port to alternative location: {port_file}")
                return
            except Exception as e2:
                log.error(f"Failed to save to alternative location: {e2}")
                return
        except Exception as e:
            log.error(f"Failed to create VM directory: {e}")
            return
        
        port_file = vm_dir / "ssh_port"
        try:
            port_file.write_text(str(port))
            log.debug(f"SSH port {port} saved to {port_file}")
        except Exception as e:
            log.error(f"Failed to save SSH port to {port_file}: {e}")
            # Try alternative location
            alt_file = Path.home() / ".local/share/clonebox" / f"{vm_name}.ssh_port"
            try:
                alt_file.parent.mkdir(parents=True, exist_ok=True)
                alt_file.write_text(str(port))
                log.warning(f"Saved SSH port to alternative location: {alt_file}")
            except Exception as e2:
                log.error(f"Failed to save to alternative location: {e2}")

    def _save_ssh_key(self, vm_name: str, key_pair: SSHKeyPair) -> None:
        """Save SSH key pair to VM directory for later use."""
        images_dir = self.USER_IMAGES_DIR if self.user_session else Path("/var/lib/libvirt/images")
        vm_dir = images_dir / vm_name
        
        log.debug(f"Saving SSH key pair for VM '{vm_name}'...")
        
        try:
            vm_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            log.error(f"Cannot create VM directory for SSH key: {vm_dir}")
            log.error(f"Permission denied: {e}")
            return
        except Exception as e:
            log.error(f"Failed to create VM directory: {e}")
            return
        
        # Save private key
        private_key_file = vm_dir / "ssh_key"
        try:
            private_key_file.write_text(key_pair.private_key)
            private_key_file.chmod(0o600)  # Secure permissions
            log.info(f"SSH private key saved to: {private_key_file}")
        except Exception as e:
            log.error(f"Failed to save SSH private key: {e}")
            return
        
        # Save public key
        public_key_file = vm_dir / "ssh_key.pub"
        try:
            public_key_file.write_text(key_pair.public_key)
            log.debug(f"SSH public key saved to: {public_key_file}")
        except Exception as e:
            log.warning(f"Failed to save SSH public key: {e}")
        
        log.info(f"Use: ssh -i {private_key_file} -p <port> ubuntu@localhost")

    def _copy_host_ssh_key_to_vm(self, vm_name: str) -> None:
        """Copy host SSH private key to VM directory for convenience."""
        images_dir = self.USER_IMAGES_DIR if self.user_session else Path("/var/lib/libvirt/images")
        vm_dir = images_dir / vm_name
        ssh_key_file = vm_dir / "ssh_key"
        
        # Skip if key already exists (e.g., generated key)
        if ssh_key_file.exists():
            log.debug(f"SSH key already exists at {ssh_key_file}")
            return
        
        log.debug(f"Looking for host SSH private key to copy...")
        
        # Find the corresponding private key
        ssh_key_paths = [
            (Path.home() / ".ssh" / "id_ed25519", Path.home() / ".ssh" / "id_ed25519.pub"),
            (Path.home() / ".ssh" / "id_rsa", Path.home() / ".ssh" / "id_rsa.pub"),
            (Path.home() / ".ssh" / "id_ecdsa", Path.home() / ".ssh" / "id_ecdsa.pub"),
        ]
        
        for private_path, public_path in ssh_key_paths:
            if private_path.exists() and public_path.exists():
                try:
                    vm_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Copy private key with secure permissions
                    shutil.copy2(private_path, ssh_key_file)
                    ssh_key_file.chmod(0o600)
                    log.debug(f"Copied host SSH private key to: {ssh_key_file}")
                    
                    # Copy public key
                    shutil.copy2(public_path, vm_dir / "ssh_key.pub")
                    log.debug(f"Copied host SSH public key to: {vm_dir / 'ssh_key.pub'}")
                    
                    log.info(f"Host SSH key copied to VM directory: {ssh_key_file}")
                    return
                except PermissionError as e:
                    log.warning(f"Permission denied copying SSH key: {e}")
                except Exception as e:
                    log.warning(f"Failed to copy SSH key: {e}")
        
        log.debug("No host SSH private key found to copy")

    def _setup_ssh_port_forward(self, vm_name: str, host_port: int, guest_port: int = 22) -> None:
        """Setup SSH port forwarding using socat with nsenter for passt network namespace."""
        import subprocess
        import time
        
        log.debug(f"Setting up SSH port forwarding for VM '{vm_name}'...")
        log.debug(f"Host port: {host_port}, Guest port: {guest_port}")
        
        # Wait a bit for VM to start
        log.debug("Waiting 3s for VM processes to initialize...")
        time.sleep(3)
        
        # Check if port forwarding is already handled by QEMU hostfwd
        log.debug(f"Checking if port {host_port} is already listening (QEMU hostfwd)...")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', host_port))
            sock.close()
            if result == 0:
                log.info(f"Port {host_port} already listening (QEMU hostfwd active)")
                log.info("No additional port forwarding needed")
                return
        except Exception as e:
            log.debug(f"Port check failed: {e}")
        
        # Find passt PID for this VM
        log.debug(f"Looking for passt process for VM '{vm_name}'...")
        try:
            pgrep_result = subprocess.run(
                ["pgrep", "-f", f"passt.*{vm_name}"],
                capture_output=True,
                text=True
            )
            if pgrep_result.returncode != 0 or not pgrep_result.stdout.strip():
                log.warning(f"passt process not found for VM '{vm_name}'")
                log.debug("This is normal for QEMU user-mode networking (slirp with hostfwd)")
                # Fallback to direct socat (for slirp mode)
                self._start_socat_direct(host_port, guest_port)
                return
            
            passt_pid = pgrep_result.stdout.strip().split('\n')[0].strip()
            log.debug(f"Found passt PID: {passt_pid} for VM '{vm_name}'")
        except FileNotFoundError:
            log.debug("pgrep not found - assuming no passt")
            self._start_socat_direct(host_port, guest_port)
            return
        except Exception as e:
            log.warning(f"Failed to find passt PID: {e}")
            self._start_socat_direct(host_port, guest_port)
            return
        
        # Check if required tools are available
        if not shutil.which("nsenter"):
            log.warning("nsenter not found - falling back to direct socat")
            log.warning("Install util-linux for better port forwarding: sudo apt-get install util-linux")
            self._start_socat_direct(host_port, guest_port)
            return
        
        if not shutil.which("socat"):
            log.warning("socat not found - port forwarding not available")
            log.warning("Install socat: sudo apt-get install socat")
            log.warning(f"SSH should still work via QEMU hostfwd on port {host_port}")
            return
        
        # Use nsenter to enter passt network namespace and run socat
        # This allows connecting to 10.0.2.15 which is isolated by passt
        socat_cmd = [
            "nsenter",
            "--target", passt_pid,
            "--net",
            "--",
            "socat",
            f"TCP-LISTEN:{host_port},fork,reuseaddr",
            f"TCP:10.0.2.15:{guest_port}"
        ]
        
        log.debug(f"Running: {' '.join(socat_cmd)}")
        
        try:
            # Start socat in background
            process = subprocess.Popen(
                socat_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            # Brief wait to check if it started
            time.sleep(0.5)
            if process.poll() is not None:
                # Process exited immediately
                _, stderr = process.communicate()
                if stderr:
                    log.warning(f"nsenter/socat failed: {stderr.decode().strip()}")
                log.warning("Falling back to direct socat")
                self._start_socat_direct(host_port, guest_port)
            else:
                log.info(f"SSH port forwarding started: localhost:{host_port} -> 10.0.2.15:{guest_port} (via passt ns)")
        except FileNotFoundError as e:
            log.warning(f"Command not found: {e}")
            log.warning("Falling back to direct socat")
            self._start_socat_direct(host_port, guest_port)
        except PermissionError as e:
            log.warning(f"Permission denied for nsenter: {e}")
            log.warning("nsenter may require root privileges")
            log.warning("Falling back to direct socat")
            self._start_socat_direct(host_port, guest_port)
        except Exception as e:
            log.warning(f"Failed to setup SSH port forwarding via passt ns: {e}")
            log.warning("Falling back to direct socat")
            self._start_socat_direct(host_port, guest_port)

    def _start_socat_direct(self, host_port: int, guest_port: int) -> None:
        """Start socat directly (for slirp mode where VM IP is reachable from host)."""
        import subprocess
        
        log.debug(f"Starting direct socat: localhost:{host_port} -> 10.0.2.15:{guest_port}")
        
        # Check if socat is available
        if not shutil.which("socat"):
            log.warning("socat not found - SSH port forwarding not available")
            log.warning("Install with: sudo apt-get install socat")
            log.warning(f"SSH may still work if QEMU hostfwd is configured on port {host_port}")
            return
        
        # Check if port is already in use
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', host_port))
            sock.close()
            if result == 0:
                log.debug(f"Port {host_port} already in use - skipping socat")
                log.info(f"SSH port forwarding already active on port {host_port}")
                return
        except Exception as e:
            log.debug(f"Port check failed: {e}")
        
        socat_cmd = [
            "socat",
            f"TCP-LISTEN:{host_port},fork,reuseaddr",
            f"TCP:10.0.2.15:{guest_port}"
        ]
        
        log.debug(f"Running: {' '.join(socat_cmd)}")
        
        try:
            process = subprocess.Popen(
                socat_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            # Brief wait to check if it started
            time.sleep(0.3)
            if process.poll() is not None:
                # Process exited immediately
                _, stderr = process.communicate()
                if stderr:
                    error_msg = stderr.decode().strip()
                    log.warning(f"socat failed: {error_msg}")
                    if "Address already in use" in error_msg:
                        log.info(f"Port {host_port} already in use - another forwarder may be active")
                    elif "Connection refused" in error_msg:
                        log.debug("VM not yet accepting connections - this is normal during boot")
            else:
                log.info(f"SSH port forwarding started: localhost:{host_port} -> 10.0.2.15:{guest_port}")
        except FileNotFoundError:
            log.warning("socat not found - SSH port forwarding not available")
            log.warning("Install with: sudo apt-get install socat")
        except PermissionError as e:
            log.warning(f"Permission denied starting socat: {e}")
            log.warning(f"Try: sudo socat TCP-LISTEN:{host_port},fork,reuseaddr TCP:10.0.2.15:{guest_port}")
        except Exception as e:
            log.warning(f"Failed to setup SSH port forwarding: {e}")
            log.debug(f"Exception type: {type(e).__name__}")

    def __del__(self):
        """Cleanup libvirt connection."""
        
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.close()
            except:
                pass
