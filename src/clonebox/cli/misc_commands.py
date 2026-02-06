#!/usr/bin/env python3
"""
Miscellaneous commands for CloneBox CLI.
"""

import json
import secrets
import string
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import questionary

from clonebox.detector import SystemDetector
from clonebox.cli.utils import console, custom_style, load_clonebox_config, CLONEBOX_CONFIG_FILE, _resolve_vm_name_and_config_file, resolve_vm_name
from clonebox import paths as _paths
from clonebox.ssh import ssh_exec as _ssh_exec, build_ssh_command as _build_ssh_cmd


def cmd_clone(args):
    """Clone current environment to VM."""
    from clonebox.cloner import SelectiveVMCloner
    import os
    from rich.progress import Progress, SpinnerColumn, TextColumn
    
    path = Path(args.path).expanduser().resolve()
    user_session = getattr(args, "user", False)
    
    if not path.exists():
        console.print(f"[red]❌ Path does not exist: {path}[/]")
        return
    
    console.print(f"[cyan]🔍 Analyzing system for cloning...[/]")
    
    # Detect system state
    detector = SystemDetector()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning system...", total=None)
        
        # Take snapshot
        snapshot = detector.detect_all()
        
        # Detect Docker containers
        containers = detector.detect_docker_containers()
        
        progress.update(task, description="Finalizing...")
    
    # Generate config
    from clonebox.cli.utils import generate_clonebox_yaml
    yaml_content = generate_clonebox_yaml(
        snapshot,
        detector,
        deduplicate=getattr(args, "dedupe", True),
        target_path=str(path) if args.path else None,
        vm_name=getattr(args, "name", None),
        network_mode=getattr(args, "network", "auto"),
        base_image=getattr(args, "base_image", None),
        disk_size_gb=getattr(args, "disk_size_gb", None),
    )
    
    # Save config file
    config_file = path / CLONEBOX_CONFIG_FILE
    
    if config_file.exists() and not getattr(args, "replace", False):
        console.print(f"[yellow]⚠️  Config file already exists: {config_file}[/]")
        if not questionary.confirm(
            "Overwrite existing config?", default=False, style=custom_style
        ).ask():
            console.print("[dim]Cancelled.[/]")
            return
    
    with open(config_file, "w") as f:
        f.write(yaml_content)
    
    console.print(f"[green]✅ Config saved to: {config_file}[/]")
    
    # Edit if requested
    if getattr(args, "edit", False):
        editor = os.environ.get("EDITOR", "nano")
        os.system(f"{editor} {config_file}")
    
    # Run VM if requested
    if getattr(args, "run", False):
        console.print("[cyan]🚀 Creating VM from config...[/]")
        config = load_clonebox_config(config_file)
        
        # Add browser profiles if specified
        browser_profiles = getattr(args, "browser_profiles", None)
        if browser_profiles:
            console.print(f"[cyan]📂 Browser profiles to copy: {', '.join(browser_profiles)}[/]")
            config["browser_profiles"] = browser_profiles
        else:
            # Auto-detect and copy browser profiles for GUI VMs
            from clonebox.browser_profiles import detect_browser_profiles
            detected = detect_browser_profiles()
            if detected and config.get("vm", {}).get("gui", True):
                auto_profiles = list(detected.keys())
                console.print(f"[cyan]📂 Auto-detected browser profiles: {', '.join(auto_profiles)}[/]")
                config["browser_profiles"] = auto_profiles
        
        from clonebox.cli.utils import create_vm_from_config
        vm_uuid = create_vm_from_config(
            config, start=True, user_session=user_session, replace=getattr(args, "replace", False), approved=getattr(args, "approve", False)
        )
        console.print(f"[green]✅ VM created: {vm_uuid}[/]")


