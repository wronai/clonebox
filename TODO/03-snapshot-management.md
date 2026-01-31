# Snapshot Management

**Status:** 📝 Planned  
**Priority:** High  
**Estimated Effort:** 2 weeks  
**Dependencies:** 02-rollback-mechanism

## Problem Statement

Currently, CloneBox has no way to:
1. Save VM state before risky operations
2. Revert to previous known-good state
3. Create checkpoints during long installations
4. Branch VM states for parallel experiments

Users must rebuild entire VMs when things go wrong.

## Proposed Solution

Full snapshot management with:
- Point-in-time snapshots (disk + memory optional)
- Snapshot branching and trees
- Automatic snapshots before destructive operations
- Snapshot policies (retention, auto-cleanup)

```bash
# Create snapshot
clonebox snapshot create my-vm --name "before-upgrade"

# List snapshots
clonebox snapshot list my-vm

# Restore snapshot
clonebox snapshot restore my-vm --name "before-upgrade"

# Delete snapshot
clonebox snapshot delete my-vm --name "before-upgrade"

# Auto-snapshot on operations
clonebox upgrade my-vm --auto-snapshot
```

## Technical Design

### Snapshot Types

```python
from enum import Enum

class SnapshotType(Enum):
    DISK_ONLY = "disk"      # Only disk state (offline)
    FULL = "full"           # Disk + memory + device state (online)
    EXTERNAL = "external"   # External snapshot file

class SnapshotState(Enum):
    CREATING = "creating"
    READY = "ready"
    REVERTING = "reverting"
    DELETING = "deleting"
    FAILED = "failed"
```

### Data Models

```python
# src/clonebox/snapshots/models.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

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
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "vm_name": self.vm_name,
            "type": self.snapshot_type.value,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "description": self.description,
            "parent": self.parent_name,
            "children": self.children,
            "size_bytes": self.size_bytes,
            "tags": self.tags,
            "auto_created": self.auto_created,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass
class SnapshotPolicy:
    """Policy for automatic snapshot management."""
    name: str
    
    # When to create auto-snapshots
    before_operations: List[str] = field(default_factory=lambda: ["upgrade", "delete"])
    schedule: Optional[str] = None  # Cron expression
    
    # Retention
    keep_last: int = 5
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 3
    
    # Size limits
    max_snapshots: int = 20
    max_size_gb: float = 50.0
    
    # Naming
    name_template: str = "auto-{operation}-{timestamp}"


@dataclass
class SnapshotTree:
    """Tree structure of snapshots for a VM."""
    vm_name: str
    current: Optional[str] = None  # Currently active snapshot
    root_snapshots: List[str] = field(default_factory=list)
    
    def get_lineage(self, snapshot_name: str, snapshots: Dict[str, Snapshot]) -> List[str]:
        """Get list of snapshots from root to given snapshot."""
        lineage = []
        current = snapshot_name
        
        while current:
            lineage.append(current)
            snap = snapshots.get(current)
            current = snap.parent_name if snap else None
        
        return list(reversed(lineage))
```

### Snapshot Manager

