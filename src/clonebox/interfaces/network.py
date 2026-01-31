"""Interfaces for CloneBox network management."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class NetworkManager(ABC):
    """Abstract interface for network operations."""

    @abstractmethod
    def create_network(self, name: str, config: Dict[str, Any]) -> None:
        """Create a virtual network."""
        pass

    @abstractmethod
    def delete_network(self, name: str) -> None:
        """Delete a virtual network."""
        pass

    @abstractmethod
    def network_exists(self, name: str) -> bool:
        """Check if network exists."""
        pass

    @abstractmethod
    def is_network_active(self, name: str) -> bool:
        """Check if network is active."""
        pass

    @abstractmethod
    def get_vm_ip(self, vm_name: str) -> Optional[str]:
        """Get VM's IP address."""
        pass
