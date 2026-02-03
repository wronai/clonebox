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
        self.policy_engine = self.container.resolve(PolicyEngine)
        self.audit_logger = get_audit_logger()

        # Initialize libvirt connection
        if conn_uri is None:
            conn_uri = "qemu:///session" if user_session else "qemu:///system"
        
        self.conn_uri = conn_uri
        self.conn = libvirt.open(conn_uri) if libvirt else None
        
        if not self.conn:
            raise RuntimeError("Failed to connect to libvirt")

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
            self.audit_logger,
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
                self.delete_vm(config.name, keep_storage=True, approved=approved)
            else:
                try:
                    self.conn.lookupByName(config.name)
                    raise ValueError(f"VM '{config.name}' already exists")
                except libvirt.libvirtError:
                    pass
            
            # Validate configuration against policies
            if not approved:
                self.policy_engine.validate_vm_creation(config)
            
            # Generate VM UUID
            vm_uuid = str(uuid.uuid4())
            
            # Create transaction for rollback
            with vm_creation_transaction(config.name, vm_uuid):
                # Create base disk
                disk_path = self._create_vm_disk(config)
                
                # Generate cloud-init ISO
                cloud_init_path = self._generate_cloud_init(config)
                
                # Generate VM XML
                vm_xml = generate_vm_xml(
                    config=config,
                    vm_uuid=vm_uuid,
                    disk_path=disk_path,
                    cdrom_path=cloud_init_path,
                    user_session=self.user_session,
                )
                
                # Define and start VM
                vm = self.conn.defineXML(vm_xml)
                
                if start:
                    vm.create()
                    log.info(f"VM '{config.name}' started")
                
                # Setup networking
                self._setup_vm_networking(vm, config)
                
                # Wait for IP address
                if start:
                    ip = self._wait_for_ip(vm)
                    if ip:
                        log.info(f"VM '{config.name}' IP: {ip}")
                
                return vm_uuid

    def start_vm(self, vm_name: str, open_viewer: bool = False, console: Any = None) -> None:
        """Start an existing VM."""
        
        try:
            vm = self.conn.lookupByName(vm_name)
            
            if vm.isActive():
                log.info(f"VM '{vm_name}' is already running")
                return
            
            vm.create()
            log.info(f"VM '{vm_name}' started")
            
            # Wait for IP address
            ip = self._wait_for_ip(vm)
            if ip:
                log.info(f"VM '{vm_name}' IP: {ip}")
            
            # Open viewer if requested
            if open_viewer:
                self._open_viewer(vm_name)
                
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

    def delete_vm(self, vm_name: str, keep_storage: bool = False, approved: bool = False, console: Any = None) -> None:
        """Delete a VM and its storage."""
        
        with log_operation(
            self.audit_logger,
            "vm_delete",
            vm_name=vm_name,
            user=os.getenv("USER"),
            details={"keep_storage": keep_storage}
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
                if not keep_storage:
                    for disk_path in disk_paths:
                        if os.path.exists(disk_path):
                            os.remove(disk_path)
                            log.info(f"Deleted disk: {disk_path}")
                
            except libvirt.libvirtError as e:
                log.error(f"Failed to delete VM '{vm_name}': {e}")
                raise

    def list_vms(self) -> List[Dict]:
        """List all VMs."""
        
        vms = []
        
        try:
            for domain_id in self.conn.listAllDomains(0):
                info = domain_id.info()
                state = self._get_state_string(info[0])
                
                vm_data = {
                    "name": domain_id.name(),
                    "state": state,
                    "uuid": domain_id.UUIDString(),
                    "memory": info[1] // 1024,  # Convert to MB
                    "vcpus": info[3],
                }
                
                # Get IP address if running
                if state == "running":
                    ip = self._get_vm_ip(domain_id)
                    if ip:
                        vm_data["ip"] = ip
                
                vms.append(vm_data)
                
        except libvirt.libvirtError as e:
            log.error(f"Failed to list VMs: {e}")
            
        return vms

    def _create_vm_disk(self, config: VMConfig) -> str:
        """Create the VM disk image."""
        
        # Get base image path
        if config.base_image:
            base_image = config.base_image
        else:
            base_image = self._get_default_base_image()
        
        if not os.path.exists(base_image):
            raise FileNotFoundError(f"Base image not found: {base_image}")
        
        # Create disk path
        disk_dir = Path("/var/lib/libvirt/images") if not self.user_session else Path.home() / ".local/share/libvirt/images"
        disk_dir.mkdir(parents=True, exist_ok=True)
        
        disk_path = disk_dir / f"{config.name}.qcow2"
        
        # Create disk from base image
        cmd = [
            "qemu-img",
            "create",
            "-f", "qcow2",
            "-b", base_image,
            str(disk_path),
            f"{config.disk_size_gb}G"
        ]
        
        subprocess.run(cmd, check=True)
        log.info(f"Created disk: {disk_path}")
        
        return str(disk_path)

    def _generate_cloud_init(self, config: VMConfig) -> str:
        """Generate cloud-init ISO image."""
        
        # Generate SSH key if not provided
        if not config.ssh_public_key and config.auth_method == "ssh_key":
            key_pair = self.secrets.generate_ssh_key_pair()
            config.ssh_public_key = key_pair.public_key
        
        # Generate cloud-init config
        cloud_config = generate_cloud_init_config(
            config=config,
            user_session=self.user_session,
        )
        
        # Create temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write user-data
            user_data_path = Path(tmpdir) / "user-data"
            user_data_path.write_text(cloud_config)
            
            # Write meta-data
            meta_data_path = Path(tmpdir) / "meta-data"
            meta_data_path.write_text(f"instance-id: {config.name}\nlocal-hostname: {config.name}\n")
            
            # Create ISO
            iso_path = Path(tmpdir) / "cloud-init.iso"
            cmd = [
                "mkisofs",
                "-o", str(iso_path),
                "-V", "cidata",
                "-J", "-r",
                str(user_data_path),
                str(meta_data_path),
            ]
            
            subprocess.run(cmd, check=True)
            
            # Copy to final location
            iso_dir = Path("/var/lib/libvirt/images") if not self.user_session else Path.home() / ".local/share/libvirt/images"
            iso_dir.mkdir(parents=True, exist_ok=True)
            
            final_iso_path = iso_dir / f"{config.name}-cloud-init.iso"
            shutil.copy2(iso_path, final_iso_path)
            
            return str(final_iso_path)

    def _setup_vm_networking(self, vm, config: VMConfig) -> None:
        """Setup networking for VM."""
        
        # Network setup is handled in the VM XML
        # Additional network configuration can be done here if needed
        pass

    def _wait_for_ip(self, vm, timeout: int = 60) -> Optional[str]:
        """Wait for VM to get an IP address."""
        
        for _ in range(timeout):
            ip = self._get_vm_ip(vm)
            if ip:
                return ip
            time.sleep(1)
        
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

    def _open_viewer(self, vm_name: str) -> None:
        """Open SPICE/VNC viewer for VM."""
        
        cmd = ["virt-viewer", "--connect", self.conn_uri, vm_name]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
            "/var/lib/libvirt/base-images/ubuntu-22.04.qcow2",
            "/var/lib/libvirt/images/ubuntu-22.04.qcow2",
            "/usr/share/clonebox/images/ubuntu-22.04.qcow2",
        ]
        
        for path in paths:
            if os.path.exists(path):
                return path
        
        raise FileNotFoundError("No base image found. Please download or specify one.")

    def __del__(self):
        """Cleanup libvirt connection."""
        
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.close()
            except:
                pass
