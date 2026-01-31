#!/usr/bin/env python3
"""Data models for snapshot management."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class SnapshotType(Enum):
    """Type of snapshot."""

    DISK_ONLY = "disk"  # Only disk state (offline)
    FULL = "full"  # Disk + memory + device state (online)
    EXTERNAL = "external"  # External snapshot file


class SnapshotState(Enum):
    """State of snapshot operation."""

    CREATING = "creating"
    READY = "ready"
    REVERTING = "reverting"
    DELETING = "deleting"
    FAILED = "failed"


@dataclass
class Snapshot:
    """Represents a VM snapshot."""

    name: str
    vm_name: str
    snapshot_type: SnapshotType
    state: SnapshotState
    created_at: datetime

    description: Optional[str] = None

    # Snapshot hierarchy
    parent_name: Optional[str] = None
    children: List[str] = field(default_factory=list)

    # Storage info
    disk_path: Optional[Path] = None
    memory_path: Optional[Path] = None
    size_bytes: int = 0

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    # Auto-snapshot info
    auto_created: bool = False
    auto_policy: Optional[str] = None
    expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "vm_name": self.vm_name,
            "type": self.snapshot_type.value,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "description": self.description,
            "parent_name": self.parent_name,
            "children": self.children,
            "disk_path": str(self.disk_path) if self.disk_path else None,
            "memory_path": str(self.memory_path) if self.memory_path else None,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata,
            "tags": self.tags,
            "auto_created": self.auto_created,
            "auto_policy": self.auto_policy,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Snapshot":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            vm_name=data["vm_name"],
            snapshot_type=SnapshotType(data["type"]),
            state=SnapshotState(data["state"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            description=data.get("description"),
            parent_name=data.get("parent_name"),
            children=data.get("children", []),
            disk_path=Path(data["disk_path"]) if data.get("disk_path") else None,
            memory_path=Path(data["memory_path"]) if data.get("memory_path") else None,
            size_bytes=data.get("size_bytes", 0),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            auto_created=data.get("auto_created", False),
            auto_policy=data.get("auto_policy"),
            expires_at=(
                datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
            ),
        )

    @property
    def is_expired(self) -> bool:
        """Check if snapshot has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    @property
    def age(self) -> timedelta:
        """Get snapshot age."""
        return datetime.now() - self.created_at


@dataclass
class SnapshotPolicy:
    """Policy for automatic snapshots."""

    name: str
    enabled: bool = True

    # Retention settings
    max_snapshots: int = 10
    max_age_days: int = 30
    min_snapshots: int = 1  # Keep at least N snapshots

    # Auto-snapshot triggers
    before_operations: List[str] = field(
        default_factory=lambda: ["upgrade", "resize", "config-change"]
    )
    scheduled_interval_hours: Optional[int] = None  # e.g., 24 for daily

    # Naming
    name_prefix: str = "auto-"
    include_timestamp: bool = True

    # Cleanup
    auto_cleanup: bool = True
    cleanup_on_success: bool = False  # Remove pre-operation snapshot if op succeeds

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "max_snapshots": self.max_snapshots,
            "max_age_days": self.max_age_days,
            "min_snapshots": self.min_snapshots,
            "before_operations": self.before_operations,
            "scheduled_interval_hours": self.scheduled_interval_hours,
            "name_prefix": self.name_prefix,
            "include_timestamp": self.include_timestamp,
            "auto_cleanup": self.auto_cleanup,
            "cleanup_on_success": self.cleanup_on_success,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SnapshotPolicy":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            enabled=data.get("enabled", True),
            max_snapshots=data.get("max_snapshots", 10),
            max_age_days=data.get("max_age_days", 30),
            min_snapshots=data.get("min_snapshots", 1),
            before_operations=data.get("before_operations", ["upgrade", "resize", "config-change"]),
            scheduled_interval_hours=data.get("scheduled_interval_hours"),
            name_prefix=data.get("name_prefix", "auto-"),
            include_timestamp=data.get("include_timestamp", True),
            auto_cleanup=data.get("auto_cleanup", True),
            cleanup_on_success=data.get("cleanup_on_success", False),
        )

    def generate_snapshot_name(self, operation: Optional[str] = None) -> str:
        """Generate snapshot name based on policy."""
        parts = [self.name_prefix]
        if operation:
            parts.append(operation)
        if self.include_timestamp:
            parts.append(datetime.now().strftime("%Y%m%d-%H%M%S"))
        return "-".join(parts)
