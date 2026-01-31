# Dependency Injection Refactor

**Status:** 📝 Planned  
**Priority:** Medium  
**Estimated Effort:** 2 weeks  
**Dependencies:** None

## Problem Statement

Current codebase has hardcoded dependencies making testing difficult:

```python
# Current: hardcoded dependencies
class SelectiveVMCloner:
    def __init__(self, conn_uri=None, user_session=False):
        # Hardcoded libvirt import and connection
        import libvirt
        self.conn = libvirt.open(conn_uri)  # Can't mock easily
        
    def create_vm(self, config):
        # Hardcoded subprocess calls
        subprocess.run(["qemu-img", "create", ...])  # Can't mock
```

**Issues:**
1. Can't test without real libvirt
2. Can't replace implementations
3. Hard to add new backends (Podman, cloud providers)
4. Monolithic structure

## Proposed Solution

Dependency injection with interface abstractions:

```python
# New: injected dependencies
class SelectiveVMCloner:
    def __init__(
        self,
        hypervisor: HypervisorBackend,
        disk_manager: DiskManager,
        network_manager: NetworkManager,
        secrets_manager: SecretsManager,
    ):
        self.hypervisor = hypervisor
        self.disk = disk_manager
        self.network = network_manager
        self.secrets = secrets_manager
```

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Application Layer                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │     CLI     │  │   Dashboard │  │     API     │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│         └────────────────┼────────────────┘                      │
│                          │                                       │
│              ┌───────────▼───────────┐                          │
│              │   DependencyContainer  │                          │
│              └───────────┬───────────┘                          │
├──────────────────────────┼───────────────────────────────────────┤
│                   Service Layer                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  VMCloner   │  │ SnapshotMgr │  │  HealthMgr  │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
├─────────┼────────────────┼────────────────┼──────────────────────┤
│                  Infrastructure Layer                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ Hypervisor  │  │    Disk     │  │   Network   │              │
│  │  Backend    │  │   Manager   │  │   Manager   │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐              │
│  │   libvirt   │  │   qemu-img  │  │   iptables  │              │
│  │   podman    │  │     lvm     │  │   libvirt   │              │
│  │    aws      │  │    cloud    │  │    cloud    │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

### Interface Definitions

```python
# src/clonebox/interfaces/hypervisor.py
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

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
    def define_vm(self, config: 'VMConfig') -> str:
        """Define a new VM. Returns VM name."""
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


# src/clonebox/interfaces/disk.py
class DiskManager(ABC):
    """Abstract interface for disk operations."""
    
    @abstractmethod
    def create_disk(
        self,
        path: Path,
        size_gb: int,
        format: str = "qcow2",
        backing_file: Optional[Path] = None,
    ) -> Path:
        """Create a disk image."""
        pass
    
    @abstractmethod
    def resize_disk(self, path: Path, new_size_gb: int) -> None:
        """Resize a disk image."""
        pass
    
    @abstractmethod
    def get_disk_info(self, path: Path) -> Dict[str, Any]:
        """Get disk image information."""
        pass
    
    @abstractmethod
    def create_snapshot(self, path: Path, snapshot_name: str) -> Path:
        """Create disk snapshot."""
        pass
    
    @abstractmethod
    def delete_disk(self, path: Path) -> None:
        """Delete disk image."""
        pass


# src/clonebox/interfaces/network.py
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


# src/clonebox/interfaces/process.py
class ProcessRunner(ABC):
    """Abstract interface for process execution."""
    
    @abstractmethod
    def run(
        self,
        command: List[str],
        capture_output: bool = True,
        timeout: Optional[int] = None,
        check: bool = True,
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> 'ProcessResult':
        """Run a command."""
        pass
    
    @abstractmethod
    def run_shell(
        self,
        command: str,
        capture_output: bool = True,
        timeout: Optional[int] = None,
    ) -> 'ProcessResult':
        """Run a shell command."""
        pass

@dataclass
class ProcessResult:
    """Result of process execution."""
    returncode: int
    stdout: str
    stderr: str
    
    @property
    def success(self) -> bool:
        return self.returncode == 0
```

### Implementation: libvirt Backend

