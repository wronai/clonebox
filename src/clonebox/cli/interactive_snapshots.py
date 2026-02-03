#!/usr/bin/env python3
"""
Interactive snapshot management functions.
"""

import questionary
from rich.console import Console

from clonebox.cli.utils import console, custom_style


def interactive_snapshot_menu():
    """Snapshot management menu."""
    console.print("\n[bold cyan]Snapshot Management[/]\n")
    
    # Get VM name
    from clonebox.cloner import SelectiveVMCloner
    cloner = SelectiveVMCloner()
    
    try:
        vms = cloner.list_vms()
        
        if not vms:
            console.print("[dim]No VMs found[/]")
            return
        
        choices = [vm["name"] for vm in vms]
        vm_name = questionary.select(
            "Select VM:",
            choices=choices,
            style=custom_style,
        ).ask()
        
        if not vm_name:
            return
        
        # Snapshot actions
        choice = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("📸 Create snapshot", value="create"),
                questionary.Choice("📋 List snapshots", value="list"),
                questionary.Choice("↩️  Restore snapshot", value="restore"),
                questionary.Choice("🗑️  Delete snapshot", value="delete"),
                questionary.Choice("🔙 Back", value="back"),
            ],
            style=custom_style,
        ).ask()
        
        if choice == "back":
            return
        
        from clonebox.snapshots import SnapshotManager
        manager = SnapshotManager()
        
        if choice == "create":
            name = questionary.text(
                "Snapshot name:",
                style=custom_style,
            ).ask()
            
            description = questionary.text(
                "Description (optional):",
                style=custom_style,
            ).ask()
            
            snapshot_id = manager.create_snapshot(
                vm_name=vm_name,
                name=name,
                description=description,
                console=console,
            )
            console.print(f"[green]✅ Snapshot created: {snapshot_id}[/]")
            
        elif choice == "list":
            snapshots = manager.list_snapshots(vm_name)
            
            if not snapshots:
                console.print(f"[dim]No snapshots found for VM '{vm_name}'[/]")
                return
            
            from rich.table import Table
            table = Table()
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Created", style="yellow")
            
            for snapshot in snapshots:
                table.add_row(
                    snapshot["id"],
                    snapshot["name"],
                    snapshot["created"],
                )
            
            console.print(table)
            
        elif choice in ["restore", "delete"]:
            snapshots = manager.list_snapshots(vm_name)
            
            if not snapshots:
                console.print(f"[dim]No snapshots found for VM '{vm_name}'[/]")
                return
            
            choices = [
                questionary.Choice(f"{s['name']} ({s['id']})", value=s["id"])
                for s in snapshots
            ]
            
            snapshot_id = questionary.select(
                f"Select snapshot to {choice}:",
                choices=choices,
                style=custom_style,
            ).ask()
            
            if snapshot_id:
                if choice == "restore":
                    manager.restore_snapshot(vm_name, snapshot_id, console=console)
                    console.print("[green]✅ Snapshot restored[/]")
                else:
                    manager.delete_snapshot(vm_name, snapshot_id, console=console)
                    console.print("[green]✅ Snapshot deleted[/]")
                    
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")
