# Resource Limits & Quotas

**Status:** 📝 Planned  
**Priority:** Medium  
**Estimated Effort:** 1 week  
**Dependencies:** None

## Problem Statement

Currently, VMs can consume unlimited host resources:
- No CPU limits → VM can starve host
- No memory caps → OOM killer may kill host processes
- No I/O throttling → VM can saturate disk
- No network bandwidth limits

## Proposed Solution

```yaml
# .clonebox.yaml
vm:
  name: dev-vm
  
  resources:
    cpu:
      vcpus: 4
      shares: 1024          # Relative weight (default: 1024)
      period: 100000        # CFS period in microseconds
      quota: 400000         # CFS quota (400% = 4 cores max)
      pin: [0, 1, 2, 3]     # Pin to specific host CPUs
      
    memory:
      limit: 8G             # Hard limit
      soft_limit: 6G        # Soft limit (for pressure)
      swap: 2G              # Swap limit
      hugepages: false      # Use hugepages
      
    disk:
      read_bps: 100M        # Read bytes/sec limit
      write_bps: 100M       # Write bytes/sec limit
      read_iops: 1000       # Read IOPS limit
      write_iops: 1000      # Write IOPS limit
      
    network:
      inbound: 100Mbps      # Inbound bandwidth
      outbound: 100Mbps     # Outbound bandwidth
```

## Technical Design

### Resource Limit Models

```python
# src/clonebox/resources/models.py
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

def parse_size(value: str) -> int:
    """Parse size string like '8G', '512M' to bytes."""
    value = value.strip().upper()
    multipliers = {
        'K': 1024,
        'M': 1024**2,
        'G': 1024**3,
        'T': 1024**4,
    }
    
    if value[-1] in multipliers:
        return int(float(value[:-1]) * multipliers[value[-1]])
    return int(value)

def parse_bandwidth(value: str) -> int:
    """Parse bandwidth like '100Mbps' to bits/sec."""
    value = value.strip().lower()
    
    if value.endswith('gbps'):
        return int(float(value[:-4]) * 1_000_000_000)
    elif value.endswith('mbps'):
        return int(float(value[:-4]) * 1_000_000)
    elif value.endswith('kbps'):
        return int(float(value[:-4]) * 1_000)
    elif value.endswith('bps'):
        return int(float(value[:-3]))
    
    return int(value)

@dataclass
class CPULimits:
    """CPU resource limits."""
    vcpus: int = 2
    shares: int = 1024           # CFS shares (weight)
    period: int = 100000         # CFS period (microseconds)
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
        
        elements.append(f"<shares>{self.shares}</shares>")
        
        if self.quota:
            elements.append(f"<period>{self.period}</period>")
            elements.append(f"<quota>{self.quota}</quota>")
        
        if self.pin:
            for idx, cpu in enumerate(self.pin):
                elements.append(f'<vcpupin vcpu="{idx}" cpuset="{cpu}"/>')
        
        return f"<cputune>\n{''.join(elements)}\n</cputune>"

@dataclass
class MemoryLimits:
    """Memory resource limits."""
    limit: str = "4G"           # Hard limit
    soft_limit: Optional[str] = None  # Soft limit
    swap: Optional[str] = None  # Swap limit
    hugepages: bool = False     # Use hugepages
    
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
        elements.append(f"<hard_limit unit='KiB'>{limit_kib}</hard_limit>")
        
        if self.soft_limit_bytes:
            soft_kib = self.soft_limit_bytes // 1024
            elements.append(f"<soft_limit unit='KiB'>{soft_kib}</soft_limit>")
        
        if self.swap_bytes:
            swap_kib = self.swap_bytes // 1024
            elements.append(f"<swap_hard_limit unit='KiB'>{swap_kib}</swap_hard_limit>")
        
        return f"<memtune>\n{''.join(elements)}\n</memtune>"

@dataclass
class DiskLimits:
    """Disk I/O limits."""
    read_bps: Optional[str] = None    # Read bytes/sec
    write_bps: Optional[str] = None   # Write bytes/sec
    read_iops: Optional[int] = None   # Read IOPS
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
            elements.append(f"<read_bytes_sec>{self.read_bps_bytes}</read_bytes_sec>")
        if self.write_bps_bytes:
            elements.append(f"<write_bytes_sec>{self.write_bps_bytes}</write_bytes_sec>")
        if self.read_iops:
            elements.append(f"<read_iops_sec>{self.read_iops}</read_iops_sec>")
        if self.write_iops:
            elements.append(f"<write_iops_sec>{self.write_iops}</write_iops_sec>")
        
        if elements:
            return f"<iotune>\n{''.join(elements)}\n</iotune>"
        return ""

@dataclass
class NetworkLimits:
    """Network bandwidth limits."""
    inbound: Optional[str] = None   # Inbound bandwidth
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
            # average in KB/s, peak, burst
            avg_kbs = self.inbound_kbps // 8
            elements.append(f'<inbound average="{avg_kbs}"/>')
        
        if self.outbound_kbps:
            avg_kbs = self.outbound_kbps // 8
            elements.append(f'<outbound average="{avg_kbs}"/>')
        
        if elements:
            return f"<bandwidth>\n{''.join(elements)}\n</bandwidth>"
        return ""

@dataclass
class ResourceLimits:
    """Combined resource limits for a VM."""
    cpu: CPULimits = field(default_factory=CPULimits)
    memory: MemoryLimits = field(default_factory=MemoryLimits)
    disk: DiskLimits = field(default_factory=DiskLimits)
    network: NetworkLimits = field(default_factory=NetworkLimits)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ResourceLimits':
        """Create from config dict."""
        return cls(
            cpu=CPULimits(**data.get('cpu', {})),
            memory=MemoryLimits(**data.get('memory', {})),
            disk=DiskLimits(**data.get('disk', {})),
            network=NetworkLimits(**data.get('network', {})),
        )
```