```python
# src/clonebox/backends/libvirt_backend.py
import libvirt
from typing import List, Optional, Dict, Any
import xml.etree.ElementTree as ET

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
        if self._conn is not None:
            return
        
        try:
            self._conn = libvirt.open(self.uri)
        except libvirt.libvirtError as e:
            raise ConnectionError(f"Failed to connect to libvirt: {e}")
    
    def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
    
    @property
    def conn(self) -> libvirt.virConnect:
        if self._conn is None:
            self.connect()
        return self._conn
    
    def define_vm(self, config: 'VMConfig') -> str:
        xml = self._generate_xml(config)
        domain = self.conn.defineXML(xml)
        return domain.name()
    
    def undefine_vm(self, name: str) -> None:
        try:
            domain = self.conn.lookupByName(name)
            domain.undefine()
        except libvirt.libvirtError as e:
            if "not found" not in str(e).lower():
                raise
    
    def start_vm(self, name: str) -> None:
        domain = self.conn.lookupByName(name)
        if not domain.isActive():
            domain.create()
    
    def stop_vm(self, name: str, force: bool = False) -> None:
        domain = self.conn.lookupByName(name)
        if domain.isActive():
            if force:
                domain.destroy()
            else:
                domain.shutdown()
    
    def get_vm_info(self, name: str) -> Optional[VMInfo]:
        try:
            domain = self.conn.lookupByName(name)
        except libvirt.libvirtError:
            return None
        
        info = domain.info()
        state_map = {
            libvirt.VIR_DOMAIN_RUNNING: "running",
            libvirt.VIR_DOMAIN_PAUSED: "paused",
            libvirt.VIR_DOMAIN_SHUTDOWN: "shutdown",
            libvirt.VIR_DOMAIN_SHUTOFF: "shutoff",
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
        vms = []
        for domain in self.conn.listAllDomains():
            info = self.get_vm_info(domain.name())
            if info:
                vms.append(info)
        return vms
    
    def vm_exists(self, name: str) -> bool:
        try:
            self.conn.lookupByName(name)
            return True
        except libvirt.libvirtError:
            return False
    
    def is_running(self, name: str) -> bool:
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
        """Execute via QEMU Guest Agent."""
        import json
        import base64
        
        domain = self.conn.lookupByName(name)
        
        # Build QGA command
        qga_cmd = {
            "execute": "guest-exec",
            "arguments": {
                "path": "/bin/bash",
                "arg": ["-c", command],
                "capture-output": True,
            }
        }
        
        try:
            result = domain.qemuAgentCommand(json.dumps(qga_cmd), timeout)
            result_data = json.loads(result)
            pid = result_data["return"]["pid"]
            
            # Wait for completion
            status_cmd = {
                "execute": "guest-exec-status",
                "arguments": {"pid": pid}
            }
            
            import time
            start = time.time()
            while time.time() - start < timeout:
                status = domain.qemuAgentCommand(json.dumps(status_cmd), timeout)
                status_data = json.loads(status)
                
                if status_data["return"]["exited"]:
                    if "out-data" in status_data["return"]:
                        return base64.b64decode(
                            status_data["return"]["out-data"]
                        ).decode()
                    return ""
                
                time.sleep(0.5)
            
            return None
            
        except Exception:
            return None
    
    def _get_ip_addresses(self, domain) -> List[str]:
        """Get IP addresses from domain."""
        ips = []
        try:
            ifaces = domain.interfaceAddresses(
                libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT
            )
            for iface_data in ifaces.values():
                for addr in iface_data.get("addrs", []):
                    if addr["type"] == 0:  # IPv4
                        ips.append(addr["addr"])
        except Exception:
            pass
        return ips
    
    def _generate_xml(self, config: 'VMConfig') -> str:
        """Generate libvirt domain XML."""
        # ... (existing XML generation logic)
        pass
```

### Dependency Container

