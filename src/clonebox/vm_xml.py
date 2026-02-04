#!/usr/bin/env python3
"""
VM XML generation for libvirt.
"""

import uuid
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from clonebox.models import VMConfig


def generate_vm_xml(
    config: VMConfig,
    vm_uuid: str,
    disk_path: str,
    cdrom_path: Optional[str] = None,
    user_session: bool = False,
) -> str:
    """Generate libvirt XML configuration for VM."""
    from pathlib import Path
    
    # Create root domain element
    domain = ET.Element("domain", type="kvm")
    
    # Basic metadata
    ET.SubElement(domain, "name").text = config.name
    ET.SubElement(domain, "uuid").text = vm_uuid
    ET.SubElement(domain, "metadata")
    
    # Memory and CPU
    ET.SubElement(domain, "memory", unit="MiB").text = str(config.ram_mb)
    ET.SubElement(domain, "currentMemory", unit="MiB").text = str(config.ram_mb)
    ET.SubElement(domain, "vcpu", placement="static").text = str(config.vcpus)
    
    # CPU configuration
    cpu = ET.SubElement(domain, "cpu", mode="host-model", check="partial")
    ET.SubElement(cpu, "feature", policy="require", name="vmx")
    
    # OS configuration
    os_elem = ET.SubElement(domain, "os")
    ET.SubElement(os_elem, "type", arch="x86_64", machine="pc").text = "hvm"
    ET.SubElement(os_elem, "boot", dev="hd")
    if cdrom_path:
        ET.SubElement(os_elem, "boot", dev="cdrom")
    
    # Features
    features = ET.SubElement(domain, "features")
    ET.SubElement(features, "acpi")
    ET.SubElement(features, "apic")
    ET.SubElement(features, "vmport", state="off")
    
    # CPU mode
    ET.SubElement(domain, "cpu", mode="host-model", check="partial")
    
    # Clock
    clock = ET.SubElement(domain, "clock", offset="utc")
    ET.SubElement(clock, "timer", name="rtc", tickpolicy="catchup", track="guest")
    ET.SubElement(clock, "timer", name="pit", tickpolicy="delay")
    ET.SubElement(clock, "timer", name="hpet", present="no")
    
    # PM (Power Management)
    pm = ET.SubElement(domain, "pm")
    ET.SubElement(pm, "suspend-to-mem", enabled="no")
    ET.SubElement(pm, "suspend-to-disk", enabled="no")
    
    # Devices
    devices = ET.SubElement(domain, "devices")
    
    # Controller for SCSI
    controller = ET.SubElement(devices, "controller", type="scsi", index="0", model="virtio-scsi")
    
    # Disk
    disk = ET.SubElement(devices, "disk", type="file", device="disk")
    ET.SubElement(disk, "driver", name="qemu", type="qcow2", cache="writeback", io="threads")
    ET.SubElement(disk, "source", file=disk_path)
    ET.SubElement(disk, "target", dev="vda", bus="virtio")
    
    # CDROM (if provided)
    if cdrom_path:
        disk = ET.SubElement(devices, "disk", type="file", device="cdrom")
        ET.SubElement(disk, "driver", name="qemu", type="raw")
        ET.SubElement(disk, "source", file=cdrom_path)
        ET.SubElement(disk, "target", dev="sda", bus="sata")
        ET.SubElement(disk, "readonly")
    
    # Network interface
    _add_network_interface(devices, config, user_session)
    
    # Graphics (if GUI enabled)
    if config.gui:
        _add_graphics(devices, config)
    
    # Channel for QEMU Guest Agent (only for system session)
    if not user_session:
        channel = ET.SubElement(devices, "channel", type="unix")
        # Let libvirt handle the socket path
        ET.SubElement(channel, "source", mode="bind")
        ET.SubElement(channel, "target", type="virtio", name="org.qemu.guest_agent.0")
    
    # Filesystem for 9p mounts
    for idx, (host_path, guest_path) in enumerate(config.paths.items()):
        fs = ET.SubElement(devices, "filesystem", type="mount", accessmode="passthrough")
        ET.SubElement(fs, "source", dir=host_path)
        ET.SubElement(fs, "target", dir=guest_path)
        ET.SubElement(fs, "alias", name=f"fs{idx}")
    
    # Input devices (only for system session)
    if not user_session:
        input_dev = ET.SubElement(devices, "input", type="tablet", bus="usb")
        ET.SubElement(input_dev, "address", type="usb", bus="0", port="1")
        
        input_dev = ET.SubElement(devices, "input", type="keyboard", bus="usb")
        ET.SubElement(input_dev, "address", type="usb", bus="0", port="2")
    
    # Always add PS/2 input
    ET.SubElement(devices, "input", type="mouse", bus="ps2")
    ET.SubElement(devices, "input", type="keyboard", bus="ps2")
    
    # Serial console for cloud-init logs and debugging
    serial = ET.SubElement(devices, "serial", type="pty")
    ET.SubElement(serial, "source", path="/dev/ttyS0")
    ET.SubElement(serial, "target", type="isa-serial", port="0")
    ET.SubElement(serial, "log", file=f"/home/tom/.local/share/libvirt/images/{config.name}/serial.log", append="on")
    
    console = ET.SubElement(devices, "console", type="pty")
    ET.SubElement(console, "target", type="serial", port="0")
    
    # Video
    video = ET.SubElement(devices, "video")
    if user_session:
        # Use standard VGA for user session
        model = ET.SubElement(video, "model", type="vga", heads="1", primary="yes")
    else:
        # Use virtio with OpenGL for system session
        model = ET.SubElement(video, "model", type="virtio", heads="1", primary="yes")
        ET.SubElement(model, "acceleration", accel3d="yes")
    
    # Sound (only for system session)
    if not user_session:
        _add_sound_device(devices)
    
    # Memory balloon (only for system session)
    if not user_session:
        memballoon = ET.SubElement(devices, "memballoon", model="virtio")
    
    # RNG device (only for system session)
    if not user_session:
        rng = ET.SubElement(devices, "rng", model="virtio")
        ET.SubElement(rng, "backend", model="random", device="/dev/urandom")
    
    # Resource limits (only for system session)
    if not user_session:
        _add_resource_limits(domain, config)
    
    # Generate XML string
    ET.indent(domain, space="  ")
    return ET.tostring(domain, encoding="unicode")