def cmd_detect(args):
    """Detect system configuration."""
    console.print("[bold cyan]🔍 Detecting system configuration...[/]")
    
    detector = SystemDetector()
    
    if args.component:
        # Detect specific component
        if args.component == "packages":
            result = detector.detect_packages()
        elif args.component == "services":
            result = detector.detect_services()
        elif args.component == "paths":
            result = detector.detect_important_paths()
        elif args.component == "network":
            result = detector.detect_network_config()
        elif args.component == "hardware":
            result = detector.detect_hardware()
        elif args.component == "users":
            result = detector.detect_user_config()
        else:
            console.print(f"[red]❌ Unknown component: {args.component}[/]")
            return
        
        sys_info = {args.component: result}
    else:
        # Detect all
        sys_info = detector.detect_all()
    
    # Format and display output
    if args.json:
        console.print(json.dumps(sys_info, indent=2, default=str))
    elif getattr(args, "yaml", False):
        import yaml
        console.print(yaml.dump(sys_info, default_flow_style=False, allow_unicode=True))
    else:
        format_detection_output(sys_info, console)
    
    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        if args.json:
            with open(output_path, "w") as f:
                json.dump(sys_info, f, indent=2, default=str)
        elif getattr(args, "yaml", False):
            with open(output_path, "w") as f:
                import yaml
                yaml.dump(sys_info, f, default_flow_style=False, allow_unicode=True)
        else:
            with open(output_path, "w") as f:
                import yaml
                yaml.dump(sys_info, f, default_flow_style=False, allow_unicode=True)
        
        console.print(f"\n[green]✅ Detection results saved to: {output_path}[/]")


def format_detection_output(sys_info, console):
    """Format system detection output for display."""
    from rich.table import Table
    from rich.panel import Panel
    from rich.tree import Tree
    
    # System info
    if "system" in sys_info:
        system = sys_info["system"]
        tree = Tree("🖥️  System Information")
        tree.add(f"OS: {system.get('os', 'Unknown')}")
        tree.add(f"Version: {system.get('version', 'Unknown')}")
        tree.add(f"Architecture: {system.get('arch', 'Unknown')}")
        tree.add(f"Desktop: {system.get('desktop', 'Unknown')}")
        
        console.print(Panel(tree, title="System"))
    
    # Hardware
    if "hardware" in sys_info:
        hw = sys_info["hardware"]
        tree = Tree("💻 Hardware")
        tree.add(f"CPU: {hw.get('cpu', 'Unknown')}")
        tree.add(f"Memory: {hw.get('memory', 'Unknown')}")
        tree.add(f"Disk: {hw.get('disk', 'Unknown')}")
        
        console.print(Panel(tree, title="Hardware"))
    
    # Packages
    if "packages" in sys_info:
        packages = sys_info["packages"]
        console.print("\n[bold]📦 Installed Packages:[/]")
        
        if packages.get("apt"):
            console.print(f"  APT: {len(packages['apt'])} packages")
            if args.verbose:
                for pkg in packages["apt"][:10]:
                    console.print(f"    • {pkg}")
                if len(packages["apt"]) > 10:
                    console.print(f"    ... and {len(packages['apt']) - 10} more")
        
        if packages.get("snap"):
            console.print(f"  Snap: {len(packages['snap'])} packages")
            if args.verbose:
                for pkg in packages["snap"][:10]:
                    console.print(f"    • {pkg}")
                if len(packages["snap"]) > 10:
                    console.print(f"    ... and {len(packages['snap']) - 10} more")
    
    # Services
    if "services" in sys_info:
        services = sys_info["services"]
        console.print(f"\n[bold]⚙️  Running Services: {len(services)}[/]")
        
        if args.verbose:
            for service in services[:10]:
                status = "🟢" if service.get("enabled") else "🔴"
                console.print(f"  {status} {service['name']}")
            if len(services) > 10:
                console.print(f"  ... and {len(services) - 10} more")
    
    # Important paths
    if "paths" in sys_info:
        paths = sys_info["paths"]
        console.print(f"\n[bold]📁 Important Paths:[/]")
        
        for path_name, path_info in paths.items():
            if path_info.get("exists"):
                size = path_info.get("size", "0")
                console.print(f"  {path_name}: {path_info['path']} ({size})")
    
    # Network
    if "network" in sys_info:
        network = sys_info["network"]
        console.print(f"\n[bold]🌐 Network Configuration:[/]")
        console.print(f"  Hostname: {network.get('hostname', 'Unknown')}")
        console.print(f"  Domain: {network.get('domain', 'Unknown')}")
        
        if network.get("interfaces"):
            for iface in network["interfaces"]:
                console.print(f"  {iface['name']}: {iface.get('ip', 'No IP')}")