```python
# src/clonebox/container.py
from typing import Dict, Type, Any, Optional, Callable, TypeVar
from dataclasses import dataclass, field
import threading

T = TypeVar('T')

@dataclass
class ServiceRegistration:
    """Registration info for a service."""
    factory: Callable[..., Any]
    singleton: bool = True
    instance: Optional[Any] = None

class DependencyContainer:
    """
    IoC container for dependency injection.
    
    Usage:
        container = DependencyContainer()
        
        # Register services
        container.register(HypervisorBackend, LibvirtBackend, singleton=True)
        container.register(DiskManager, QemuDiskManager)
        
        # Resolve dependencies
        cloner = container.resolve(SelectiveVMCloner)
    """
    
    def __init__(self):
        self._registrations: Dict[Type, ServiceRegistration] = {}
        self._lock = threading.Lock()
    
    def register(
        self,
        interface: Type[T],
        implementation: Type[T] = None,
        factory: Callable[..., T] = None,
        singleton: bool = True,
        instance: T = None,
    ) -> 'DependencyContainer':
        """
        Register a service.
        
        Args:
            interface: The interface/base class
            implementation: Concrete implementation class
            factory: Factory function to create instance
            singleton: If True, reuse same instance
            instance: Pre-created instance to use
        """
        if instance is not None:
            self._registrations[interface] = ServiceRegistration(
                factory=lambda: instance,
                singleton=True,
                instance=instance,
            )
        elif factory is not None:
            self._registrations[interface] = ServiceRegistration(
                factory=factory,
                singleton=singleton,
            )
        elif implementation is not None:
            self._registrations[interface] = ServiceRegistration(
                factory=implementation,
                singleton=singleton,
            )
        else:
            raise ValueError("Must provide implementation, factory, or instance")
        
        return self  # Enable chaining
    
    def resolve(self, interface: Type[T]) -> T:
        """Resolve a service instance."""
        with self._lock:
            if interface not in self._registrations:
                raise KeyError(f"No registration for {interface}")
            
            reg = self._registrations[interface]
            
            # Return existing instance for singletons
            if reg.singleton and reg.instance is not None:
                return reg.instance
            
            # Create new instance
            instance = self._create_instance(reg.factory)
            
            # Store for singleton
            if reg.singleton:
                reg.instance = instance
            
            return instance
    
    def _create_instance(self, factory: Callable) -> Any:
        """Create instance, resolving constructor dependencies."""
        import inspect
        
        sig = inspect.signature(factory)
        kwargs = {}
        
        for name, param in sig.parameters.items():
            if param.annotation != inspect.Parameter.empty:
                # Try to resolve dependency
                try:
                    kwargs[name] = self.resolve(param.annotation)
                except KeyError:
                    if param.default == inspect.Parameter.empty:
                        raise
                    # Use default if available
        
        return factory(**kwargs)
    
    def has(self, interface: Type) -> bool:
        """Check if service is registered."""
        return interface in self._registrations
    
    def reset(self) -> None:
        """Reset all singleton instances."""
        with self._lock:
            for reg in self._registrations.values():
                reg.instance = None


# Global container instance
_container: Optional[DependencyContainer] = None

def get_container() -> DependencyContainer:
    """Get the global container instance."""
    global _container
    if _container is None:
        _container = create_default_container()
    return _container

def set_container(container: DependencyContainer) -> None:
    """Set the global container (useful for testing)."""
    global _container
    _container = container

def create_default_container() -> DependencyContainer:
    """Create container with default registrations."""
    from .backends.libvirt_backend import LibvirtBackend
    from .backends.qemu_disk import QemuDiskManager
    from .backends.subprocess_runner import SubprocessRunner
    from .secrets.manager import SecretsManager
    
    container = DependencyContainer()
    
    container.register(HypervisorBackend, LibvirtBackend)
    container.register(DiskManager, QemuDiskManager)
    container.register(ProcessRunner, SubprocessRunner)
    container.register(SecretsManager, SecretsManager)
    
    return container
```

### Updated Cloner with DI

