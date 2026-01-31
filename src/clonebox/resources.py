"""
Resource limits and monitoring for CloneBox VMs.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Union


def parse_size(value: Union[str, int]) -> int:
    """Parse size string like '8G', '512M' to bytes."""
    if isinstance(value, int):
        return value
        
    value = str(value).strip().upper()
    multipliers = {
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
    }

    if value[-1] in multipliers:
        try:
            return int(float(value[:-1]) * multipliers[value[-1]])
        except ValueError:
            return 0
    
    try:
        return int(value)
    except ValueError:
        return 0


def parse_bandwidth(value: Union[str, int]) -> int:
    """Parse bandwidth like '100Mbps' to bits/sec."""
    if isinstance(value, int):
        return value
        
    value = str(value).strip().lower()

    if value.endswith("gbps"):
        return int(float(value[:-4]) * 1_000_000_000)
    elif value.endswith("mbps"):
        return int(float(value[:-4]) * 1_000_000)
    elif value.endswith("kbps"):
        return int(float(value[:-4]) * 1_000)
    elif value.endswith("bps"):
        return int(float(value[:-3]))

    try:
        return int(value)
    except ValueError:
        return 0


@dataclass
class CPULimits:
    """CPU resource limits."""

    vcpus: int = 2
    shares: int = 1024  # CFS shares (weight)
    period: int = 100000  # CFS period (microseconds)
    quota: Optional[int] = None  # CFS quota (microseconds)
    pin: Optional[List[int]] = None  # CPU pinning

    def get_max_percent(self) -> float:
        """Get max CPU percentage."""
        if self.quota:
            return (self.quota / self.period) * 100
        return self.vcpus * 100

    def to_libvirt_xml(self) -> str:
        """Generate libvirt cputune XML."""
        elements = []
        elements.append(f"    <shares>{self.shares}</shares>")

        if self.quota:
            elements.append(f"    <period>{self.period}</period>")
            elements.append(f"    <quota>{self.quota}</quota>")

        if self.pin:
            for idx, cpu in enumerate(self.pin):
                elements.append(f'    <vcpupin vcpu="{idx}" cpuset="{cpu}"/>')

        if not elements:
            return ""
            
        return f"  <cputune>\n{chr(10).join(elements)}\n  </cputune>"


@dataclass
class MemoryLimits:
    """Memory resource limits."""

    limit: str = "4G"  # Hard limit
    soft_limit: Optional[str] = None  # Soft limit
    swap: Optional[str] = None  # Swap limit
    hugepages: bool = False  # Use hugepages

    @property
    def limit_bytes(self) -> int:
        return parse_size(self.limit)

    @property
    def soft_limit_bytes(self) -> Optional[int]:
        return parse_size(self.soft_limit) if self.soft_limit else None

    @property
    def swap_bytes(self) -> Optional[int]:
        return parse_size(self.swap) if self.swap else None

    def to_libvirt_xml(self) -> str:
        """Generate libvirt memtune XML."""
        elements = []

        # Convert to KiB for libvirt
        limit_kib = self.limit_bytes // 1024
        elements.append(f"    <hard_limit unit='KiB'>{limit_kib}</hard_limit>")

        if self.soft_limit_bytes:
            soft_kib = self.soft_limit_bytes // 1024
            elements.append(f"    <soft_limit unit='KiB'>{soft_kib}</soft_limit>")

        if self.swap_bytes:
            swap_kib = self.swap_bytes // 1024
            elements.append(f"    <swap_hard_limit unit='KiB'>{swap_kib}</swap_hard_limit>")

        return f"  <memtune>\n{chr(10).join(elements)}\n  </memtune>"


@dataclass
class DiskLimits:
    """Disk I/O limits."""

    read_bps: Optional[str] = None  # Read bytes/sec
    write_bps: Optional[str] = None  # Write bytes/sec
    read_iops: Optional[int] = None  # Read IOPS
    write_iops: Optional[int] = None  # Write IOPS

    @property
    def read_bps_bytes(self) -> Optional[int]:
        return parse_size(self.read_bps) if self.read_bps else None

    @property
    def write_bps_bytes(self) -> Optional[int]:
        return parse_size(self.write_bps) if self.write_bps else None

    def to_libvirt_xml(self) -> str:
        """Generate libvirt iotune XML for disk device."""
        elements = []

        if self.read_bps_bytes:
            elements.append(f"      <read_bytes_sec>{self.read_bps_bytes}</read_bytes_sec>")
        if self.write_bps_bytes:
            elements.append(f"      <write_bytes_sec>{self.write_bps_bytes}</write_bytes_sec>")
        if self.read_iops:
            elements.append(f"      <read_iops_sec>{self.read_iops}</read_iops_sec>")
        if self.write_iops:
            elements.append(f"      <write_iops_sec>{self.write_iops}</write_iops_sec>")

        if elements:
            return f"    <iotune>\n{chr(10).join(elements)}\n    </iotune>"
        return ""


@dataclass
class NetworkLimits:
    """Network bandwidth limits."""

    inbound: Optional[str] = None  # Inbound bandwidth
    outbound: Optional[str] = None  # Outbound bandwidth

    @property
    def inbound_kbps(self) -> Optional[int]:
        if self.inbound:
            return parse_bandwidth(self.inbound) // 1000  # Convert to kbps
        return None

    @property
    def outbound_kbps(self) -> Optional[int]:
        if self.outbound:
            return parse_bandwidth(self.outbound) // 1000
        return None

    def to_libvirt_xml(self) -> str:
        """Generate libvirt bandwidth XML for interface."""
        elements = []

        if self.inbound_kbps:
            # average in KB/s (libvirt uses kbps but sometimes expects KB/s depending on version,
            # usually it's average in kbytes/s)
            avg_kbs = self.inbound_kbps // 8
            elements.append(f'      <inbound average="{avg_kbs}"/>')

        if self.outbound_kbps:
            avg_kbs = self.outbound_kbps // 8
            elements.append(f'      <outbound average="{avg_kbs}"/>')

        if elements:
            return f"    <bandwidth>\n{chr(10).join(elements)}\n    </bandwidth>"
        return ""


@dataclass
class ResourceLimits:
    """Combined resource limits for a VM."""

    cpu: CPULimits = field(default_factory=CPULimits)
    memory: MemoryLimits = field(default_factory=MemoryLimits)
    disk: DiskLimits = field(default_factory=DiskLimits)
    network: NetworkLimits = field(default_factory=NetworkLimits)

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceLimits":
        """Create from config dict."""
        return cls(
            cpu=CPULimits(**data.get("cpu", {})),
            memory=MemoryLimits(**data.get("memory", {})),
            disk=DiskLimits(**data.get("disk", {})),
            network=NetworkLimits(**data.get("network", {})),
        )
