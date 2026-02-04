#!/usr/bin/env python3
"""
Compose commands for CloneBox CLI - Manage multi-VM environments.
"""

import yaml
from pathlib import Path
from typing import Dict, List

from rich.table import Table

from clonebox.orchestrator import Orchestrator, OrchestrationResult
from clonebox.cli.utils import console, custom_style, load_clonebox_config, CLONEBOX_CONFIG_FILE


def cmd_compose_up(args):
    """Create and start all VMs in a compose file."""
    compose_file = Path(args.file) if args.file else Path.cwd() / "clonebox-compose.yaml"
    
    if not compose_file.exists():
        console.print(f"[red]❌ Compose file not found: {compose_file}[/]")
        return
    
    # Load compose file
    with open(compose_file) as f:
        compose_config = yaml.safe_load(f)
    
    console.print(f"[cyan]Starting compose environment: {compose_file.name}[/]")
    
    # Create orchestrator
    orchestrator = Orchestrator.from_file(compose_file)
    
    # Start services
    services = args.services if args.services else list(compose_config.get("services", {}).keys())
    
    result = orchestrator.up(
        compose_file=compose_file,
        services=services,
        detach=args.detach,
        console=console,
    )
    
    if result.success:
        console.print(f"\n[green]✅ Compose environment started[/]")
        
        # Show started services
        table = Table(title="Started Services")
        table.add_column("Service", style="cyan")
        table.add_column("VM Name", style="green")
        table.add_column("State", style="yellow")
        table.add_column("IP Address", style="blue")
        
        for service in result.services:
            table.add_row(
                service["name"],
                service["vm_name"],
                service["state"],
                service.get("ip", "-"),
            )
        
        console.print(table)
        
        # Show network info
        if result.networks:
            console.print("\n[bold]Networks:[/]")
            for network in result.networks:
                console.print(f"  • {network['name']}: {network['subnet']}")
    else:
        console.print(f"\n[red]❌ Failed to start compose environment[/]")
        if result.errors:
            for error in result.errors:
                console.print(f"  • {error}")


def cmd_compose_down(args):
    """Stop and remove all VMs in a compose file."""
    compose_file = Path(args.file) if args.file else Path.cwd() / "clonebox-compose.yaml"
    
    if not compose_file.exists():
        console.print(f"[red]❌ Compose file not found: {compose_file}[/]")
        return
    
    # Load compose file
    with open(compose_file) as f:
        compose_config = yaml.safe_load(f)
    
    console.print(f"[cyan]Stopping compose environment: {compose_file.name}[/]")
    
    # Create orchestrator
    orchestrator = Orchestrator()
    
    # Stop services
    services = args.services if args.services else list(compose_config.get("services", {}).keys())
    
    result = orchestrator.down(
        compose_file=compose_file,
        services=services,
        remove_volumes=args.volumes,
        console=console,
    )
    
    if result.success:
        console.print(f"\n[green]✅ Compose environment stopped[/]")
    else:
        console.print(f"\n[red]❌ Failed to stop compose environment[/]")
        if result.errors:
            for error in result.errors:
                console.print(f"  • {error}")


def cmd_compose_status(args):
    """Show status of all services in a compose file."""
    compose_file = Path(args.file) if args.file else Path.cwd() / "clonebox-compose.yaml"
    
    if not compose_file.exists():
        console.print(f"[red]❌ Compose file not found: {compose_file}[/]")
        return
    
    # Load compose file
    with open(compose_file) as f:
        compose_config = yaml.safe_load(f)
    
    # Create orchestrator
    orchestrator = Orchestrator()
    
    # Get status
    status = orchestrator.status(compose_file=compose_file)
    
    if not status:
        console.print("[dim]No services found[/]")
        return
    
    # Display status
    table = Table(title=f"Compose Status: {compose_file.name}")
    table.add_column("Service", style="cyan")
    table.add_column("VM Name", style="green")
    table.add_column("State", style="yellow")
    table.add_column("IP Address", style="blue")
    table.add_column("Ports", style="magenta")
    
    for service in status:
        state_style = "green" if service["state"] == "running" else "red"
        
        ports = []
        for port in service.get("ports", []):
            if port.get("host"):
                ports.append(f"{port['host']}:{port['guest']}")
            else:
                ports.append(str(port["guest"]))
        
        table.add_row(
            service["name"],
            service["vm_name"],
            f"[{state_style}]{service['state']}[/{state_style}]",
            service.get("ip", "-"),
            ", ".join(ports),
        )
    
    console.print(table)