```python
# src/clonebox/cloner.py (refactored)
from .interfaces import HypervisorBackend, DiskManager, NetworkManager
from .container import get_container

class SelectiveVMCloner:
    """VM cloner with dependency injection."""
    
    def __init__(
        self,
        hypervisor: HypervisorBackend = None,
        disk_manager: DiskManager = None,
        network_manager: NetworkManager = None,
        secrets_manager: 'SecretsManager' = None,
    ):
        # Resolve from container if not provided
        container = get_container()
        
        self.hypervisor = hypervisor or container.resolve(HypervisorBackend)
        self.disk = disk_manager or container.resolve(DiskManager)
        self.network = network_manager or container.resolve(NetworkManager)
        self.secrets = secrets_manager or container.resolve(SecretsManager)
        
        # Connect hypervisor
        self.hypervisor.connect()
    
    def create_vm(self, config: VMConfig, replace: bool = False) -> str:
        """Create VM using injected dependencies."""
        
        if replace and self.hypervisor.vm_exists(config.name):
            self.delete_vm(config.name)
        
        # Create disk
        vm_dir = self._get_vm_dir(config.name)
        vm_dir.mkdir(parents=True, exist_ok=True)
        
        root_disk = self.disk.create_disk(
            path=vm_dir / "root.qcow2",
            size_gb=config.disk_size_gb,
            backing_file=config.base_image,
        )
        
        # Define and optionally start VM
        vm_name = self.hypervisor.define_vm(config)
        
        return vm_name
    
    def start_vm(self, name: str) -> bool:
        """Start VM."""
        self.hypervisor.start_vm(name)
        return True
    
    def stop_vm(self, name: str, force: bool = False) -> bool:
        """Stop VM."""
        self.hypervisor.stop_vm(name, force)
        return True
    
    def delete_vm(self, name: str) -> bool:
        """Delete VM and its storage."""
        if self.hypervisor.is_running(name):
            self.hypervisor.stop_vm(name, force=True)
        
        self.hypervisor.undefine_vm(name)
        
        # Delete storage
        vm_dir = self._get_vm_dir(name)
        if vm_dir.exists():
            shutil.rmtree(vm_dir)
        
        return True
    
    def list_vms(self) -> list:
        """List all VMs."""
        return self.hypervisor.list_vms()
```

### Testing with DI

```python
# tests/conftest.py
import pytest
from clonebox.container import DependencyContainer, set_container
from clonebox.interfaces import HypervisorBackend, DiskManager

class MockHypervisor(HypervisorBackend):
    """Mock hypervisor for testing."""
    
    name = "mock"
    
    def __init__(self):
        self.vms = {}
        self.calls = []
    
    def connect(self): 
        self.calls.append(('connect',))
    
    def disconnect(self): 
        self.calls.append(('disconnect',))
    
    def define_vm(self, config):
        self.calls.append(('define_vm', config))
        self.vms[config.name] = {'state': 'shutoff', 'config': config}
        return config.name
    
    # ... other mock implementations

@pytest.fixture
def mock_container():
    """Provide container with mocked dependencies."""
    container = DependencyContainer()
    
    mock_hypervisor = MockHypervisor()
    mock_disk = MockDiskManager()
    
    container.register(HypervisorBackend, instance=mock_hypervisor)
    container.register(DiskManager, instance=mock_disk)
    
    set_container(container)
    
    yield container, mock_hypervisor, mock_disk
    
    # Reset global container
    set_container(None)

def test_create_vm(mock_container):
    """Test VM creation with mocked dependencies."""
    container, mock_hypervisor, mock_disk = mock_container
    
    cloner = SelectiveVMCloner()
    config = VMConfig(name="test-vm", disk_size_gb=20)
    
    vm_name = cloner.create_vm(config)
    
    assert vm_name == "test-vm"
    assert "test-vm" in mock_hypervisor.vms
    assert ('define_vm', config) in mock_hypervisor.calls
```

## Migration Guide

### Before (Hardcoded)

```python
from clonebox import SelectiveVMCloner

cloner = SelectiveVMCloner(user_session=True)
cloner.create_vm(config)
```

### After (With DI)

```python
# Option 1: Use defaults (backward compatible)
from clonebox import SelectiveVMCloner

cloner = SelectiveVMCloner()  # Uses default container
cloner.create_vm(config)

# Option 2: Explicit injection
from clonebox import SelectiveVMCloner
from clonebox.backends import LibvirtBackend, QemuDiskManager

cloner = SelectiveVMCloner(
    hypervisor=LibvirtBackend(user_session=True),
    disk_manager=QemuDiskManager(),
)

# Option 3: Custom container
from clonebox.container import DependencyContainer, set_container

container = DependencyContainer()
container.register(HypervisorBackend, PodmanBackend)
set_container(container)

cloner = SelectiveVMCloner()  # Uses Podman backend
```

## Implementation Timeline

| Week | Tasks |
|------|-------|
| 1 | Interface definitions, DI container, libvirt backend |
| 2 | Disk/Network managers, update cloner, tests |
