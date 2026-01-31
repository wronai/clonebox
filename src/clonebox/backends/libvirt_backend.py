"""libvirt hypervisor backend implementation."""

import base64
import json
import time
from typing import Any, Dict, List, Optional

try:
    import libvirt
except ImportError:
    libvirt = None

from ..interfaces.hypervisor import HypervisorBackend, VMInfo


class LibvirtBackend(HypervisorBackend):
    """libvirt hypervisor backend."""

    name = "libvirt"

    def __init__(
        self,
        uri: Optional[str] = None,
        user_session: bool = False,
    ):
        self.uri = uri or ("qemu:///session" if user_session else "qemu:///system")
        self._conn: Optional[libvirt.virConnect] = None

    def connect(self) -> None:
        """Establish connection to libvirt."""
        if self._conn is not None:
            try:
                if self._conn.isAlive():
                    return
            except libvirt.libvirtError:
                pass

        try:
            self._conn = libvirt.open(self.uri)
        except libvirt.libvirtError as e:
            raise ConnectionError(f"Failed to connect to libvirt at {self.uri}: {e}")

    def disconnect(self) -> None:
        """Close connection."""
        if self._conn:
            try:
                self._conn.close()
            except libvirt.libvirtError:
                pass
            self._conn = None

    @property
    def conn(self) -> libvirt.virConnect:
        """Get active libvirt connection."""
        if self._conn is None:
            self.connect()
        return self._conn

    def define_vm(self, config: Any) -> str:
        """Define a new VM. Returns VM name."""
        # This normally takes XML, but for DI we might want to pass config
        # and let the backend handle XML generation if it's backend-specific.
        # For now, we assume the caller provides the XML via config.xml or similar
        # if they want to use this generic interface, or we refactor cloner to use backend.
        if hasattr(config, "xml"):
            domain = self.conn.defineXML(config.xml)
            return domain.name()
        raise ValueError("Config must provide XML for libvirt backend")

    def undefine_vm(self, name: str) -> None:
        """Remove VM definition."""
        try:
            domain = self.conn.lookupByName(name)
            if domain.isActive():
                domain.destroy()
            domain.undefine()
        except libvirt.libvirtError as e:
            if "not found" not in str(e).lower():
                raise

    def start_vm(self, name: str) -> None:
        """Start a VM."""
        domain = self.conn.lookupByName(name)
        if not domain.isActive():
            domain.create()

    def stop_vm(self, name: str, force: bool = False) -> None:
        """Stop a VM."""
        domain = self.conn.lookupByName(name)
        if domain.isActive():
            if force:
                domain.destroy()
            else:
                domain.shutdown()

    def get_vm_info(self, name: str) -> Optional[VMInfo]:
        """Get VM information."""
        try:
            domain = self.conn.lookupByName(name)
        except libvirt.libvirtError:
            return None

        info = domain.info()
        state_map = {
            libvirt.VIR_DOMAIN_RUNNING: "running",
            libvirt.VIR_DOMAIN_BLOCKED: "blocked",
            libvirt.VIR_DOMAIN_PAUSED: "paused",
            libvirt.VIR_DOMAIN_SHUTDOWN: "shutdown",
            libvirt.VIR_DOMAIN_SHUTOFF: "shutoff",
            libvirt.VIR_DOMAIN_CRASHED: "crashed",
            libvirt.VIR_DOMAIN_PMSUSPENDED: "pmsuspended",
        }

        return VMInfo(
            name=domain.name(),
            state=state_map.get(info[0], "unknown"),
            uuid=domain.UUIDString(),
            memory_mb=info[1] // 1024,
            vcpus=info[3],
            ip_addresses=self._get_ip_addresses(domain),
        )

    def list_vms(self) -> List[VMInfo]:
        """List all VMs."""
        vms = []
        try:
            # List all domains (running and defined)
            for domain in self.conn.listAllDomains():
                info = self.get_vm_info(domain.name())
                if info:
                    vms.append(info)
        except libvirt.libvirtError:
            pass
        return vms

    def vm_exists(self, name: str) -> bool:
        """Check if VM exists."""
        try:
            self.conn.lookupByName(name)
            return True
        except libvirt.libvirtError:
            return False

    def is_running(self, name: str) -> bool:
        """Check if VM is running."""
        try:
            domain = self.conn.lookupByName(name)
            return domain.isActive() == 1
        except libvirt.libvirtError:
            return False

    def execute_command(
        self,
        name: str,
        command: str,
        timeout: int = 30,
    ) -> Optional[str]:
        """Execute command in VM via QEMU Guest Agent."""
        domain = self.conn.lookupByName(name)

        # Build QGA guest-exec command
        qga_cmd = {
            "execute": "guest-exec",
            "arguments": {
                "path": "/bin/bash",
                "arg": ["-c", command],
                "capture-output": True,
            },
        }

        try:
            result_json = domain.qemuAgentCommand(json.dumps(qga_cmd), timeout)
            result_data = json.loads(result_json)
            pid = result_data["return"]["pid"]

            # Poll for completion
            status_cmd = {"execute": "guest-exec-status", "arguments": {"pid": pid}}
            start_time = time.time()
            while time.time() - start_time < timeout:
                status_json = domain.qemuAgentCommand(json.dumps(status_cmd), timeout)
                status_data = json.loads(status_json)

                if status_data["return"]["exited"]:
                    if "out-data" in status_data["return"]:
                        return base64.b64decode(status_data["return"]["out-data"]).decode(
                            "utf-8", errors="replace"
                        )
                    return ""

                time.sleep(0.5)

            return None  # Timeout

        except Exception:
            return None

    def _get_ip_addresses(self, domain) -> List[str]:
        """Get IP addresses from domain via guest agent or lease."""
        ips = []
        try:
            # Try guest agent first (more accurate)
            ifaces = domain.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT)
            for iface_data in ifaces.values():
                for addr in iface_data.get("addrs", []):
                    if addr["type"] == 0:  # IPv4
                        ips.append(addr["addr"])
        except libvirt.libvirtError:
            # Fallback to network leases
            try:
                ifaces = domain.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                for iface_data in ifaces.values():
                    for addr in iface_data.get("addrs", []):
                        if addr["type"] == 0:
                            ips.append(addr["addr"])
            except libvirt.libvirtError:
                pass
        return ips