### Updated VM XML Generation

```python
# src/clonebox/cloner.py (updated method)

def _generate_vm_xml(
    self,
    config: VMConfig,
    root_disk: Path,
    cloudinit_iso: Optional[Path] = None,
) -> str:
    """Generate libvirt XML with resource limits."""
    
    # Get resource limits
    limits = ResourceLimits.from_dict(config.resources or {})
    
    # Base XML structure
    xml_parts = [
        f'<domain type="kvm">',
        f'  <name>{config.name}</name>',
        f'  <memory unit="KiB">{limits.memory.limit_bytes // 1024}</memory>',
        f'  <vcpu placement="static">{limits.cpu.vcpus}</vcpu>',
    ]
    
    # CPU tuning
    xml_parts.append(limits.cpu.to_libvirt_xml())
    
    # Memory tuning
    xml_parts.append(limits.memory.to_libvirt_xml())
    
    # OS configuration
    xml_parts.extend([
        '  <os>',
        '    <type arch="x86_64" machine="q35">hvm</type>',
        '    <boot dev="hd"/>',
        '  </os>',
    ])
    
    # Devices section
    xml_parts.append('  <devices>')
    
    # Disk with I/O limits
    disk_iotune = limits.disk.to_libvirt_xml()
    xml_parts.extend([
        f'    <disk type="file" device="disk">',
        f'      <driver name="qemu" type="qcow2"/>',
        f'      <source file="{root_disk}"/>',
        f'      <target dev="vda" bus="virtio"/>',
        f'      {disk_iotune}',
        f'    </disk>',
    ])
    
    # Network with bandwidth limits
    network_bandwidth = limits.network.to_libvirt_xml()
    network_mode = self.resolve_network_mode(config)
    
    if network_mode == "user":
        xml_parts.extend([
            '    <interface type="user">',
            '      <model type="virtio"/>',
            f'      {network_bandwidth}',
            '    </interface>',
        ])
    else:
        xml_parts.extend([
            '    <interface type="network">',
            '      <source network="default"/>',
            '      <model type="virtio"/>',
            f'      {network_bandwidth}',
            '    </interface>',
        ])
    
    # Close devices and domain
    xml_parts.extend([
        '  </devices>',
        '</domain>',
    ])
    
    return '\n'.join(xml_parts)
```

