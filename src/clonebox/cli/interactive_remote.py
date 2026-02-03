#!/usr/bin/env python3
"""
Interactive remote management functions.
"""

import questionary
from rich.console import Console

from clonebox.cli.utils import console, custom_style


def interactive_remote_menu():
    """Remote management menu."""
    console.print("\n[bold cyan]Remote Management[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("📋 List remote hosts", value="list"),
            questionary.Choice("🔗 Add remote host", value="add"),
            questionary.Choice("👀 List remote VMs", value="list_vms"),
            questionary.Choice("▶️  Start remote VM", value="start"),
            questionary.Choice("⏹️  Stop remote VM", value="stop"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    if choice == "list":
        from clonebox.cli.remote_commands import cmd_list_remote
        args = type('Args', (), {})()
        cmd_list_remote(args)
        
    elif choice == "add":
        host = questionary.text(
            "Remote host (user@hostname):",
            style=custom_style,
        ).ask()
        
        if host:
            # Add to config
            from clonebox.remote import add_remote_host
            add_remote_host(host)
            console.print(f"[green]✅ Added remote host: {host}[/]")
            
    elif choice in ["list_vms", "start", "stop"]:
        host = questionary.text(
            "Remote host (user@hostname):",
            style=custom_style,
        ).ask()
        
        if not host:
            return
        
        if choice == "list_vms":
            from clonebox.cli.remote_commands import cmd_remote_list
            args = type('Args', (), {'host': host, 'user': False, 'json': False})()
            cmd_remote_list(args)
            
        elif choice in ["start", "stop"]:
            # Get VMs first
            from clonebox.remote import RemoteConnection, RemoteCloner
            conn = RemoteConnection(host)
            remote = RemoteCloner(conn)
            
            try:
                vms = remote.list_vms()
                conn.close()
                
                if not vms:
                    console.print("[dim]No VMs found on remote host[/]")
                    return
                
                choices = [vm["name"] for vm in vms]
                vm_name = questionary.select(
                    f"Select VM to {choice}:",
                    choices=choices,
                    style=custom_style,
                ).ask()
                
                if vm_name:
                    if choice == "start":
                        from clonebox.cli.remote_commands import cmd_remote_start
                        args = type('Args', (), {
                            'host': host,
                            'vm_name': vm_name,
                            'user': False,
                            'viewer': False
                        })()
                        cmd_remote_start(args)
                    else:
                        from clonebox.cli.remote_commands import cmd_remote_stop
                        args = type('Args', (), {
                            'host': host,
                            'vm_name': vm_name,
                            'user': False,
                            'force': False
                        })()
                        cmd_remote_stop(args)
                        
            except Exception as e:
                console.print(f"[red]❌ Error: {e}[/]")
