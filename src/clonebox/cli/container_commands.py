#!/usr/bin/env python3
"""
Container commands for CloneBox CLI.
"""

from pathlib import Path

from clonebox.container import ContainerCloner
from clonebox.cli.utils import console


def cmd_container_up(args):
    """Start a container sandbox."""
    path = Path(args.path).resolve()
    
    cloner = ContainerCloner(engine=args.engine)
    container_id = cloner.create_container(
        workspace_path=path,
        name=args.name,
        image=args.image,
        profile=args.profile,
        mounts=args.mount,
        ports=args.port,
        packages=args.package,
        detach=args.detach,
        console=console,
    )
    
    if not args.detach:
        console.print("\n[dim]Container is running. Press Ctrl+C to stop.[/]")
        try:
            cloner.attach_container(container_id)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping container...[/]")
            cloner.stop_container(container_id)
            console.print("[green]✅ Container stopped[/]")


def cmd_container_ps(args):
    """List running containers."""
    cloner = ContainerCloner(engine=args.engine)
    containers = cloner.list_containers()
    
    if not containers:
        console.print("[dim]No containers running[/]")
        return
    
    from rich.table import Table
    table = Table(title="Containers")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Image", style="yellow")
    table.add_column("Status", style="blue")
    table.add_column("Workspace", style="magenta")
    
    for container in containers:
        table.add_row(
            container["id"][:12],
            container["name"],
            container["image"],
            container["status"],
            container["workspace"],
        )
    
    console.print(table)


def cmd_container_stop(args):
    """Stop a running container."""
    cloner = ContainerCloner(engine=args.engine)
    cloner.stop_container(args.name, console=console)


def cmd_container_rm(args):
    """Remove a container."""
    cloner = ContainerCloner(engine=args.engine)
    cloner.remove_container(args.name, console=console)


def cmd_container_down(args):
    """Stop and remove container."""
    cloner = ContainerCloner(engine=args.engine)
    cloner.stop_container(args.name, console=console)
    cloner.remove_container(args.name, console=console)
