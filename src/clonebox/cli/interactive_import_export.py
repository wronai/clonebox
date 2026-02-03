#!/usr/bin/env python3
"""
Interactive import/export functions.
"""

from pathlib import Path

import questionary
from rich.console import Console

from clonebox.cli.utils import console, custom_style


def interactive_import_export_menu():
    """Import/Export menu."""
    console.print("\n[bold cyan]Import/Export[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("📤 Export VM", value="export"),
            questionary.Choice("📥 Import VM", value="import"),
            questionary.Choice("🔐 Export encrypted", value="export_enc"),
            questionary.Choice("🔓 Import encrypted", value="import_enc"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    # Get VM name for export operations
    if choice in ["export", "export_enc"]:
        from clonebox.cloner import SelectiveVMCloner
        cloner = SelectiveVMCloner()
        
        try:
            vms = cloner.list_vms()
            
            if not vms:
                console.print("[dim]No VMs found[/]")
                return
            
            choices = [vm["name"] for vm in vms]
            vm_name = questionary.select(
                "Select VM to export:",
                choices=choices,
                style=custom_style,
            ).ask()
            
            if not vm_name:
                return
            
            output_path = questionary.text(
                "Output file path:",
                default=f"{vm_name}-export.tar.gz",
                style=custom_style,
            ).ask()
            
            if choice == "export":
                from clonebox.cli.import_export_commands import cmd_export
                args = type('Args', (), {
                    'name': vm_name,
                    'output': output_path,
                    'include_disk': False,
                    'include_memory': False,
                    'compress': True,
                    'user': False
                })()
                cmd_export(args)
            else:
                from clonebox.cli.import_export_commands import cmd_export_encrypted
                args = type('Args', (), {
                    'name': vm_name,
                    'output': output_path,
                    'password': None,
                    'include_disk': False,
                    'user': False
                })()
                cmd_export_encrypted(args)
                
        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/]")
            
    elif choice in ["import", "import_enc"]:
        import_path = questionary.text(
            "Path to import file:",
            style=custom_style,
        ).ask()
        
        if not import_path or not Path(import_path).exists():
            console.print("[red]❌ File not found[/]")
            return
        
        new_name = questionary.text(
            "New VM name (optional):",
            style=custom_style,
        ).ask()
        
        start = questionary.confirm(
            "Start VM after import?",
            default=True,
            style=custom_style,
        ).ask()
        
        if choice == "import":
            from clonebox.cli.import_export_commands import cmd_import
            args = type('Args', (), {
                'import_path': import_path,
                'name': new_name,
                'start': start,
                'user': False
            })()
            cmd_import(args)
        else:
            from clonebox.cli.import_export_commands import cmd_import_encrypted
            args = type('Args', (), {
                'import_path': import_path,
                'name': new_name,
                'password': None,
                'start': start,
                'user': False
            })()
            cmd_import_encrypted(args)
