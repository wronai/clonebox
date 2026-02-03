#!/usr/bin/env python3
"""
Interactive compose functions.
"""

import yaml
from pathlib import Path

import questionary
from rich.console import Console

from clonebox.cli.utils import console, custom_style


def interactive_compose_menu():
    """Compose menu for multi-VM management."""
    console.print("\n[bold cyan]Compose - Multi-VM Management[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("🚀 Start services", value="up"),
            questionary.Choice("⏹️  Stop services", value="down"),
            questionary.Choice("📋 Show status", value="status"),
            questionary.Choice("📜 Show logs", value="logs"),
            questionary.Choice("🔄 Restart services", value="restart"),
            questionary.Choice("💻 Execute command", value="exec"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    # Check for compose file
    compose_file = Path.cwd() / "clonebox-compose.yaml"
    if not compose_file.exists():
        compose_file = Path.cwd() / "docker-compose.yaml"  # Also check for docker-compose
    
    if not compose_file.exists():
        console.print("[dim]No compose file found in current directory[/]")
        console.print("[dim]Expected: clonebox-compose.yaml or docker-compose.yaml[/]")
        return
    
    if choice == "up":
        from clonebox.cli.compose_commands import cmd_compose_up
        args = type('Args', (), {
            'file': str(compose_file),
            'detach': True,
            'services': None
        })()
        cmd_compose_up(args)
        
    elif choice == "down":
        from clonebox.cli.compose_commands import cmd_compose_down
        args = type('Args', (), {
            'file': str(compose_file),
            'volumes': False,
            'services': None
        })()
        cmd_compose_down(args)
        
    elif choice == "status":
        from clonebox.cli.compose_commands import cmd_compose_status
        args = type('Args', (), {'file': str(compose_file)})()
        cmd_compose_status(args)
        
    elif choice == "logs":
        follow = questionary.confirm(
            "Follow log output?",
            default=False,
            style=custom_style,
        ).ask()
        
        from clonebox.cli.compose_commands import cmd_compose_logs
        args = type('Args', (), {
            'file': str(compose_file),
            'follow': follow,
            'lines': 50,
            'services': None
        })()
        cmd_compose_logs(args)
        
    elif choice == "restart":
        from clonebox.cli.compose_commands import cmd_compose_restart
        args = type('Args', (), {
            'file': str(compose_file),
            'services': None
        })()
        cmd_compose_restart(args)
        
    elif choice == "exec":
        # Load compose file to get services
        with open(compose_file) as f:
            compose_config = yaml.safe_load(f)
        
        services = list(compose_config.get("services", {}).keys())
        
        if not services:
            console.print("[dim]No services found in compose file[/]")
            return
        
        service = questionary.select(
            "Select service:",
            choices=services,
            style=custom_style,
        ).ask()
        
        command = questionary.text(
            "Command to execute:",
            style=custom_style,
        ).ask()
        
        if service and command:
            from clonebox.cli.compose_commands import cmd_compose_exec
            args = type('Args', (), {
                'file': str(compose_file),
                'service': service,
                'command': command.split(),
                'timeout': 30
            })()
            cmd_compose_exec(args)
