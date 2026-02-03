"""Libvirt network manager implementation."""

from clonebox.interfaces.network import NetworkManager


class LibvirtNetworkManager(NetworkManager):
    """Default network manager using libvirt."""
    
    def create_network(self, name: str, config: dict) -> str:
        """Create a new network."""
        # For now, just return the name
        # In a full implementation, this would use libvirt to create the network
        return name
    
    def delete_network(self, name: str) -> bool:
        """Delete a network."""
        # For now, just return True
        # In a full implementation, this would use libvirt to delete the network
        return True
    
    def get_vm_ip(self, vm_name: str) -> str:
        """Get IP address of a VM."""
        # For now, return a default IP
        # In a full implementation, this would query libvirt for the VM's IP
        return "192.168.122.100"
    
    def is_network_active(self, name: str) -> bool:
        """Check if a network is active."""
        # For now, just return True for the default network
        return name == "default"
    
    def network_exists(self, name: str) -> bool:
        """Check if a network exists."""
        # For now, just return True for the default network
        return name == "default"
