#!/usr/bin/env python3
"""
SelectiveVMCloner - Creates isolated VMs with only selected apps/paths/services.
"""

import os
import subprocess
import tempfile
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import libvirt
except ImportError:
    libvirt = None

SNAP_INTERFACES = {
    'pycharm-community': ['desktop', 'desktop-legacy', 'x11', 'wayland', 'home', 'network', 'network-bind', 'cups-control', 'removable-media'],
    'chromium': ['desktop', 'desktop-legacy', 'x11', 'wayland', 'home', 'network', 'audio-playback', 'camera'],
    'firefox': ['desktop', 'desktop-legacy', 'x11', 'wayland', 'home', 'network', 'audio-playback', 'removable-media'],
    'code': ['desktop', 'desktop-legacy', 'x11', 'wayland', 'home', 'network', 'ssh-keys'],
    'slack': ['desktop', 'desktop-legacy', 'x11', 'wayland', 'home', 'network', 'audio-playback'],
    'spotify': ['desktop', 'x11', 'wayland', 'home', 'network', 'audio-playback'],
}
DEFAULT_SNAP_INTERFACES = ['desktop', 'desktop-legacy', 'x11', 'home', 'network']


@dataclass
class VMConfig:
    """Configuration for the VM to create."""

    name: str = "clonebox-vm"
    ram_mb: int = 4096
    vcpus: int = 4
    disk_size_gb: int = 20
    gui: bool = True
    base_image: Optional[str] = None
    paths: dict = field(default_factory=dict)
    packages: list = field(default_factory=list)
    snap_packages: list = field(default_factory=list)  # Snap packages to install
    services: list = field(default_factory=list)
    post_commands: list = field(default_factory=list)  # Commands to run after setup
    user_session: bool = False  # Use qemu:///session instead of qemu:///system
    network_mode: str = "auto"  # auto|default|user
    username: str = "ubuntu"  # VM default username
    password: str = "ubuntu"  # VM default password

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

    # Default images directories
    SYSTEM_IMAGES_DIR = Path("/var/lib/libvirt/images")
    USER_IMAGES_DIR = Path.home() / ".local/share/libvirt/images"

    DEFAULT_BASE_IMAGE_URL = (
        "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img"
    )
    DEFAULT_BASE_IMAGE_FILENAME = "clonebox-ubuntu-jammy-amd64.qcow2"

    def __init__(self, conn_uri: str = None, user_session: bool = False):
        self.user_session = user_session
        if conn_uri:
            self.conn_uri = conn_uri
        else:
            self.conn_uri = "qemu:///session" if user_session else "qemu:///system"
        self.conn = None
        self._connect()

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
        def log(msg):
            if console:
                console.print(msg)
            else:
                print(msg)

        downloads_dir = self._get_downloads_dir()
        downloads_dir.mkdir(parents=True, exist_ok=True)
        cached_path = downloads_dir / self.DEFAULT_BASE_IMAGE_FILENAME

        if cached_path.exists() and cached_path.stat().st_size > 0:
            return cached_path

        log(
            "[cyan]⬇️  Downloading base image (first run only). This will be cached in ~/Downloads...[/]"
        )

        try:
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

        def log(msg):
            if console:
                console.print(msg)
            else:
                print(msg)

        # If VM already exists, optionally replace it
        existing_vm = None
        try:
            candidate_vm = self.conn.lookupByName(config.name)
            if candidate_vm is not None:
                # libvirt returns a domain object whose .name() should match the requested name.
                # In tests, an unconfigured MagicMock may be returned here; avoid treating that as
                # a real existing domain unless we can confirm the name matches.
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

            log(f"[yellow]⚠️  VM '{config.name}' already exists - replacing...[/]")
            self.delete_vm(config.name, delete_storage=True, console=console, ignore_not_found=True)

        # Determine images directory
        images_dir = self.get_images_dir()
        vm_dir = images_dir / config.name

        try:
            vm_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(
                f"Cannot create VM directory: {vm_dir}\n\n"
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
        root_disk = vm_dir / "root.qcow2"

        if not config.base_image:
            config.base_image = str(self._ensure_default_base_image(console=console))

        if config.base_image and Path(config.base_image).exists():
            # Use backing file for faster creation
            log(f"[cyan]📀 Creating disk with backing file: {config.base_image}[/]")
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
            log(f"[cyan]📀 Creating empty {config.disk_size_gb}GB disk...[/]")
            cmd = ["qemu-img", "create", "-f", "qcow2", str(root_disk), f"{config.disk_size_gb}G"]

        subprocess.run(cmd, check=True, capture_output=True)

        # Create cloud-init ISO if packages/services specified
        cloudinit_iso = None
        if config.packages or config.services:
            cloudinit_iso = self._create_cloudinit_iso(vm_dir, config)
            log(f"[cyan]☁️  Created cloud-init ISO with {len(config.packages)} packages[/]")

        # Resolve network mode
        network_mode = self.resolve_network_mode(config)
        if network_mode == "user":
            log(
                "[yellow]⚠️  Using user-mode networking (slirp) because default libvirt network is unavailable[/]"
            )
        else:
            log(f"[dim]Network mode: {network_mode}[/]")

        # Generate VM XML
        vm_xml = self._generate_vm_xml(config, root_disk, cloudinit_iso)

        # Define and create VM
        log(f"[cyan]🔧 Defining VM '{config.name}'...[/]")
        try:
            vm = self.conn.defineXML(vm_xml)
        except Exception as e:
            raise RuntimeError(
                f"Failed to define VM '{config.name}'.\n"
                f"Error: {e}\n\n"
                f"If the VM already exists, try: clonebox clone . --name {config.name} --replace\n"
            ) from e

        log(f"[green]✅ VM '{config.name}' created successfully![/]")
        log(f"[dim]   UUID: {vm.UUIDString()}[/]")

        return vm.UUIDString()

    def _generate_vm_xml(
        self, config: VMConfig, root_disk: Path, cloudinit_iso: Optional[Path]
    ) -> str:
        """Generate libvirt XML for the VM."""

        root = ET.Element("domain", type="kvm")

        # Basic metadata
        ET.SubElement(root, "name").text = config.name
        ET.SubElement(root, "uuid").text = str(uuid.uuid4())
        ET.SubElement(root, "memory", unit="MiB").text = str(config.ram_mb)
        ET.SubElement(root, "currentMemory", unit="MiB").text = str(config.ram_mb)
        ET.SubElement(root, "vcpu", placement="static").text = str(config.vcpus)

        # OS configuration
        os_elem = ET.SubElement(root, "os")
        ET.SubElement(os_elem, "type", arch="x86_64", machine="q35").text = "hvm"
        ET.SubElement(os_elem, "boot", dev="hd")

        # Features
        features = ET.SubElement(root, "features")
        ET.SubElement(features, "acpi")
        ET.SubElement(features, "apic")

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

        # Channel for guest agent
        channel = ET.SubElement(devices, "channel", type="unix")
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
        snap_checks_str = "\n".join(snap_checks) if snap_checks else "echo 'No snap packages to check'"
        service_checks_str = "\n".join(service_checks) if service_checks else "echo 'No services to check'"
        mount_checks_str = "\n".join(mount_checks) if mount_checks else "echo 'No mounts to check'"
        
        script = f'''#!/bin/bash
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
'''
        # Encode script to base64 for safe embedding in cloud-init
        encoded = base64.b64encode(script.encode()).decode()
        return encoded

    def _create_cloudinit_iso(self, vm_dir: Path, config: VMConfig) -> Path:
        """Create cloud-init ISO with user-data and meta-data."""

        cloudinit_dir = vm_dir / "cloud-init"
        cloudinit_dir.mkdir(exist_ok=True)

        # Meta-data
        meta_data = f"instance-id: {config.name}\nlocal-hostname: {config.name}\n"
        (cloudinit_dir / "meta-data").write_text(meta_data)

        # Generate mount commands and fstab entries for 9p filesystems
        mount_commands = []
        fstab_entries = []
        all_paths = dict(config.paths) if config.paths else {}
        for idx, (host_path, guest_path) in enumerate(all_paths.items()):
            if Path(host_path).exists():
                tag = f"mount{idx}"
                # Use uid=1000,gid=1000 to give ubuntu user access to mounts
                # mmap allows proper file mapping
                mount_opts = "trans=virtio,version=9p2000.L,mmap,uid=1000,gid=1000,users"
                mount_commands.append(f"  - mkdir -p {guest_path}")
                mount_commands.append(f"  - chown 1000:1000 {guest_path}")
                mount_commands.append(
                    f"  - mount -t 9p -o {mount_opts} {tag} {guest_path} || true"
                )
                # Add fstab entry for persistence after reboot
                fstab_entries.append(f"{tag} {guest_path} 9p {mount_opts},nofail 0 0")

        # User-data
        # Add desktop environment if GUI is enabled
        base_packages = ["qemu-guest-agent", "cloud-guest-utils"]
        if config.gui:
            base_packages.extend([
                "ubuntu-desktop-minimal",
                "firefox",
            ])
        
        all_packages = base_packages + list(config.packages)
        packages_yaml = (
            "\n".join(f"  - {pkg}" for pkg in all_packages) if all_packages else ""
        )
        
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
            runcmd_lines.append("  - grep -q '^# CloneBox 9p mounts' /etc/fstab || echo '# CloneBox 9p mounts' >> /etc/fstab")
            for entry in fstab_entries:
                runcmd_lines.append(f"  - grep -qF \"{entry}\" /etc/fstab || echo '{entry}' >> /etc/fstab")
            runcmd_lines.append("  - mount -a || true")
        
        # Add mounts (immediate, before reboot)
        for cmd in mount_commands:
            runcmd_lines.append(cmd)
        
        # Install snap packages
        if config.snap_packages:
            runcmd_lines.append("  - echo 'Installing snap packages...'")
            for snap_pkg in config.snap_packages:
                runcmd_lines.append(f"  - snap install {snap_pkg} --classic || snap install {snap_pkg} || true")
            
            # Connect snap interfaces for GUI apps (not auto-connected via cloud-init)
            runcmd_lines.append("  - echo 'Connecting snap interfaces...'")
            for snap_pkg in config.snap_packages:
                interfaces = SNAP_INTERFACES.get(snap_pkg, DEFAULT_SNAP_INTERFACES)
                for iface in interfaces:
                    runcmd_lines.append(f"  - snap connect {snap_pkg}:{iface} :{iface} 2>/dev/null || true")

            runcmd_lines.append("  - systemctl restart snapd || true")
        
        # Add GUI setup if enabled - runs AFTER package installation completes
        if config.gui:
            runcmd_lines.extend([
                "  - systemctl set-default graphical.target",
                "  - systemctl enable gdm3 || systemctl enable gdm || true",
            ])
        
        # Run user-defined post commands
        if config.post_commands:
            runcmd_lines.append("  - echo 'Running post-setup commands...'")
            for cmd in config.post_commands:
                runcmd_lines.append(f"  - {cmd}")
        
        # Generate health check script
        health_script = self._generate_health_check_script(config)
        runcmd_lines.append(f"  - echo '{health_script}' | base64 -d > /usr/local/bin/clonebox-health")
        runcmd_lines.append("  - chmod +x /usr/local/bin/clonebox-health")
        runcmd_lines.append("  - /usr/local/bin/clonebox-health >> /var/log/clonebox-health.log 2>&1")
        runcmd_lines.append("  - echo 'CloneBox VM ready!' > /var/log/clonebox-ready")
        
        # Add reboot command at the end if GUI is enabled
        if config.gui:
            runcmd_lines.append("  - echo 'Rebooting in 10 seconds to start GUI...'")
            runcmd_lines.append("  - sleep 10 && reboot")
        
        runcmd_yaml = "\n".join(runcmd_lines) if runcmd_lines else ""
        bootcmd_yaml = "\n".join(mount_commands) if mount_commands else ""
        bootcmd_block = f"\nbootcmd:\n{bootcmd_yaml}\n" if bootcmd_yaml else ""

        # Remove power_state - using shutdown -r instead
        power_state_yaml = ""

        user_data = f"""#cloud-config
hostname: {config.name}
manage_etc_hosts: true

# Default user
users:
  - name: {config.username}
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    groups: sudo,adm,dialout,cdrom,floppy,audio,dip,video,plugdev,netdev,docker
    plain_text_passwd: {config.password}

# Allow password authentication
ssh_pwauth: true
chpasswd:
  expire: false

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
{power_state_yaml}

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
