#!/usr/bin/env python3
"""
Interactive container management functions.
"""

from pathlib import Path

import questionary
from rich.console import Console

from clonebox.cli.utils import console, custom_style


def interactive_container_menu():
    """Container management menu."""
    console.print("\n[bold cyan]Container Management[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("🚀 Start container", value="start"),
            questionary.Choice("📋 List containers", value="list"),
            questionary.Choice("⏹️  Stop container", value="stop"),
            questionary.Choice("🗑️  Remove container", value="remove"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    # Handle container actions
    from clonebox.container import ContainerCloner
    cloner = ContainerCloner()
    
    if choice == "start":
        workspace = questionary.text(
            "Workspace path:",
            default=".",
            style=custom_style,
        ).ask()
        
        name = questionary.text(
            "Container name (optional):",
            style=custom_style,
        ).ask()
        
        image = questionary.text(
            "Container image:",
            default="ubuntu:22.04",
            style=custom_style,
        ).ask()
        
        console.print(f"\n[cyan]Starting container...[/]")
        container_id = cloner.create_container(
            workspace_path=Path(workspace),
            name=name or None,
            image=image,
            detach=True,
            console=console,
        )
        console.print(f"[green]✅ Container started: {container_id[:12]}[/]")
        
    elif choice == "list":
        containers = cloner.list_containers()
        
        if not containers:
            console.print("[dim]No containers running[/]")
            return
        
        from rich.table import Table
        table = Table()
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Image", style="yellow")
        table.add_column("Status", style="blue")
        
        for container in containers:
            table.add_row(
                container["id"][:12],
                container["name"],
                container["image"],
                container["status"],
            )
        
        console.print(table)
        
    elif choice in ["stop", "remove"]:
        containers = cloner.list_containers()
        
        if not containers:
            console.print("[dim]No containers running[/]")
            return
        
        choices = [
            questionary.Choice(f"{c['name']} ({c['id'][:12]})", value=c["name"])
            for c in containers
        ]
        
        container_name = questionary.select(
            f"Select container to {choice}:",
            choices=choices,
            style=custom_style,
        ).ask()
        
        if container_name:
            if choice == "stop":
                cloner.stop_container(container_name, console=console)
                console.print("[green]✅ Container stopped[/]")
            else:
                cloner.stop_container(container_name, console=console)
                cloner.remove_container(container_name, console=console)
                console.print("[green]✅ Container removed[/]")