def _add_network_interface(devices: ET.Element, config: VMConfig, user_session: bool):
    """Add network interface configuration."""
    
    if config.network_mode == "user":
        # User mode networking (slirp)
        interface = ET.SubElement(devices, "interface", type="user")
        ET.SubElement(interface, "mac", address=_generate_mac_address())
        ET.SubElement(interface, "model", type="virtio")
    elif config.network_mode == "auto":
        if user_session:
            # Use passt for user session if available
            interface = ET.SubElement(devices, "interface", type="user")
            ET.SubElement(interface, "backend", type="passt")
            ET.SubElement(interface, "mac", address=_generate_mac_address())
            ET.SubElement(interface, "model", type="virtio")
        else:
            # Use default network for system session
            interface = ET.SubElement(devices, "interface", type="network")
            ET.SubElement(interface, "source", network="default")
            ET.SubElement(interface, "mac", address=_generate_mac_address())
            ET.SubElement(interface, "model", type="virtio")
    else:
        # Default network
        interface = ET.SubElement(devices, "interface", type="network")
        ET.SubElement(interface, "source", network="default")
        ET.SubElement(interface, "mac", address=_generate_mac_address())
        ET.SubElement(interface, "model", type="virtio")


def _add_graphics(devices: ET.Element, config: VMConfig):
    """Add graphics configuration."""
    
    # SPICE graphics
    graphics = ET.SubElement(devices, "graphics", type="spice", autoport="yes", listen="0.0.0.0")
    ET.SubElement(graphics, "listen", type="address", address="0.0.0.0")
    ET.SubElement(graphics, "image", compression="off")
    
    # SPICE channel
    channel = ET.SubElement(devices, "channel", type="spicevmc")
    ET.SubElement(channel, "target", type="virtio", name="com.redhat.spice.0")
    
    # VNC graphics (fallback)
    graphics = ET.SubElement(devices, "graphics", type="vnc", port="-1", autoport="yes", listen="0.0.0.0")
    ET.SubElement(graphics, "listen", type="address", address="0.0.0.0")


def _add_sound_device(devices: ET.Element):
    """Add sound device configuration."""
    
    sound = ET.SubElement(devices, "sound", model="ich9")
    
    # Audio devices
    audio = ET.SubElement(devices, "audio", id="1", type="pulseaudio")
    ET.SubElement(audio, "input", mixers="master")
    ET.SubElement(audio, "output", mixers="master")


