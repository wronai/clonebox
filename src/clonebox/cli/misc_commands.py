#!/usr/bin/env python3
"""
Miscellaneous commands for CloneBox CLI.
"""

import json
import secrets
import string
from pathlib import Path
from typing import Dict, List

import questionary

from clonebox.detector import SystemDetector
from clonebox.cli.utils import console, custom_style, load_clonebox_config, CLONEBOX_CONFIG_FILE


def cmd_clone(args):
    """Clone current environment to VM."""
    from clonebox.cloner import SelectiveVMCloner
    
    path = Path(args.path).expanduser().resolve()
    user_session = getattr(args, "user", False)
    
    # Detect system configuration
    console.print("[bold cyan]🔍 Detecting system configuration...[/]")
    detector = SystemDetector()
    sys_info = detector.detect_all()
    
    # Show detected configuration
    format_detection_output(sys_info, console)
    
    # Ask what to include
    if args.interactive:
        choices = questionary.checkbox(
            "Select what to include in the VM:",
            choices=[
                questionary.Choice("Installed packages", value="packages", checked=True),
                questionary.Choice("Snap packages", value="snaps", checked=True),
                questionary.Choice("Running services", value="services", checked=True),
                questionary.Choice("User home directory", value="home", checked=True),
                questionary.Choice("Configuration files", value="config", checked=True),
                questionary.Choice("Development tools", value="devtools", checked=True),
            ],
            style=custom_style,
        ).ask()
        
        if not choices:
            console.print("[yellow]No selections made[/]")
            return
        
        # Build configuration from choices
        config = build_config_from_detection(sys_info, choices, path)
    else:
        # Use all detected
        config = build_config_from_detection(sys_info, ["packages", "snaps", "services", "home", "config", "devtools"], path)
    
    # Ask for VM settings
    if args.interactive:
        config["vm"]["name"] = questionary.text(
            "VM name:",
            default=config["vm"]["name"],
            style=custom_style,
        ).ask()
        
        config["vm"]["ram_mb"] = questionary.text(
            "RAM (MB):",
            default=str(config["vm"]["ram_mb"]),
            validate=lambda x: x.isdigit(),
            style=custom_style,
        ).ask()
        
        config["vm"]["ram_mb"] = int(config["vm"]["ram_mb"])
        
        config["vm"]["vcpus"] = questionary.text(
            "vCPUs:",
            default=str(config["vm"]["vcpus"]),
            validate=lambda x: x.isdigit(),
            style=custom_style,
        ).ask()
        
        config["vm"]["vcpus"] = int(config["vm"]["vcpus"])
    
    # Save configuration
    config_file = path / ".clonebox.yaml"
    with open(config_file, "w") as f:
        import yaml
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    console.print(f"\n[green]✅ Configuration saved to: {config_file}[/]")
    
    # Ask if user wants to create VM now
    if args.interactive:
        if questionary.confirm(
            "Create VM now?",
            default=True,
            style=custom_style,
        ).ask():
            from clonebox.cli.utils import create_vm_from_config
            console.print(f"\n[cyan]Creating VM '{config['vm']['name']}'...[/]")
            vm_uuid = create_vm_from_config(
                config, start=True, user_session=user_session, approved=args.approve
            )
            console.print(f"\n[bold green]🎉 VM created and started![/]")
            console.print(f"[dim]UUID: {vm_uuid}[/]")


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
    else:
        format_detection_output(sys_info, console)
    
    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        if args.json:
            with open(output_path, "w") as f:
                json.dump(sys_info, f, indent=2, default=str)
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
            svc["name"] for svc in sys_info["services"]
            if svc.get("enabled") and not svc["name"].startswith(("systemd-", "dbus-", "networkd-"))
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
    
    vm_name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = "qemu:///session" if user_session else "qemu:///system"
    
    # Resolve VM name from config if needed
    if not vm_name or vm_name == ".":
        config_file = Path.cwd() / CLONEBOX_CONFIG_FILE
        if config_file.exists():
            config = load_clonebox_config(config_file)
            vm_name = config["vm"]["name"]
        else:
            console.print("[red]❌ No VM name specified[/]")
            return
    
    # Generate password if not provided
    if args.password:
        password = args.password
    else:
        password = generate_password(12)
        console.print(f"[cyan]Generated password: {password}[/]")
    
    # Set password via QEMU Guest Agent
    from clonebox.cli.utils import _qga_exec
    
    username = args.username or "ubuntu"
    cmd = f'echo "{username}:{password}" | sudo chpasswd'
    
    if _qga_exec(vm_name, conn_uri, cmd):
        console.print("[green]✅ Password updated successfully[/]")
    else:
        console.print("[red]❌ Failed to update password[/]")
        console.print("[dim]Make sure QEMU Guest Agent is running in the VM[/]")


def generate_password(length=12):
    """Generate a random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))