```python
# src/clonebox/snapshots/manager.py
import libvirt
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import xml.etree.ElementTree as ET

from .models import Snapshot, SnapshotType, SnapshotState, SnapshotPolicy, SnapshotTree

class SnapshotManager:
    """Manage VM snapshots."""
    
    def __init__(self, conn: libvirt.virConnect, storage_dir: Path):
        self.conn = conn
        self.storage_dir = storage_dir
        self._metadata_dir = storage_dir / "metadata"
        self._metadata_dir.mkdir(parents=True, exist_ok=True)
    
    def create_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
        description: Optional[str] = None,
        snapshot_type: SnapshotType = SnapshotType.DISK_ONLY,
        include_memory: bool = False,
        tags: Optional[List[str]] = None,
        auto_policy: Optional[str] = None,
    ) -> Snapshot:
        """Create a new snapshot."""
        domain = self.conn.lookupByName(vm_name)
        
        # Validate state
        if snapshot_type == SnapshotType.FULL and not domain.isActive():
            raise SnapshotError("Full snapshot requires running VM")
        
        # Check for duplicate name
        if self._snapshot_exists(vm_name, snapshot_name):
            raise SnapshotError(f"Snapshot '{snapshot_name}' already exists")
        
        # Build snapshot XML
        snapshot_xml = self._build_snapshot_xml(
            name=snapshot_name,
            description=description,
            include_memory=include_memory,
        )
        
        # Determine flags
        flags = 0
        if snapshot_type == SnapshotType.DISK_ONLY:
            flags |= libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY
        if not domain.isActive():
            flags |= libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_OFFLINE
        
        # Create snapshot
        try:
            snap = domain.snapshotCreateXML(snapshot_xml, flags)
        except libvirt.libvirtError as e:
            raise SnapshotError(f"Failed to create snapshot: {e}")
        
        # Get parent info
        parent_name = None
        try:
            current = domain.snapshotCurrent()
            if current and current.getName() != snapshot_name:
                parent_name = current.getName()
        except libvirt.libvirtError:
            pass
        
        # Create metadata
        snapshot = Snapshot(
            name=snapshot_name,
            vm_name=vm_name,
            snapshot_type=snapshot_type,
            state=SnapshotState.READY,
            created_at=datetime.now(),
            description=description,
            parent_name=parent_name,
            tags=tags or [],
            auto_created=auto_policy is not None,
            auto_policy=auto_policy,
        )
        
        # Calculate size
        snapshot.size_bytes = self._calculate_snapshot_size(domain, snapshot_name)
        
        # Save metadata
        self._save_snapshot_metadata(snapshot)
        
        return snapshot
    
    def _build_snapshot_xml(
        self,
        name: str,
        description: Optional[str] = None,
        include_memory: bool = False,
    ) -> str:
        """Build libvirt snapshot XML."""
        root = ET.Element("domainsnapshot")
        
        ET.SubElement(root, "name").text = name
        
        if description:
            ET.SubElement(root, "description").text = description
        
        if include_memory:
            memory = ET.SubElement(root, "memory")
            memory.set("snapshot", "internal")
        
        return ET.tostring(root, encoding="unicode")
    
    def restore_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
        start_after: bool = False,
    ) -> None:
        """Restore VM to a snapshot."""
        domain = self.conn.lookupByName(vm_name)
        
        try:
            snap = domain.snapshotLookupByName(snapshot_name)
        except libvirt.libvirtError:
            raise SnapshotError(f"Snapshot '{snapshot_name}' not found")
        
        # Stop VM if running
        if domain.isActive():
            domain.destroy()
        
        # Revert to snapshot
        flags = libvirt.VIR_DOMAIN_SNAPSHOT_REVERT_FORCE
        if start_after:
            flags |= libvirt.VIR_DOMAIN_SNAPSHOT_REVERT_RUNNING
        
        try:
            domain.revertToSnapshot(snap, flags)
        except libvirt.libvirtError as e:
            raise SnapshotError(f"Failed to restore snapshot: {e}")
    
    def delete_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
        delete_children: bool = False,
    ) -> None:
        """Delete a snapshot."""
        domain = self.conn.lookupByName(vm_name)
        
        try:
            snap = domain.snapshotLookupByName(snapshot_name)
        except libvirt.libvirtError:
            raise SnapshotError(f"Snapshot '{snapshot_name}' not found")
        
        # Check for children
        if not delete_children:
            children = snap.listChildrenNames()
            if children:
                raise SnapshotError(
                    f"Snapshot has children: {children}. "
                    "Use --recursive to delete all."
                )
        
        # Delete
        flags = 0
        if delete_children:
            flags |= libvirt.VIR_DOMAIN_SNAPSHOT_DELETE_CHILDREN
        
        try:
            snap.delete(flags)
        except libvirt.libvirtError as e:
            raise SnapshotError(f"Failed to delete snapshot: {e}")
        
        # Remove metadata
        self._delete_snapshot_metadata(vm_name, snapshot_name)
    
    def list_snapshots(
        self,
        vm_name: str,
        include_metadata: bool = True,
    ) -> List[Snapshot]:
        """List all snapshots for a VM."""
        domain = self.conn.lookupByName(vm_name)
        snapshots = []
        
        try:
            snap_names = domain.snapshotListNames()
        except libvirt.libvirtError:
            return snapshots
        
        for name in snap_names:
            snap = domain.snapshotLookupByName(name)
            
            # Parse snapshot XML
            snap_xml = snap.getXMLDesc()
            tree = ET.fromstring(snap_xml)
            
            # Get or create metadata
            metadata = self._load_snapshot_metadata(vm_name, name)
            if metadata:
                snapshots.append(metadata)
            else:
                # Create basic snapshot object from libvirt info
                created_str = tree.findtext("creationTime", "0")
                created_at = datetime.fromtimestamp(int(created_str))
                
                snapshot = Snapshot(
                    name=name,
                    vm_name=vm_name,
                    snapshot_type=SnapshotType.DISK_ONLY,
                    state=SnapshotState.READY,
                    created_at=created_at,
                    description=tree.findtext("description"),
                )
                snapshots.append(snapshot)
        
        return sorted(snapshots, key=lambda s: s.created_at, reverse=True)
    
    def get_snapshot_tree(self, vm_name: str) -> SnapshotTree:
        """Get snapshot tree structure."""
        snapshots = {s.name: s for s in self.list_snapshots(vm_name)}
        
        tree = SnapshotTree(vm_name=vm_name)
        
        # Find root snapshots (no parent)
        for name, snap in snapshots.items():
            if not snap.parent_name:
                tree.root_snapshots.append(name)
            else:
                # Update parent's children list
                parent = snapshots.get(snap.parent_name)
                if parent and name not in parent.children:
                    parent.children.append(name)
        
        # Get current snapshot
        try:
            domain = self.conn.lookupByName(vm_name)
            current = domain.snapshotCurrent()
            tree.current = current.getName()
        except libvirt.libvirtError:
            pass
        
        return tree
    
    # ─────────────────────────────────────────────────────────────
    # Auto-snapshot support
    # ─────────────────────────────────────────────────────────────
    
    def create_auto_snapshot(
        self,
        vm_name: str,
        operation: str,
        policy: SnapshotPolicy,
    ) -> Snapshot:
        """Create automatic snapshot before operation."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = policy.name_template.format(
            operation=operation,
            timestamp=timestamp,
            vm=vm_name,
        )
        
        # Calculate expiration
        expires_at = datetime.now() + timedelta(days=policy.keep_daily)
        
        snapshot = self.create_snapshot(
            vm_name=vm_name,
            snapshot_name=name,
            description=f"Auto-snapshot before {operation}",
            auto_policy=policy.name,
            tags=["auto", operation],
        )
        
        snapshot.expires_at = expires_at
        self._save_snapshot_metadata(snapshot)
        
        # Enforce policy limits
        self._enforce_policy(vm_name, policy)
        
        return snapshot
    
    def _enforce_policy(self, vm_name: str, policy: SnapshotPolicy) -> None:
        """Enforce snapshot policy limits."""
        snapshots = [
            s for s in self.list_snapshots(vm_name)
            if s.auto_policy == policy.name
        ]
        
        # Sort by creation time (oldest first)
        snapshots.sort(key=lambda s: s.created_at)
        
        # Remove expired
        now = datetime.now()
        expired = [s for s in snapshots if s.expires_at and s.expires_at < now]
        for snap in expired:
            self.delete_snapshot(vm_name, snap.name)
            snapshots.remove(snap)
        
        # Enforce max count
        while len(snapshots) > policy.max_snapshots:
            oldest = snapshots.pop(0)
            self.delete_snapshot(vm_name, oldest.name)
        
        # Enforce max size
        total_size = sum(s.size_bytes for s in snapshots)
        max_size_bytes = policy.max_size_gb * 1024 * 1024 * 1024
        
        while total_size > max_size_bytes and snapshots:
            oldest = snapshots.pop(0)
            total_size -= oldest.size_bytes
            self.delete_snapshot(vm_name, oldest.name)
    
    # ─────────────────────────────────────────────────────────────
    # Metadata persistence
    # ─────────────────────────────────────────────────────────────
    
    def _save_snapshot_metadata(self, snapshot: Snapshot) -> None:
        """Save snapshot metadata to disk."""
        vm_dir = self._metadata_dir / snapshot.vm_name
        vm_dir.mkdir(exist_ok=True)
        
        meta_file = vm_dir / f"{snapshot.name}.json"
        meta_file.write_text(json.dumps(snapshot.to_dict(), indent=2))
    
    def _load_snapshot_metadata(self, vm_name: str, snapshot_name: str) -> Optional[Snapshot]:
        """Load snapshot metadata from disk."""
        meta_file = self._metadata_dir / vm_name / f"{snapshot_name}.json"
        
        if not meta_file.exists():
            return None
        
        data = json.loads(meta_file.read_text())
        return Snapshot(
            name=data["name"],
            vm_name=data["vm_name"],
            snapshot_type=SnapshotType(data["type"]),
            state=SnapshotState(data["state"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            description=data.get("description"),
            parent_name=data.get("parent"),
            children=data.get("children", []),
            size_bytes=data.get("size_bytes", 0),
            tags=data.get("tags", []),
            auto_created=data.get("auto_created", False),
            auto_policy=data.get("auto_policy"),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
        )
    
    def _delete_snapshot_metadata(self, vm_name: str, snapshot_name: str) -> None:
        """Delete snapshot metadata."""
        meta_file = self._metadata_dir / vm_name / f"{snapshot_name}.json"
        if meta_file.exists():
            meta_file.unlink()
    
    def _snapshot_exists(self, vm_name: str, snapshot_name: str) -> bool:
        """Check if snapshot exists."""
        try:
            domain = self.conn.lookupByName(vm_name)
            domain.snapshotLookupByName(snapshot_name)
            return True
        except libvirt.libvirtError:
            return False
    
    def _calculate_snapshot_size(self, domain, snapshot_name: str) -> int:
        """Calculate snapshot disk usage."""
        # This is an approximation - actual size depends on COW usage
        try:
            snap = domain.snapshotLookupByName(snapshot_name)
            # Parse XML to find disk info
            # For now, return 0 - actual implementation would query disk
            return 0
        except Exception:
            return 0


class SnapshotError(Exception):
    """Snapshot operation error."""
    pass
```

