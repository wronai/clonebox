#!/usr/bin/env python3
"""
Monitoring and health check commands for CloneBox CLI.
"""

import time
from pathlib import Path
from typing import Optional

from rich.table import Table
from rich.live import Live

from clonebox.monitor import ResourceMonitor, format_bytes
from clonebox.health import HealthCheckManager, ProbeConfig, ProbeType
from clonebox.cli.utils import console, load_clonebox_config, CLONEBOX_CONFIG_FILE, _qga_ping, _qga_exec, resolve_vm_name
from clonebox.validation.validator import VMValidator
from clonebox import paths as _paths


def cmd_monitor(args):
    """Monitor VM resource usage."""
    vm_name = resolve_vm_name(args.name)
    user_session = getattr(args, "user", False)
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
    monitor = ResourceMonitor(user_session=user_session)
    
    def generate_table():
        stats = monitor.get_stats(vm_name)
        if not stats:
            return Table(title=f"Resource Monitor - {vm_name} (Offline)")
        
        table = Table(title=f"Resource Monitor - {vm_name}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_column("Usage", style="yellow")
        
        # CPU
        cpu_percent = stats.get("cpu_percent", 0)
        table.add_row("CPU", f"{cpu_percent}%", _get_progress_bar(cpu_percent, 100))
        
        # Memory
        memory_used = stats.get("memory_used", 0)
        memory_total = stats.get("memory_total", 0)
        memory_percent = (memory_used / memory_total * 100) if memory_total > 0 else 0
        table.add_row(
            "Memory",
            f"{format_bytes(memory_used)} / {format_bytes(memory_total)}",
            f"{memory_percent:.1f}%"
        )
        
        # Disk
        disk_used = stats.get("disk_used", 0)
        disk_total = stats.get("disk_total", 0)
        disk_percent = (disk_used / disk_total * 100) if disk_total > 0 else 0
        table.add_row(
            "Disk",
            f"{format_bytes(disk_used)} / {format_bytes(disk_total)}",
            f"{disk_percent:.1f}%"
        )
        
        # Network
        net_rx = stats.get("network_rx", 0)
        net_tx = stats.get("network_tx", 0)
        table.add_row("Network RX", format_bytes(net_rx), "")
        table.add_row("Network TX", format_bytes(net_tx), "")
        
        # Processes
        processes = stats.get("processes", 0)
        table.add_row("Processes", str(processes), "")
        
        return table
    
    def _get_progress_bar(value, total, width=20):
        filled = int(width * value / total)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {value}/{total}"
    
    try:
        with Live(generate_table(), refresh_per_second=1) as live:
            while True:
                live.update(generate_table())
                time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitoring stopped[/]")


def cmd_health(args):
    """Run health checks on a VM."""
    vm_name = resolve_vm_name(args.name)
    user_session = getattr(args, "user", False)
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
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
            threshold=90,  # Alert if > 90% full
        ),
        ProbeConfig(
            name="memory_usage",
            type=ProbeType.AGENT,
            config={"command": "free | awk 'NR==2{printf \"%.0f\", $3*100/$2}'"},
            timeout=5,
            retries=1,
            threshold=90,  # Alert if > 90% used
        ),
    ]
    
    # Add custom probe if specified
    if getattr(args, 'probe', None):
        probes.append(ProbeConfig(
            name="custom",
            type=ProbeType.AGENT,
            config={"command": args.probe},
            timeout=getattr(args, 'timeout', None) or 10,
            retries=1,
        ))
    
    manager = HealthCheckManager(user_session=user_session)
    results = manager.run_health_checks(vm_name, probes)
    
    # Display results
    table = Table(title=f"Health Check Results - {vm_name}")
    table.add_column("Probe", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Response Time", style="yellow")
    table.add_column("Details", style="magenta")
    
    all_passed = True
    for result in results:
        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        status_style = "green" if result["passed"] else "red"
        response_time = f"{result['response_time']:.2f}s"
        details = result.get("output", "")[:50]
        
        table.add_row(result["name"], f"[{status_style}]{status}[/{status_style}]", response_time, details)
        
        if not result["passed"]:
            all_passed = False
    
    console.print(table)
    
    if all_passed:
        console.print("[green]✅ All health checks passed[/]")
    else:
        console.print("[red]❌ Some health checks failed[/]")


def cmd_validate(args):
    """Validate a running VM (services/apps/smoke tests)."""
    vm_name = resolve_vm_name(getattr(args, "name", None))
    user_session = getattr(args, "user", False)
    smoke_test = getattr(args, "smoke_test", False)
    require_running_apps = getattr(args, "require_running_apps", False)
    browsers_only = getattr(args, "browsers_only", False)

    conn_uri = _paths.conn_uri(user_session)

    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    else:
        config_file = Path.cwd() / CLONEBOX_CONFIG_FILE
        config = load_clonebox_config(config_file) if config_file.exists() else {"vm": {"name": vm_name}}

    if browsers_only:
        # Reduce config to browser-related expectations only.
        reduced = dict(config)
        reduced_vm = dict((config.get("vm") or {}))
        reduced["vm"] = reduced_vm

        packages = list(reduced.get("packages", []) or [])
        snap_packages = list(reduced.get("snap_packages", []) or [])
        copy_paths = reduced.get("copy_paths", None)
        if not isinstance(copy_paths, dict) or not copy_paths:
            copy_paths = reduced.get("app_data_paths", {}) or {}

        packages = [p for p in packages if p in {"firefox", "chromium-browser", "google-chrome-stable"}]
        snap_packages = [p for p in snap_packages if p in {"firefox", "chromium"}]

        keep_guest_paths = {
            f"/home/{reduced_vm.get('username','ubuntu')}/.config/google-chrome",
            f"/home/{reduced_vm.get('username','ubuntu')}/.mozilla/firefox",
            f"/home/{reduced_vm.get('username','ubuntu')}/.config/chromium",
        }
        reduced_copy = {h: g for h, g in copy_paths.items() if str(g) in keep_guest_paths}

        reduced["packages"] = packages
        reduced["snap_packages"] = snap_packages
        reduced["copy_paths"] = reduced_copy
        config = reduced

    validator = VMValidator(
        config=config,
        vm_name=vm_name,
        conn_uri=conn_uri,
        console=console,
        require_running_apps=require_running_apps,
        smoke_test=smoke_test,
    )

    validator.validate_all()


def cmd_exec(args):
    """Execute command in VM."""
    vm_name = resolve_vm_name(args.name)
    user_session = getattr(args, "user", False)
    conn_uri = _paths.conn_uri(user_session)
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
    if not args.command:
        console.print("[red]❌ No command specified[/]")
        return
    
    command = " ".join(args.command)
    
    # Check if QEMU Guest Agent is available
    if not _qga_ping(vm_name, conn_uri):
        console.print(f"[red]❌ QEMU Guest Agent not responding for VM '{vm_name}'[/]")
        console.print("[dim]Make sure the VM is running and has qemu-guest-agent installed[/]")
        return
    
    # Execute command
    output = _qga_exec(vm_name, conn_uri, command, timeout=args.timeout)
    
    if output is not None:
        console.print(output)
    else:
        console.print(f"[red]❌ Failed to execute command in VM '{vm_name}'[/]")
        console.print(f"[dim]Command: {command}[/]")


def cmd_watch(args):
    """Watch VM logs and status."""
    vm_name = resolve_vm_name(args.name)
    user_session = getattr(args, "user", False)
    conn_uri = _paths.conn_uri(user_session)
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
    console.print(f"[cyan]Watching VM '{vm_name}'... Press Ctrl+C to stop[/]")
    
    try:
        while True:
            # Get VM state
            import subprocess
            result = subprocess.run(
                ["virsh", "--connect", conn_uri, "domstate", vm_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            state = result.stdout.strip()
            
            # Get QEMU Guest Agent status
            qga_status = "🟢" if _qga_ping(vm_name, conn_uri) else "🔴"
            
            # Get IP address
            ip_cmd = 'ip route get 1.1.1.1 | awk \'{print $7}\' | head -n1'
            ip = _qga_exec(vm_name, conn_uri, ip_cmd, timeout=5)
            ip = ip.strip() if ip else "N/A"
            
            # Clear screen and print status
            import os
            os.system('clear' if os.name == 'posix' else 'cls')
            
            console.print(f"[bold]VM Status: {vm_name}[/]")
            console.print(f"State: {state}")
            console.print(f"QEMU Guest Agent: {qga_status}")
            console.print(f"IP Address: {ip}")
            console.print(f"\n[dim]Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}[/]")
            
            time.sleep(2)
            
    except KeyboardInterrupt:
        console.print("\n[yellow]Watching stopped[/]")


def cmd_repair(args):
    """Attempt to repair VM issues."""
    vm_name = resolve_vm_name(args.name)
    user_session = getattr(args, "user", False)
    conn_uri = _paths.conn_uri(user_session)
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
    console.print(f"[cyan]Attempting to repair VM '{vm_name}'...[/]")
    
    # Check VM state
    import subprocess
    result = subprocess.run(
        ["virsh", "--connect", conn_uri, "domstate", vm_name],
        capture_output=True,
        text=True,
        timeout=5,
    )
    state = result.stdout.strip()
    
    if state == "running":
        console.print("[yellow]VM is running, checking services...[/]")
        
        # Check if QEMU Guest Agent is running
        if not _qga_ping(vm_name, conn_uri):
            console.print("[yellow]QEMU Guest Agent not responding, attempting to restart...[/]")
            _qga_exec(vm_name, conn_uri, "sudo systemctl restart qemu-guest-agent", timeout=10)
            
            if _qga_ping(vm_name, conn_uri):
                console.print("[green]✅ QEMU Guest Agent restarted successfully[/]")
            else:
                console.print("[red]❌ Failed to restart QEMU Guest Agent[/]")
        
        # Check network connectivity
        ip = _qga_exec(vm_name, conn_uri, "ip route get 1.1.1.1 | awk '{print $7}' | head -n1", timeout=5)
        if ip:
            console.print(f"[green]✅ Network connectivity OK (IP: {ip.strip()})[/]")
        else:
            console.print("[yellow]Attempting to restart network...[/]")
            _qga_exec(vm_name, conn_uri, "sudo systemctl restart systemd-networkd", timeout=10)
            
    elif state in ["paused", "p suspended"]:
        console.print(f"[yellow]VM is {state}, resuming...[/]")
        subprocess.run(["virsh", "--connect", conn_uri, "resume", vm_name], check=True)
        console.print("[green]✅ VM resumed[/]")
        
    elif state == "shut off":
        console.print("[yellow]VM is shut off, starting...[/]")
        subprocess.run(["virsh", "--connect", conn_uri, "start", vm_name], check=True)
        console.print("[green]✅ VM started[/]")
        
    else:
        console.print(f"[red]Unknown VM state: {state}[/]")
    
    console.print("[dim]Repair completed[/]")


def cmd_logs(args):
    """Show VM logs."""
    vm_name = resolve_vm_name(args.name)
    user_session = getattr(args, "user", False)
    all_logs = getattr(args, "all", False)
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
    # Call clonebox-logs script
    import subprocess
    script_path = Path(__file__).parent.parent.parent.parent / "scripts" / "clonebox-logs.sh"
    cmd = [str(script_path), vm_name, "true" if user_session else "false", "true" if all_logs else "false"]
    subprocess.run(cmd, check=True)