def _add_resource_limits(domain: ET.Element, config: VMConfig):
    """Add resource limits (cgroups)."""
    
    if not config.resources:
        return
    
    # Memory tuning
    if "memory" in config.resources:
        memtune = ET.SubElement(domain, "memtune")
        if "hard_limit" in config.resources["memory"]:
            ET.SubElement(memtune, "hard_limit", unit="MiB").text = str(config.resources["memory"]["hard_limit"])
        if "soft_limit" in config.resources["memory"]:
            ET.SubElement(memtune, "soft_limit", unit="MiB").text = str(config.resources["memory"]["soft_limit"])
        if "swap_limit" in config.resources["memory"]:
            ET.SubElement(memtune, "swap_hard_limit", unit="MiB").text = str(config.resources["memory"]["swap_limit"])
    
    # CPU tuning
    if "cpu" in config.resources:
        cputune = ET.SubElement(domain, "cputune")
        if "quota" in config.resources["cpu"]:
            ET.SubElement(cputune, "quota").text = str(config.resources["cpu"]["quota"])
        if "period" in config.resources["cpu"]:
            ET.SubElement(cputune, "period").text = str(config.resources["cpu"]["period"])
        if "vcpus" in config.resources["cpu"]:
            ET.SubElement(cputune, "vcpupin", vcpu="0", cpuset=config.resources["cpu"]["vcpus"])
    
    # Block I/O tuning
    if "disk" in config.resources:
        blkiotune = ET.SubElement(domain, "blkiotune")
        if "weight" in config.resources["disk"]:
            ET.SubElement(blkiotune, "weight").text = str(config.resources["disk"]["weight"])
        if "read_bytes_sec" in config.resources["disk"]:
            ET.SubElement(blkiotune, "device", path="/dev/vda").set("read_bytes_sec", str(config.resources["disk"]["read_bytes_sec"]))
        if "write_bytes_sec" in config.resources["disk"]:
            ET.SubElement(blkiotune, "device", path="/dev/vda").set("write_bytes_sec", str(config.resources["disk"]["write_bytes_sec"]))


def _generate_mac_address() -> str:
    """Generate a random MAC address for VM."""
    import random
    mac = [0x52, 0x54, 0x00, random.randint(0x00, 0xff), random.randint(0x00, 0xff), random.randint(0x00, 0xff)]
    return ":".join(f"{b:02x}" for b in mac)


def generate_network_xml(network_name: str, bridge_name: str = "virbr0", dhcp: bool = True) -> str:
    """Generate network XML for libvirt."""
    
    network = ET.Element("network")
    ET.SubElement(network, "name").text = network_name
    
    if dhcp:
        ip = ET.SubElement(network, "ip", address="192.168.122.1", netmask="255.255.255.0")
        dhcp = ET.SubElement(ip, "dhcp")
        ET.SubElement(dhcp, "range", start="192.168.122.2", end="192.168.122.254")
    
    ET.indent(network, space="  ")
    return ET.tostring(network, encoding="unicode")


def generate_pool_xml(pool_name: str, pool_path: str, pool_type: str = "dir") -> str:
    """Generate storage pool XML for libvirt."""
    
    pool = ET.Element("pool", type=pool_type)
    ET.SubElement(pool, "name").text = pool_name
    
    target = ET.SubElement(pool, "target")
    ET.SubElement(target, "path").text = pool_path
    
    if pool_type == "dir":
        ET.SubElement(target, "permissions")
        ET.SubElement(target, "mode").text = "0755"
        ET.SubElement(target, "owner").text = "0"
        ET.SubElement(target, "group").text = "0"
    
    ET.indent(pool, space="  ")
    return ET.tostring(pool, encoding="unicode")


def generate_volume_xml(volume_name: str, capacity_gb: int, format_type: str = "qcow2") -> str:
    """Generate storage volume XML for libvirt."""
    
    volume = ET.Element("volume", type="file")
    ET.SubElement(volume, "name").text = volume_name
    ET.SubElement(volume, "capacity", unit="G").text = str(capacity_gb)
    
    target = ET.SubElement(volume, "target")
    ET.SubElement(target, "format", type=format_type)
    
    permissions = ET.SubElement(volume, "permissions")
    ET.SubElement(permissions, "mode").text = "0644"
    ET.SubElement(permissions, "owner").text = "0"
    ET.SubElement(permissions, "group").text = "0"
    
    ET.indent(volume, space="  ")
    return ET.tostring(volume, encoding="unicode")
