#!/usr/bin/env python3
"""
CloneBox CLI - Interactive command-line interface for creating VMs.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import questionary
import yaml
from questionary import Style
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from clonebox import __version__
from clonebox.cloner import SelectiveVMCloner, VMConfig
from clonebox.detector import SystemDetector

# Custom questionary style
custom_style = Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:green"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
        ("separator", "fg:gray"),
        ("instruction", "fg:gray italic"),
    ]
)

console = Console()


def print_banner():
    """Print the CloneBox banner."""
    banner = """
╔═══════════════════════════════════════════════════════════════╗
║   ____  _                    ____                             ║
║  / ___|| |  ___   _ __   ___|  _ \\  ___ __  __                ║
║ | |    | | / _ \\ | '_ \\ / _ \\ |_) |/ _ \\\\ \\/ /                ║
║ | |___ | || (_) || | | |  __/  _ <| (_) |>  <                 ║
║  \\____||_| \\___/ |_| |_|\\___|_| \\_\\\\___//_/\\_\\                ║
║                                                               ║
║  Clone your workstation to an isolated VM                     ║
╚═══════════════════════════════════════════════════════════════╝
"""
    console.print(banner, style="cyan")
    console.print(f"  Version {__version__}\n", style="dim")


def interactive_mode():
    """Run the interactive VM creation wizard."""
    print_banner()

    console.print("[bold cyan]🔍 Detecting system state...[/]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Scanning services, apps, and paths...", total=None)
        detector = SystemDetector()
        snapshot = detector.detect_all()
        sys_info = detector.get_system_info()
        docker_containers = detector.detect_docker_containers()

    # Show system info
    console.print(
        Panel(
            f"[bold]Hostname:[/] {sys_info['hostname']}\n"
            f"[bold]User:[/] {sys_info['user']}\n"
            f"[bold]CPU:[/] {sys_info['cpu_count']} cores\n"
            f"[bold]RAM:[/] {sys_info['memory_available_gb']:.1f} / {sys_info['memory_total_gb']:.1f} GB available\n"
            f"[bold]Disk:[/] {sys_info['disk_free_gb']:.1f} / {sys_info['disk_total_gb']:.1f} GB free",
            title="[bold cyan]System Info[/]",
            border_style="cyan",
        )
    )

    console.print()

    # === VM Name ===
    vm_name = questionary.text("VM name:", default="clonebox-vm", style=custom_style).ask()

    if not vm_name:
        console.print("[red]Cancelled.[/]")
        return

    # === RAM ===
    max_ram = int(sys_info["memory_available_gb"] * 1024 * 0.75)  # 75% of available
    default_ram = min(4096, max_ram)

    ram_mb = questionary.text(
        f"RAM (MB) [max recommended: {max_ram}]:", default=str(default_ram), style=custom_style
    ).ask()
    ram_mb = int(ram_mb) if ram_mb else default_ram

    # === vCPUs ===
    max_vcpus = sys_info["cpu_count"]
    default_vcpus = max(2, max_vcpus // 2)

    vcpus = questionary.text(
        f"vCPUs [max: {max_vcpus}]:", default=str(default_vcpus), style=custom_style
    ).ask()
    vcpus = int(vcpus) if vcpus else default_vcpus

    # === Services Selection ===
    console.print("\n[bold cyan]📦 Select services to include in VM:[/]")

    service_choices = []
    for svc in snapshot.running_services:
        label = f"{svc.name} ({svc.status})"
        if svc.description:
            label += f" - {svc.description[:40]}"
        service_choices.append(questionary.Choice(label, value=svc.name))

    selected_services = []
    if service_choices:
        selected_services = (
            questionary.checkbox(
                "Services (space to select, enter to confirm):",
                choices=service_choices,
                style=custom_style,
            ).ask()
            or []
        )
    else:
        console.print("[dim]  No interesting services detected[/]")

    # === Applications/Processes Selection ===
    console.print("\n[bold cyan]🚀 Select applications to track:[/]")

    app_choices = []
    for app in snapshot.running_apps[:20]:  # Limit to top 20
        label = f"{app.name} (PID: {app.pid}, {app.memory_mb:.0f} MB)"
        if app.working_dir:
            label += f" @ {app.working_dir[:30]}"
        app_choices.append(questionary.Choice(label, value=app))

    selected_apps = []
    if app_choices:
        selected_apps = (
            questionary.checkbox(
                "Applications (will add their working dirs):",
                choices=app_choices,
                style=custom_style,
            ).ask()
            or []
        )
    else:
        console.print("[dim]  No interesting applications detected[/]")

    # === Docker Containers ===
    if docker_containers:
        console.print("\n[bold cyan]🐳 Docker containers detected:[/]")

        container_choices = [
            questionary.Choice(f"{c['name']} ({c['image']}) - {c['status']}", value=c["name"])
            for c in docker_containers
        ]

        selected_containers = (
            questionary.checkbox(
                "Containers (will share docker socket):",
                choices=container_choices,
                style=custom_style,
            ).ask()
            or []
        )

        # If any docker selected, add docker socket
        if selected_containers:
            if "docker" not in selected_services:
                selected_services.append("docker")

    # === Paths Selection ===
    console.print("\n[bold cyan]📁 Select paths to mount in VM:[/]")

    # Group paths by type
    path_groups = {}
    for p in snapshot.paths:
        if p.type not in path_groups:
            path_groups[p.type] = []
        path_groups[p.type].append(p)

    path_choices = []
    for ptype in ["project", "config", "data"]:
        if ptype in path_groups:
            for p in path_groups[ptype]:
                size_str = f"{p.size_mb:.0f} MB" if p.size_mb > 0 else "?"
                label = f"[{ptype}] {p.path} ({size_str})"
                if p.description:
                    label += f" - {p.description}"
                path_choices.append(questionary.Choice(label, value=p.path))

    selected_paths = []
    if path_choices:
        selected_paths = (
            questionary.checkbox(
                "Paths (will be bind-mounted read-write):", choices=path_choices, style=custom_style
            ).ask()
            or []
        )

    # Add working directories from selected applications
    for app in selected_apps:
        if app.working_dir and app.working_dir not in selected_paths:
            selected_paths.append(app.working_dir)

    # === Additional Packages ===
    console.print("\n[bold cyan]📦 Additional packages to install:[/]")

    common_packages = [
        "build-essential",
        "git",
        "curl",
        "wget",
        "vim",
        "htop",
        "python3",
        "python3-pip",
        "python3-venv",
        "nodejs",
        "npm",
        "docker.io",
        "docker-compose",
        "nginx",
        "postgresql",
        "redis",
    ]

    pkg_choices = [questionary.Choice(pkg, value=pkg) for pkg in common_packages]

    selected_packages = (
        questionary.checkbox(
            "Packages (space to select):", choices=pkg_choices, style=custom_style
        ).ask()
        or []
    )

    # Add custom packages
    custom_pkgs = questionary.text(
        "Additional packages (space-separated):", default="", style=custom_style
    ).ask()

    if custom_pkgs:
        selected_packages.extend(custom_pkgs.split())

    # === Base Image ===
    base_image = questionary.text(
        "Base image path (optional, leave empty for blank disk):", default="", style=custom_style
    ).ask()

    # === GUI ===
    enable_gui = questionary.confirm(
        "Enable SPICE graphics (GUI)?", default=True, style=custom_style
    ).ask()

    # === Summary ===
    console.print("\n")

    # Build paths mapping
    paths_mapping = {}
    for idx, host_path in enumerate(selected_paths):
        guest_path = f"/mnt/host{idx}"
        paths_mapping[host_path] = guest_path

    # Summary table
    summary_table = Table(title="VM Configuration Summary", border_style="cyan")
    summary_table.add_column("Setting", style="bold")
    summary_table.add_column("Value")

    summary_table.add_row("Name", vm_name)
    summary_table.add_row("RAM", f"{ram_mb} MB")
    summary_table.add_row("vCPUs", str(vcpus))
    summary_table.add_row("Services", ", ".join(selected_services) or "None")
    summary_table.add_row(
        "Packages",
        ", ".join(selected_packages[:5]) + ("..." if len(selected_packages) > 5 else "") or "None",
    )
    summary_table.add_row("Paths", f"{len(paths_mapping)} bind mounts")
    summary_table.add_row("GUI", "Yes (SPICE)" if enable_gui else "No")

    console.print(summary_table)

    if paths_mapping:
        console.print("\n[bold]Bind mounts:[/]")
        for host, guest in paths_mapping.items():
            console.print(f"  [cyan]{host}[/] → [green]{guest}[/]")

    console.print()

    # === Confirm ===
    if not questionary.confirm(
        "Create VM with these settings?", default=True, style=custom_style
    ).ask():
        console.print("[yellow]Cancelled.[/]")
        return

    # === Create VM ===
    console.print("\n[bold cyan]🔧 Creating VM...[/]\n")

    config = VMConfig(
        name=vm_name,
        ram_mb=ram_mb,
        vcpus=vcpus,
        gui=enable_gui,
        base_image=base_image if base_image else None,
        paths=paths_mapping,
        packages=selected_packages,
        services=selected_services,
    )

    try:
        cloner = SelectiveVMCloner(user_session=user_session)

        # Check prerequisites
        checks = cloner.check_prerequisites()
        if not all(checks.values()):
            console.print("[yellow]⚠️  Prerequisites check:[/]")
            for check, passed in checks.items():
                icon = "✅" if passed else "❌"
                console.print(f"   {icon} {check}")

            if not checks["libvirt_connected"]:
                console.print("\n[red]Cannot proceed without libvirt connection.[/]")
                console.print("Try: [cyan]sudo systemctl start libvirtd[/]")
                return

        vm_uuid = cloner.create_vm(config, console=console)

        # Ask to start
        if questionary.confirm("Start VM now?", default=True, style=custom_style).ask():
            cloner.start_vm(vm_name, open_viewer=enable_gui, console=console)
            console.print("\n[bold green]🎉 VM is running![/]")

            if paths_mapping:
                console.print("\n[bold]Inside the VM, mount shared folders with:[/]")
                for idx, (host, guest) in enumerate(paths_mapping.items()):
                    console.print(f"  [cyan]sudo mount -t 9p -o trans=virtio mount{idx} {guest}[/]")

        console.print(f"\n[dim]VM UUID: {vm_uuid}[/]")

    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/]")
        raise


def cmd_create(args):
    """Create VM from JSON config."""
    config_data = json.loads(args.config)

    config = VMConfig(
        name=args.name,
        ram_mb=args.ram,
        vcpus=args.vcpus,
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
        vm_uuid = create_vm_from_config(config, start=True, user_session=getattr(args, "user", False))
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
    cloner.start_vm(name, open_viewer=not args.no_viewer, console=console)


def cmd_stop(args):
    """Stop a VM."""
    cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))
    cloner.stop_vm(args.name, force=args.force, console=console)


def cmd_delete(args):
    """Delete a VM."""
    if not args.yes:
        if not questionary.confirm(
            f"Delete VM '{args.name}' and its storage?", default=False, style=custom_style
        ).ask():
            console.print("[yellow]Cancelled.[/]")
            return

    cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))
    cloner.delete_vm(args.name, delete_storage=not args.keep_storage, console=console)


def cmd_list(args):
    """List all VMs."""
    cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))
    vms = cloner.list_vms()

    if not vms:
        console.print("[dim]No VMs found.[/]")
        return

    table = Table(title="Virtual Machines", border_style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("State")
    table.add_column("UUID", style="dim")

    for vm in vms:
        state_style = "green" if vm["state"] == "running" else "dim"
        table.add_row(vm["name"], f"[{state_style}]{vm['state']}[/]", vm["uuid"][:8])

    console.print(table)


CLONEBOX_CONFIG_FILE = ".clonebox.yaml"


def deduplicate_list(items: list, key=None) -> list:
    """Remove duplicates from list, preserving order."""
    seen = set()
    result = []
    for item in items:
        k = key(item) if key else item
        if k not in seen:
            seen.add(k)
            result.append(item)
    return result


def generate_clonebox_yaml(
    snapshot,
    detector,
    deduplicate: bool = True,
    target_path: str = None,
    vm_name: str = None,
    network_mode: str = "auto",
    base_image: str | None = None,
) -> str:
    """Generate YAML config from system snapshot."""
    sys_info = detector.get_system_info()

    # Collect services
    services = [s.name for s in snapshot.running_services]
    if deduplicate:
        services = deduplicate_list(services)

    # Collect paths with types
    paths_by_type = {"project": [], "config": [], "data": []}
    for p in snapshot.paths:
        if p.type in paths_by_type:
            paths_by_type[p.type].append(p.path)

    if deduplicate:
        for ptype in paths_by_type:
            paths_by_type[ptype] = deduplicate_list(paths_by_type[ptype])

    # Collect working directories from running apps
    working_dirs = []
    for app in snapshot.applications:
        if app.working_dir and app.working_dir != "/" and app.working_dir.startswith("/home"):
            working_dirs.append(app.working_dir)

    if deduplicate:
        working_dirs = deduplicate_list(working_dirs)

    # If target_path specified, prioritize it
    if target_path:
        target_path = Path(target_path).resolve()
        target_str = str(target_path)
        if target_str not in paths_by_type["project"]:
            paths_by_type["project"].insert(0, target_str)

    # Build paths mapping
    paths_mapping = {}
    idx = 0
    for host_path in paths_by_type["project"][:5]:  # Limit projects
        paths_mapping[host_path] = f"/mnt/project{idx}"
        idx += 1

    for host_path in working_dirs[:3]:  # Limit working dirs
        if host_path not in paths_mapping:
            paths_mapping[host_path] = f"/mnt/workdir{idx}"
            idx += 1

    # Determine VM name
    if not vm_name:
        if target_path:
            vm_name = f"clone-{target_path.name}"
        else:
            vm_name = f"clone-{sys_info['hostname']}"

    # Calculate recommended resources
    ram_mb = min(4096, int(sys_info["memory_available_gb"] * 1024 * 0.5))
    vcpus = max(2, sys_info["cpu_count"] // 2)

    # Build config
    config = {
        "version": "1",
        "generated": datetime.now().isoformat(),
        "vm": {
            "name": vm_name,
            "ram_mb": ram_mb,
            "vcpus": vcpus,
            "gui": True,
            "base_image": base_image,
            "network_mode": network_mode,
        },
        "services": services,
        "packages": [
            "build-essential",
            "git",
            "curl",
            "vim",
            "python3",
            "python3-pip",
        ],
        "paths": paths_mapping,
        "detected": {
            "running_apps": [
                {"name": a.name, "cwd": a.working_dir, "memory_mb": round(a.memory_mb)}
                for a in snapshot.applications[:10]
            ],
            "all_paths": {
                "projects": paths_by_type["project"],
                "configs": paths_by_type["config"][:5],
                "data": paths_by_type["data"][:5],
            },
        },
    }

    return yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_clonebox_config(path: Path) -> dict:
    """Load .clonebox.yaml config file."""
    config_file = path / CLONEBOX_CONFIG_FILE if path.is_dir() else path

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with open(config_file) as f:
        return yaml.safe_load(f)


def create_vm_from_config(
    config: dict,
    start: bool = False,
    user_session: bool = False,
    replace: bool = False,
) -> str:
    """Create VM from YAML config dict."""
    vm_config = VMConfig(
        name=config["vm"]["name"],
        ram_mb=config["vm"].get("ram_mb", 4096),
        vcpus=config["vm"].get("vcpus", 4),
        gui=config["vm"].get("gui", True),
        base_image=config["vm"].get("base_image"),
        paths=config.get("paths", {}),
        packages=config.get("packages", []),
        services=config.get("services", []),
        user_session=user_session,
        network_mode=config["vm"].get("network_mode", "auto"),
    )

    cloner = SelectiveVMCloner(user_session=user_session)

    # Check prerequisites and show detailed info
    checks = cloner.check_prerequisites()

    if not checks["images_dir_writable"]:
        console.print(f"[yellow]⚠️  Storage directory: {checks['images_dir']}[/]")
        if "images_dir_error" in checks:
            console.print(f"[red]{checks['images_dir_error']}[/]")
            raise PermissionError(checks["images_dir_error"])

    console.print(f"[dim]Session: {checks['session_type']}, Storage: {checks['images_dir']}[/]")

    vm_uuid = cloner.create_vm(vm_config, console=console, replace=replace)

    if start:
        cloner.start_vm(vm_config.name, open_viewer=vm_config.gui, console=console)

    return vm_uuid


def cmd_clone(args):
    """Generate clone config from path and optionally create VM."""
    target_path = Path(args.path).resolve()

    if not target_path.exists():
        console.print(f"[red]❌ Path does not exist: {target_path}[/]")
        return

    console.print(f"[bold cyan]📦 Generating clone config for: {target_path}[/]\n")

    # Detect system state
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Scanning system...", total=None)
        detector = SystemDetector()
        snapshot = detector.detect_all()

    # Generate config
    vm_name = args.name or f"clone-{target_path.name}"
    yaml_content = generate_clonebox_yaml(
        snapshot,
        detector,
        deduplicate=args.dedupe,
        target_path=str(target_path),
        vm_name=vm_name,
        network_mode=args.network,
        base_image=getattr(args, "base_image", None),
    )

    # Save config file
    config_file = (
        target_path / CLONEBOX_CONFIG_FILE
        if target_path.is_dir()
        else target_path.parent / CLONEBOX_CONFIG_FILE
    )
    config_file.write_text(yaml_content)
    console.print(f"[green]✅ Config saved: {config_file}[/]\n")

    # Show config
    console.print(Panel(yaml_content, title="[bold].clonebox.yaml[/]", border_style="cyan"))

    # Open in editor if requested
    if args.edit:
        editor = os.environ.get("EDITOR", "nano")
        console.print(f"[cyan]Opening {editor}...[/]")
        os.system(f"{editor} {config_file}")
        # Reload after edit
        yaml_content = config_file.read_text()

    # Ask to create VM
    if args.run:
        create_now = True
    else:
        create_now = questionary.confirm(
            "Create VM with this config?", default=True, style=custom_style
        ).ask()

    if create_now:
        config = yaml.safe_load(yaml_content)
        user_session = getattr(args, "user", False)

        console.print("\n[bold cyan]🔧 Creating VM...[/]\n")
        if user_session:
            console.print("[cyan]Using user session (qemu:///session) - no root required[/]")

        try:
            vm_uuid = create_vm_from_config(
                config,
                start=True,
                user_session=user_session,
                replace=getattr(args, "replace", False),
            )
            console.print(f"\n[bold green]🎉 VM '{config['vm']['name']}' is running![/]")
            console.print(f"[dim]UUID: {vm_uuid}[/]")

            # Show mount instructions
            if config.get("paths"):
                console.print("\n[bold]Inside VM, mount paths with:[/]")
                for idx, (host, guest) in enumerate(config["paths"].items()):
                    console.print(f"  [cyan]sudo mount -t 9p -o trans=virtio mount{idx} {guest}[/]")
        except PermissionError as e:
            console.print(f"[red]❌ Permission Error:[/]\n{e}")
            console.print("\n[yellow]💡 Try running with --user flag:[/]")
            console.print(f"  [cyan]clonebox clone {target_path} --user[/]")
        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/]")
    else:
        console.print("\n[dim]To create VM later, run:[/]")
        console.print(f"  [cyan]clonebox start {target_path}[/]")


def cmd_detect(args):
    """Detect and show system state."""
    console.print("[bold cyan]🔍 Detecting system state...[/]\n")

    detector = SystemDetector()
    snapshot = detector.detect_all()

    # JSON output
    if args.json:
        result = {
            "services": [{"name": s.name, "status": s.status} for s in snapshot.running_services],
            "applications": [
                {"name": a.name, "pid": a.pid, "cwd": a.working_dir} for a in snapshot.applications
            ],
            "paths": [
                {"path": p.path, "type": p.type, "size_mb": p.size_mb} for p in snapshot.paths
            ],
        }
        print(json.dumps(result, indent=2))
        return

    # YAML output
    if args.yaml:
        result = generate_clonebox_yaml(snapshot, detector, deduplicate=args.dedupe)

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(result)
            console.print(f"[green]✅ Config saved to: {output_path}[/]")
        else:
            print(result)
        return

    # Services
    services = detector.detect_services()
    running = [s for s in services if s.status == "running"]

    if running:
        table = Table(title="Running Services", border_style="green")
        table.add_column("Service")
        table.add_column("Status")
        table.add_column("Enabled")

        for svc in running:
            table.add_row(svc.name, f"[green]{svc.status}[/]", "✓" if svc.enabled else "")

        console.print(table)

    # Applications
    apps = detector.detect_applications()

    if apps:
        console.print()
        table = Table(title="Running Applications", border_style="blue")
        table.add_column("Name")
        table.add_column("PID")
        table.add_column("Memory")
        table.add_column("Working Dir")

        for app in apps[:15]:
            table.add_row(
                app.name,
                str(app.pid),
                f"{app.memory_mb:.0f} MB",
                app.working_dir[:40] if app.working_dir else "",
            )

        console.print(table)

    # Paths
    paths = detector.detect_paths()

    if paths:
        console.print()
        table = Table(title="Detected Paths", border_style="yellow")
        table.add_column("Type")
        table.add_column("Path")
        table.add_column("Size")

        for p in paths[:20]:
            table.add_row(
                f"[cyan]{p.type}[/]", p.path, f"{p.size_mb:.0f} MB" if p.size_mb > 0 else "-"
            )

        console.print(table)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="clonebox", description="Clone your workstation environment to an isolated VM"
    )
    parser.add_argument("--version", action="version", version=f"clonebox {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Interactive mode (default)
    parser.set_defaults(func=lambda args: interactive_mode())

    # Create command
    create_parser = subparsers.add_parser("create", help="Create VM from config")
    create_parser.add_argument("--name", "-n", default="clonebox-vm", help="VM name")
    create_parser.add_argument(
        "--config",
        "-c",
        required=True,
        help='JSON config: {"paths": {}, "packages": [], "services": []}',
    )
    create_parser.add_argument("--ram", type=int, default=4096, help="RAM in MB")
    create_parser.add_argument("--vcpus", type=int, default=4, help="Number of vCPUs")
    create_parser.add_argument("--base-image", help="Path to base qcow2 image")
    create_parser.add_argument("--no-gui", action="store_true", help="Disable SPICE graphics")
    create_parser.add_argument("--start", "-s", action="store_true", help="Start VM after creation")
    create_parser.set_defaults(func=cmd_create)

    # Start command
    start_parser = subparsers.add_parser("start", help="Start a VM")
    start_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    start_parser.add_argument("--no-viewer", action="store_true", help="Don't open virt-viewer")
    start_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    start_parser.set_defaults(func=cmd_start)

    # Stop command
    stop_parser = subparsers.add_parser("stop", help="Stop a VM")
    stop_parser.add_argument("name", help="VM name")
    stop_parser.add_argument("--force", "-f", action="store_true", help="Force stop")
    stop_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    stop_parser.set_defaults(func=cmd_stop)

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a VM")
    delete_parser.add_argument("name", help="VM name")
    delete_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    delete_parser.add_argument("--keep-storage", action="store_true", help="Keep disk images")
    delete_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    delete_parser.set_defaults(func=cmd_delete)

    # List command
    list_parser = subparsers.add_parser("list", aliases=["ls"], help="List VMs")
    list_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    list_parser.set_defaults(func=cmd_list)

    # Detect command
    detect_parser = subparsers.add_parser("detect", help="Detect system state")
    detect_parser.add_argument("--json", action="store_true", help="Output as JSON")
    detect_parser.add_argument("--yaml", action="store_true", help="Output as YAML config")
    detect_parser.add_argument("--dedupe", action="store_true", help="Remove duplicate entries")
    detect_parser.add_argument("-o", "--output", help="Save output to file")
    detect_parser.set_defaults(func=cmd_detect)

    # Clone command
    clone_parser = subparsers.add_parser("clone", help="Generate clone config from path")
    clone_parser.add_argument(
        "path", nargs="?", default=".", help="Path to clone (default: current dir)"
    )
    clone_parser.add_argument("--name", "-n", help="VM name (default: directory name)")
    clone_parser.add_argument(
        "--run", "-r", action="store_true", help="Create and start VM immediately"
    )
    clone_parser.add_argument(
        "--edit", "-e", action="store_true", help="Open config in editor before creating"
    )
    clone_parser.add_argument(
        "--dedupe", action="store_true", default=True, help="Remove duplicate entries"
    )
    clone_parser.add_argument(
        "--user",
        "-u",
        action="store_true",
        help="Use user session (qemu:///session) - no root required, stores in ~/.local/share/libvirt/",
    )
    clone_parser.add_argument(
        "--network",
        choices=["auto", "default", "user"],
        default="auto",
        help="Network mode: auto (default), default (libvirt network), user (slirp)",
    )
    clone_parser.add_argument(
        "--base-image",
        help="Path to a bootable qcow2 image to use as a base disk",
    )
    clone_parser.add_argument(
        "--replace",
        action="store_true",
        help="If VM already exists, stop+undefine it and recreate (also deletes its storage)",
    )
    clone_parser.set_defaults(func=cmd_clone)

    args = parser.parse_args()

    if hasattr(args, "func"):
        try:
            args.func(args)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
            sys.exit(1)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
