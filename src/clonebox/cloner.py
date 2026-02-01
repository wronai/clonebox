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
import string
import subprocess
import tempfile
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
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
from clonebox.resources import ResourceLimits
from clonebox.rollback import vm_creation_transaction
from clonebox.secrets import SecretsManager, SSHKeyPair

log = get_logger(__name__)

SNAP_INTERFACES = {
    "pycharm-community": [
        "desktop",
        "desktop-legacy",
        "x11",
        "wayland",
        "home",
        "network",
        "network-bind",
        "cups-control",
        "removable-media",
    ],
    "chromium": [
        "desktop",
        "desktop-legacy",
        "x11",
        "wayland",
        "home",
        "network",
        "audio-playback",
        "camera",
    ],
    "firefox": [
        "desktop",
        "desktop-legacy",
        "x11",
        "wayland",
        "home",
        "network",
        "audio-playback",
        "removable-media",
    ],
    "code": ["desktop", "desktop-legacy", "x11", "wayland", "home", "network", "ssh-keys"],
    "slack": ["desktop", "desktop-legacy", "x11", "wayland", "home", "network", "audio-playback"],
    "spotify": ["desktop", "x11", "wayland", "home", "network", "audio-playback"],
}
DEFAULT_SNAP_INTERFACES = ["desktop", "desktop-legacy", "x11", "home", "network"]