def build_config_from_detection(sys_info: Dict, choices: List[str], path: Path) -> Dict:
    """Build CloneBox configuration from detection results."""
    config = {
        "version": "1",
        "generated": sys_info.get("system", {}).get("timestamp", ""),
        "vm": {
            "name": f"clonebox-{path.name}",
            "ram_mb": 4096,
            "vcpus": 4,
            "disk_size_gb": 20,
            "gui": True,
            "network_mode": "auto",
            "username": "ubuntu",
            "password": "ubuntu",
        },
        "paths": {},
        "packages": [],
        "snap_packages": [],
        "services": [],
        "post_commands": [],
        "copy_paths": {},
    }
    
    # Include packages
    if "packages" in choices and "packages" in sys_info:
        if sys_info["packages"].get("apt"):
            # Filter out system packages
            user_packages = [
                pkg for pkg in sys_info["packages"]["apt"]
                if not any(pkg.startswith(prefix) for prefix in ["linux-", "libc", "libg", "libx"])
            ]
            config["packages"] = user_packages[:100]  # Limit to 100 packages
        
        if sys_info["packages"].get("snap"):
            config["snap_packages"] = sys_info["packages"]["snap"]
    
    # Include services
    if "services" in choices and "services" in sys_info:
        # Only include user-enabled services
        user_services = [
            svc.name for svc in sys_info["services"]
            if svc.enabled and not svc.name.startswith(("systemd-", "dbus-", "networkd-"))
        ]
        config["services"] = user_services
    
    # Include paths
    if "home" in choices and "paths" in sys_info:
        home_path = Path.home()
        config["paths"][str(home_path)] = f"/home/{config['vm']['username']}"
        
        # Include important config directories
        if "config" in choices:
            config_paths = [
                ".config",
                ".local/share",
                ".cache",
                ".ssh",
                ".gnupg",
                ".mozilla",
                ".thunderbird",
            ]
            
            for config_path in config_paths:
                full_path = home_path / config_path
                if full_path.exists():
                    config["copy_paths"][str(full_path)] = f"/home/{config['vm']['username']}/{config_path}"
    
    # Include development tools
    if "devtools" in choices:
        dev_packages = ["git", "vim", "nano", "curl", "wget", "build-essential"]
        config["packages"].extend(dev_packages)
        config["packages"] = list(set(config["packages"]))  # Deduplicate
    
    # Post-commands for setup
    config["post_commands"] = [
        f"usermod -s /bin/bash {config['vm']['username']}",
        "echo 'export TERM=xterm-256color' >> /etc/bash.bashrc",
    ]
    
    return config


def cmd_test(args):
    """Run CloneBox self-test."""
    console.print("[bold cyan]🧪 Running CloneBox self-test...[/]\n")
    
    tests = []
    
    # Test libvirt connection
    console.print("Testing libvirt connection...")
    try:
        import libvirt
        conn = libvirt.open("qemu:///system")
        if conn:
            console.print("  ✅ System connection OK")
            conn.close()
        
        conn = libvirt.open("qemu:///session")
        if conn:
            console.print("  ✅ Session connection OK")
            conn.close()
    except Exception as e:
        console.print(f"  ❌ Libvirt error: {e}")
        tests.append(("libvirt", False, str(e)))
    
    # Test base image
    console.print("\nTesting base image...")
    base_image = args.base_image or "/var/lib/libvirt/images/ubuntu-22.04.qcow2"
    if Path(base_image).exists():
        console.print(f"  ✅ Base image found: {base_image}")
    else:
        console.print(f"  ❌ Base image not found: {base_image}")
        console.print("  Download with: clonebox download-base-image")
    
    # Test disk space
    console.print("\nChecking disk space...")
    import shutil
    total, used, free = shutil.disk_usage("/var/lib/libvirt")
    free_gb = free // (1024**3)
    
    if free_gb >= 20:
        console.print(f"  ✅ Available disk space: {free_gb} GB")
    else:
        console.print(f"  ⚠️  Low disk space: {free_gb} GB available")
    
    # Test network
    console.print("\nTesting network...")
    import socket
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        console.print("  ✅ Internet connectivity OK")
    except Exception as e:
        console.print(f"  ❌ Network error: {e}")
    
    # Test dependencies
    console.print("\nChecking dependencies...")
    dependencies = [
        ("libvirt", "libvirt"),
        ("qemu", "qemu-system-x86"),
        ("virt-install", "virtinst"),
        ("cloud-image-utils", "cloud-image-utils"),
    ]
    
    for dep_name, package in dependencies:
        try:
            __import__(dep_name)
            console.print(f"  ✅ {dep_name} module OK")
        except ImportError:
            # Check if package is installed
            import subprocess
            result = subprocess.run(["dpkg", "-l", package], capture_output=True)
            if result.returncode == 0:
                console.print(f"  ✅ {package} installed")
            else:
                console.print(f"  ❌ {package} not installed")
    
    console.print("\n[bold green]✅ Self-test completed[/]")


