"""Interfaces for CloneBox disk management."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional


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
