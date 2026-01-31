"""QEMU disk manager implementation."""

import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from ..interfaces.disk import DiskManager


class QemuDiskManager(DiskManager):
    """Manage VM disks using qemu-img."""

    def create_disk(
        self,
        path: Path,
        size_gb: int,
        format: str = "qcow2",
        backing_file: Optional[Path] = None,
    ) -> Path:
        """Create a disk image."""
        cmd = ["qemu-img", "create", "-f", format]
        
        if backing_file:
            cmd.extend(["-b", str(backing_file), "-F", format])
            
        cmd.extend([str(path), f"{size_gb}G"])
        
        subprocess.run(cmd, check=True, capture_output=True)
        return path

    def resize_disk(self, path: Path, new_size_gb: int) -> None:
        """Resize a disk image."""
        cmd = ["qemu-img", "resize", str(path), f"{new_size_gb}G"]
        subprocess.run(cmd, check=True, capture_output=True)

    def get_disk_info(self, path: Path) -> Dict[str, Any]:
        """Get disk image information."""
        import json
        cmd = ["qemu-img", "info", "--output=json", str(path)]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def create_snapshot(self, path: Path, snapshot_name: str) -> Path:
        """Create internal disk snapshot."""
        cmd = ["qemu-img", "snapshot", "-c", snapshot_name, str(path)]
        subprocess.run(cmd, check=True, capture_output=True)
        return path

    def delete_disk(self, path: Path) -> None:
        """Delete disk image."""
        if path.exists():
            path.unlink()