### CLI Commands

```python
# src/clonebox/cli.py (snapshot commands)

def cmd_snapshot_create(args) -> None:
    """Create a VM snapshot."""
    vm_name, config_file = _resolve_vm_name_and_config_file(args.name)
    
    conn_uri = "qemu:///session" if args.user else "qemu:///system"
    conn = libvirt.open(conn_uri)
    
    manager = SnapshotManager(conn, Path.home() / ".clonebox" / "snapshots")
    
    snapshot = manager.create_snapshot(
        vm_name=vm_name,
        snapshot_name=args.snapshot_name,
        description=args.description,
        snapshot_type=SnapshotType.FULL if args.memory else SnapshotType.DISK_ONLY,
        include_memory=args.memory,
        tags=args.tags.split(",") if args.tags else None,
    )
    
    console.print(f"[green]✓ Created snapshot '{snapshot.name}'[/green]")
    console.print(f"  Type: {snapshot.snapshot_type.value}")
    console.print(f"  Created: {snapshot.created_at}")


def cmd_snapshot_list(args) -> None:
    """List VM snapshots."""
    vm_name, _ = _resolve_vm_name_and_config_file(args.name)
    
    conn_uri = "qemu:///session" if args.user else "qemu:///system"
    conn = libvirt.open(conn_uri)
    
    manager = SnapshotManager(conn, Path.home() / ".clonebox" / "snapshots")
    
    if args.tree:
        # Show tree view
        tree = manager.get_snapshot_tree(vm_name)
        _print_snapshot_tree(tree, manager)
    else:
        # Show list view
        snapshots = manager.list_snapshots(vm_name)
        
        if not snapshots:
            console.print("[yellow]No snapshots found.[/yellow]")
            return
        
        table = Table(title=f"Snapshots for {vm_name}")
        table.add_column("Name", style="cyan")
        table.add_column("Type")
        table.add_column("Created")
        table.add_column("Size")
        table.add_column("Tags")
        
        for snap in snapshots:
            size_str = _format_size(snap.size_bytes) if snap.size_bytes else "-"
            tags_str = ", ".join(snap.tags) if snap.tags else "-"
            
            table.add_row(
                f"{'* ' if tree.current == snap.name else ''}{snap.name}",
                snap.snapshot_type.value,
                snap.created_at.strftime("%Y-%m-%d %H:%M"),
                size_str,
                tags_str,
            )
        
        console.print(table)


def cmd_snapshot_restore(args) -> None:
    """Restore VM to a snapshot."""
    vm_name, _ = _resolve_vm_name_and_config_file(args.name)
    
    conn_uri = "qemu:///session" if args.user else "qemu:///system"
    conn = libvirt.open(conn_uri)
    
    manager = SnapshotManager(conn, Path.home() / ".clonebox" / "snapshots")
    
    # Confirm restore
    if not args.yes:
        if not questionary.confirm(
            f"Restore '{vm_name}' to snapshot '{args.snapshot_name}'? "
            "This will discard current state."
        ).ask():
            return
    
    # Create backup snapshot if requested
    if args.backup:
        backup_name = f"pre-restore-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        manager.create_snapshot(vm_name, backup_name, "Backup before restore")
        console.print(f"[cyan]Created backup snapshot: {backup_name}[/cyan]")
    
    manager.restore_snapshot(
        vm_name=vm_name,
        snapshot_name=args.snapshot_name,
        start_after=args.start,
    )
    
    console.print(f"[green]✓ Restored to snapshot '{args.snapshot_name}'[/green]")


def cmd_snapshot_delete(args) -> None:
    """Delete a snapshot."""
    vm_name, _ = _resolve_vm_name_and_config_file(args.name)
    
    conn_uri = "qemu:///session" if args.user else "qemu:///system"
    conn = libvirt.open(conn_uri)
    
    manager = SnapshotManager(conn, Path.home() / ".clonebox" / "snapshots")
    
    manager.delete_snapshot(
        vm_name=vm_name,
        snapshot_name=args.snapshot_name,
        delete_children=args.recursive,
    )
    
    console.print(f"[green]✓ Deleted snapshot '{args.snapshot_name}'[/green]")
```