def cmd_dashboard(args):
    """Launch CloneBox dashboard."""
    import webbrowser
    from clonebox.dashboard import create_dashboard
    
    console.print("[cyan]Starting CloneBox dashboard...[/]")
    
    if args.browser:
        # Open in browser
        webbrowser.open(f"http://localhost:{args.port}")
    
    # Start dashboard server
    create_dashboard(host=args.host, port=args.port, debug=args.debug)


def cmd_status(args):
    """Show CloneBox system status."""
    from rich.table import Table
    from rich.panel import Panel
    
    # System status
    console.print("[bold]CloneBox System Status[/]\n")
    
    # Version
    from clonebox import __version__
    console.print(f"Version: {__version__}")
    
    # VM count
    from clonebox.cloner import SelectiveVMCloner
    cloner = SelectiveVMCloner()
    vms = cloner.list_vms()
    
    table = Table(title="Virtual Machines")
    table.add_column("Name", style="cyan")
    table.add_column("State", style="green")
    table.add_column("IP", style="yellow")
    
    for vm in vms:
        state_style = "green" if vm["state"] == "running" else "red"
        table.add_row(
            vm["name"],
            f"[{state_style}]{vm['state']}[/{state_style}]",
            vm.get("ip", "-"),
        )
    
    console.print(table)
    
    # Container count
    from clonebox.container import ContainerCloner
    container_cloner = ContainerCloner()
    containers = container_cloner.list_containers()
    
    if containers:
        table = Table(title="Containers")
        table.add_column("Name", style="cyan")
        table.add_column("Status", style="green")
        
        for container in containers:
            table.add_row(container["name"], container["status"])
        
        console.print(table)
    
    # Disk usage
    total, used, free = shutil.disk_usage("/var/lib/libvirt")
    console.print(f"\nDisk Usage: {used // (1024**3)} GB used, {free // (1024**3)} GB free")


def cmd_set_password(args):
    """Set VM password."""
    import subprocess
    
    vm_name = resolve_vm_name(args.name)
    user_session = getattr(args, "user", False)
    username = getattr(args, "username", "ubuntu")
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
    # Generate password if not provided
    password = getattr(args, "password", None)
    if password:
        pass  # Use provided password
    else:
        password = generate_password(12)
        console.print(f"[cyan]Generated password: {password}[/]")
    
    # Call set-vm-password script
    script_path = Path(__file__).parent.parent.parent.parent / "scripts" / "set-vm-password.sh"
    cmd = [
        str(script_path),
        vm_name,
        password,
        "true" if user_session else "false",
        username,
    ]
    subprocess.run(cmd, check=True)


