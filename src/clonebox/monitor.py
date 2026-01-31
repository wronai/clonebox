#!/usr/bin/env python3
"""
Real-time resource monitoring for CloneBox VMs and containers.
"""

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import libvirt
except ImportError:
    libvirt = None


@dataclass
class VMStats:
    """VM resource statistics."""

    name: str
    state: str
    cpu_percent: float
    memory_used_mb: int
    memory_total_mb: int
    disk_used_gb: float
    disk_total_gb: float
    network_rx_bytes: int
    network_tx_bytes: int
    uptime_seconds: int


@dataclass
class ContainerStats:
    """Container resource statistics."""

    name: str
    state: str
    cpu_percent: float
    memory_used_mb: int
    memory_limit_mb: int
    network_rx_bytes: int
    network_tx_bytes: int
    pids: int


class ResourceMonitor:
    """Monitor VM and container resources in real-time."""

    def __init__(self, conn_uri: str = "qemu:///session"):
        self.conn_uri = conn_uri
        self._conn = None
        self._prev_cpu: Dict[str, tuple] = {}

    @property
    def conn(self):
        if self._conn is None:
            if libvirt is None:
                raise RuntimeError("libvirt-python not installed")
            self._conn = libvirt.open(self.conn_uri)
        return self._conn

    def get_vm_stats(self, vm_name: str) -> Optional[VMStats]:
        """Get resource statistics for a VM."""
        try:
            dom = self.conn.lookupByName(vm_name)
            info = dom.info()

            state_map = {
                libvirt.VIR_DOMAIN_RUNNING: "running",
                libvirt.VIR_DOMAIN_PAUSED: "paused",
                libvirt.VIR_DOMAIN_SHUTDOWN: "shutdown",
                libvirt.VIR_DOMAIN_SHUTOFF: "shutoff",
                libvirt.VIR_DOMAIN_CRASHED: "crashed",
            }
            state = state_map.get(info[0], "unknown")

            # Memory
            memory_total_mb = info[1] // 1024
            memory_used_mb = info[2] // 1024 if info[2] > 0 else memory_total_mb

            # CPU percentage (requires two samples)
            cpu_time = info[4]
            now = time.time()
            cpu_percent = 0.0

            if vm_name in self._prev_cpu:
                prev_time, prev_cpu = self._prev_cpu[vm_name]
                time_delta = now - prev_time
                if time_delta > 0:
                    cpu_delta = cpu_time - prev_cpu
                    # CPU time is in nanoseconds
                    cpu_percent = (cpu_delta / (time_delta * 1e9)) * 100
                    cpu_percent = min(cpu_percent, 100.0 * info[3])  # Cap at vcpus * 100%

            self._prev_cpu[vm_name] = (now, cpu_time)

            # Disk stats (from block devices)
            disk_used_gb = 0.0
            disk_total_gb = 0.0
            try:
                xml = dom.XMLDesc()
                import xml.etree.ElementTree as ET

                root = ET.fromstring(xml)
                for disk in root.findall(".//disk[@type='file']"):
                    source = disk.find(".//source")
                    if source is not None and source.get("file"):
                        disk_path = Path(source.get("file"))
                        if disk_path.exists():
                            size_bytes = disk_path.stat().st_size
                            disk_total_gb += size_bytes / (1024**3)
                            # Actual usage requires qemu-img info
                            disk_used_gb += size_bytes / (1024**3)
            except Exception:
                pass

            # Network stats
            network_rx = 0
            network_tx = 0
            try:
                for iface in dom.interfaceAddresses(
                    libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT
                ).keys():
                    stats = dom.interfaceStats(iface)
                    network_rx += stats[0]
                    network_tx += stats[4]
            except Exception:
                pass

            return VMStats(
                name=vm_name,
                state=state,
                cpu_percent=cpu_percent,
                memory_used_mb=memory_used_mb,
                memory_total_mb=memory_total_mb,
                disk_used_gb=disk_used_gb,
                disk_total_gb=disk_total_gb,
                network_rx_bytes=network_rx,
                network_tx_bytes=network_tx,
                uptime_seconds=0,  # Would need guest agent for accurate uptime
            )

        except Exception:
            return None

    def get_all_vm_stats(self) -> List[VMStats]:
        """Get stats for all VMs."""
        stats = []
        try:
            for dom in self.conn.listAllDomains():
                vm_stats = self.get_vm_stats(dom.name())
                if vm_stats:
                    stats.append(vm_stats)
        except Exception:
            pass
        return stats

    def get_container_stats(self, engine: str = "auto") -> List[ContainerStats]:
        """Get resource statistics for containers."""
        if engine == "auto":
            engine = "podman" if self._check_engine("podman") else "docker"

        try:
            result = subprocess.run(
                [engine, "stats", "--no-stream", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []

            containers = json.loads(result.stdout) if result.stdout.strip() else []
            stats = []

            for c in containers:
                # Parse CPU percentage
                cpu_str = c.get("CPUPerc", "0%").replace("%", "")
                try:
                    cpu_percent = float(cpu_str)
                except ValueError:
                    cpu_percent = 0.0

                # Parse memory
                mem_usage = c.get("MemUsage", "0MiB / 0MiB")
                mem_parts = mem_usage.split("/")
                mem_used = self._parse_memory(mem_parts[0].strip()) if len(mem_parts) > 0 else 0
                mem_limit = self._parse_memory(mem_parts[1].strip()) if len(mem_parts) > 1 else 0

                # Parse network
                net_io = c.get("NetIO", "0B / 0B")
                net_parts = net_io.split("/")
                net_rx = self._parse_bytes(net_parts[0].strip()) if len(net_parts) > 0 else 0
                net_tx = self._parse_bytes(net_parts[1].strip()) if len(net_parts) > 1 else 0

                stats.append(
                    ContainerStats(
                        name=c.get("Name", c.get("Names", "unknown")),
                        state="running",
                        cpu_percent=cpu_percent,
                        memory_used_mb=mem_used,
                        memory_limit_mb=mem_limit,
                        network_rx_bytes=net_rx,
                        network_tx_bytes=net_tx,
                        pids=int(c.get("PIDs", 0)),
                    )
                )

            return stats

        except Exception:
            return []

    def _check_engine(self, engine: str) -> bool:
        """Check if container engine is available."""
        try:
            result = subprocess.run([engine, "--version"], capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def _parse_memory(self, mem_str: str) -> int:
        """Parse memory string like '100MiB' to MB."""
        mem_str = mem_str.upper()
        try:
            if "GIB" in mem_str or "GB" in mem_str:
                return int(float(mem_str.replace("GIB", "").replace("GB", "").strip()) * 1024)
            elif "MIB" in mem_str or "MB" in mem_str:
                return int(float(mem_str.replace("MIB", "").replace("MB", "").strip()))
            elif "KIB" in mem_str or "KB" in mem_str:
                return int(float(mem_str.replace("KIB", "").replace("KB", "").strip()) / 1024)
            else:
                return int(float(mem_str.replace("B", "").strip()) / (1024 * 1024))
        except ValueError:
            return 0

    def _parse_bytes(self, bytes_str: str) -> int:
        """Parse byte string like '1.5GB' to bytes."""
        bytes_str = bytes_str.upper()
        try:
            if "GB" in bytes_str:
                return int(float(bytes_str.replace("GB", "").strip()) * 1024**3)
            elif "MB" in bytes_str:
                return int(float(bytes_str.replace("MB", "").strip()) * 1024**2)
            elif "KB" in bytes_str:
                return int(float(bytes_str.replace("KB", "").strip()) * 1024)
            else:
                return int(float(bytes_str.replace("B", "").strip()))
        except ValueError:
            return 0

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def format_bytes(num_bytes: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f}PB"