### Resource Monitoring

```python
# src/clonebox/resources/monitor.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import libvirt

@dataclass
class ResourceUsage:
    """Current resource usage of a VM."""
    timestamp: datetime
    
    # CPU
    cpu_time_ns: int
    cpu_percent: float
    
    # Memory
    memory_used_bytes: int
    memory_percent: float
    swap_used_bytes: int
    
    # Disk I/O
    disk_read_bytes: int
    disk_write_bytes: int
    disk_read_requests: int
    disk_write_requests: int
    
    # Network I/O
    net_rx_bytes: int
    net_tx_bytes: int
    net_rx_packets: int
    net_tx_packets: int

class ResourceMonitor:
    """Monitor VM resource usage."""
    
    def __init__(self, conn: libvirt.virConnect):
        self.conn = conn
        self._prev_stats: dict = {}
    
    def get_usage(self, vm_name: str) -> ResourceUsage:
        """Get current resource usage."""
        domain = self.conn.lookupByName(vm_name)
        
        # CPU stats
        cpu_stats = domain.getCPUStats(True)[0]
        cpu_time = cpu_stats.get('cpu_time', 0)
        
        # Calculate CPU percentage
        cpu_percent = self._calculate_cpu_percent(vm_name, cpu_time)
        
        # Memory stats
        mem_stats = domain.memoryStats()
        memory_used = mem_stats.get('actual', 0) * 1024
        memory_total = mem_stats.get('available', 1) * 1024
        memory_percent = (memory_used / memory_total) * 100 if memory_total else 0
        swap_used = mem_stats.get('swap_in', 0) * 1024
        
        # Block stats
        disk_stats = self._get_disk_stats(domain)
        
        # Network stats
        net_stats = self._get_network_stats(domain)
        
        return ResourceUsage(
            timestamp=datetime.now(),
            cpu_time_ns=cpu_time,
            cpu_percent=cpu_percent,
            memory_used_bytes=memory_used,
            memory_percent=memory_percent,
            swap_used_bytes=swap_used,
            **disk_stats,
            **net_stats,
        )
    
    def _calculate_cpu_percent(self, vm_name: str, cpu_time: int) -> float:
        """Calculate CPU percentage from time delta."""
        import time
        
        now = time.time()
        prev = self._prev_stats.get(vm_name, {})
        prev_time = prev.get('cpu_time', cpu_time)
        prev_timestamp = prev.get('timestamp', now)
        
        # Update stored stats
        self._prev_stats[vm_name] = {
            'cpu_time': cpu_time,
            'timestamp': now,
        }
        
        # Calculate percentage
        time_delta = now - prev_timestamp
        if time_delta <= 0:
            return 0.0
        
        cpu_delta = cpu_time - prev_time
        # cpu_time is in nanoseconds
        return (cpu_delta / (time_delta * 1e9)) * 100
    
    def _get_disk_stats(self, domain) -> dict:
        """Get aggregated disk stats."""
        stats = {
            'disk_read_bytes': 0,
            'disk_write_bytes': 0,
            'disk_read_requests': 0,
            'disk_write_requests': 0,
        }
        
        # Parse XML to find disk devices
        import xml.etree.ElementTree as ET
        xml = domain.XMLDesc()
        tree = ET.fromstring(xml)
        
        for disk in tree.findall('.//disk'):
            target = disk.find('target')
            if target is not None:
                dev = target.get('dev')
                try:
                    disk_stats = domain.blockStats(dev)
                    stats['disk_read_requests'] += disk_stats[0]
                    stats['disk_read_bytes'] += disk_stats[1]
                    stats['disk_write_requests'] += disk_stats[2]
                    stats['disk_write_bytes'] += disk_stats[3]
                except Exception:
                    pass
        
        return stats
    
    def _get_network_stats(self, domain) -> dict:
        """Get aggregated network stats."""
        stats = {
            'net_rx_bytes': 0,
            'net_tx_bytes': 0,
            'net_rx_packets': 0,
            'net_tx_packets': 0,
        }
        
        import xml.etree.ElementTree as ET
        xml = domain.XMLDesc()
        tree = ET.fromstring(xml)
        
        for iface in tree.findall('.//interface'):
            target = iface.find('target')
            if target is not None:
                dev = target.get('dev')
                try:
                    net_stats = domain.interfaceStats(dev)
                    stats['net_rx_bytes'] += net_stats[0]
                    stats['net_rx_packets'] += net_stats[1]
                    stats['net_tx_bytes'] += net_stats[4]
                    stats['net_tx_packets'] += net_stats[5]
                except Exception:
                    pass
        
        return stats
    
    def check_limits(
        self,
        vm_name: str,
        limits: ResourceLimits,
    ) -> dict:
        """Check if VM is within resource limits."""
        usage = self.get_usage(vm_name)
        
        violations = []
        
        # Check CPU
        max_cpu = limits.cpu.get_max_percent()
        if usage.cpu_percent > max_cpu:
            violations.append({
                'resource': 'cpu',
                'limit': max_cpu,
                'actual': usage.cpu_percent,
            })
        
        # Check memory
        if usage.memory_used_bytes > limits.memory.limit_bytes:
            violations.append({
                'resource': 'memory',
                'limit': limits.memory.limit_bytes,
                'actual': usage.memory_used_bytes,
            })
        
        return {
            'within_limits': len(violations) == 0,
            'violations': violations,
            'usage': usage,
        }
```

