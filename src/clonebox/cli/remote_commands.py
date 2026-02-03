#!/usr/bin/env python3
"""
Remote management commands for CloneBox CLI.
"""

import tempfile
from pathlib import Path
from typing import Optional

from clonebox.remote import RemoteCloner, RemoteConnection
from clonebox.cli.utils import console, custom_style, load_clonebox_config, CLONEBOX_CONFIG_FILE


def cmd_remote_list(args):
    """List VMs on remote host."""
    host = args.host
    user_session = getattr(args, "user", False)
    
    # Connect to remote host
    conn = RemoteConnection(host, user_session=user_session)
    remote = RemoteCloner(conn)
    
    try:
        vms = remote.list_vms()
        
        if args.json:
            import json
            console.print(json.dumps(vms, indent=2))
        else:
            if not vms:
                console.print(f"[dim]No VMs found on {host}[/]")
                return
            
            from rich.table import Table
            table = Table(title=f"Virtual Machines on {host}")
            table.add_column("Name", style="cyan")
            table.add_column("State", style="green")
            table.add_column("IP", style="yellow")
            table.add_column("Memory", style="blue")
            table.add_column("vCPUs", style="magenta")
            
            for vm in vms:
                state_style = "green" if vm["state"] == "running" else "red"
                table.add_row(
                    vm["name"],
                    f"[{state_style}]{vm['state']}[/{state_style}]",
                    vm.get("ip", "-"),
                    f"{vm.get('memory', 0)} MB",
                    str(vm.get('vcpus', 0))
                )
            
            console.print(table)
            
    finally:
        conn.close()


def cmd_remote_status(args):
    """Get detailed status of a remote VM."""
    host = args.host
    vm_name = args.vm_name
    user_session = getattr(args, "user", False)
    
    conn = RemoteConnection(host, user_session=user_session)
    remote = RemoteCloner(conn)
    
    try:
        status = remote.get_vm_status(vm_name)
        
        from rich.panel import Panel
        from rich.table import Table
        
        # Create status table
        table = Table(show_header=False)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Name", status["name"])
        table.add_row("State", status["state"])
        table.add_row("UUID", status["uuid"])
        table.add_row("Memory", f"{status['memory']} MB")
        table.add_row("vCPUs", str(status["vcpus"]))
        table.add_row("Disk Size", f"{status['disk_size']} GB")
        
        if status.get("ip"):
            table.add_row("IP Address", status["ip"])
        
        if status.get("uptime"):
            table.add_row("Uptime", status["uptime"])
        
        console.print(Panel(table, title=f"VM Status: {vm_name}"))
        
        # Show recent logs if requested
        if args.logs:
            console.print("\n[bold]Recent Logs:[/]")
            logs = remote.get_vm_logs(vm_name, lines=20)
            for line in logs:
                console.print(line)
                
    finally:
        conn.close()


def cmd_remote_start(args):
    """Start a VM on remote host."""
    host = args.host
    vm_name = args.vm_name
    user_session = getattr(args, "user", False)
    
    conn = RemoteConnection(host, user_session=user_session)
    remote = RemoteCloner(conn)
    
    try:
        remote.start_vm(vm_name, open_viewer=args.viewer, console=console)
        console.print(f"[green]✅ VM '{vm_name}' started on {host}[/]")
        
        if args.viewer:
            console.print("[dim]Opening remote viewer...[/]")
            
    finally:
        conn.close()


def cmd_remote_stop(args):
    """Stop a VM on remote host."""
    host = args.host
    vm_name = args.vm_name
    user_session = getattr(args, "user", False)
    
    conn = RemoteConnection(host, user_session=user_session)
    remote = RemoteCloner(conn)
    
    try:
        remote.stop_vm(vm_name, force=args.force, console=console)
        console.print(f"[green]✅ VM '{vm_name}' stopped on {host}[/]")
        
    finally:
        conn.close()


def cmd_remote_delete(args):
    """Delete a VM on remote host."""
    host = args.host
    vm_name = args.vm_name
    user_session = getattr(args, "user", False)
    
    if not args.yes:
        import questionary
        if not questionary.confirm(
            f"Delete VM '{vm_name}' on {host} and all its data?", 
            default=False, 
            style=custom_style
        ).ask():
            return
    
    conn = RemoteConnection(host, user_session=user_session)
    remote = RemoteCloner(conn)
    
    try:
        remote.delete_vm(vm_name, keep_storage=args.keep_storage, approved=args.approve, console=console)
        console.print(f"[green]✅ VM '{vm_name}' deleted on {host}[/]")
        
    finally:
        conn.close()


def cmd_remote_exec(args):
    """Execute command in VM on remote host."""
    host = args.host
    vm_name = args.vm_name
    command = args.command
    user_session = getattr(args, "user", False)
    
    if not command:
        console.print("[red]❌ No command specified[/]")
        return
    
    conn = RemoteConnection(host, user_session=user_session)
    remote = RemoteCloner(conn)
    
    try:
        output = remote.exec_in_vm(vm_name, command, timeout=args.timeout)
        
        if output:
            console.print(output)
        else:
            console.print(f"[red]❌ Failed to execute command in VM '{vm_name}'[/]")
            
    finally:
        conn.close()


def cmd_remote_health(args):
    """Run health check on remote VM."""
    host = args.host
    vm_name = args.vm_name
    user_session = getattr(args, "user", False)
    
    conn = RemoteConnection(host, user_session=user_session)
    remote = RemoteCloner(conn)
    
    try:
        result = remote.health_check(vm_name)
        
        if result["passed"]:
            console.print("[green]✅ Health check passed[/]")
        else:
            console.print("[red]❌ Health check failed[/]")
        
        if result.get("output"):
            console.print(result["output"])
            
    finally:
        conn.close()


def cmd_list_remote(args):
    """List configured remote hosts."""
    from clonebox.remote import get_remote_hosts
    
    hosts = get_remote_hosts()
    
    if not hosts:
        console.print("[dim]No remote hosts configured[/]")
        console.print("[dim]Add hosts with: clonebox remote add <host>[/]")
        return
    
    from rich.table import Table
    table = Table(title="Remote Hosts")
    table.add_column("Host", style="cyan")
    table.add_column("User", style="green")
    table.add_column("Port", style="yellow")
    table.add_column("Last Seen", style="blue")
    
    for host in hosts:
        table.add_row(
            host["hostname"],
            host["user"],
            str(host.get("port", 22)),
            host.get("last_seen", "Never"),
        )
    
    console.print(table)
