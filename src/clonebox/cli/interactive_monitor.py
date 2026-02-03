#!/usr/bin/env python3
"""
Interactive monitoring and health check functions.
"""

import time
from typing import List

import questionary
from rich.console import Console
from rich.live import Live
from rich.table import Table

from clonebox.cli.utils import console, custom_style
from clonebox.monitor import ResourceMonitor, format_bytes


def interactive_monitor():
    """Interactive resource monitoring."""
    console.print("\n[bold cyan]Resource Monitoring[/]\n")
    
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
            "Select VM to monitor:",
            choices=choices,
            style=custom_style,
        ).ask()
        
        if vm_name:
            console.print(f"\n[cyan]Monitoring {vm_name}. Press Ctrl+C to stop.[/]")
            
            monitor = ResourceMonitor()
            
            def generate_table():
                stats = monitor.get_stats(vm_name)
                if not stats:
                    return Table(title=f"Resource Monitor - {vm_name} (Offline)")
                
                table = Table(title=f"Resource Monitor - {vm_name}")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="green")
                
                # CPU
                cpu_percent = stats.get("cpu_percent", 0)
                table.add_row("CPU", f"{cpu_percent}%")
                
                # Memory
                memory_used = stats.get("memory_used", 0)
                memory_total = stats.get("memory_total", 0)
                table.add_row(
                    "Memory",
                    f"{format_bytes(memory_used)} / {format_bytes(memory_total)}"
                )
                
                # Disk
                disk_used = stats.get("disk_used", 0)
                disk_total = stats.get("disk_total", 0)
                table.add_row(
                    "Disk",
                    f"{format_bytes(disk_used)} / {format_bytes(disk_total)}"
                )
                
                # Network
                net_rx = stats.get("network_rx", 0)
                net_tx = stats.get("network_tx", 0)
                table.add_row("Network RX", format_bytes(net_rx))
                table.add_row("Network TX", format_bytes(net_tx))
                
                return table
            
            try:
                with Live(generate_table(), refresh_per_second=1) as live:
                    while True:
                        live.update(generate_table())
                        time.sleep(1)
            except KeyboardInterrupt:
                console.print("\n[yellow]Monitoring stopped[/]")
                
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


def interactive_health_check():
    """Interactive health check."""
    console.print("\n[bold cyan]Health Check[/]\n")
    
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
            "Select VM to check:",
            choices=choices,
            style=custom_style,
        ).ask()
        
        if vm_name:
            console.print(f"\n[cyan]Running health checks on {vm_name}...[/]")
            
            from clonebox.health import HealthCheckManager, ProbeConfig, ProbeType
            
            # Default probes
            probes = [
                ProbeConfig(
                    name="qemu_agent",
                    type=ProbeType.AGENT,
                    config={"command": "echo 'ok'"},
                    timeout=5,
                    retries=3,
                ),
                ProbeConfig(
                    name="disk_space",
                    type=ProbeType.AGENT,
                    config={"command": "df / | awk 'NR==2 {print $5}' | sed 's/%//'"},
                    timeout=5,
                    retries=1,
                    threshold=90,
                ),
            ]
            
            manager = HealthCheckManager()
            results = manager.run_health_checks(vm_name, probes)
            
            # Display results
            table = Table()
            table.add_column("Probe", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Response Time", style="yellow")
            
            all_passed = True
            for result in results:
                status = "✅ PASS" if result["passed"] else "❌ FAIL"
                status_style = "green" if result["passed"] else "red"
                response_time = f"{result['response_time']:.2f}s"
                
                table.add_row(
                    result["name"],
                    f"[{status_style}]{status}[/{status_style}]",
                    response_time,
                )
                
                if not result["passed"]:
                    all_passed = False
            
            console.print(table)
            
            if all_passed:
                console.print("[green]✅ All health checks passed[/]")
            else:
                console.print("[red]❌ Some health checks failed[/]")
                
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")
