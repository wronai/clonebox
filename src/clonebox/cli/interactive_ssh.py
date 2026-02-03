#!/usr/bin/env python3
"""
Interactive SSH key management functions.
"""

from pathlib import Path

import questionary
from rich.console import Console

from clonebox.cli.utils import console, custom_style


def interactive_ssh_menu():
    """SSH key management menu."""
    console.print("\n[bold cyan]SSH Key Management[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("🔑 Generate new key pair", value="generate"),
            questionary.Choice("🔄 Sync key with VM", value="sync"),
            questionary.Choice("📋 Show public key", value="show"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    if choice == "generate":
        output_path = questionary.text(
            "Output path for key:",
            default=str(Path.cwd() / "clonebox_key"),
            style=custom_style,
        ).ask()
        
        from clonebox.cli.misc_commands import generate_password
        from clonebox.secrets import SecretsManager
        
        secrets = SecretsManager()
        key_pair = secrets.generate_ssh_key_pair(Path(output_path))
        
        console.print(f"\n[green]✅ SSH key pair generated:[/]")
        console.print(f"  Private key: {output_path}")
        console.print(f"  Public key: {output_path}.pub")
        
        if questionary.confirm("Copy public key to clipboard?", default=True, style=custom_style).ask():
            import pyperclip
            pyperclip.copy(key_pair.public_key)
            console.print("[green]✅ Public key copied to clipboard[/]")
            
    elif choice == "sync":
        # Get VM name
        from clonebox.cloner import SelectiveVMCloner
        cloner = SelectiveVMCloner()
        
        try:
            vms = cloner.list_vms()
            
            if not vms:
                console.print("[dim]No VMs found[/]")
                return
            
            # Only show running VMs
            running_vms = [vm for vm in vms if vm["state"] == "running"]
            
            if not running_vms:
                console.print("[dim]No running VMs found[/]")
                return
            
            choices = [vm["name"] for vm in running_vms]
            vm_name = questionary.select(
                "Select VM:",
                choices=choices,
                style=custom_style,
            ).ask()
            
            if vm_name:
                from clonebox.cli.import_export_commands import cmd_sync_key
                args = type('Args', (), {'name': vm_name, 'user': False})()
                cmd_sync_key(args)
                
        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/]")
            
    elif choice == "show":
        ssh_dir = Path.home() / ".ssh"
        pub_key_path = ssh_dir / "id_rsa.pub"
        
        if pub_key_path.exists():
            pub_key = pub_key_path.read_text().strip()
            console.print(f"\n[bold]Public key:[/]")
            console.print(pub_key)
            
            if questionary.confirm("Copy to clipboard?", default=True, style=custom_style).ask():
                import pyperclip
                pyperclip.copy(pub_key)
                console.print("[green]✅ Copied to clipboard[/]")
        else:
            console.print("[yellow]No SSH key found. Generate one first.[/]")
