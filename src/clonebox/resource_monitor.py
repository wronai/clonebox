"""Resource monitoring system for CloneBox."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import libvirt
except ImportError:
    libvirt = None


@dataclass
class ResourceUsage:
    """Current resource usage of a VM."""

    timestamp: datetime
    cpu_time_ns: int
    cpu_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    memory_percent: float
    swap_used_bytes: int
    disk_read_bytes: int
    disk_write_bytes: int
    disk_read_requests: int
    disk_write_requests: int
    net_rx_bytes: int
    net_tx_bytes: int
    net_rx_packets: int
    net_tx_packets: int


class ResourceMonitor:
    """Monitor VM resource usage using libvirt."""

    def __init__(self, conn: Optional[Any] = None):
        self.conn = conn
        self._prev_stats: Dict[str, Dict] = {}

    def get_usage(self, vm_name: str) -> ResourceUsage:
        """Get current resource usage for a VM."""
        if not self.conn:
            raise RuntimeError("libvirt connection not available")

        domain = self.conn.lookupByName(vm_name)
        if not domain.isActive():
            raise RuntimeError(f"VM '{vm_name}' is not running")

        # CPU stats
        cpu_stats = domain.getCPUStats(True)[0]
        cpu_time = cpu_stats.get("cpu_time", 0)
        cpu_percent = self._calculate_cpu_percent(vm_name, cpu_time)

        # Memory stats
        # Need to ensure memory balloon driver is active for accurate stats
        mem_stats = domain.memoryStats()
        memory_used = mem_stats.get("rss", 0) * 1024  # RSS is often most accurate for host view
        memory_total = mem_stats.get("actual", 1) * 1024
        if "unused" in mem_stats:
            memory_used = (mem_stats["actual"] - mem_stats["unused"]) * 1024
        
        memory_percent = (memory_used / memory_total * 100) if memory_total else 0
        swap_used = mem_stats.get("swap_in", 0) * 1024

        # Block and Network stats
        disk_stats = self._get_disk_stats(domain)
        net_stats = self._get_network_stats(domain)

        return ResourceUsage(
            timestamp=datetime.now(),
            cpu_time_ns=cpu_time,
            cpu_percent=cpu_percent,
            memory_used_bytes=memory_used,
            memory_total_bytes=memory_total,
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
        prev_time = prev.get("cpu_time", cpu_time)
        prev_timestamp = prev.get("timestamp", now)

        # Update stored stats
        self._prev_stats[vm_name] = {
            "cpu_time": cpu_time,
            "timestamp": now,
        }

        time_delta = now - prev_timestamp
        if time_delta <= 0:
            return 0.0

        cpu_delta = cpu_time - prev_time
        # cpu_time is in nanoseconds, time_delta in seconds
        # (delta_ns / (delta_sec * 1e9)) * 100
        return (cpu_delta / (time_delta * 1e9)) * 100

    def _get_disk_stats(self, domain) -> Dict[str, int]:
        """Get aggregated disk stats."""
        stats = {
            "disk_read_bytes": 0,
            "disk_write_bytes": 0,
            "disk_read_requests": 0,
            "disk_write_requests": 0,
        }

        xml = domain.XMLDesc()
        tree = ET.fromstring(xml)

        for disk in tree.findall(".//disk"):
            target = disk.find("target")
            if target is not None:
                dev = target.get("dev")
                try:
                    # blockStats returns: (read_req, read_bytes, write_req, write_bytes, errs)
                    ds = domain.blockStats(dev)
                    stats["disk_read_requests"] += ds[0]
                    stats["disk_read_bytes"] += ds[1]
                    stats["disk_write_requests"] += ds[2]
                    stats["disk_write_bytes"] += ds[3]
                except Exception:
                    continue

        return stats

    def _get_network_stats(self, domain) -> Dict[str, int]:
        """Get aggregated network stats."""
        stats = {
            "net_rx_bytes": 0,
            "net_tx_bytes": 0,
            "net_rx_packets": 0,
            "net_tx_packets": 0,
        }

        xml = domain.XMLDesc()
        tree = ET.fromstring(xml)

        for iface in tree.findall(".//interface"):
            target = iface.find("target")
            if target is not None:
                dev = target.get("dev")
                try:
                    # interfaceStats returns: (rx_bytes, rx_packets, rx_errs, rx_drop, 
                    #                          tx_bytes, tx_packets, tx_errs, tx_drop)
                    ns = domain.interfaceStats(dev)
                    stats["net_rx_bytes"] += ns[0]
                    stats["net_rx_packets"] += ns[1]
                    stats["net_tx_bytes"] += ns[4]
                    stats["net_tx_packets"] += ns[5]
                except Exception:
                    continue

        return stats