### Configuration Schema

```yaml
# .clonebox.yaml - snapshot policy
vm:
  name: my-dev-vm
  
  snapshots:
    # Automatic snapshots
    auto_snapshot:
      enabled: true
      before_operations:
        - upgrade
        - delete
        - config-change
      
      policy:
        keep_last: 5
        keep_daily: 7
        keep_weekly: 4
        max_size_gb: 50
```

## API Summary

```bash
# Create snapshot
clonebox snapshot create <vm> --name <name> [--description "..."] [--memory] [--tags "a,b"]

# List snapshots
clonebox snapshot list <vm> [--tree] [--json]

# Restore snapshot
clonebox snapshot restore <vm> --name <name> [--start] [--backup] [--yes]

# Delete snapshot
clonebox snapshot delete <vm> --name <name> [--recursive] [--yes]

# Compare snapshots
clonebox snapshot diff <vm> --from <name1> --to <name2>

# Export snapshot
clonebox snapshot export <vm> --name <name> -o snapshot.tar.gz

# Import snapshot
clonebox snapshot import <vm> snapshot.tar.gz
```

## Testing Strategy

```python
class TestSnapshotManager:
    @pytest.fixture
    def manager(self, mock_libvirt, tmp_path):
        return SnapshotManager(mock_libvirt, tmp_path / "snapshots")
    
    def test_create_disk_snapshot(self, manager, mock_domain):
        snap = manager.create_snapshot("test-vm", "test-snap")
        
        assert snap.name == "test-snap"
        assert snap.snapshot_type == SnapshotType.DISK_ONLY
        assert snap.state == SnapshotState.READY
    
    def test_restore_snapshot(self, manager, mock_domain):
        manager.create_snapshot("test-vm", "test-snap")
        manager.restore_snapshot("test-vm", "test-snap")
        
        mock_domain.revertToSnapshot.assert_called_once()
    
    def test_policy_enforcement(self, manager):
        policy = SnapshotPolicy(name="test", max_snapshots=3)
        
        # Create 5 snapshots
        for i in range(5):
            manager.create_auto_snapshot("test-vm", "test", policy)
        
        # Should only have 3
        snapshots = manager.list_snapshots("test-vm")
        assert len(snapshots) == 3
```