def generate_password(length=12):
    """Generate a random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def run_vm_diagnostics(
    vm_name: str,
    conn_uri: str,
    config_file: Optional[Path] = None,
    verbose: bool = False,
    json_output: bool = False,
):
    """Run comprehensive VM diagnostics."""
    import json
    import subprocess
    
    diagnostics = {
        "vm_name": vm_name,
        "timestamp": datetime.now().isoformat(),
        "checks": {},
        "summary": {"passed": 0, "failed": 0, "warnings": 0},
    }
    
    console.print(f"\n[bold cyan]🔍 Diagnosing VM: {vm_name}[/]\n")
    
    # Check 1: VM exists
    console.print("[dim]Checking VM existence...[/]")
    try:
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "dominfo", vm_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            diagnostics["checks"]["vm_exists"] = {"status": "PASS", "message": "VM found"}
            diagnostics["summary"]["passed"] += 1
            console.print("[green]✅ VM exists[/]")
            
            # Parse VM info
            for line in result.stdout.split('\n'):
                if "State:" in line:
                    state = line.split(':')[1].strip()
                    diagnostics["vm_state"] = state
        else:
            diagnostics["checks"]["vm_exists"] = {"status": "FAIL", "message": "VM not found"}
            diagnostics["summary"]["failed"] += 1
            console.print("[red]❌ VM not found[/]")
            return
    except subprocess.TimeoutExpired:
        diagnostics["checks"]["vm_exists"] = {"status": "FAIL", "message": "Timeout checking VM"}
        diagnostics["summary"]["failed"] += 1
        console.print("[red]❌ Timeout checking VM[/]")
        return
    except Exception as e:
        diagnostics["checks"]["vm_exists"] = {"status": "FAIL", "message": str(e)}
        diagnostics["summary"]["failed"] += 1
        console.print(f"[red]❌ Error checking VM: {e}[/]")
        return
    
    # Check 2: VM is running
    console.print("\n[dim]Checking VM state...[/]")
    if diagnostics.get("vm_state") == "running":
        diagnostics["checks"]["vm_running"] = {"status": "PASS", "message": "VM is running"}
        diagnostics["summary"]["passed"] += 1
        console.print("[green]✅ VM is running[/]")
        
        # Check 3: QEMU Guest Agent
        console.print("\n[dim]Checking QEMU Guest Agent...[/]")
        try:
            result = subprocess.run(
                ["virsh", "--connect", conn_uri, "qemu-agent-command", vm_name, '{"execute": "guest-ping"}'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                diagnostics["checks"]["guest_agent"] = {"status": "PASS", "message": "QEMU Guest Agent responding"}
                diagnostics["summary"]["passed"] += 1
                console.print("[green]✅ QEMU Guest Agent is responding[/]")
                
                # Get IP addresses
                try:
                    result = subprocess.run(
                        ["virsh", "--connect", conn_uri, "domifaddr", vm_name],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        ips = []
                        for line in result.stdout.split('\n'):
                            if '192.168.' in line or '10.0.' in line:
                                ip = line.split()[-1].rstrip('/')
                                ips.append(ip)
                        if ips:
                            diagnostics["ip_addresses"] = ips
                            console.print(f"[green]✅ IP addresses: {', '.join(ips)}[/]")
                except:
                    pass
            else:
                diagnostics["checks"]["guest_agent"] = {"status": "FAIL", "message": "QEMU Guest Agent not responding"}
                diagnostics["summary"]["failed"] += 1
                console.print("[red]❌ QEMU Guest Agent not responding[/]")
        except subprocess.TimeoutExpired:
            diagnostics["checks"]["guest_agent"] = {"status": "FAIL", "message": "QEMU Guest Agent timeout"}
            diagnostics["summary"]["failed"] += 1
            console.print("[red]❌ QEMU Guest Agent timeout[/]")
        except Exception as e:
            diagnostics["checks"]["guest_agent"] = {"status": "FAIL", "message": str(e)}
            diagnostics["summary"]["failed"] += 1
            console.print(f"[red]❌ Error checking QEMU Guest Agent: {e}[/]")
    else:
        diagnostics["checks"]["vm_running"] = {"status": "FAIL", "message": f"VM is not running (state: {diagnostics.get('vm_state')})"}
        diagnostics["summary"]["failed"] += 1
        console.print(f"[red]❌ VM is not running (state: {diagnostics.get('vm_state')})[/]")
    
    # Check 4: Config file
    if config_file and config_file.exists():
        console.print("\n[dim]Checking configuration file...[/]")
        try:
            config = load_clonebox_config(config_file)
            diagnostics["checks"]["config_file"] = {"status": "PASS", "message": "Config file loaded"}
            diagnostics["summary"]["passed"] += 1
            console.print("[green]✅ Configuration file is valid[/]")
            
            # Show some config details
            if verbose:
                vm_config = config.get("vm", {})
                console.print(f"[dim]  RAM: {vm_config.get('ram_mb', 'N/A')} MB[/]")
                console.print(f"[dim]  vCPUs: {vm_config.get('vcpus', 'N/A')}[/]")
                console.print(f"[dim]  Disk: {vm_config.get('disk_size_gb', 'N/A')} GB[/]")
        except Exception as e:
            diagnostics["checks"]["config_file"] = {"status": "FAIL", "message": str(e)}
            diagnostics["summary"]["failed"] += 1
            console.print(f"[red]❌ Error loading config: {e}[/]")
    
    # Summary
    console.print(f"\n[bold]Summary:[/]")
    console.print(f"  Passed: {diagnostics['summary']['passed']}")
    console.print(f"  Failed: {diagnostics['summary']['failed']}")
    console.print(f"  Warnings: {diagnostics['summary']['warnings']}")
    
    if json_output:
        console.print("\n" + json.dumps(diagnostics, indent=2))


def cmd_diagnose(args):
    """Run detailed VM diagnostics (standalone)."""
    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = _paths.conn_uri(user_session)

    try:
        vm_name, config_file = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return

    run_vm_diagnostics(
        vm_name,
        conn_uri,
        config_file,
        verbose=getattr(args, "verbose", False),
        json_output=getattr(args, "json", False),
    )


def cmd_status(args):
    """Check VM installation status and health from workstation."""
    import subprocess

    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = _paths.conn_uri(user_session)

    try:
        vm_name, config_file = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return

    run_vm_diagnostics(
        vm_name,
        conn_uri,
        config_file,
        verbose=getattr(args, "verbose", False),
        json_output=getattr(args, "json", False),
    )

    # Show useful commands
    console.print("\n[bold]📋 Useful commands:[/]")
    console.print(f"  [cyan]virt-viewer --connect {conn_uri} {vm_name}[/]  # Open GUI")
    console.print(f"  [cyan]virsh --connect {conn_uri} console {vm_name}[/]  # Console access")
    console.print("  [dim]Inside VM:[/]")
    console.print("    [cyan]cat /var/log/clonebox-health.log[/]  # Full health report")
    console.print("    [cyan]sudo cloud-init status[/]  # Cloud-init status")
    console.print("    [cyan]clonebox-health[/]  # Re-run health check")
    console.print("  [dim]On host:[/]")
    console.print(
        f"    [cyan]virsh --connect {conn_uri} dominfo {vm_name}[/]  # VM info"
    )
    console.print(
        f"    [cyan]virsh --connect {conn_uri} domifaddr {vm_name}[/]  # IP addresses"
    )


def cmd_watch(args):
    """Watch VM status in real-time."""
    import subprocess
    import time

    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = _paths.conn_uri(user_session)

    try:
        vm_name, _ = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return

    console.print(f"[bold cyan]👁️ Watching VM: {vm_name}[/]")
    console.print("[dim]Press Ctrl+C to stop[/]\n")

    try:
        while True:
            result = subprocess.run(
                ["virsh", "--connect", conn_uri, "dominfo", vm_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                state = "unknown"
                cpu_time = ""
                for line in result.stdout.split('\n'):
                    if 'State:' in line:
                        state = line.split(':')[1].strip()
                    if 'CPU time:' in line:
                        cpu_time = line.split(':')[1].strip()

                status_color = "green" if state == "running" else "yellow" if state == "paused" else "red"
                console.print(f"\r[{status_color}]{state:12}[white] | CPU: {cpu_time}[/]", end="")
            else:
                console.print(f"\r[red]VM not found[/]", end="")
            time.sleep(2)
    except KeyboardInterrupt:
        console.print("\n\n[dim]Stopped watching[/]")
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/]")


def cmd_logs(args):
    """Show VM logs (serial log or console output)."""
    import subprocess

    name = args.name
    user_session = getattr(args, "user", False)
    show_all = getattr(args, "all", False)
    conn_uri = _paths.conn_uri(user_session)

    try:
        vm_name, _ = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return

    # Try serial log first
    serial_log = _paths.serial_log_path(vm_name, user_session)

    console.print(f"[bold cyan]📜 Logs for VM: {vm_name}[/]\n")

    if serial_log.exists() and serial_log.stat().st_size > 0:
        console.print("[dim]Reading serial log...[/]\n")
        if show_all:
            subprocess.run(["cat", str(serial_log)])
        else:
            subprocess.run(["tail", "-50", str(serial_log)])
    else:
        console.print("[yellow]Serial log not available, using console...[/]")
        console.print("[dim]Press Ctrl+] to exit console[/]\n")
        try:
            subprocess.run(
                ["virsh", "--connect", conn_uri, "console", vm_name],
                timeout=30 if not show_all else None,
            )
        except subprocess.TimeoutExpired:
            console.print("\n[dim]Log view timeout[/]")


def cmd_repair(args):
    """Attempt to repair common VM issues."""
    import subprocess

    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = _paths.conn_uri(user_session)

    try:
        vm_name, config_file = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return

    console.print(f"[bold cyan]🔧 Repairing VM: {vm_name}[/]\n")

    repairs_made = []

    # Repair 1: Check if VM exists
    result = subprocess.run(
        ["virsh", "--connect", conn_uri, "dominfo", vm_name],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        console.print("[yellow]VM not found. Attempting to redefine from config...[/]")
        if config_file and config_file.exists():
            # Try to redefine VM
            console.print("[dim]Looking for VM XML...[/]")
            repairs_made.append("VM was missing - manual recreation needed")
        else:
            console.print("[red]❌ Cannot repair: no config file found[/]")
            return
    else:
        # Repair 2: Check if running
        state = "unknown"
        for line in result.stdout.split('\n'):
            if 'State:' in line:
                state = line.split(':')[1].strip()

        if state != "running":
            console.print(f"[yellow]VM is {state}, attempting to start...[/]")
            subprocess.run(
                ["virsh", "--connect", conn_uri, "start", vm_name],
                capture_output=True,
            )
            repairs_made.append(f"Started VM (was {state})")

    # Repair 3: Check SSH port forwarding
    ssh_port = _paths.resolve_ssh_port(vm_name, user_session)
    ssh_pf = _paths.ssh_port_file(vm_name, user_session)
    ssh_key = _paths.ssh_key_path(vm_name, user_session)

    if ssh_pf.exists():
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True,
            text=True,
        )
        if f":{ssh_port}" not in result.stdout:
            console.print(f"[yellow]SSH port {ssh_port} not listening[/]")
            repairs_made.append(f"SSH port {ssh_port} not listening - may need VM restart")

    # Repair 4: Check GDM/GUI
    if ssh_key:
        console.print("[dim]Checking GUI status via SSH...[/]")
        gdm_out = _ssh_exec(
            port=ssh_port, key=ssh_key,
            command="systemctl is-active gdm3 gdm 2>/dev/null | head -1",
            connect_timeout=3, timeout=10,
        )

        if not gdm_out or "active" not in gdm_out:
            console.print("[yellow]Display Manager not running, attempting to start...[/]")
            _ssh_exec(
                port=ssh_port, key=ssh_key,
                command="sudo systemctl start gdm3 2>/dev/null || sudo systemctl start gdm",
                connect_timeout=3, timeout=10,
            )
            repairs_made.append("Started Display Manager (GDM)")
        else:
            console.print("[green]✅ Display Manager is running[/]")

    # Summary
    console.print(f"\n[bold]🔧 Repair Summary:[/]")
    if repairs_made:
        for repair in repairs_made:
            console.print(f"  [green]✓[/] {repair}")
    else:
        console.print("  [dim]No repairs needed - VM looks healthy![/]")

    console.print(f"\n[dim]Run 'clonebox status {vm_name}' to verify[/]")
