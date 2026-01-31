#!/usr/bin/env python3
"""Snapshot manager for CloneBox VMs."""

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Snapshot, SnapshotPolicy, SnapshotState, SnapshotType

try:
    import libvirt
except ImportError:
    libvirt = None


class SnapshotManager:
    """Manage VM snapshots via libvirt."""

    def __init__(self, conn_uri: str = "qemu:///session"):
        self.conn_uri = conn_uri
        self._conn = None
        self._snapshots_dir = Path.home() / ".local/share/clonebox/snapshots"
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)

    @property
    def conn(self):
        if self._conn is None:
            if libvirt is None:
                raise RuntimeError("libvirt-python not installed")
            self._conn = libvirt.open(self.conn_uri)
        return self._conn

    def create(
        self,
        vm_name: str,
        name: str,
        description: Optional[str] = None,
        snapshot_type: SnapshotType = SnapshotType.DISK_ONLY,
        tags: Optional[List[str]] = None,
        auto_policy: Optional[str] = None,
        expires_in_days: Optional[int] = None,
    ) -> Snapshot:
        """Create a new snapshot.

        Args:
            vm_name: Name of VM to snapshot
            name: Snapshot name
            description: Optional description
            snapshot_type: Type of snapshot (disk, full, external)
            tags: Optional tags for categorization
            auto_policy: If auto-created, the policy name
            expires_in_days: Auto-expire after N days
        """
        domain = self.conn.lookupByName(vm_name)

        # Generate snapshot XML
        snapshot_xml = self._generate_snapshot_xml(
            name=name,
            description=description,
            snapshot_type=snapshot_type,
        )

        # Create snapshot
        flags = 0
        if snapshot_type == SnapshotType.DISK_ONLY:
            flags = libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY
        elif snapshot_type == SnapshotType.FULL:
            flags = libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_ATOMIC

        try:
            snap = domain.snapshotCreateXML(snapshot_xml, flags)
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to create snapshot: {e}")

        # Build snapshot object
        snapshot = Snapshot(
            name=name,
            vm_name=vm_name,
            snapshot_type=snapshot_type,
            state=SnapshotState.READY,
            created_at=datetime.now(),
            description=description,
            tags=tags or [],
            auto_created=auto_policy is not None,
            auto_policy=auto_policy,
            expires_at=(
                datetime.now() + timedelta(days=expires_in_days) if expires_in_days else None
            ),
        )

        # Save metadata
        self._save_snapshot_metadata(snapshot)

        return snapshot

    def restore(
        self,
        vm_name: str,
        name: str,
        force: bool = False,
    ) -> bool:
        """Restore VM to a snapshot.

        Args:
            vm_name: Name of VM
            name: Snapshot name to restore
            force: Force restore even if VM is running
        """
        domain = self.conn.lookupByName(vm_name)

        # Check if VM is running
        if domain.isActive() and not force:
            raise RuntimeError(f"VM '{vm_name}' is running. Stop it first or use --force")

        try:
            snap = domain.snapshotLookupByName(name)
        except libvirt.libvirtError:
            raise RuntimeError(f"Snapshot '{name}' not found for VM '{vm_name}'")

        # Revert to snapshot
        flags = libvirt.VIR_DOMAIN_SNAPSHOT_REVERT_FORCE if force else 0
        try:
            domain.revertToSnapshot(snap, flags)
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to restore snapshot: {e}")

        return True

    def delete(
        self,
        vm_name: str,
        name: str,
        delete_children: bool = False,
    ) -> bool:
        """Delete a snapshot.

        Args:
            vm_name: Name of VM
            name: Snapshot name to delete
            delete_children: Also delete child snapshots
        """
        domain = self.conn.lookupByName(vm_name)

        try:
            snap = domain.snapshotLookupByName(name)
        except libvirt.libvirtError:
            raise RuntimeError(f"Snapshot '{name}' not found for VM '{vm_name}'")

        flags = 0
        if delete_children:
            flags = libvirt.VIR_DOMAIN_SNAPSHOT_DELETE_CHILDREN

        try:
            snap.delete(flags)
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to delete snapshot: {e}")

        # Remove metadata
        self._delete_snapshot_metadata(vm_name, name)

        return True

    def list(self, vm_name: str) -> List[Snapshot]:
        """List all snapshots for a VM."""
        domain = self.conn.lookupByName(vm_name)
        snapshots = []

        try:
            snap_names = domain.snapshotListNames()
        except libvirt.libvirtError:
            return []

        for snap_name in snap_names:
            try:
                snap = domain.snapshotLookupByName(snap_name)
                snap_xml = snap.getXMLDesc()

                # Parse XML for details
                import xml.etree.ElementTree as ET

                root = ET.fromstring(snap_xml)

                name = root.findtext("name", snap_name)
                description = root.findtext("description", "")
                creation_time = root.findtext("creationTime", "0")

                # Check for saved metadata
                metadata = self._load_snapshot_metadata(vm_name, name)

                snapshot = Snapshot(
                    name=name,
                    vm_name=vm_name,
                    snapshot_type=SnapshotType(
                        metadata.get("type", "disk") if metadata else "disk"
                    ),
                    state=SnapshotState.READY,
                    created_at=(
                        datetime.fromtimestamp(int(creation_time))
                        if creation_time != "0"
                        else datetime.now()
                    ),
                    description=description or None,
                    tags=metadata.get("tags", []) if metadata else [],
                    auto_created=metadata.get("auto_created", False) if metadata else False,
                    auto_policy=metadata.get("auto_policy") if metadata else None,
                    expires_at=(
                        datetime.fromisoformat(metadata["expires_at"])
                        if metadata and metadata.get("expires_at")
                        else None
                    ),
                )
                snapshots.append(snapshot)

            except Exception:
                continue

        return sorted(snapshots, key=lambda s: s.created_at, reverse=True)

    def get(self, vm_name: str, name: str) -> Optional[Snapshot]:
        """Get a specific snapshot."""
        snapshots = self.list(vm_name)
        for snap in snapshots:
            if snap.name == name:
                return snap
        return None

    def cleanup_expired(self, vm_name: str) -> List[str]:
        """Delete expired snapshots for a VM."""
        deleted = []
        for snapshot in self.list(vm_name):
            if snapshot.is_expired:
                try:
                    self.delete(vm_name, snapshot.name)
                    deleted.append(snapshot.name)
                except Exception:
                    pass
        return deleted

    def apply_policy(self, vm_name: str, policy: SnapshotPolicy) -> List[str]:
        """Apply retention policy to VM snapshots."""
        if not policy.auto_cleanup:
            return []

        snapshots = self.list(vm_name)
        auto_snapshots = [s for s in snapshots if s.auto_policy == policy.name]

        deleted = []

        # Sort by age (oldest first)
        auto_snapshots.sort(key=lambda s: s.created_at)

        # Delete if over max count
        while len(auto_snapshots) > policy.max_snapshots:
            if len(auto_snapshots) <= policy.min_snapshots:
                break
            oldest = auto_snapshots.pop(0)
            try:
                self.delete(vm_name, oldest.name)
                deleted.append(oldest.name)
            except Exception:
                pass

        # Delete if over max age
        max_age = timedelta(days=policy.max_age_days)
        for snap in auto_snapshots[:]:
            if snap.age > max_age:
                if len(auto_snapshots) <= policy.min_snapshots:
                    break
                try:
                    self.delete(vm_name, snap.name)
                    deleted.append(snap.name)
                    auto_snapshots.remove(snap)
                except Exception:
                    pass

        return deleted

    def create_auto_snapshot(
        self,
        vm_name: str,
        operation: str,
        policy: Optional[SnapshotPolicy] = None,
    ) -> Snapshot:
        """Create automatic snapshot before operation."""
        policy = policy or SnapshotPolicy(name="default")

        name = policy.generate_snapshot_name(operation)

        return self.create(
            vm_name=vm_name,
            name=name,
            description=f"Auto-snapshot before {operation}",
            snapshot_type=SnapshotType.DISK_ONLY,
            auto_policy=policy.name,
            expires_in_days=policy.max_age_days,
        )

    def _generate_snapshot_xml(
        self,
        name: str,
        description: Optional[str],
        snapshot_type: SnapshotType,
    ) -> str:
        """Generate libvirt snapshot XML."""
        desc_xml = f"<description>{description}</description>" if description else ""

        if snapshot_type == SnapshotType.DISK_ONLY:
            disks_xml = "<disks><disk name='vda' snapshot='internal'/></disks>"
        else:
            disks_xml = ""

        return f"""
        <domainsnapshot>
            <name>{name}</name>
            {desc_xml}
            {disks_xml}
        </domainsnapshot>
        """

    def _save_snapshot_metadata(self, snapshot: Snapshot) -> None:
        """Save snapshot metadata to disk."""
        vm_dir = self._snapshots_dir / snapshot.vm_name
        vm_dir.mkdir(parents=True, exist_ok=True)

        meta_file = vm_dir / f"{snapshot.name}.json"
        meta_file.write_text(json.dumps(snapshot.to_dict(), indent=2))

    def _load_snapshot_metadata(self, vm_name: str, name: str) -> Optional[Dict[str, Any]]:
        """Load snapshot metadata from disk."""
        meta_file = self._snapshots_dir / vm_name / f"{name}.json"
        if meta_file.exists():
            try:
                return json.loads(meta_file.read_text())
            except Exception:
                return None
        return None

    def _delete_snapshot_metadata(self, vm_name: str, name: str) -> None:
        """Delete snapshot metadata from disk."""
        meta_file = self._snapshots_dir / vm_name / f"{name}.json"
        if meta_file.exists():
            meta_file.unlink()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
