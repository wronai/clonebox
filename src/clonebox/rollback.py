"""
Transactional rollback support for CloneBox operations.
"""

import logging
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

log = logging.getLogger(__name__)


@dataclass
class RollbackAction:
    """A single rollback action."""

    description: str
    action: Callable[[], None]
    critical: bool = True  # If True, failure stops rollback chain


@dataclass
class RollbackContext:
    """
    Context manager for transactional operations with automatic rollback.

    Usage:
        with RollbackContext("create VM") as ctx:
            ctx.add_file(disk_path)  # Will be deleted on error
            ctx.add_directory(vm_dir)  # Will be deleted on error
            ctx.add_action("stop VM", lambda: cloner.stop_vm(name))

            # If any exception occurs, all registered items are cleaned up
            do_risky_operation()
    """

    operation_name: str
    _files: List[Path] = field(default_factory=list)
    _directories: List[Path] = field(default_factory=list)
    _actions: List[RollbackAction] = field(default_factory=list)
    _committed: bool = False
    _console: Optional[Any] = None

    def add_file(self, path: Path, description: Optional[str] = None) -> Path:
        """Register a file for cleanup on rollback."""
        self._files.append(path)
        log.debug(f"Registered file for rollback: {path}")
        return path

    def add_directory(self, path: Path, description: Optional[str] = None) -> Path:
        """Register a directory for cleanup on rollback."""
        self._directories.append(path)
        log.debug(f"Registered directory for rollback: {path}")
        return path

    def add_action(
        self, description: str, action: Callable[[], None], critical: bool = False
    ) -> None:
        """Register a custom rollback action."""
        self._actions.append(
            RollbackAction(description=description, action=action, critical=critical)
        )
        log.debug(f"Registered action for rollback: {description}")

    def add_libvirt_domain(self, conn, domain_name: str) -> None:
        """Register a libvirt domain for cleanup."""

        def cleanup_domain():
            try:
                dom = conn.lookupByName(domain_name)
                if dom.isActive():
                    dom.destroy()
                dom.undefine()
            except Exception as e:
                log.warning(f"Failed to cleanup domain {domain_name}: {e}")

        self._actions.append(
            RollbackAction(
                description=f"undefine domain {domain_name}",
                action=cleanup_domain,
                critical=False,
            )
        )

    def commit(self) -> None:
        """Mark operation as successful, preventing rollback."""
        self._committed = True
        log.info(f"Operation '{self.operation_name}' committed successfully")

    def rollback(self) -> List[str]:
        """Execute rollback actions. Returns list of errors."""
        errors = []

        if self._console:
            self._console.print(
                f"[yellow]Rolling back '{self.operation_name}'...[/yellow]"
            )

        # Execute custom actions first (in reverse order)
        for action in reversed(self._actions):
            try:
                log.info(f"Rollback action: {action.description}")
                action.action()
            except Exception as e:
                error_msg = f"Rollback action '{action.description}' failed: {e}"
                errors.append(error_msg)
                log.error(error_msg)
                if action.critical:
                    break

        # Delete files
        for path in reversed(self._files):
            try:
                if path.exists():
                    path.unlink()
                    log.info(f"Deleted file: {path}")
            except Exception as e:
                errors.append(f"Failed to delete {path}: {e}")

        # Delete directories
        for path in reversed(self._directories):
            try:
                if path.exists():
                    shutil.rmtree(path)
                    log.info(f"Deleted directory: {path}")
            except Exception as e:
                errors.append(f"Failed to delete {path}: {e}")

        return errors

    def __enter__(self) -> "RollbackContext":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None and not self._committed:
            errors = self.rollback()
            if errors and self._console:
                self._console.print("[red]Rollback completed with errors:[/red]")
                for error in errors:
                    self._console.print(f"  [dim]- {error}[/dim]")
        return False  # Don't suppress the exception


@contextmanager
def vm_creation_transaction(cloner: Any, config: Any, console: Optional[Any] = None):
    """
    Context manager for VM creation with automatic rollback.

    Usage:
        with vm_creation_transaction(cloner, config, console) as ctx:
            vm_dir = ctx.add_directory(images_dir / config.name)
            vm_dir.mkdir(parents=True, exist_ok=True)

            disk_path = ctx.add_file(vm_dir / "root.qcow2")
            create_disk(disk_path)

            ctx.add_libvirt_domain(cloner.conn, config.name)
            cloner.conn.defineXML(xml)

            ctx.commit()  # Success!
    """
    ctx = RollbackContext(
        operation_name=f"create VM '{config.name}'", _console=console
    )
    try:
        yield ctx
    except Exception:
        if not ctx._committed:
            ctx.rollback()
        raise
