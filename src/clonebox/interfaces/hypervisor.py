"""Interfaces for CloneBox hypervisor backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class VMInfo:
    """VM information returned by hypervisor."""

    name: str
    state: str
    uuid: str
    memory_mb: int
    vcpus: int
    ip_addresses: List[str]
    created_at: Optional[str] = None
    metadata: Dict[str, Any] = None


class HypervisorBackend(ABC):
    """Abstract interface for hypervisor operations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name (e.g., 'libvirt', 'podman')."""
        pass

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to hypervisor."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection."""
        pass

    @abstractmethod
    def define_vm(self, config: Any) -> str:
        """Define a new VM. Returns VM UUID or name."""
        pass

    @abstractmethod
    def undefine_vm(self, name: str) -> None:
        """Remove VM definition."""
        pass

    @abstractmethod
    def start_vm(self, name: str) -> None:
        """Start a VM."""
        pass

    @abstractmethod
    def stop_vm(self, name: str, force: bool = False) -> None:
        """Stop a VM."""
        pass

    @abstractmethod
    def get_vm_info(self, name: str) -> Optional[VMInfo]:
        """Get VM information."""
        pass

    @abstractmethod
    def list_vms(self) -> List[VMInfo]:
        """List all VMs."""
        pass

    @abstractmethod
    def vm_exists(self, name: str) -> bool:
        """Check if VM exists."""
        pass

    @abstractmethod
    def is_running(self, name: str) -> bool:
        """Check if VM is running."""
        pass

    @abstractmethod
    def execute_command(
        self,
        name: str,
        command: str,
        timeout: int = 30,
    ) -> Optional[str]:
        """Execute command in VM."""
        pass