### CLI Commands

```bash
# Set resource limits on existing VM
clonebox resources set my-vm --cpu-quota 200000 --memory 8G

# Show current resource usage
clonebox resources usage my-vm

# Watch resource usage live
clonebox resources watch my-vm --interval 1

# Show resource limits
clonebox resources limits my-vm
```

## Configuration Examples

```yaml
# Development VM - generous limits
vm:
  name: dev-vm
  resources:
    cpu:
      vcpus: 4
      shares: 1024
    memory:
      limit: 8G
    disk:
      read_bps: 500M
      write_bps: 500M

# CI/CD VM - strict limits
vm:
  name: ci-runner
  resources:
    cpu:
      vcpus: 2
      quota: 200000    # Max 200% CPU (2 cores)
    memory:
      limit: 4G
      swap: 0          # No swap
    disk:
      read_iops: 500
      write_iops: 500
    network:
      outbound: 50Mbps

# Database VM - I/O optimized
vm:
  name: postgres-vm
  resources:
    cpu:
      vcpus: 4
      pin: [4, 5, 6, 7]  # Pin to dedicated cores
    memory:
      limit: 16G
      hugepages: true
    disk:
      read_iops: 10000
      write_iops: 10000
```

## Testing Strategy

```python
class TestResourceLimits:
    def test_parse_size(self):
        assert parse_size("8G") == 8 * 1024**3
        assert parse_size("512M") == 512 * 1024**2
        assert parse_size("1T") == 1024**4
    
    def test_cpu_limits_xml(self):
        limits = CPULimits(vcpus=4, shares=2048, quota=400000)
        xml = limits.to_libvirt_xml()
        
        assert "<shares>2048</shares>" in xml
        assert "<quota>400000</quota>" in xml
    
    def test_memory_limits_xml(self):
        limits = MemoryLimits(limit="8G", soft_limit="6G")
        xml = limits.to_libvirt_xml()
        
        assert "8388608" in xml  # 8G in KiB
    
    @pytest.mark.integration
    def test_vm_respects_cpu_limit(self, running_vm):
        # Run CPU-intensive task
        # Verify it doesn't exceed quota
        pass
```