def cmd_compose_logs(args):
    """Show logs for services in a compose file."""
    compose_file = Path(args.file) if args.file else Path.cwd() / "clonebox-compose.yaml"
    
    if not compose_file.exists():
        console.print(f"[red]❌ Compose file not found: {compose_file}[/]")
        return
    
    # Load compose file
    with open(compose_file) as f:
        compose_config = yaml.safe_load(f)
    
    # Create orchestrator
    orchestrator = Orchestrator()
    
    # Get logs
    services = args.services if args.services else list(compose_config.get("services", {}).keys())
    
    if args.follow:
        # Follow logs
        console.print(f"[cyan]Following logs for services: {', '.join(services)}[/]")
        console.print("[dim]Press Ctrl+C to stop[/]")
        
        try:
            for log_entry in orchestrator.follow_logs(compose_file, services):
                timestamp = log_entry["timestamp"].strftime("%H:%M:%S")
                service = log_entry["service"]
                message = log_entry["message"]
                
                console.print(f"[dim]{timestamp}[/] [{service}] {message}")
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped following logs[/]")
    else:
        # Show recent logs
        lines = args.lines or 50
        
        for service in services:
            console.print(f"\n[bold]Logs for {service}:[/]")
            
            logs = orchestrator.get_logs(compose_file, service, lines)
            
            if not logs:
                console.print("[dim]No logs available[/]")
                continue
            
            for log_entry in logs:
                timestamp = log_entry["timestamp"].strftime("%H:%M:%S")
                message = log_entry["message"]
                
                console.print(f"[dim]{timestamp}[/] {message}")


def cmd_compose_ps(args):
    """List all running containers/VMs in compose environment."""
    compose_file = Path(args.file) if args.file else Path.cwd() / "clonebox-compose.yaml"
    
    if not compose_file.exists():
        console.print(f"[red]❌ Compose file not found: {compose_file}[/]")
        return
    
    # Load compose file
    with open(compose_file) as f:
        compose_config = yaml.safe_load(f)
    
    # Create orchestrator
    orchestrator = Orchestrator()
    
    # List processes
    processes = orchestrator.ps(compose_file)
    
    if not processes:
        console.print("[dim]No running services[/]")
        return
    
    # Display processes
    table = Table(title=f"Running Services: {compose_file.name}")
    table.add_column("ID", style="cyan")
    table.add_column("Service", style="green")
    table.add_column("VM Name", style="yellow")
    table.add_column("State", style="blue")
    table.add_column("Uptime", style="magenta")
    
    for process in processes:
        state_style = "green" if process["state"] == "running" else "red"
        
        table.add_row(
            process["id"][:12],
            process["name"],
            process["vm_name"],
            f"[{state_style}]{process['state']}[/{state_style}]",
            process.get("uptime", "-"),
        )
    
    console.print(table)


def cmd_compose_exec(args):
    """Execute command in a service VM."""
    compose_file = Path(args.file) if args.file else Path.cwd() / "clonebox-compose.yaml"
    
    if not compose_file.exists():
        console.print(f"[red]❌ Compose file not found: {compose_file}[/]")
        return
    
    service = args.service
    command = args.command
    
    if not command:
        console.print("[red]❌ No command specified[/]")
        return
    
    # Create orchestrator
    orchestrator = Orchestrator()
    
    # Execute command
    console.print(f"[cyan]Executing in service '{service}': {' '.join(command)}[/]")
    
    result = orchestrator.exec(
        compose_file=compose_file,
        service=service,
        command=command,
        timeout=args.timeout,
    )
    
    if result["success"]:
        if result["output"]:
            console.print(result["output"])
        console.print("[green]✅ Command executed successfully[/]")
    else:
        console.print(f"[red]❌ Command failed: {result.get('error', 'Unknown error')}[/]")


def cmd_compose_restart(args):
    """Restart services in a compose file."""
    compose_file = Path(args.file) if args.file else Path.cwd() / "clonebox-compose.yaml"
    
    if not compose_file.exists():
        console.print(f"[red]❌ Compose file not found: {compose_file}[/]")
        return
    
    # Create orchestrator
    orchestrator = Orchestrator()
    
    # Restart services
    services = args.services if args.services else list(compose_config.get("services", {}).keys())
    
    console.print(f"[cyan]Restarting services: {', '.join(services)}[/]")
    
    result = orchestrator.restart(
        compose_file=compose_file,
        services=services,
        console=console,
    )
    
    if result.success:
        console.print(f"\n[green]✅ Services restarted[/]")
    else:
        console.print(f"\n[red]❌ Failed to restart services[/]")
        if result.errors:
            for error in result.errors:
                console.print(f"  • {error}")
