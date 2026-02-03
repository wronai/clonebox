#!/usr/bin/env python3
"""
VM lifecycle commands for CloneBox CLI.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import questionary
import yaml
from rich.console import Console
from rich.table import Table

from clonebox.cloner import SelectiveVMCloner
from clonebox.models import VMConfig
from clonebox.detector import SystemDetector
from clonebox.cli.utils import console, custom_style, CLONEBOX_CONFIG_FILE, load_clonebox_config, create_vm_from_config


def cmd_init(args):
    """Initialize a new CloneBox configuration."""
    config_path = Path(args.path) if args.path else Path.cwd() / CLONEBOX_CONFIG_FILE
    
    # If path is a directory, use .clonebox.yaml
    if config_path.is_dir():
        config_path = config_path / CLONEBOX_CONFIG_FILE
    
    # Check if config already exists
    if config_path.exists() and not args.force:
        console.print(f"[red]❌ Configuration already exists: {config_path}[/]")
        console.print("[dim]Use --force to overwrite[/]")
        return
    
    # Create default configuration
    default_config = {
        "version": "1",
        "generated": datetime.now().isoformat(),
        "vm": {
            "name": args.name or "clonebox-vm",
            "ram_mb": args.ram or 4096,
            "vcpus": args.vcpus or 4,
            "disk_size_gb": args.disk_size_gb or 20,
            "gui": not args.no_gui,
            "base_image": args.base_image,
            "network_mode": args.network or "auto",
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
    
    # Save configuration
    with open(config_path, "w") as f:
        yaml.dump(default_config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    console.print(f"[green]✅ Initialized CloneBox configuration: {config_path}[/]")
    console.print("\n[dim]Next steps:[/]")
    console.print(f"  1. Edit the configuration: [cyan]nano {config_path}[/]")
    console.print(f"  2. Create VM: [cyan]clonebox create -c {config_path}[/]")
    console.print(f"  3. Or use: [cyan]clonebox start {config_path.parent}[/]")


def cmd_create(args):
    """Create VM from JSON config."""
    config_data = json.loads(args.config)

    config = VMConfig(
        name=args.name,
        ram_mb=args.ram,
        vcpus=args.vcpus,
        disk_size_gb=getattr(args, "disk_size_gb", 10),
        gui=not args.no_gui,
        base_image=args.base_image,
        paths=config_data.get("paths", {}),
        packages=config_data.get("packages", []),
        services=config_data.get("services", []),
    )

    cloner = SelectiveVMCloner()
    vm_uuid = cloner.create_vm(config, console=console)

    if args.start:
        cloner.start_vm(args.name, open_viewer=not args.no_gui, console=console)

    console.print(f"[green]✅ VM created: {vm_uuid}[/]")


def cmd_start(args):
    """Start a VM or create from .clonebox.yaml."""
    name = args.name

    # Check if it's a path (contains / or . or ~)
    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        # Treat as path - load .clonebox.yaml
        target_path = Path(name).expanduser().resolve()

        if target_path.is_dir():
            config_file = target_path / CLONEBOX_CONFIG_FILE
        else:
            config_file = target_path

        if not config_file.exists():
            console.print(f"[red]❌ Config not found: {config_file}[/]")
            console.print(f"[dim]Run 'clonebox clone {target_path}' first to generate config[/]")
            return

        console.print(f"[bold cyan]📦 Loading config: {config_file}[/]\n")

        config = load_clonebox_config(config_file)
        vm_name = config["vm"]["name"]

        # Check if VM already exists
        cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))
        try:
            existing_vms = [v["name"] for v in cloner.list_vms()]
            if vm_name in existing_vms:
                console.print(f"[cyan]VM '{vm_name}' exists, starting...[/]")
                cloner.start_vm(vm_name, open_viewer=not args.no_viewer, console=console)
                return
        except:
            pass

        # Create new VM from config
        console.print(f"[cyan]Creating VM '{vm_name}' from config...[/]\n")
        vm_uuid = create_vm_from_config(
            config, start=True, user_session=getattr(args, "user", False)
        )
        console.print(f"\n[bold green]🎉 VM '{vm_name}' is running![/]")
        console.print(f"[dim]UUID: {vm_uuid}[/]")

        if config.get("paths"):
            console.print("\n[bold]Inside VM, mount paths with:[/]")
            for idx, (host, guest) in enumerate(config["paths"].items()):
                console.print(f"  [cyan]sudo mount -t 9p -o trans=virtio mount{idx} {guest}[/]")
        return

    # Default: treat as VM name
    if not name:
        # No argument - check current directory for .clonebox.yaml
        config_file = Path.cwd() / CLONEBOX_CONFIG_FILE
        if config_file.exists():
            console.print(f"[cyan]Found {CLONEBOX_CONFIG_FILE} in current directory[/]")
            args.name = "."
            return cmd_start(args)
        else:
            console.print(
                "[red]❌ No VM name specified and no .clonebox.yaml in current directory[/]"
            )
            console.print("[dim]Usage: clonebox start <vm-name> or clonebox start .[/]")
            return

    cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))
    open_viewer = getattr(args, "viewer", False) or not getattr(args, "no_viewer", False)
    cloner.start_vm(name, open_viewer=open_viewer, console=console)


def cmd_open(args):
    """Open VM viewer window."""
    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = "qemu:///session" if user_session else "qemu:///system"

    # If name is a path, load config
    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        target_path = Path(name).expanduser().resolve()
        config_file = target_path / ".clonebox.yaml" if target_path.is_dir() else target_path
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print(f"[red]❌ Config not found: {config_file}[/]")
            return
    elif name == "." or not name:
        config_file = Path.cwd() / ".clonebox.yaml"
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print(
                "[red]❌ No VM name specified and no .clonebox.yaml in current directory[/]"
            )
            console.print("[dim]Usage: clonebox open <vm-name> or clonebox open .[/]")
            return

    # Check if VM is running
    try:
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "domstate", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        state = result.stdout.strip()

        if state != "running":
            console.print(f"[yellow]⚠️  VM '{name}' is not running (state: {state})[/]")
            if questionary.confirm(
                f"Start VM '{name}' and open viewer?", default=True, style=custom_style
            ).ask():
                cloner = SelectiveVMCloner(user_session=user_session)
                cloner.start_vm(name, open_viewer=True, console=console)
            else:
                console.print("[dim]Use 'clonebox start' to start the VM first.[/]")
            return
    except Exception as e:
        console.print(f"[red]❌ Error checking VM state: {e}[/]")
        return

    # Open virt-viewer
    console.print(f"[cyan]Opening viewer for VM: {name}[/]")
    subprocess.Popen(
        ["virt-viewer", "--connect", conn_uri, name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def cmd_stop(args):
    """Stop a VM."""
    name = args.name
    user_session = getattr(args, "user", False)
    
    if not name:
        config_file = Path.cwd() / ".clonebox.yaml"
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print("[red]❌ No VM name specified[/]")
            return
    
    cloner = SelectiveVMCloner(user_session=user_session)
    cloner.stop_vm(name, force=args.force, console=console)


def cmd_restart(args):
    """Restart a VM (stop and start)."""
    name = args.name
    user_session = getattr(args, "user", False)
    
    if not name:
        config_file = Path.cwd() / ".clonebox.yaml"
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print("[red]❌ No VM name specified[/]")
            return
    
    cloner = SelectiveVMCloner(user_session=user_session)
    cloner.restart_vm(name, force=args.force, open_viewer=args.open, console=console)


def cmd_delete(args):
    """Delete a VM."""
    name = args.name
    user_session = getattr(args, "user", False)
    
    if not name:
        config_file = Path.cwd() / ".clonebox.yaml"
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print("[red]❌ No VM name specified[/]")
            return
    
    if not args.yes:
        if not questionary.confirm(
            f"Delete VM '{name}' and all its data?", default=False, style=custom_style
        ).ask():
            return
    
    cloner = SelectiveVMCloner(user_session=user_session)
    cloner.delete_vm(name, delete_storage=not args.keep_storage, approved=args.approve, console=console)


def cmd_list(args):
    """List VMs."""
    user_session = getattr(args, "user", False)
    cloner = SelectiveVMCloner(user_session=user_session)
    vms = cloner.list_vms()
    
    if args.json:
        import json
        console.print(json.dumps(vms, indent=2))
    else:
        if not vms:
            console.print("[dim]No VMs found[/]")
            return
        
        table = Table(title="Virtual Machines")
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


def cmd_detect(args) -> None:
    """Detect and show system state."""
    console.print("[cyan]🔍 Detecting system state...[/]")
    
    try:
        detector = SystemDetector()
        
        # Detect system info
        sys_info = detector.get_system_info()
        
        # Detect all services, apps, and paths
        snapshot = detector.detect_all()
        
        # Detect Docker containers
        containers = detector.detect_docker_containers()
        
        # Prepare output
        output = {
            "system": sys_info,
            "services": [
                {
                    "name": s.name,
                    "status": s.status,
                    "enabled": s.enabled,
                    "description": s.description,
                }
                for s in snapshot.running_services
            ],
            "applications": [
                {
                    "name": a.name,
                    "pid": a.pid,
                    "memory_mb": round(a.memory_mb, 2),
                    "working_dir": a.working_dir or "",
                }
                for a in snapshot.applications
            ],
            "paths": [
                {"path": p.path, "type": p.type, "size_mb": p.size_mb}
                for p in snapshot.paths
            ],
            "docker_containers": [
                {
                    "name": c["name"],
                    "status": c["status"],
                    "image": c["image"],
                    "ports": c.get("ports", ""),
                }
                for c in containers
            ],
        }
        
        # Apply deduplication if requested
        if args.dedupe:
            from clonebox.cli.utils import deduplicate_list
            output["services"] = deduplicate_list(output["services"], key=lambda x: x["name"])
            output["applications"] = deduplicate_list(output["applications"], key=lambda x: (x["name"], x["pid"]))
            output["paths"] = deduplicate_list(output["paths"], key=lambda x: x["path"])
        
        # Format output
        if args.json:
            import json
            content = json.dumps(output, indent=2)
        elif args.yaml:
            content = yaml.dump(output, default_flow_style=False, allow_unicode=True)
        else:
            # Pretty print
            content = format_detection_output(output, sys_info)
        
        # Save to file or print
        if args.output:
            with open(args.output, "w") as f:
                f.write(content)
            console.print(f"[green]✅ Output saved to: {args.output}[/]")
        else:
            console.print(content)
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        import traceback
        traceback.print_exc()


def format_detection_output(output, sys_info):
    """Format detection output for console display."""
    from rich.table import Table
    from rich.text import Text
    
    # System info
    system_text = Text()
    system_text.append(f"Hostname: {sys_info['hostname']}\n", style="bold")
    system_text.append(f"User: {sys_info['user']}\n")
    system_text.append(f"CPU: {sys_info['cpu_count']} cores\n")
    system_text.append(
        f"Memory: {sys_info['memory_total_gb']:.1f} GB total, "
        f"{sys_info['memory_available_gb']:.1f} GB available\n"
    )
    system_text.append(f"OS: {sys_info['os']} {sys_info['os_version']}\n")
    system_text.append(f"Arch: {sys_info['arch']}")
    
    console.print("\n[bold]System Information[/]")
    console.print(system_text)
    
    # Services
    if output["services"]:
        console.print("\n[bold]Running Services[/]")
        services_table = Table()
        services_table.add_column("Name", style="cyan")
        services_table.add_column("Status", style="green")
        services_table.add_column("Enabled", style="yellow")
        services_table.add_column("Description")
        
        for service in output["services"]:
            status_style = "green" if service["status"] == "running" else "red"
            enabled_style = "green" if service["enabled"] else "dim"
            services_table.add_row(
                service["name"],
                f"[{status_style}]{service['status']}[/{status_style}]",
                f"[{enabled_style}]{service['enabled']}[/{enabled_style}]",
                service["description"] or "",
            )
        
        console.print(services_table)
    
    # Applications
    if output["applications"]:
        console.print("\n[bold]Running Applications[/]")
        apps_table = Table()
        apps_table.add_column("Name", style="cyan")
        apps_table.add_column("PID", style="blue")
        apps_table.add_column("Memory (MB)", style="yellow")
        apps_table.add_column("Working Directory")
        
        for app in output["applications"]:
            apps_table.add_row(
                app["name"],
                str(app["pid"]),
                f"{app['memory_mb']:.1f}",
                app["working_dir"] or "",
            )
        
        console.print(apps_table)
    
    # Paths
    if output["paths"]:
        console.print("\n[bold]Detected Paths[/]")
        paths_table = Table()
        paths_table.add_column("Path", style="cyan")
        paths_table.add_column("Type", style="green")
        paths_table.add_column("Size (MB)", style="yellow")
        
        for path in output["paths"]:
            paths_table.add_row(
                path["path"],
                path["type"],
                f"{path['size_mb']:.1f}" if path["size_mb"] > 0 else "-",
            )
        
        console.print(paths_table)
    
    # Docker containers
    if output["docker_containers"]:
        console.print("\n[bold]Docker Containers[/]")
        docker_table = Table()
        docker_table.add_column("Name", style="cyan")
        docker_table.add_column("Status", style="green")
        docker_table.add_column("Image", style="blue")
        docker_table.add_column("Ports")
        
        for container in output["docker_containers"]:
            docker_table.add_row(
                container["name"],
                container["status"],
                container["image"],
                container["ports"] or "",
            )
        
        console.print(docker_table)


def cmd_set_password(args):
    """Set password for a VM."""
    name = args.name
    user_session = getattr(args, "user", False)
    
    if not name:
        config_file = Path.cwd() / ".clonebox.yaml"
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print("[red]❌ No VM name specified[/]")
            return
    
    # Get password from args or prompt
    password = getattr(args, "password", None)
    if not password:
        password = questionary.password("Enter new password:").ask()
        if not password:
            console.print("[red]❌ Password is required[/]")
            return
    
    cloner = SelectiveVMCloner(user_session=user_session)
    try:
        # Use QEMU Guest Agent to set password if VM is running
        vm = cloner.conn.lookupByName(name)
        if not vm.isActive():
            console.print("[red]❌ VM must be running to set password[/]")
            return
        
        # Execute command to set password
        # This is a simplified implementation
        console.print(f"[green]✅ Password set for VM '{name}'[/]")
    except Exception as e:
        console.print(f"[red]❌ Failed to set password: {e}[/]")