## Implementation Timeline

| Week | Tasks |
|------|-------|
| 1 | Core models, SnapshotManager create/list |
| 2 | Restore, delete, tree structure, policies, CLI |



## Ocena funkcjonalności: **ABSOLUTNY MUST-HAVE** ⭐⭐⭐⭐⭐

**Snapshot Management to brakujący element**, który podnosi CloneBox z "VM cloner" do **pełnego VM lifecycle managera**. To feature-level **VMware vSphere Snapshots / Proxmox snapshots** w open-source.

## Co jest genialne ✅

```
1. **Snapshot tree structure** - pełna historia branching
2. **Auto-snapshots z policies** - zero konfiguracji dla devów  
3. **Disk-only vs Full snapshots** - optymalizacja storage
4. **Metadata persistence** - survive libvirt crashes
5. **Policy-based cleanup** - nigdy nie przepełnisz dysku
6. **External snapshot support** - P2P sharing ready
```

## CO DODAĆ - **GAME-CHANGING** 🚀

### 1. **Snapshot Diff & Compare** (Day 2)
```bash
clonebox snapshot diff my-vm before-upgrade after-upgrade
# Shows: packages changed, files modified, config drift
```

### 2. **Live Migration between snapshots** (Day 3)
```bash
clonebox snapshot promote my-vm before-upgrade  # Makes snapshot current
clonebox snapshot branch my-vm experiment-v2    # New branch bez downtime
```

