#!/usr/bin/env python3
"""
Snapshot commands for CloneBox CLI.
"""

from pathlib import Path
from typing import Optional

from clonebox.snapshots import SnapshotManager, SnapshotType
from clonebox.cli.utils import console, load_clonebox_config, CLONEBOX_CONFIG_FILE


def cmd_snapshot_create(args):
    """Create a VM snapshot."""
    vm_name = args.name
    user_session = getattr(args, "user", False)
    
    # Resolve VM name from config if needed
    if not vm_name or vm_name == ".":
        config_file = Path.cwd() / CLONEBOX_CONFIG_FILE
        if config_file.exists():
            config = load_clonebox_config(config_file)
            vm_name = config["vm"]["name"]
        else:
            console.print("[red]❌ No VM name specified[/]")
            return
    
    snapshot_type = SnapshotType.DISK if args.type == "disk" else SnapshotType.MEMORY
    
    manager = SnapshotManager(user_session=user_session)
    snapshot_id = manager.create_snapshot(
        vm_name=vm_name,
        name=args.name,
        description=args.description,
        snapshot_type=snapshot_type,
        console=console,
    )
    
    console.print(f"[green]✅ Snapshot created: {snapshot_id}[/]")


def cmd_snapshot_list(args):
    """List VM snapshots."""
    vm_name = args.name
    user_session = getattr(args, "user", False)
    
    # Resolve VM name from config if needed
    if not vm_name or vm_name == ".":
        config_file = Path.cwd() / CLONEBOX_CONFIG_FILE
        if config_file.exists():
            config = load_clonebox_config(config_file)
            vm_name = config["vm"]["name"]
        else:
            console.print("[red]❌ No VM name specified[/]")
            return
    
    manager = SnapshotManager(user_session=user_session)
    snapshots = manager.list_snapshots(vm_name)
    
    if not snapshots:
        console.print(f"[dim]No snapshots found for VM '{vm_name}'[/]")
        return
    
    from rich.table import Table
    table = Table(title=f"Snapshots for {vm_name}")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Type", style="yellow")
    table.add_column("Created", style="blue")
    table.add_column("Description", style="magenta")
    
    for snapshot in snapshots:
        table.add_row(
            snapshot["id"],
            snapshot["name"],
            snapshot["type"],
            snapshot["created"],
            snapshot.get("description", ""),
        )
    
    console.print(table)


def cmd_snapshot_restore(args):
    """Restore a VM snapshot."""
    vm_name = args.vm_name
    snapshot_id = args.snapshot_id
    user_session = getattr(args, "user", False)
    
    manager = SnapshotManager(user_session=user_session)
    manager.restore_snapshot(
        vm_name=vm_name,
        snapshot_id=snapshot_id,
        console=console,
    )
    
    console.print(f"[green]✅ Snapshot {snapshot_id} restored[/]")


def cmd_snapshot_delete(args):
    """Delete a VM snapshot."""
    vm_name = args.vm_name
    snapshot_id = args.snapshot_id
    user_session = getattr(args, "user", False)
    
    manager = SnapshotManager(user_session=user_session)
    manager.delete_snapshot(
        vm_name=vm_name,
        snapshot_id=snapshot_id,
        console=console,
    )
    
    console.print(f"[green]✅ Snapshot {snapshot_id} deleted[/]")
