"""IoC container for dependency injection in CloneBox."""

import inspect
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Type, TypeVar

T = TypeVar("T")


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
        self._lock = threading.RLock()

    def register(
        self,
        interface: Type[T],
        implementation: Type[T] = None,
        factory: Callable[..., T] = None,
        singleton: bool = True,
        instance: T = None,
    ) -> "DependencyContainer":
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
                # If it's a class and not an interface, try to auto-resolve it
                if inspect.isclass(interface):
                    return self._create_instance(interface)
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
        try:
            sig = inspect.signature(factory)
        except ValueError:
            # Handle cases where signature can't be inspected (e.g., some built-ins)
            return factory()

        kwargs = {}

        for name, param in sig.parameters.items():
            if param.annotation != inspect.Parameter.empty:
                # Try to resolve dependency
                try:
                    kwargs[name] = self.resolve(param.annotation)
                except (KeyError, TypeError):
                    if param.default == inspect.Parameter.empty:
                        raise
                    # Use default if available
            elif param.default != inspect.Parameter.empty:
                # Use default if no annotation but default exists
                pass
            else:
                # Can't resolve this parameter
                pass

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
    from .interfaces.disk import DiskManager
    from .interfaces.hypervisor import HypervisorBackend
    from .interfaces.process import ProcessRunner
    from .secrets import SecretsManager

    container = DependencyContainer()

    container.register(HypervisorBackend, LibvirtBackend)
    container.register(DiskManager, QemuDiskManager)
    container.register(ProcessRunner, SubprocessRunner)
    container.register(SecretsManager, SecretsManager)

    return container