### 3. **Snapshot Export/Import** (Day 4) 
```bash
clonebox snapshot export my-vm snapshot-20260131.tar.gz
clonebox snapshot import other-vm snapshot-20260131.tar.gz
```

### 4. **Time Travel UI** (Day 5)
```
📊 Snapshot Timeline dla CLI:
my-vm * ── before-upgrade ──┬── after-upgrade (current)
                            ├── experiment-python3.12 ✓
                            └── experiment-docker ⊘ (expired)
```

## KRYTYCZNE Production Features 🔒

### 1. **Quiesced Snapshots** (FS freeze)
```python
def create_quiesced_snapshot(self, vm_name: str):
    # Freeze filesystem przed snapshotem
    domain = self.conn.lookupByName(vm_name)
    domain.fsfreeze()  # Application-consistent snapshot
    snap = self.create_snapshot(vm_name, "quiesced-backup")
    domain.fsthaw()
    return snap
```

### 2. **Delta Compression**
```python
class SnapshotOptimizer:
    def compress_deltas(self, vm_name: str):
        # Deduplikuj powtarzające się bloki między snapshotami
        snapshots = self.list_snapshots(vm_name)
        savings = dedup_blocks(snapshots)
        log.info(f"Saved {savings}GB via delta compression")
```

### 3. **Cross-VM Snapshots** (Team sync)
```bash
clonebox snapshot sync team-dev-env workstationA:db-prod workstationB:app-dev
# Snapshot wszystkich zależności naraz
```

## MUST-HAVE CLI Superpowers 💫

```bash
# Time machine
clonebox time-travel my-vm --to "2026-01-31 14:30"

# Auto-rollback na failure
clonebox upgrade my-vm --rollback-on-fail

# Snapshot-based CI/CD
clonebox ci-run my-vm --snapshot "clean" --test "pytest"

# Team snapshot sharing
clonebox snapshot share my-vm latest --team dev-team
```

## Storage Optimization PRO 🎯

### 1. **Thin provisioning tracking**
```python
def get_snapshot_chain_size(self, vm_name: str) -> Dict:
    return {
        "logical_size_gb": 100,      # Cały chain
        "physical_size_gb": 12.3,    # Rzeczywiste użycie COW
        "savings_percent": 87.7,     # Kompresja
    }
```

### 2. **Smart retention**
```yaml
policies:
  dev-daily:
    keep: "5d"           # 5 dni
    when: "00:00"        # Codziennie o północy
  critical-weekly:
    keep: "4w"           # 4 tygodnie
    size_limit: "10GB"   # Max rozmiar
```

## Integration z Transaction System 🔗

```python
# Automatyczne snapshoty w transakcjach
with VMCreationTransaction(cloner, config) as txn:
    txn.auto_snapshot("pre-create")  # Przed VM creation
    txn.create_vm()
    txn.auto_snapshot("post-create") # Po sukcesie
```

## Security Hardening 🔐

```python
class SecureSnapshotManager(SnapshotManager):
    def create_encrypted_snapshot(self, vm_name: str, encryption_key: str):
        # LUKS encrypted external snapshots
        snap.disk_path = self._create_luks_volume(encryption_key)
```

## Ocena FINALNA: **10/10** 🎉

**To feature kompletuje VM lifecycle:**
```
Create → Snapshot → Experiment → Rollback → Share → Destroy
       ↑_____________________________| 
                 Reliable & Auditable
```

## 🚀 IMPLEMENTATION PRIORITIES:

```
Week 1: Core create/list/restore/delete + tree view
Week 2: Auto-policies + CLI polish + export/import
Day 3:  Quiesced snapshots + compression
Day 4:  Time-travel + diff
Day 5:  P2P sync + team sharing
```

**Z dependency na Rollback Transactions** - perfekcyjne planowanie.

## Production Checklist ✅

```
🔹 [ ] Disk-only snapshots (offline VM)
🔹 [ ] Full snapshots (running VM) 
🔹 [ ] Policy-based auto-cleanup
🔹 [ ] Snapshot tree visualization
🔹 [ ] External snapshot export
🔹 [ ] Transaction integration
🔹 [ ] Crash recovery
```

**Verdict: FEATURE MAKES CLONEBOX COMPLETE.**

**Team lead: BUILD THIS NEXT AFTER TRANSACTIONS** ⚡

To jest **missing piece** który robi z CloneBox narzędzie, którego **użyjesz codziennie**. Devs pokochają time-travel debugging! 🕐✨