@dataclass
class VMConfig:
    """Configuration for the VM to create."""

    name: str = field(default_factory=lambda: os.getenv("VM_NAME", "clonebox-vm"))
    ram_mb: int = field(default_factory=lambda: int(os.getenv("VM_RAM_MB", "8192")))
    vcpus: int = field(default_factory=lambda: int(os.getenv("VM_VCPUS", "4")))
    disk_size_gb: int = field(default_factory=lambda: int(os.getenv("VM_DISK_SIZE_GB", "20")))
    gui: bool = field(default_factory=lambda: os.getenv("VM_GUI", "true").lower() == "true")
    base_image: Optional[str] = field(default_factory=lambda: os.getenv("VM_BASE_IMAGE") or None)
    paths: dict = field(default_factory=dict)
    packages: list = field(default_factory=list)
    snap_packages: list = field(default_factory=list)  # Snap packages to install
    services: list = field(default_factory=list)
    post_commands: list = field(default_factory=list)  # Commands to run after setup
    user_session: bool = field(
        default_factory=lambda: os.getenv("VM_USER_SESSION", "false").lower() == "true"
    )  # Use qemu:///session instead of qemu:///system
    network_mode: str = field(
        default_factory=lambda: os.getenv("VM_NETWORK_MODE", "auto")
    )  # auto|default|user
    username: str = field(
        default_factory=lambda: os.getenv("VM_USERNAME", "ubuntu")
    )  # VM default username
    password: str = field(
        default_factory=lambda: os.getenv("VM_PASSWORD", "ubuntu")
    )  # VM default password
    autostart_apps: bool = field(
        default_factory=lambda: os.getenv("VM_AUTOSTART_APPS", "true").lower() == "true"
    )  # Auto-start GUI apps after login (desktop autostart)
    web_services: list = field(default_factory=list)  # Web services to start (uvicorn, etc.)
    resources: dict = field(default_factory=dict)  # Resource limits (cpu, memory, disk, network)
    auth_method: str = "ssh_key"  # ssh_key | one_time_password | password
    ssh_public_key: Optional[str] = None
    shutdown_after_setup: bool = False

    def to_dict(self) -> dict:
        return {
            "paths": self.paths,
            "packages": self.packages,
            "services": self.services,
        }


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
        container = get_container()

        # Resolve dependencies
        self.hypervisor = hypervisor or container.resolve(HypervisorBackend)
        self.disk = disk_manager or container.resolve(DiskManager)
        # self.network = network_manager or container.resolve(NetworkManager)
        self.secrets = secrets_manager or container.resolve(SecretsManager)

        if conn_uri:
            self.conn_uri = conn_uri
        else:
            self.conn_uri = "qemu:///session" if user_session else "qemu:///system"

        self.conn = None
        self._connect()

    @property
    def SYSTEM_IMAGES_DIR(self) -> Path:
        return Path(os.getenv("CLONEBOX_SYSTEM_IMAGES_DIR", "/var/lib/libvirt/images"))

    @property
    def USER_IMAGES_DIR(self) -> Path:
        return Path(
            os.getenv("CLONEBOX_USER_IMAGES_DIR", str(Path.home() / ".local/share/libvirt/images"))
        ).expanduser()

    @property
    def DEFAULT_BASE_IMAGE_URL(self) -> str:
        return os.getenv(
            "CLONEBOX_BASE_IMAGE_URL",
            "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        )

    @property
    def DEFAULT_BASE_IMAGE_FILENAME(self) -> str:
        return os.getenv("CLONEBOX_BASE_IMAGE_FILENAME", "clonebox-ubuntu-jammy-amd64.qcow2")

    def _connect(self):
        """Connect to libvirt."""
        if libvirt is None:
            raise ImportError(
                "libvirt-python is required. Install with: pip install libvirt-python\n"
                "Also ensure libvirt is installed: sudo apt install libvirt-daemon-system"
            )

        try:
            self.conn = libvirt.open(self.conn_uri)
        except libvirt.libvirtError as e:
            raise ConnectionError(
                f"Cannot connect to {self.conn_uri}\n"
                f"Error: {e}\n\n"
                f"Troubleshooting:\n"
                f"  1. Check if libvirtd is running: sudo systemctl status libvirtd\n"
                f"  2. Start libvirtd: sudo systemctl start libvirtd\n"
                f"  3. Add user to libvirt group: sudo usermod -aG libvirt $USER\n"
                f"  4. Re-login or run: newgrp libvirt\n"
                f"  5. For user session (no sudo): use --user flag"
            )

        if self.conn is None:
            raise ConnectionError(f"Cannot connect to {self.conn_uri}")

    def get_images_dir(self) -> Path:
        """Get the appropriate images directory based on session type."""
        if self.user_session:
            return self.USER_IMAGES_DIR
        return self.SYSTEM_IMAGES_DIR

    def _get_downloads_dir(self) -> Path:
        return Path.home() / "Downloads"

    def _ensure_default_base_image(self, console=None) -> Path:
        """Ensure a default Ubuntu 22.04 base image is available."""
        with log_operation(log, "vm.ensure_base_image"):
            downloads_dir = self._get_downloads_dir()
            downloads_dir.mkdir(parents=True, exist_ok=True)
            cached_path = downloads_dir / self.DEFAULT_BASE_IMAGE_FILENAME

            if cached_path.exists() and cached_path.stat().st_size > 0:
                return cached_path

            log.info(
                "Downloading base image (first run only). This will be cached in ~/Downloads...",
                url=self.DEFAULT_BASE_IMAGE_URL,
            )

            try:
                import urllib.request

                with tempfile.NamedTemporaryFile(
                    prefix=f"{self.DEFAULT_BASE_IMAGE_FILENAME}.",
                    dir=str(downloads_dir),
                    delete=False,
                ) as tmp:
                    tmp_path = Path(tmp.name)

                try:
                    urllib.request.urlretrieve(self.DEFAULT_BASE_IMAGE_URL, tmp_path)
                    tmp_path.replace(cached_path)
                finally:
                    if tmp_path.exists() and tmp_path != cached_path:
                        try:
                            tmp_path.unlink()
                        except Exception:
                            pass
            except Exception as e:
                log.error(f"Failed to download base image: {e}")
                raise RuntimeError(
                    "Failed to download a default base image.\n\n"
                    "🔧 Solutions:\n"
                    "  1. Provide a base image explicitly:\n"
                    "     clonebox clone . --base-image /path/to/image.qcow2\n"
                    "  2. Download it manually and reuse it:\n"
                    f"     wget -O {cached_path} {self.DEFAULT_BASE_IMAGE_URL}\n\n"
                    f"Original error: {e}"
                ) from e

            return cached_path

    def _default_network_active(self) -> bool:
        """Check if libvirt default network is active."""
        try:
            net = self.conn.networkLookupByName("default")
            return net.isActive() == 1
        except Exception:
            return False

    def resolve_network_mode(self, config: VMConfig) -> str:
        """Resolve network mode based on config and session type."""
        mode = (config.network_mode or "auto").lower()
        if mode == "auto":
            if self.user_session and not self._default_network_active():
                return "user"
            return "default"
        if mode in {"default", "user"}:
            return mode
        return "default"

    def check_prerequisites(self) -> dict:
        """Check system prerequisites for VM creation."""
        images_dir = self.get_images_dir()

        checks = {
            "libvirt_connected": False,
            "kvm_available": False,
            "default_network": False,
            "images_dir_writable": False,
            "images_dir": str(images_dir),
            "session_type": "user" if self.user_session else "system",
        }

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
        try:
            net = self.conn.networkLookupByName("default")
            checks["default_network"] = net.isActive() == 1
        except libvirt.libvirtError:
            checks["network_error"] = (
                "Default network not found or inactive.\n"
                "  For user session, CloneBox can use user-mode networking (slirp) automatically.\n"
                "  Or create a user network:\n"
                "    virsh --connect qemu:///session net-define /tmp/default-network.xml\n"
                "    virsh --connect qemu:///session net-start default\n"
                "  Or use system session: clonebox clone . (without --user)\n"
            )

        # Check images directory
        if images_dir.exists():
            checks["images_dir_writable"] = os.access(images_dir, os.W_OK)
            if not checks["images_dir_writable"]:
                checks["images_dir_error"] = (
                    f"Cannot write to {images_dir}\n"
                    f"  Option 1: Run with sudo\n"
                    f"  Option 2: Use --user flag for user session (no root needed)\n"
                    f"  Option 3: Fix permissions: sudo chown -R $USER:libvirt {images_dir}"
                )
        else:
            # Try to create it
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

    def create_vm(self, config: VMConfig, console=None, replace: bool = False) -> str:
        """
        Create a VM with only selected applications/paths.

        Args:
            config: VMConfig with paths, packages, services
            console: Rich console for output (optional)

        Returns:
            UUID of created VM
        """
        with log_operation(
            log, "vm.create", vm_name=config.name, ram_mb=config.ram_mb
        ):
            with vm_creation_transaction(self, config, console) as ctx:
                # If VM already exists, optionally replace it
                existing_vm = None
                try:
                    candidate_vm = self.conn.lookupByName(config.name)
                    if candidate_vm is not None:
                        try:
                            if hasattr(candidate_vm, "name") and callable(candidate_vm.name):
                                if candidate_vm.name() == config.name:
                                    existing_vm = candidate_vm
                            else:
                                existing_vm = candidate_vm
                        except Exception:
                            existing_vm = candidate_vm
                except Exception:
                    existing_vm = None

                if existing_vm is not None:
                    if not replace:
                        raise RuntimeError(
                            f"VM '{config.name}' already exists.\n\n"
                            f"🔧 Solutions:\n"
                            f"  1. Reuse existing VM: clonebox start {config.name}\n"
                            f"  2. Replace it: clonebox clone . --name {config.name} --replace\n"
                            f"  3. Delete it: clonebox delete {config.name}\n"
                        )

                    log.info(f"VM '{config.name}' already exists - replacing...")
                    self.delete_vm(config.name, delete_storage=True, console=console, ignore_not_found=True)

                # Determine images directory
                images_dir = self.get_images_dir()
                try:
                    vm_dir = ctx.add_directory(images_dir / config.name)
                    vm_dir.mkdir(parents=True, exist_ok=True)
                except PermissionError as e:
                    raise PermissionError(
                        f"Cannot create VM directory: {images_dir / config.name}\n\n"
                        f"🔧 Solutions:\n"
                        f"  1. Use --user flag to run in user session (recommended):\n"
                        f"     clonebox clone . --user\n\n"
                        f"  2. Run with sudo (not recommended):\n"
                        f"     sudo clonebox clone .\n\n"
                        f"  3. Fix directory permissions:\n"
                        f"     sudo mkdir -p {images_dir}\n"
                        f"     sudo chown -R $USER:libvirt {images_dir}\n\n"
                        f"Original error: {e}"
                    ) from e

                # Create root disk
                root_disk = ctx.add_file(vm_dir / "root.qcow2")

                if not config.base_image:
                    config.base_image = str(self._ensure_default_base_image(console=console))

                if config.base_image and Path(config.base_image).exists():
                    # Use backing file for faster creation
                    log.debug(f"Creating disk with backing file: {config.base_image}")
                    cmd = [
                        "qemu-img",
                        "create",
                        "-f",
                        "qcow2",
                        "-b",
                        config.base_image,
                        "-F",
                        "qcow2",
                        str(root_disk),
                        f"{config.disk_size_gb}G",
                    ]
                else:
                    # Create empty disk
                    log.debug(f"Creating empty {config.disk_size_gb}GB disk...")
                    cmd = ["qemu-img", "create", "-f", "qcow2", str(root_disk), f"{config.disk_size_gb}G"]

                subprocess.run(cmd, check=True, capture_output=True)

                # Create cloud-init ISO if packages/services specified
                cloudinit_iso = None
                if (
                    config.packages
                    or config.services
                    or config.snap_packages
                    or config.post_commands
                    or config.gui
                ):
                    cloudinit_iso = ctx.add_file(self._create_cloudinit_iso(vm_dir, config))
                    log.info(f"Created cloud-init ISO with {len(config.packages)} packages")

                # Generate VM XML
                vm_xml = self._generate_vm_xml(config, root_disk, cloudinit_iso)
                ctx.add_libvirt_domain(self.conn, config.name)

                # Define VM
                log.info(f"Defining VM '{config.name}'...")
                try:
                    vm = self.conn.defineXML(vm_xml)
                except Exception as e:
                    raise RuntimeError(
                        f"Failed to define VM '{config.name}'.\n"
                        f"Error: {e}\n\n"
                        f"If the VM already exists, try: clonebox clone . --name {config.name} --replace\n"
                    ) from e

                # Start if autostart requested
                if getattr(config, "autostart", False):
                    self.start_vm(config.name, open_viewer=True)

                # All good - commit transaction
                ctx.commit()

                return vm.UUIDString()

    def _generate_vm_xml(
        self, config: VMConfig = None, root_disk: Path = None, cloudinit_iso: Optional[Path] = None
    ) -> str:
        """Generate libvirt XML for the VM."""

        # Backward compatibility: if called without args, try to derive defaults
        if config is None:
            config = VMConfig()
        if root_disk is None:
            root_disk = Path("/var/lib/libvirt/images/default-disk.qcow2")

        # Get resource limits from config or defaults
        resource_data = getattr(config, "resources", {})
        if not resource_data:
            # Fallback to top-level fields
            resource_data = {
                "cpu": {"vcpus": config.vcpus},
                "memory": {"limit": f"{config.ram_mb}M"},
            }
        
        limits = ResourceLimits.from_dict(resource_data)

        root = ET.Element("domain", type="kvm")

        # Basic metadata
        ET.SubElement(root, "name").text = config.name
        ET.SubElement(root, "uuid").text = str(uuid.uuid4())
        
        # Memory configuration using limits
        limit_kib = limits.memory.limit_bytes // 1024
        ET.SubElement(root, "memory", unit="KiB").text = str(limit_kib)
        ET.SubElement(root, "currentMemory", unit="KiB").text = str(limit_kib)
        
        # CPU configuration
        ET.SubElement(root, "vcpu", placement="static").text = str(limits.cpu.vcpus)

        # OS configuration
        os_elem = ET.SubElement(root, "os")
        ET.SubElement(os_elem, "type", arch="x86_64", machine="q35").text = "hvm"
        ET.SubElement(os_elem, "boot", dev="hd")

        # Features
        features = ET.SubElement(root, "features")
        ET.SubElement(features, "acpi")
        ET.SubElement(features, "apic")

        # Resource tuning (CPU and Memory)
        cputune_xml = limits.cpu.to_libvirt_xml()
        if cputune_xml:
            # We append pre-generated XML string later or use ET to parse it
            # For simplicity with existing ET code, we'll use SubElement for basic ones 
            # and manual string insertion for complex tuning if needed, 
            # but let's try to stick to ET where possible.
            pass

        # CPU tuning element
        if limits.cpu.shares or limits.cpu.quota or limits.cpu.pin:
            cputune = ET.SubElement(root, "cputune")
            ET.SubElement(cputune, "shares").text = str(limits.cpu.shares)
            if limits.cpu.quota:
                ET.SubElement(cputune, "period").text = str(limits.cpu.period)
                ET.SubElement(cputune, "quota").text = str(limits.cpu.quota)
            if limits.cpu.pin:
                for idx, cpu in enumerate(limits.cpu.pin):
                    ET.SubElement(cputune, "vcpupin", vcpu=str(idx), cpuset=str(cpu))

        # Memory tuning element
        if limits.memory.soft_limit or limits.memory.swap:
            memtune = ET.SubElement(root, "memtune")
            ET.SubElement(memtune, "hard_limit", unit="KiB").text = str(limit_kib)
            if limits.memory.soft_limit_bytes:
                ET.SubElement(memtune, "soft_limit", unit="KiB").text = str(limits.memory.soft_limit_bytes // 1024)
            if limits.memory.swap_bytes:
                ET.SubElement(memtune, "swap_hard_limit", unit="KiB").text = str(limits.memory.swap_bytes // 1024)

        # CPU
        ET.SubElement(root, "cpu", mode="host-passthrough", check="none")

        # Devices
        devices = ET.SubElement(root, "devices")

        # Emulator
        ET.SubElement(devices, "emulator").text = "/usr/bin/qemu-system-x86_64"

        # Root disk
        disk = ET.SubElement(devices, "disk", type="file", device="disk")
        ET.SubElement(disk, "driver", name="qemu", type="qcow2", cache="writeback")
        ET.SubElement(disk, "source", file=str(root_disk))
        ET.SubElement(disk, "target", dev="vda", bus="virtio")
        
        # Disk I/O tuning
        if limits.disk.read_bps or limits.disk.write_bps or limits.disk.read_iops or limits.disk.write_iops:
            iotune = ET.SubElement(disk, "iotune")
            if limits.disk.read_bps_bytes:
                ET.SubElement(iotune, "read_bytes_sec").text = str(limits.disk.read_bps_bytes)
            if limits.disk.write_bps_bytes:
                ET.SubElement(iotune, "write_bytes_sec").text = str(limits.disk.write_bps_bytes)
            if limits.disk.read_iops:
                ET.SubElement(iotune, "read_iops_sec").text = str(limits.disk.read_iops)
            if limits.disk.write_iops:
                ET.SubElement(iotune, "write_iops_sec").text = str(limits.disk.write_iops)

        # Cloud-init ISO
        if cloudinit_iso:
            cdrom = ET.SubElement(devices, "disk", type="file", device="cdrom")
            ET.SubElement(cdrom, "driver", name="qemu", type="raw")
            ET.SubElement(cdrom, "source", file=str(cloudinit_iso))
            ET.SubElement(cdrom, "target", dev="sda", bus="sata")
            ET.SubElement(cdrom, "readonly")

        # 9p filesystem mounts (bind mounts from host)
        # Use accessmode="mapped" to allow VM user to access host files regardless of UID
        for idx, (host_path, guest_tag) in enumerate(config.paths.items()):
            if Path(host_path).exists():
                fs = ET.SubElement(devices, "filesystem", type="mount", accessmode="mapped")
                ET.SubElement(fs, "driver", type="path", wrpolicy="immediate")
                ET.SubElement(fs, "source", dir=host_path)
                # Use simple tag names for 9p mounts
                tag = f"mount{idx}"
                ET.SubElement(fs, "target", dir=tag)

        # Network interface
        network_mode = self.resolve_network_mode(config)
        if network_mode == "user":
            iface = ET.SubElement(devices, "interface", type="user")
            ET.SubElement(iface, "model", type="virtio")
        else:
            iface = ET.SubElement(devices, "interface", type="network")
            ET.SubElement(iface, "source", network="default")
            ET.SubElement(iface, "model", type="virtio")
        
        # Network bandwidth tuning
        if limits.network.inbound or limits.network.outbound:
            bandwidth = ET.SubElement(iface, "bandwidth")
            if limits.network.inbound_kbps:
                # average in KB/s
                ET.SubElement(bandwidth, "inbound", average=str(limits.network.inbound_kbps // 8))
            if limits.network.outbound_kbps:
                ET.SubElement(bandwidth, "outbound", average=str(limits.network.outbound_kbps // 8))

        # Serial console
        serial = ET.SubElement(devices, "serial", type="pty")
        ET.SubElement(serial, "target", port="0")

        console_elem = ET.SubElement(devices, "console", type="pty")
        ET.SubElement(console_elem, "target", type="serial", port="0")

        # Graphics (SPICE)
        if config.gui:
            graphics = ET.SubElement(
                devices, "graphics", type="spice", autoport="yes", listen="127.0.0.1"
            )
            ET.SubElement(graphics, "listen", type="address", address="127.0.0.1")

            # Video
            video = ET.SubElement(devices, "video")
            ET.SubElement(video, "model", type="virtio", heads="1", primary="yes")

            # Input devices
            ET.SubElement(devices, "input", type="tablet", bus="usb")
            ET.SubElement(devices, "input", type="keyboard", bus="usb")

        ET.SubElement(devices, "controller", type="virtio-serial", index="0")

        # Channel for guest agent
        channel = ET.SubElement(devices, "channel", type="unix")
        ET.SubElement(channel, "source", mode="bind")
        ET.SubElement(channel, "target", type="virtio", name="org.qemu.guest_agent.0")

        # Memory balloon
        memballoon = ET.SubElement(devices, "memballoon", model="virtio")
        ET.SubElement(
            memballoon,
            "address",
            type="pci",
            domain="0x0000",
            bus="0x00",
            slot="0x08",
            function="0x0",
        )

        return ET.tostring(root, encoding="unicode")

    def _generate_boot_diagnostic_script(self, config: VMConfig) -> str:
        """Generate boot diagnostic script with self-healing capabilities."""
        import base64

        wants_google_chrome = any(
            p == "/home/ubuntu/.config/google-chrome" for p in (config.paths or {}).values()
        )

        apt_pkg_list = list(config.packages or [])
        for base_pkg in ["qemu-guest-agent", "cloud-guest-utils"]:
            if base_pkg not in apt_pkg_list:
                apt_pkg_list.insert(0, base_pkg)
        if config.gui:
            for gui_pkg in ["ubuntu-desktop-minimal", "firefox"]:
                if gui_pkg not in apt_pkg_list:
                    apt_pkg_list.append(gui_pkg)

        apt_packages = " ".join(f'"{p}"' for p in apt_pkg_list) if apt_pkg_list else ""
        snap_packages = (
            " ".join(f'"{p}"' for p in config.snap_packages) if config.snap_packages else ""
        )
        services = " ".join(f'"{s}"' for s in config.services) if config.services else ""

        snap_ifaces_bash = "\n".join(
            f'SNAP_INTERFACES["{snap}"]="{" ".join(ifaces)}"'
            for snap, ifaces in SNAP_INTERFACES.items()
        )

        script = f"""#!/bin/bash
set -uo pipefail
LOG="/var/log/clonebox-boot.log"
STATUS_KV="/var/run/clonebox-status"
STATUS_JSON="/var/run/clonebox-status.json"
MAX_RETRIES=3
PASSED=0 FAILED=0 REPAIRED=0 TOTAL=0

RED='\\033[0;31m' GREEN='\\033[0;32m' YELLOW='\\033[1;33m' CYAN='\\033[0;36m' NC='\\033[0m' BOLD='\\033[1m'

log() {{ echo -e "[$(date +%H:%M:%S)] $1" | tee -a "$LOG"; }}
ok() {{ log "${{GREEN}}✅ $1${{NC}}"; ((PASSED++)); ((TOTAL++)); }}
fail() {{ log "${{RED}}❌ $1${{NC}}"; ((FAILED++)); ((TOTAL++)); }}
repair() {{ log "${{YELLOW}}🔧 $1${{NC}}"; }}
section() {{ log ""; log "${{BOLD}}[$1] $2${{NC}}"; }}

write_status() {{
    local phase="$1"
    local current_task="${{2:-}}"
    printf 'passed=%s failed=%s repaired=%s\n' "$PASSED" "$FAILED" "$REPAIRED" > "$STATUS_KV" 2>/dev/null || true
    cat > "$STATUS_JSON" <<EOF
{{"phase":"$phase","current_task":"$current_task","total":$TOTAL,"passed":$PASSED,"failed":$FAILED,"repaired":$REPAIRED,"timestamp":"$(date -Iseconds)"}}
EOF
}}

header() {{
    log ""
    log "${{BOLD}}${{CYAN}}═══════════════════════════════════════════════════════════${{NC}}"
    log "${{BOLD}}${{CYAN}}  $1${{NC}}"
    log "${{BOLD}}${{CYAN}}═══════════════════════════════════════════════════════════${{NC}}"
}}

declare -A SNAP_INTERFACES
{snap_ifaces_bash}
DEFAULT_IFACES="desktop desktop-legacy x11 home network"

check_apt() {{
    dpkg -l "$1" 2>/dev/null | grep -q "^ii"
}}

install_apt() {{
    for i in $(seq 1 $MAX_RETRIES); do
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$1" &>>"$LOG" && return 0
        sleep 3
    done
    return 1
}}

check_snap() {{
    snap list "$1" &>/dev/null
}}

install_snap() {{
    timeout 60 snap wait system seed.loaded 2>/dev/null || true
    for i in $(seq 1 $MAX_RETRIES); do
        snap install "$1" --classic &>>"$LOG" && return 0
        snap install "$1" &>>"$LOG" && return 0
        sleep 5
    done
    return 1
}}

connect_interfaces() {{
    local snap="$1"
    local ifaces="${{SNAP_INTERFACES[$snap]:-$DEFAULT_IFACES}}"
    for iface in $ifaces; do
        snap connect "$snap:$iface" ":$iface" 2>/dev/null && log "    ${{GREEN}}✓${{NC}} $snap:$iface" || true
    done
}}

test_launch() {{
    local app="$1"
    local temp_output="/tmp/$app-test.log"
    local error_detail="/tmp/$app-error.log"
    
    case "$app" in
        pycharm-community) 
            if timeout 10 /snap/pycharm-community/current/jbr/bin/java -version &>"$temp_output"; then
                return 0
            else
                echo "PyCharm Java test failed:" >> "$error_detail"
                cat "$temp_output" >> "$error_detail" 2>&1 || true
                return 1
            fi
            ;;
        chromium) 
            # First check if chromium can run at all
            if ! command -v chromium >/dev/null 2>&1; then
                echo "ERROR: chromium not found in PATH" >> "$error_detail"
                echo "PATH=$PATH" >> "$error_detail"
                return 1
            fi
            
            # Try with different approaches
            if timeout 10 chromium --headless=new --dump-dom about:blank &>"$temp_output" 2>&1; then
                return 0
            else
                echo "Chromium headless test failed:" >> "$error_detail"
                cat "$temp_output" >> "$error_detail"
                
                # Try basic version check
                echo "Trying chromium --version:" >> "$error_detail"
                timeout 5 chromium --version >> "$error_detail" 2>&1 || true
                
                # Check display
                echo "Display check:" >> "$error_detail"
                echo "DISPLAY=${{DISPLAY:-unset}}" >> "$error_detail"
                echo "XDG_RUNTIME_DIR=${{XDG_RUNTIME_DIR:-unset}}" >> "$error_detail"
                ls -la /tmp/.X11-unix/ >> "$error_detail" 2>&1 || true
                
                return 1
            fi
            ;;
        firefox) 
            if timeout 15 firefox --headless --version &>/dev/null; then
                return 0
            else
                echo "Firefox test failed" >> "$error_detail"
                return 1
            fi
            ;;
        google-chrome|google-chrome-stable)
            if timeout 15 google-chrome-stable --headless --version &>/dev/null; then
                return 0
            else
                echo "Chrome test failed" >> "$error_detail"
                return 1
            fi
            ;;
        docker) 
            if docker info &>/dev/null; then
                return 0
            else
                echo "Docker info failed:" >> "$error_detail"
                docker info >> "$error_detail" 2>&1 || true
                return 1
            fi
            ;;
        *) 
            if command -v "$1" &>/dev/null; then
                return 0
            else
                echo "Command not found: $1" >> "$error_detail"
                echo "PATH=$PATH" >> "$error_detail"
                return 1
            fi
            ;;
    esac
}}

header "CloneBox VM Boot Diagnostic"
write_status "starting" "boot diagnostic starting"

APT_PACKAGES=({apt_packages})
SNAP_PACKAGES=({snap_packages})
SERVICES=({services})
VM_USER="${{SUDO_USER:-ubuntu}}"
VM_HOME="/home/$VM_USER"

# ═══════════════════════════════════════════════════════════════════════════════
# Section 0: Fix permissions for GNOME directories (runs first!)
# ═══════════════════════════════════════════════════════════════════════════════
section "0/7" "Fixing directory permissions..."
write_status "fixing_permissions" "fixing directory permissions"

GNOME_DIRS=(
    "$VM_HOME/.config"
    "$VM_HOME/.config/pulse"
    "$VM_HOME/.config/dconf"
    "$VM_HOME/.config/ibus"
    "$VM_HOME/.cache"
    "$VM_HOME/.cache/ibus"
    "$VM_HOME/.cache/tracker3"
    "$VM_HOME/.cache/mesa_shader_cache"
    "$VM_HOME/.local"
    "$VM_HOME/.local/share"
    "$VM_HOME/.local/share/applications"
    "$VM_HOME/.local/share/keyrings"
)

for dir in "${{GNOME_DIRS[@]}}"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir" 2>/dev/null && log "    Created $dir" || true
    fi
done

# Fix ownership for all critical directories
chown -R 1000:1000 "$VM_HOME/.config" "$VM_HOME/.cache" "$VM_HOME/.local" 2>/dev/null || true
chmod 700 "$VM_HOME/.config" "$VM_HOME/.cache" 2>/dev/null || true

# Fix snap directories ownership
for snap_dir in "$VM_HOME/snap"/*; do
    [ -d "$snap_dir" ] && chown -R 1000:1000 "$snap_dir" 2>/dev/null || true
done

ok "Directory permissions fixed"

section "1/7" "Checking APT packages..."
write_status "checking_apt" "checking APT packages"
for pkg in "${{APT_PACKAGES[@]}}"; do
    [ -z "$pkg" ] && continue
    if check_apt "$pkg"; then
        ok "$pkg"
    else
        repair "Installing $pkg..."
        if install_apt "$pkg"; then
            ok "$pkg installed"
            ((REPAIRED++))
        else
            fail "$pkg FAILED"
        fi
    fi
done

section "2/7" "Checking Snap packages..."
write_status "checking_snaps" "checking snap packages"
timeout 120 snap wait system seed.loaded 2>/dev/null || true
for pkg in "${{SNAP_PACKAGES[@]}}"; do
    [ -z "$pkg" ] && continue
    if check_snap "$pkg"; then
        ok "$pkg (snap)"
    else
        repair "Installing $pkg..."
        if install_snap "$pkg"; then
            ok "$pkg installed"
            ((REPAIRED++))
        else
            fail "$pkg FAILED"
        fi
    fi
done

section "3/7" "Connecting Snap interfaces..."
write_status "connecting_interfaces" "connecting snap interfaces"
for pkg in "${{SNAP_PACKAGES[@]}}"; do
    [ -z "$pkg" ] && continue
    check_snap "$pkg" && connect_interfaces "$pkg"
done
systemctl restart snapd 2>/dev/null || true

section "4/7" "Testing application launch..."
write_status "testing_launch" "testing application launch"
APPS_TO_TEST=()
for pkg in "${{SNAP_PACKAGES[@]}}"; do
    [ -z "$pkg" ] && continue
    APPS_TO_TEST+=("$pkg")
done
if [ "{str(wants_google_chrome).lower()}" = "true" ]; then
    APPS_TO_TEST+=("google-chrome")
fi
if printf '%s\n' "${{APT_PACKAGES[@]}}" | grep -qx "docker.io"; then
    APPS_TO_TEST+=("docker")
fi

for app in "${{APPS_TO_TEST[@]}}"; do
    [ -z "$app" ] && continue
    case "$app" in
        google-chrome)
            if ! command -v google-chrome >/dev/null 2>&1 && ! command -v google-chrome-stable >/dev/null 2>&1; then
                repair "Installing google-chrome..."
                tmp_deb="/tmp/google-chrome-stable_current_amd64.deb"
                if curl -fsSL -o "$tmp_deb" "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb" \
                    && DEBIAN_FRONTEND=noninteractive apt-get install -y "$tmp_deb" &>>"$LOG"; then
                    rm -f "$tmp_deb"
                    ((REPAIRED++))
                else
                    rm -f "$tmp_deb" 2>/dev/null || true
                fi
            fi
            ;;
        docker)
            check_apt "docker.io" || continue
            ;;
        *)
            if check_snap "$app"; then
                :
            else
                continue
            fi
            ;;
    esac

    if test_launch "$app"; then
        ok "$app launches OK"
    else
        fail "$app launch test FAILED"
        # Show error details in main log
        if [ -f "/tmp/$app-error.log" ]; then
            echo "  Error details:" | tee -a "$LOG"
            head -10 "/tmp/$app-error.log" | sed 's/^/    /' | tee -a "$LOG" || true
        fi
    fi
done

section "5/7" "Checking mount points..."
write_status "checking_mounts" "checking mount points"
while IFS= read -r line; do
    tag=$(echo "$line" | awk '{{print $1}}')
    mp=$(echo "$line" | awk '{{print $2}}')
    if [[ "$tag" =~ ^mount[0-9]+$ ]] && [[ "$mp" == /* ]]; then
        if mountpoint -q "$mp" 2>/dev/null; then
            ok "$mp mounted"
        else
            repair "Mounting $mp..."
            mkdir -p "$mp" 2>/dev/null || true
            if mount "$mp" &>>"$LOG"; then
                ok "$mp mounted"
                ((REPAIRED++))
            else
                fail "$mp mount FAILED"
            fi
        fi
    fi
done < /etc/fstab

section "6/7" "Checking services..."
write_status "checking_services" "checking services"
for svc in "${{SERVICES[@]}}"; do
    [ -z "$svc" ] && continue
    if systemctl is-active "$svc" &>/dev/null; then
        ok "$svc running"
    else
        repair "Starting $svc..."
        systemctl enable --now "$svc" &>/dev/null && ok "$svc started" && ((REPAIRED++)) || fail "$svc FAILED"
    fi
done

header "Diagnostic Summary"
log ""
log "  Total:    $TOTAL"
log "  ${{GREEN}}Passed:${{NC}}   $PASSED"
log "  ${{YELLOW}}Repaired:${{NC}} $REPAIRED"
log "  ${{RED}}Failed:${{NC}}   $FAILED"
log ""

write_status "complete" "complete"

if [ $FAILED -eq 0 ]; then
    log "${{GREEN}}${{BOLD}}═══════════════════════════════════════════════════════════${{NC}}"
    log "${{GREEN}}${{BOLD}}  ✅ All checks passed! CloneBox VM is ready.${{NC}}"
    log "${{GREEN}}${{BOLD}}═══════════════════════════════════════════════════════════${{NC}}"
    exit 0
else
    log "${{RED}}${{BOLD}}═══════════════════════════════════════════════════════════${{NC}}"
    log "${{RED}}${{BOLD}}  ⚠️  $FAILED checks failed. See /var/log/clonebox-boot.log${{NC}}"
    log "${{RED}}${{BOLD}}═══════════════════════════════════════════════════════════${{NC}}"
    exit 1
fi
"""
        return base64.b64encode(script.encode()).decode()

    def _generate_health_check_script(self, config: VMConfig) -> str:
        """Generate a health check script that validates all installed components."""
        import base64

        # Build package check commands
        apt_checks = []
        for pkg in config.packages:
            apt_checks.append(f'check_apt_package "{pkg}"')

        snap_checks = []
        for pkg in config.snap_packages:
            snap_checks.append(f'check_snap_package "{pkg}"')

        service_checks = []
        for svc in config.services:
            service_checks.append(f'check_service "{svc}"')

        mount_checks = []
        for idx, (host_path, guest_path) in enumerate(config.paths.items()):
            mount_checks.append(f'check_mount "{guest_path}" "mount{idx}"')

        apt_checks_str = "\n".join(apt_checks) if apt_checks else "echo 'No apt packages to check'"
        snap_checks_str = (
            "\n".join(snap_checks) if snap_checks else "echo 'No snap packages to check'"
        )
        service_checks_str = (
            "\n".join(service_checks) if service_checks else "echo 'No services to check'"
        )
        mount_checks_str = "\n".join(mount_checks) if mount_checks else "echo 'No mounts to check'"

        script = f"""#!/bin/bash
# CloneBox Health Check Script
# Generated automatically - validates all installed components

REPORT_FILE="/var/log/clonebox-health.log"
PASSED=0
FAILED=0
WARNINGS=0

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m'

log() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$REPORT_FILE"
}}

check_apt_package() {{
    local pkg="$1"
    if dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
        log "[PASS] APT package '$pkg' is installed"
        ((PASSED++))
        return 0
    else
        log "[FAIL] APT package '$pkg' is NOT installed"
        ((FAILED++))
        return 1
    fi
}}

check_snap_package() {{
    local pkg="$1"
    if snap list "$pkg" &>/dev/null; then
        log "[PASS] Snap package '$pkg' is installed"
        ((PASSED++))
        return 0
    else
        log "[FAIL] Snap package '$pkg' is NOT installed"
        ((FAILED++))
        return 1
    fi
}}

check_service() {{
    local svc="$1"
    if systemctl is-enabled "$svc" &>/dev/null; then
        if systemctl is-active "$svc" &>/dev/null; then
            log "[PASS] Service '$svc' is enabled and running"
            ((PASSED++))
            return 0
        else
            log "[WARN] Service '$svc' is enabled but not running"
            ((WARNINGS++))
            return 1
        fi
    else
        log "[INFO] Service '$svc' is not enabled (may be optional)"
        return 0
    fi
}}

check_mount() {{
    local path="$1"
    local tag="$2"
    if mountpoint -q "$path" 2>/dev/null; then
        log "[PASS] Mount '$path' ($tag) is active"
        ((PASSED++))
        return 0
    elif [ -d "$path" ]; then
        log "[WARN] Directory '$path' exists but not mounted"
        ((WARNINGS++))
        return 1
    else
        log "[INFO] Mount point '$path' does not exist yet"
        return 0
    fi
}}

check_gui() {{
    if systemctl get-default | grep -q graphical; then
        log "[PASS] System configured for graphical target"
        ((PASSED++))
        if systemctl is-active gdm3 &>/dev/null || systemctl is-active gdm &>/dev/null; then
            log "[PASS] Display manager (GDM) is running"
            ((PASSED++))
        else
            log "[WARN] Display manager not yet running (may start after reboot)"
            ((WARNINGS++))
        fi
    else
        log "[INFO] System not configured for GUI"
    fi
}}

# Start health check
log "=========================================="
log "CloneBox Health Check Report"
log "VM Name: {config.name}"
log "Date: $(date)"
log "=========================================="

log ""
log "--- APT Packages ---"
{apt_checks_str}

log ""
log "--- Snap Packages ---"
{snap_checks_str}

log ""
log "--- Services ---"
{service_checks_str}

log ""
log "--- Mounts ---"
{mount_checks_str}

log ""
log "--- GUI Status ---"
check_gui

log ""
log "=========================================="
log "Health Check Summary"
log "=========================================="
log "Passed:   $PASSED"
log "Failed:   $FAILED"
log "Warnings: $WARNINGS"

if [ $FAILED -eq 0 ]; then
    log ""
    log "[SUCCESS] All critical checks passed!"
    echo "HEALTH_STATUS=OK" > /var/log/clonebox-health-status
    exit 0
else
    log ""
    log "[ERROR] Some checks failed. Review log for details."
    echo "HEALTH_STATUS=FAILED" > /var/log/clonebox-health-status
    exit 1
fi
"""
        # Encode script to base64 for safe embedding in cloud-init
        encoded = base64.b64encode(script.encode()).decode()
        return encoded

    def _create_cloudinit_iso(self, vm_dir: Path, config: VMConfig) -> Path:
        """Create cloud-init ISO with secure credential handling."""
        secrets_mgr = SecretsManager()

        # Determine authentication method
        auth_method = getattr(config, "auth_method", "ssh_key")

        ssh_authorized_keys = []
        chpasswd_config = ""
        lock_passwd = "true"
        ssh_pwauth = "false"
        bootcmd_extra = []

        if auth_method == "ssh_key":
            ssh_key_path = vm_dir / "ssh_key"
            provided_key = getattr(config, "ssh_public_key", None)

            if provided_key:
                ssh_authorized_keys = [provided_key]
            else:
                key_pair = SSHKeyPair.generate()
                key_pair.save(ssh_key_path)
                ssh_authorized_keys = [key_pair.public_key]
                log.info(f"SSH key generated and saved to: {ssh_key_path}")

        elif auth_method == "one_time_password":
            otp, chpasswd_raw = SecretsManager.generate_one_time_password()
            chpasswd_config = chpasswd_raw
            bootcmd_extra = [
                '  - echo "===================="',
                f'  - echo "ONE-TIME PASSWORD: {otp}"',
                '  - echo "You MUST change this on first login!"',
                '  - echo "===================="',
            ]
            lock_passwd = "false"
            ssh_pwauth = "true"
            log.warning("One-time password generated. It will be shown on VM console.")

        else:
            # Fallback to legacy password from environment/secrets
            password = secrets_mgr.get("VM_PASSWORD") or getattr(config, "password", "ubuntu")
            chpasswd_config = f"chpasswd:\n  list: |\n    {config.username}:{password}\n  expire: False"
            lock_passwd = "false"
            ssh_pwauth = "true"
            log.warning("DEPRECATED: Using password authentication. Switch to 'ssh_key' for better security.")

        cloudinit_dir = vm_dir / "cloud-init"
        cloudinit_dir.mkdir(exist_ok=True)

        # Meta-data
        instance_id = f"{config.name}-{uuid.uuid4().hex}"
        meta_data = f"instance-id: {instance_id}\nlocal-hostname: {config.name}\n"
        (cloudinit_dir / "meta-data").write_text(meta_data)

        # Generate mount commands and fstab entries for 9p filesystems
        mount_commands = []
        fstab_entries = []
        all_paths = dict(config.paths) if config.paths else {}
        pre_chown_dirs: set[str] = set()
        for idx, (host_path, guest_path) in enumerate(all_paths.items()):
            if Path(host_path).exists():
                # Ensure all parent directories in /home/ubuntu are owned by user
                # This prevents "Permission denied" when creating config dirs (e.g. .config) as root
                if str(guest_path).startswith("/home/ubuntu/"):
                    try:
                        rel_path = Path(guest_path).relative_to("/home/ubuntu")
                        current = Path("/home/ubuntu")
                        # Create and chown each component in the path
                        for part in rel_path.parts:
                            current = current / part
                            d_str = str(current)
                            if d_str not in pre_chown_dirs:
                                pre_chown_dirs.add(d_str)
                                mount_commands.append(f"  - mkdir -p {d_str}")
                                mount_commands.append(f"  - chown 1000:1000 {d_str}")
                    except ValueError:
                        pass

                tag = f"mount{idx}"
                # Use uid=1000,gid=1000 to give ubuntu user access to mounts
                # mmap allows proper file mapping
                mount_opts = "trans=virtio,version=9p2000.L,mmap,uid=1000,gid=1000,users"
                
                # Ensure target exists and is owned by user (if not already handled)
                if str(guest_path) not in pre_chown_dirs:
                    mount_commands.append(f"  - mkdir -p {guest_path}")
                    mount_commands.append(f"  - chown 1000:1000 {guest_path}")

                mount_commands.append(f"  - mount -t 9p -o {mount_opts} {tag} {guest_path} || true")
                # Add fstab entry for persistence after reboot
                fstab_entries.append(f"{tag} {guest_path} 9p {mount_opts},nofail 0 0")

        # User-data
        # Add desktop environment if GUI is enabled
        base_packages = ["qemu-guest-agent", "cloud-guest-utils"]
        if config.gui:
            base_packages.extend(
                [
                    "ubuntu-desktop-minimal",
                    "firefox",
                ]
            )

        all_packages = base_packages + list(config.packages)
        packages_yaml = "\n".join(f"  - {pkg}" for pkg in all_packages) if all_packages else ""

        # Build runcmd - services, mounts, snaps, post_commands
        runcmd_lines = []

        runcmd_lines.append("  - systemctl enable --now qemu-guest-agent || true")
        runcmd_lines.append("  - systemctl enable --now snapd || true")
        runcmd_lines.append("  - timeout 300 snap wait system seed.loaded || true")

        # Add service enablement
        for svc in config.services:
            runcmd_lines.append(f"  - systemctl enable --now {svc} || true")

        # Add fstab entries for persistent mounts after reboot
        if fstab_entries:
            runcmd_lines.append(
                "  - grep -q '^# CloneBox 9p mounts' /etc/fstab || echo '# CloneBox 9p mounts' >> /etc/fstab"
            )
            for entry in fstab_entries:
                runcmd_lines.append(
                    f"  - grep -qF \"{entry}\" /etc/fstab || echo '{entry}' >> /etc/fstab"
                )
            runcmd_lines.append("  - mount -a || true")

        # Add mounts (immediate, before reboot)
        for cmd in mount_commands:
            runcmd_lines.append(cmd)

        # Create user directories with correct permissions EARLY to avoid race conditions with GDM
        if config.gui:
            # Create directories that GNOME services need
            runcmd_lines.extend(
                [
                    "  - mkdir -p /home/ubuntu/.config/pulse /home/ubuntu/.cache/ibus /home/ubuntu/.local/share",
                    "  - mkdir -p /home/ubuntu/.config/dconf /home/ubuntu/.cache/tracker3",
                    "  - mkdir -p /home/ubuntu/.config/autostart",
                    "  - chown -R 1000:1000 /home/ubuntu/.config /home/ubuntu/.cache /home/ubuntu/.local",
                    "  - chmod 700 /home/ubuntu/.config /home/ubuntu/.cache",
                    "  - systemctl set-default graphical.target",
                    "  - systemctl enable gdm3 || systemctl enable gdm || true",
                ]
            )

        runcmd_lines.append("  - chown -R 1000:1000 /home/ubuntu || true")
        runcmd_lines.append("  - chown -R 1000:1000 /home/ubuntu/snap || true")

        # Install snap packages (with retry logic)
        if config.snap_packages:
            runcmd_lines.append("  - echo 'Installing snap packages...'")
            for snap_pkg in config.snap_packages:
                # Try classic first, then strict, with retries
                cmd = (
                    f"for i in 1 2 3; do "
                    f"snap install {snap_pkg} --classic && break || "
                    f"snap install {snap_pkg} && break || "
                    f"sleep 10; "
                    f"done"
                )
                runcmd_lines.append(f"  - {cmd}")

            # Connect snap interfaces for GUI apps (not auto-connected via cloud-init)
            runcmd_lines.append("  - echo 'Connecting snap interfaces...'")
            for snap_pkg in config.snap_packages:
                interfaces = SNAP_INTERFACES.get(snap_pkg, DEFAULT_SNAP_INTERFACES)
                for iface in interfaces:
                    runcmd_lines.append(
                        f"  - snap connect {snap_pkg}:{iface} :{iface} 2>/dev/null || true"
                    )

            runcmd_lines.append("  - systemctl restart snapd || true")

        # Add remaining GUI setup if enabled
        if config.gui:
            # Create autostart entries for GUI apps
            autostart_apps = {
                "pycharm-community": (
                    "PyCharm Community",
                    "/snap/bin/pycharm-community",
                    "pycharm-community",
                ),
                "firefox": ("Firefox", "/snap/bin/firefox", "firefox"),
                "chromium": ("Chromium", "/snap/bin/chromium", "chromium"),
                "google-chrome": ("Google Chrome", "google-chrome-stable", "google-chrome"),
            }

            for snap_pkg in config.snap_packages:
                if snap_pkg in autostart_apps:
                    name, exec_cmd, icon = autostart_apps[snap_pkg]
                    desktop_entry = f"""[Desktop Entry]
Type=Application
Name={name}
Exec={exec_cmd}
Icon={icon}
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
Comment=CloneBox autostart
"""
                    import base64

                    desktop_b64 = base64.b64encode(desktop_entry.encode()).decode()
                    runcmd_lines.append(
                        f"  - echo '{desktop_b64}' | base64 -d > /home/ubuntu/.config/autostart/{snap_pkg}.desktop"
                    )

            # Check if google-chrome is in paths (app_data_paths)
            wants_chrome = any("/google-chrome" in str(p) for p in (config.paths or {}).values())
            if wants_chrome:
                name, exec_cmd, icon = autostart_apps["google-chrome"]
                desktop_entry = f"""[Desktop Entry]
Type=Application
Name={name}
Exec={exec_cmd}
Icon={icon}
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
Comment=CloneBox autostart
"""
                desktop_b64 = base64.b64encode(desktop_entry.encode()).decode()
                runcmd_lines.append(
                    f"  - echo '{desktop_b64}' | base64 -d > /home/ubuntu/.config/autostart/google-chrome.desktop"
                )

            # Fix ownership of autostart directory
            runcmd_lines.append("  - chown -R 1000:1000 /home/ubuntu/.config/autostart")

        # Run user-defined post commands
        if config.post_commands:
            runcmd_lines.append("  - echo 'Running post-setup commands...'")
            for cmd in config.post_commands:
                runcmd_lines.append(f"  - {cmd}")

        # Generate health check script
        health_script = self._generate_health_check_script(config)
        runcmd_lines.append(
            f"  - echo '{health_script}' | base64 -d > /usr/local/bin/clonebox-health"
        )
        runcmd_lines.append("  - chmod +x /usr/local/bin/clonebox-health")
        runcmd_lines.append(
            "  - /usr/local/bin/clonebox-health >> /var/log/clonebox-health.log 2>&1"
        )
        runcmd_lines.append("  - echo 'CloneBox VM ready!' > /var/log/clonebox-ready")

        # Generate boot diagnostic script (self-healing)
        boot_diag_script = self._generate_boot_diagnostic_script(config)
        runcmd_lines.append(
            f"  - echo '{boot_diag_script}' | base64 -d > /usr/local/bin/clonebox-boot-diagnostic"
        )
        runcmd_lines.append("  - chmod +x /usr/local/bin/clonebox-boot-diagnostic")

        # Create systemd service for boot diagnostic (runs before GDM on subsequent boots)
        systemd_service = """[Unit]
Description=CloneBox Boot Diagnostic
After=network-online.target snapd.service
Before=gdm.service display-manager.service
Wants=network-online.target
DefaultDependencies=no

[Service]
Type=oneshot
ExecStart=/usr/local/bin/clonebox-boot-diagnostic
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=300
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target"""
        import base64

        systemd_b64 = base64.b64encode(systemd_service.encode()).decode()
        runcmd_lines.append(
            f"  - echo '{systemd_b64}' | base64 -d > /etc/systemd/system/clonebox-diagnostic.service"
        )
        runcmd_lines.append("  - systemctl daemon-reload")
        runcmd_lines.append("  - systemctl enable clonebox-diagnostic.service")
        runcmd_lines.append("  - systemctl start clonebox-diagnostic.service || true")

        # Create MOTD banner
        motd_banner = '''#!/bin/bash
S="/var/run/clonebox-status"
echo ""
echo -e "\\033[1;34m═══════════════════════════════════════════════════════════\\033[0m"
echo -e "\\033[1;34m                  CloneBox VM Status\\033[0m"
echo -e "\\033[1;34m═══════════════════════════════════════════════════════════\\033[0m"
if [ -f "$S" ]; then
    source "$S"
    if [ "${failed:-0}" -eq 0 ]; then
        echo -e "  \\033[0;32m✅ All systems operational\\033[0m"
    else
        echo -e "  \\033[0;31m⚠️  $failed checks failed\\033[0m"
    fi
    echo -e "  Passed: ${passed:-0} | Repaired: ${repaired:-0} | Failed: ${failed:-0}"
fi
echo -e "  Log: /var/log/clonebox-boot.log"
echo -e "\\033[1;34m═══════════════════════════════════════════════════════════\\033[0m"
echo ""'''
        motd_b64 = base64.b64encode(motd_banner.encode()).decode()
        runcmd_lines.append(f"  - echo '{motd_b64}' | base64 -d > /etc/update-motd.d/99-clonebox")
        runcmd_lines.append("  - chmod +x /etc/update-motd.d/99-clonebox")

        # Create user-friendly clonebox-repair script
        repair_script = r"""#!/bin/bash
# CloneBox Repair - User-friendly repair utility for CloneBox VMs
# Usage: clonebox-repair [--auto|--status|--logs|--help]

set -uo pipefail

RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m' CYAN='\033[0;36m' NC='\033[0m' BOLD='\033[1m'

show_help() {
    echo -e "${BOLD}${CYAN}CloneBox Repair Utility${NC}"
    echo ""
    echo "Usage: clonebox-repair [OPTION]"
    echo ""
    echo "Options:"
    echo "  --auto      Run full automatic repair (same as boot diagnostic)"
    echo "  --status    Show current CloneBox status"
    echo "  --logs      Show recent repair logs"
    echo "  --perms     Fix directory permissions only"
    echo "  --audio     Fix audio (PulseAudio) and restart"
    echo "  --keyring   Reset GNOME Keyring (fixes password mismatch)"
    echo "  --snaps     Reconnect all snap interfaces only"
    echo "  --mounts    Remount all 9p filesystems only"
    echo "  --all       Run all fixes (perms + audio + snaps + mounts)"
    echo "  --help      Show this help message"
    echo ""
    echo "Without options, shows interactive menu."
}

show_status() {
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${CYAN}              CloneBox VM Status${NC}"
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}"
    
    if [ -f /var/run/clonebox-status ]; then
        source /var/run/clonebox-status
        if [ "${failed:-0}" -eq 0 ]; then
            echo -e "  ${GREEN}✅ All systems operational${NC}"
        else
            echo -e "  ${RED}⚠️  $failed checks failed${NC}"
        fi
        echo -e "  Passed: ${passed:-0} | Repaired: ${repaired:-0} | Failed: ${failed:-0}"
    else
        echo -e "  ${YELLOW}No status information available${NC}"
    fi
    echo ""
    echo -e "  Last boot diagnostic: $(stat -c %y /var/log/clonebox-boot.log 2>/dev/null || echo 'never')"
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}"
}

show_logs() {
    echo -e "${BOLD}Recent repair logs:${NC}"
    echo ""
    tail -n 50 /var/log/clonebox-boot.log 2>/dev/null || echo "No logs found"
}

fix_permissions() {
    echo -e "${CYAN}Fixing directory permissions...${NC}"
    VM_USER="${SUDO_USER:-ubuntu}"
    VM_HOME="/home/$VM_USER"
    
    DIRS_TO_CREATE=(
        "$VM_HOME/.config"
        "$VM_HOME/.config/pulse"
        "$VM_HOME/.config/dconf"
        "$VM_HOME/.config/ibus"
        "$VM_HOME/.cache"
        "$VM_HOME/.cache/ibus"
        "$VM_HOME/.cache/tracker3"
        "$VM_HOME/.cache/mesa_shader_cache"
        "$VM_HOME/.local"
        "$VM_HOME/.local/share"
        "$VM_HOME/.local/share/applications"
        "$VM_HOME/.local/share/keyrings"
    )
    
    for dir in "${DIRS_TO_CREATE[@]}"; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir" 2>/dev/null && echo "  Created $dir"
        fi
    done
    
    chown -R 1000:1000 "$VM_HOME/.config" "$VM_HOME/.cache" "$VM_HOME/.local" 2>/dev/null
    chmod 700 "$VM_HOME/.config" "$VM_HOME/.cache" 2>/dev/null
    
    for snap_dir in "$VM_HOME/snap"/*; do
        [ -d "$snap_dir" ] && chown -R 1000:1000 "$snap_dir" 2>/dev/null
    done
    
    echo -e "${GREEN}✅ Permissions fixed${NC}"
}

fix_audio() {
    echo -e "${CYAN}Fixing audio (PulseAudio/PipeWire)...${NC}"
    VM_USER="${SUDO_USER:-ubuntu}"
    VM_HOME="/home/$VM_USER"
    
    # Create pulse config directory with correct permissions
    mkdir -p "$VM_HOME/.config/pulse" 2>/dev/null
    chown -R 1000:1000 "$VM_HOME/.config/pulse" 2>/dev/null
    chmod 700 "$VM_HOME/.config/pulse" 2>/dev/null
    
    # Kill and restart audio services as user
    if [ -n "$SUDO_USER" ]; then
        sudo -u "$SUDO_USER" pulseaudio --kill 2>/dev/null || true
        sleep 1
        sudo -u "$SUDO_USER" pulseaudio --start 2>/dev/null || true
        echo "  Restarted PulseAudio for $SUDO_USER"
    else
        pulseaudio --kill 2>/dev/null || true
        sleep 1
        pulseaudio --start 2>/dev/null || true
        echo "  Restarted PulseAudio"
    fi
    
    # Restart pipewire if available
    systemctl --user restart pipewire pipewire-pulse 2>/dev/null || true
    
    echo -e "${GREEN}✅ Audio fixed${NC}"
}

fix_keyring() {
    echo -e "${CYAN}Resetting GNOME Keyring...${NC}"
    VM_USER="${SUDO_USER:-ubuntu}"
    VM_HOME="/home/$VM_USER"
    KEYRING_DIR="$VM_HOME/.local/share/keyrings"
    
    echo -e "${YELLOW}⚠️  This will delete existing keyrings and create a new one on next login${NC}"
    echo -e "${YELLOW}   Stored passwords (WiFi, Chrome, etc.) will be lost!${NC}"
    
    if [ -t 0 ]; then
        read -rp "Continue? [y/N] " confirm
        [[ "$confirm" != [yY]* ]] && { echo "Cancelled"; return; }
    fi
    
    # Backup old keyrings
    if [ -d "$KEYRING_DIR" ] && [ "$(ls -A "$KEYRING_DIR" 2>/dev/null)" ]; then
        backup_dir="$VM_HOME/.local/share/keyrings.backup.$(date +%Y%m%d%H%M%S)"
        mv "$KEYRING_DIR" "$backup_dir" 2>/dev/null
        echo "  Backed up to $backup_dir"
    fi
    
    # Create fresh keyring directory
    mkdir -p "$KEYRING_DIR" 2>/dev/null
    chown -R 1000:1000 "$KEYRING_DIR" 2>/dev/null
    chmod 700 "$KEYRING_DIR" 2>/dev/null
    
    # Kill gnome-keyring-daemon to force restart on next login
    pkill -u "$VM_USER" gnome-keyring-daemon 2>/dev/null || true
    
    echo -e "${GREEN}✅ Keyring reset - log out and back in to create new keyring${NC}"
}

fix_ibus() {
    echo -e "${CYAN}Fixing IBus input method...${NC}"
    VM_USER="${SUDO_USER:-ubuntu}"
    VM_HOME="/home/$VM_USER"
    
    # Create ibus cache directory
    mkdir -p "$VM_HOME/.cache/ibus" 2>/dev/null
    chown -R 1000:1000 "$VM_HOME/.cache/ibus" 2>/dev/null
    chmod 700 "$VM_HOME/.cache/ibus" 2>/dev/null
    
    # Restart ibus
    if [ -n "$SUDO_USER" ]; then
        sudo -u "$SUDO_USER" ibus restart 2>/dev/null || true
    else
        ibus restart 2>/dev/null || true
    fi
    
    echo -e "${GREEN}✅ IBus fixed${NC}"
}

fix_snaps() {
    echo -e "${CYAN}Reconnecting snap interfaces...${NC}"
    IFACES="desktop desktop-legacy x11 wayland home network audio-playback audio-record camera opengl"
    
    for snap in $(snap list --color=never 2>/dev/null | tail -n +2 | awk '{print $1}'); do
        [[ "$snap" =~ ^(core|snapd|gnome-|gtk-|mesa-) ]] && continue
        echo -e "  ${YELLOW}$snap${NC}"
        for iface in $IFACES; do
            snap connect "$snap:$iface" ":$iface" 2>/dev/null && echo "    ✓ $iface" || true
        done
    done
    
    systemctl restart snapd 2>/dev/null || true
    echo -e "${GREEN}✅ Snap interfaces reconnected${NC}"
}

fix_mounts() {
    echo -e "${CYAN}Remounting filesystems...${NC}"
    
    while IFS= read -r line; do
        tag=$(echo "$line" | awk '{print $1}')
        mp=$(echo "$line" | awk '{print $2}')
        if [[ "$tag" =~ ^mount[0-9]+$ ]] && [[ "$mp" == /* ]]; then
            if ! mountpoint -q "$mp" 2>/dev/null; then
                mkdir -p "$mp" 2>/dev/null
                if mount "$mp" 2>/dev/null; then
                    echo -e "  ${GREEN}✓${NC} $mp"
                else
                    echo -e "  ${RED}✗${NC} $mp (failed)"
                fi
            else
                echo -e "  ${GREEN}✓${NC} $mp (already mounted)"
            fi
        fi
    done < /etc/fstab
    
    echo -e "${GREEN}✅ Mounts checked${NC}"
}

fix_all() {
    echo -e "${BOLD}${CYAN}Running all fixes...${NC}"
    echo ""
    fix_permissions
    echo ""
    fix_audio
    echo ""
    fix_ibus
    echo ""
    fix_snaps
    echo ""
    fix_mounts
    echo ""
    echo -e "${BOLD}${GREEN}All fixes completed!${NC}"
}

interactive_menu() {
    while true; do
        echo ""
        echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}"
        echo -e "${BOLD}${CYAN}              CloneBox Repair Menu${NC}"
        echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}"
        echo ""
        echo "  1) Run full automatic repair (boot diagnostic)"
        echo "  2) Run all quick fixes (perms + audio + snaps + mounts)"
        echo "  3) Fix permissions only"
        echo "  4) Fix audio (PulseAudio) only"
        echo "  5) Reset GNOME Keyring (⚠️  deletes saved passwords)"
        echo "  6) Reconnect snap interfaces only"
        echo "  7) Remount filesystems only"
        echo "  8) Show status"
        echo "  9) Show logs"
        echo "  q) Quit"
        echo ""
        read -rp "Select option: " choice
        
        case "$choice" in
            1) sudo /usr/local/bin/clonebox-boot-diagnostic ;;
            2) fix_all ;;
            3) fix_permissions ;;
            4) fix_audio ;;
            5) fix_keyring ;;
            6) fix_snaps ;;
            7) fix_mounts ;;
            8) show_status ;;
            9) show_logs ;;
            q|Q) exit 0 ;;
            *) echo -e "${RED}Invalid option${NC}" ;;
        esac
    done
}

# Main
case "${1:-}" in
    --auto)    exec sudo /usr/local/bin/clonebox-boot-diagnostic ;;
    --all)     fix_all ;;
    --status)  show_status ;;
    --logs)    show_logs ;;
    --perms)   fix_permissions ;;
    --audio)   fix_audio ;;
    --keyring) fix_keyring ;;
    --snaps)   fix_snaps ;;
    --mounts)  fix_mounts ;;
    --help|-h) show_help ;;
    "") interactive_menu ;;
    *) show_help; exit 1 ;;
esac
"""
        repair_b64 = base64.b64encode(repair_script.encode()).decode()
        runcmd_lines.append(f"  - echo '{repair_b64}' | base64 -d > /usr/local/bin/clonebox-repair")
        runcmd_lines.append("  - chmod +x /usr/local/bin/clonebox-repair")
        runcmd_lines.append("  - ln -sf /usr/local/bin/clonebox-repair /usr/local/bin/cb-repair")

        # === AUTOSTART: Systemd user services + Desktop autostart files ===
        # Create directories for user systemd services and autostart
        runcmd_lines.append(f"  - mkdir -p /home/{config.username}/.config/systemd/user")
        runcmd_lines.append(f"  - mkdir -p /home/{config.username}/.config/autostart")

        # Enable lingering for the user (allows user services to run without login)
        runcmd_lines.append(f"  - loginctl enable-linger {config.username}")

        # Add environment variables for monitoring
        runcmd_lines.extend(
            [
                "  - echo 'CLONEBOX_ENABLE_MONITORING=true' >> /etc/environment",
                "  - echo 'CLONEBOX_MONITOR_INTERVAL=30' >> /etc/environment",
                "  - echo 'CLONEBOX_AUTO_REPAIR=true' >> /etc/environment",
                "  - echo 'CLONEBOX_WATCH_APPS=true' >> /etc/environment",
                "  - echo 'CLONEBOX_WATCH_SERVICES=true' >> /etc/environment",
            ]
        )

        # Generate autostart configurations based on installed apps (if enabled)
        autostart_apps = []

        if getattr(config, "autostart_apps", True):
            # Detect apps from snap_packages
            for snap_pkg in config.snap_packages or []:
                if snap_pkg == "pycharm-community":
                    autostart_apps.append(
                        {
                            "name": "pycharm-community",
                            "display_name": "PyCharm Community",
                            "exec": "/snap/bin/pycharm-community %U",
                            "type": "snap",
                            "after": "graphical-session.target",
                        }
                    )
                elif snap_pkg == "chromium":
                    autostart_apps.append(
                        {
                            "name": "chromium",
                            "display_name": "Chromium Browser",
                            "exec": "/snap/bin/chromium %U",
                            "type": "snap",
                            "after": "graphical-session.target",
                        }
                    )
                elif snap_pkg == "firefox":
                    autostart_apps.append(
                        {
                            "name": "firefox",
                            "display_name": "Firefox",
                            "exec": "/snap/bin/firefox %U",
                            "type": "snap",
                            "after": "graphical-session.target",
                        }
                    )
                elif snap_pkg == "code":
                    autostart_apps.append(
                        {
                            "name": "code",
                            "display_name": "Visual Studio Code",
                            "exec": "/snap/bin/code --new-window",
                            "type": "snap",
                            "after": "graphical-session.target",
                        }
                    )

            # Detect apps from packages (APT)
            for apt_pkg in config.packages or []:
                if apt_pkg == "firefox":
                    # Only add if not already added from snap
                    if not any(a["name"] == "firefox" for a in autostart_apps):
                        autostart_apps.append(
                            {
                                "name": "firefox",
                                "display_name": "Firefox",
                                "exec": "/usr/bin/firefox %U",
                                "type": "apt",
                                "after": "graphical-session.target",
                            }
                        )

            # Check for google-chrome from app_data_paths
            for host_path, guest_path in (config.paths or {}).items():
                if guest_path == "/home/ubuntu/.config/google-chrome":
                    autostart_apps.append(
                        {
                            "name": "google-chrome",
                            "display_name": "Google Chrome",
                            "exec": "/usr/bin/google-chrome-stable %U",
                            "type": "deb",
                            "after": "graphical-session.target",
                        }
                    )
                    break

        # Generate systemd user services for each app
        for app in autostart_apps:
            service_content = f"""[Unit]
Description={app["display_name"]} Autostart
After={app["after"]}
PartOf=graphical-session.target

[Service]
Type=simple
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=XDG_SESSION_TYPE=x11
ExecStart={app["exec"]}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
            service_b64 = base64.b64encode(service_content.encode()).decode()
            service_path = f"/home/{config.username}/.config/systemd/user/{app['name']}.service"
            runcmd_lines.append(f"  - echo '{service_b64}' | base64 -d > {service_path}")

        # Fix snap interfaces reconnection script to be more robust
        snap_fix_script = r"""#!/bin/bash
# Fix snap interfaces for GUI apps
set -euo pipefail
SNAP_LIST=$(snap list | awk 'NR>1 {print $1}')
for snap in $SNAP_LIST; do
    case "$snap" in
        pycharm-community|chromium|firefox|code|slack|spotify)
            echo "Connecting interfaces for $snap..."
            IFACES="desktop desktop-legacy x11 wayland home network network-bind audio-playback"
            for iface in $IFACES; do
                snap connect "$snap:$iface" ":$iface" 2>/dev/null || true
            done
            ;;
    esac
done
systemctl restart snapd 2>/dev/null || true
"""
        snap_fix_b64 = base64.b64encode(snap_fix_script.encode()).decode()
        runcmd_lines.append(
            f"  - echo '{snap_fix_b64}' | base64 -d > /usr/local/bin/clonebox-fix-snaps"
        )
        runcmd_lines.append("  - chmod +x /usr/local/bin/clonebox-fix-snaps")
        runcmd_lines.append("  - /usr/local/bin/clonebox-fix-snaps || true")

        # Generate desktop autostart files for GUI apps (alternative to systemd user services)
        for app in autostart_apps:
            desktop_content = f"""[Desktop Entry]
Type=Application
Name={app["display_name"]}
Exec={app["exec"]}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
"""
            desktop_b64 = base64.b64encode(desktop_content.encode()).decode()
            desktop_path = f"/home/{config.username}/.config/autostart/{app['name']}.desktop"
            runcmd_lines.append(f"  - echo '{desktop_b64}' | base64 -d > {desktop_path}")

        # Fix ownership of all autostart files
        runcmd_lines.append(f"  - chown -R 1000:1000 /home/{config.username}/.config/systemd")
        runcmd_lines.append(f"  - chown -R 1000:1000 /home/{config.username}/.config/autostart")

        # Enable systemd user services (must run as user)
        if autostart_apps:
            services_to_enable = " ".join(f"{app['name']}.service" for app in autostart_apps)
            runcmd_lines.append(
                f"  - sudo -u {config.username} XDG_RUNTIME_DIR=/run/user/1000 systemctl --user daemon-reload || true"
            )
            # Note: We don't enable services by default as desktop autostart is more reliable for GUI apps
            # User can enable them manually with: systemctl --user enable <service>

        # === WEB SERVICES: System-wide services for uvicorn, nginx, etc. ===
        web_services = getattr(config, "web_services", []) or []
        for svc in web_services:
            svc_name = svc.get("name", "clonebox-web")
            svc_desc = svc.get("description", f"CloneBox {svc_name}")
            svc_workdir = svc.get("workdir", "/mnt/project0")
            svc_exec = svc.get("exec", "uvicorn app:app --host 0.0.0.0 --port 8000")
            svc_user = svc.get("user", config.username)
            svc_after = svc.get("after", "network.target")
            svc_env = svc.get("environment", [])

            env_lines = "\n".join(f"Environment={e}" for e in svc_env) if svc_env else ""

            web_service_content = f"""[Unit]
Description={svc_desc}
After={svc_after}

[Service]
Type=simple
User={svc_user}
WorkingDirectory={svc_workdir}
{env_lines}
ExecStart={svc_exec}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
            web_svc_b64 = base64.b64encode(web_service_content.encode()).decode()
            runcmd_lines.append(
                f"  - echo '{web_svc_b64}' | base64 -d > /etc/systemd/system/{svc_name}.service"
            )
            runcmd_lines.append("  - systemctl daemon-reload")
            runcmd_lines.append(f"  - systemctl enable {svc_name}.service")
            runcmd_lines.append(f"  - systemctl start {svc_name}.service || true")

        # Install CloneBox Monitor for continuous monitoring and self-healing
        scripts_dir = Path(__file__).resolve().parent.parent.parent / "scripts"
        try:
            with open(scripts_dir / "clonebox-monitor.sh") as f:
                monitor_script = f.read()
            with open(scripts_dir / "clonebox-monitor.service") as f:
                monitor_service = f.read()
            with open(scripts_dir / "clonebox-monitor.default") as f:
                monitor_config = f.read()
        except (FileNotFoundError, OSError):
            # Fallback to embedded scripts if files not found
            monitor_script = """#!/bin/bash
# CloneBox Monitor - Fallback embedded version
set -euo pipefail
LOG_FILE="/var/log/clonebox-monitor.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }
log_info() { log "[INFO] $1"; }
log_warn() { log "[WARN] $1"; }
log_error() { log "[ERROR] $1"; }
log_success() { log "[SUCCESS] $1"; }
while true; do
    log_info "CloneBox Monitor running..."
    sleep 60
done
"""
            monitor_service = """[Unit]
Description=CloneBox Monitor
After=graphical-session.target
[Service]
Type=simple
User=ubuntu
ExecStart=/usr/local/bin/clonebox-monitor
Restart=always
[Install]
WantedBy=default.target
"""
            monitor_config = """# CloneBox Monitor Configuration
CLONEBOX_MONITOR_INTERVAL=30
CLONEBOX_AUTO_REPAIR=true
"""

        # Install monitor script
        monitor_b64 = base64.b64encode(monitor_script.encode()).decode()
        runcmd_lines.append(
            f"  - echo '{monitor_b64}' | base64 -d > /usr/local/bin/clonebox-monitor"
        )
        runcmd_lines.append("  - chmod +x /usr/local/bin/clonebox-monitor")

        # Install monitor configuration
        config_b64 = base64.b64encode(monitor_config.encode()).decode()
        runcmd_lines.append(f"  - echo '{config_b64}' | base64 -d > /etc/default/clonebox-monitor")

        # Install systemd user service
        service_b64 = base64.b64encode(monitor_service.encode()).decode()
        runcmd_lines.append(
            f"  - echo '{service_b64}' | base64 -d > /etc/systemd/user/clonebox-monitor.service"
        )

        # Enable lingering and start monitor
        runcmd_lines.extend(
            [
                "  - loginctl enable-linger ubuntu",
                "  - sudo -u ubuntu systemctl --user daemon-reload",
                "  - sudo -u ubuntu systemctl --user enable clonebox-monitor.service",
                "  - sudo -u ubuntu systemctl --user start clonebox-monitor.service || true",
            ]
        )

        # Create Python monitor service for continuous diagnostics (legacy)
        monitor_script = f'''#!/usr/bin/env python3
"""CloneBox Monitor - Continuous diagnostics and app restart service."""
import subprocess
import time
import os
import sys
import json
from pathlib import Path

REQUIRED_APPS = {json.dumps([app["name"] for app in autostart_apps])}
CHECK_INTERVAL = 60  # seconds
LOG_FILE = "/var/log/clonebox-monitor.log"
STATUS_FILE = "/var/run/clonebox-monitor-status.json"

def log(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{{timestamp}}] {{msg}}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\\n")
    except:
        pass

def get_running_processes():
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=10)
        return result.stdout
    except:
        return ""

def is_app_running(app_name, ps_output):
    patterns = {{
        "pycharm-community": ["pycharm", "idea"],
        "chromium": ["chromium"],
        "firefox": ["firefox", "firefox-esr"],
        "google-chrome": ["chrome", "google-chrome"],
        "code": ["code", "vscode"],
    }}
    for pattern in patterns.get(app_name, [app_name]):
        if pattern.lower() in ps_output.lower():
            return True
    return False

def restart_app(app_name):
    log(f"Restarting {{app_name}}...")
    try:
        subprocess.run(
            ["sudo", "-u", "{config.username}", "systemctl", "--user", "restart", f"{{app_name}}.service"],
            timeout=30, capture_output=True
        )
        return True
    except Exception as e:
        log(f"Failed to restart {{app_name}}: {{e}}")
        return False

def check_mounts():
    try:
        with open("/etc/fstab", "r") as f:
            fstab = f.read()
        for line in fstab.split("\\n"):
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("mount"):
                mp = parts[1]
                result = subprocess.run(["mountpoint", "-q", mp], capture_output=True)
                if result.returncode != 0:
                    log(f"Mount {{mp}} not active, attempting remount...")
                    subprocess.run(["mount", mp], capture_output=True)
    except Exception as e:
        log(f"Mount check failed: {{e}}")

def write_status(status):
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f)
    except:
        pass

def main():
    log("CloneBox Monitor started")
    
    while True:
        status = {{"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "apps": {{}}, "mounts_ok": True}}
        
        # Check mounts
        check_mounts()
        
        # Check apps (only if GUI session is active)
        if os.path.exists("/run/user/1000"):
            ps_output = get_running_processes()
            for app in REQUIRED_APPS:
                running = is_app_running(app, ps_output)
                status["apps"][app] = "running" if running else "stopped"
                # Don't auto-restart apps - user may have closed them intentionally
        
        write_status(status)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
'''
        # Note: The bash monitor is already installed above, no need to install Python monitor

        # Create logs disk for host access
        runcmd_lines.extend(
            [
                "  - mkdir -p /mnt/logs",
                "  - truncate -s 1G /var/lib/libvirt/images/clonebox-logs.qcow2",
                "  - mkfs.ext4 -F /var/lib/libvirt/images/clonebox-logs.qcow2",
                "  - echo '/var/lib/libvirt/images/clonebox-logs.qcow2 /mnt/logs ext4 loop,defaults 0 0' >> /etc/fstab",
                "  - mount -a",
                "  - mkdir -p /mnt/logs/var/log",
                "  - mkdir -p /mnt/logs/tmp",
                "  - cp -r /var/log/clonebox*.log /mnt/logs/var/log/ 2>/dev/null || true",
                "  - cp -r /tmp/*-error.log /mnt/logs/tmp/ 2>/dev/null || true",
                "  - echo 'Logs disk mounted at /mnt/logs - accessible from host as /var/lib/libvirt/images/clonebox-logs.qcow2'",
                "  - \"echo 'To view logs on host: sudo mount -o loop /var/lib/libvirt/images/clonebox-logs.qcow2 /mnt/clonebox-logs'\"",
            ]
        )

        # Add reboot command at the end if GUI is enabled
        if config.gui:
            runcmd_lines.append("  - echo 'Rebooting in 10 seconds to start GUI...'")
            runcmd_lines.append("  - sleep 10 && reboot")

        runcmd_yaml = "\n".join(runcmd_lines) if runcmd_lines else ""
        
        # Build bootcmd combining mount commands and extra security bootcmds
        bootcmd_lines = list(bootcmd_extra) if bootcmd_extra else []
            
        bootcmd_block = ""
        if bootcmd_lines:
            bootcmd_block = "\nbootcmd:\n" + "\n".join(bootcmd_lines) + "\n"

        # User-data components
        user_data_header = f"""#cloud-config
hostname: {config.name}
manage_etc_hosts: true

users:
  - name: {config.username}
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    groups: sudo,adm,dialout,cdrom,floppy,audio,dip,video,plugdev,netdev,docker
    lock_passwd: {lock_passwd}
"""
        if ssh_authorized_keys:
            user_data_header += "    ssh_authorized_keys:\n"
            for key in ssh_authorized_keys:
                user_data_header += f"      - {key}\n"
        
        if chpasswd_config:
            user_data_header += f"\n{chpasswd_config}\n"
            
        user_data_header += f"ssh_pwauth: {ssh_pwauth}\n"

        # Assemble final user-data
        user_data = f"""{user_data_header}
# Make sure root partition + filesystem grows to fill the qcow2 disk size
growpart:
  mode: auto
  devices: ["/"]
  ignore_growroot_disabled: false
resize_rootfs: true

# Update package cache and upgrade
package_update: true
package_upgrade: false
{bootcmd_block}

# Install packages (cloud-init waits for completion before runcmd)
packages:
{packages_yaml}

# Run after packages are installed
runcmd:
{runcmd_yaml}

final_message: "CloneBox VM is ready after $UPTIME seconds"
"""
        (cloudinit_dir / "user-data").write_text(user_data)

        # Create ISO
        iso_path = vm_dir / "cloud-init.iso"
        subprocess.run(
            [
                "genisoimage",
                "-output",
                str(iso_path),
                "-volid",
                "cidata",
                "-joliet",
                "-rock",
                str(cloudinit_dir / "user-data"),
                str(cloudinit_dir / "meta-data"),
            ],
            check=True,
            capture_output=True,
        )

        return iso_path

    def start_vm(self, vm_name: str, open_viewer: bool = True, console=None) -> bool:
        """Start a VM and optionally open virt-viewer."""

        def log(msg):
            if console:
                console.print(msg)
            else:
                print(msg)

        try:
            vm = self.conn.lookupByName(vm_name)
        except libvirt.libvirtError:
            log(f"[red]❌ VM '{vm_name}' not found[/]")
            return False

        if vm.isActive():
            log(f"[yellow]⚠️  VM '{vm_name}' is already running[/]")
        else:
            log(f"[cyan]🚀 Starting VM '{vm_name}'...[/]")
            vm.create()
            log("[green]✅ VM started![/]")

        if open_viewer:
            log("[cyan]🖥️  Opening virt-viewer...[/]")
            subprocess.Popen(
                ["virt-viewer", "-c", self.conn_uri, vm_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        return True

    def stop_vm(self, vm_name: str, force: bool = False, console=None) -> bool:
        """Stop a VM."""

        def log(msg):
            if console:
                console.print(msg)
            else:
                print(msg)

        try:
            vm = self.conn.lookupByName(vm_name)
        except libvirt.libvirtError:
            log(f"[red]❌ VM '{vm_name}' not found[/]")
            return False

        if not vm.isActive():
            log(f"[yellow]⚠️  VM '{vm_name}' is not running[/]")
            return True

        if force:
            log(f"[yellow]⚡ Force stopping VM '{vm_name}'...[/]")
            vm.destroy()
        else:
            log(f"[cyan]🛑 Shutting down VM '{vm_name}'...[/]")
            vm.shutdown()

        log("[green]✅ VM stopped![/]")
        return True

    def delete_vm(
        self,
        vm_name: str,
        delete_storage: bool = True,
        console=None,
        ignore_not_found: bool = False,
    ) -> bool:
        """Delete a VM and optionally its storage."""

        def log(msg):
            if console:
                console.print(msg)
            else:
                print(msg)

        try:
            vm = self.conn.lookupByName(vm_name)
        except libvirt.libvirtError:
            log(f"[red]❌ VM '{vm_name}' not found[/]")
            return False

        # Stop if running
        if vm.isActive():
            vm.destroy()

        # Undefine
        vm.undefine()
        log(f"[green]✅ VM '{vm_name}' undefined[/]")

        # Delete storage
        if delete_storage:
            vm_dir = self.get_images_dir() / vm_name
            if vm_dir.exists():
                import shutil

                shutil.rmtree(vm_dir)
                log(f"[green]🗑️  Storage deleted: {vm_dir}[/]")

        return True

    def list_vms(self) -> list:
        """List all VMs."""
        vms = []
        for vm_id in self.conn.listDomainsID():
            vm = self.conn.lookupByID(vm_id)
            vms.append({"name": vm.name(), "state": "running", "uuid": vm.UUIDString()})

        for name in self.conn.listDefinedDomains():
            vm = self.conn.lookupByName(name)
            vms.append({"name": name, "state": "stopped", "uuid": vm.UUIDString()})

        return vms

    def close(self):
        """Close libvirt connection."""
        if self.conn:
            self.conn.close()

    # Backward compatibility methods for tests
    def _get_base_image_info(self, image_path: str) -> dict:
        """Get base image information - backward compatibility shim."""
        if hasattr(self, "get_base_image_info"):
            return self.get_base_image_info(image_path)
        # Return empty dict if method doesn't exist
        return {}

    def get_vm_info(self, vm_name: str) -> dict:
        """Get VM information - backward compatibility shim."""
        if hasattr(self, "_get_vm_info"):
            return self._get_vm_info(vm_name)
        # Try to get basic info from libvirt
        try:
            vm = self.conn.lookupByName(vm_name)
            return {
                "name": vm.name(),
                "state": "running" if vm.isActive() else "stopped",
                "uuid": vm.UUIDString(),
            }
        except Exception:
            return {}
