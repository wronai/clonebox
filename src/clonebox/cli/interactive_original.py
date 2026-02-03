#!/usr/bin/env python3
"""
Interactive mode for CloneBox CLI.
"""

import os
import secrets
import string
from pathlib import Path
from typing import Dict, List, Optional

import questionary
from rich.console import Console

from clonebox import __version__
from clonebox.cli.utils import console, custom_style, print_banner, CLONEBOX_CONFIG_FILE, load_clonebox_config, create_vm_from_config


def interactive_mode():
    """Run interactive mode."""
    print_banner()
    
    while True:
        choice = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("🚀 Create a new VM", value="create"),
                questionary.Choice("▶️  Start an existing VM", value="start"),
                questionary.Choice("📋 List VMs", value="list"),
                questionary.Choice("🔧 Manage containers", value="container"),
                questionary.Choice("📸 Manage snapshots", value="snapshot"),
                questionary.Choice("📊 Monitor resources", value="monitor"),
                questionary.Choice("🏥 Health check", value="health"),
                questionary.Choice("🔑 SSH key management", value="ssh"),
                questionary.Choice("📦 Import/Export", value="import_export"),
                questionary.Choice("🌐 Remote management", value="remote"),
                questionary.Choice("📜 Audit log", value="audit"),
                questionary.Choice("🔌 Plugin management", value="plugin"),
                questionary.Choice("🐳 Compose (multi-VM)", value="compose"),
                questionary.Choice("⚙️  Settings", value="settings"),
                questionary.Choice("❌ Exit", value="exit"),
            ],
            style=custom_style,
        ).ask()
        
        if choice == "exit":
            console.print("[dim]Goodbye![/]")
            break
        
        handle_choice(choice)


def handle_choice(choice: str):
    """Handle interactive menu choice."""
    if choice == "create":
        interactive_create_vm()
    elif choice == "start":
        interactive_start_vm()
    elif choice == "list":
        interactive_list_vms()
    elif choice == "container":
        interactive_container_menu()
    elif choice == "snapshot":
        interactive_snapshot_menu()
    elif choice == "monitor":
        interactive_monitor()
    elif choice == "health":
        interactive_health_check()
    elif choice == "ssh":
        interactive_ssh_menu()
    elif choice == "import_export":
        interactive_import_export_menu()
    elif choice == "remote":
        interactive_remote_menu()
    elif choice == "audit":
        interactive_audit_menu()
    elif choice == "plugin":
        interactive_plugin_menu()
    elif choice == "compose":
        interactive_compose_menu()
    elif choice == "settings":
        interactive_settings()


def interactive_create_vm():
    """Interactive VM creation."""
    console.print("\n[bold cyan]Create a New VM[/]\n")
    
    # Check for existing config
    config_file = Path.cwd() / CLONEBOX_CONFIG_FILE
    if config_file.exists():
        if questionary.confirm(
            f"Found {CLONEBOX_CONFIG_FILE} in current directory. Use it?",
            default=True,
            style=custom_style,
        ).ask():
            config = load_clonebox_config(config_file)
            vm_name = config["vm"]["name"]
            
            if questionary.confirm(
                f"Create VM '{vm_name}' now?",
                default=True,
                style=custom_style,
            ).ask():
                console.print(f"\n[cyan]Creating VM '{vm_name}'...[/]")
                vm_uuid = create_vm_from_config(config, start=True)
                console.print(f"\n[bold green]🎉 VM created and started![/]")
                console.print(f"[dim]UUID: {vm_uuid}[/]")
            return
    
    # Get VM details
    vm_name = questionary.text(
        "VM name:",
        default="clonebox-vm",
        style=custom_style,
    ).ask()
    
    ram = questionary.text(
        "RAM in MB:",
        default="4096",
        validate=lambda x: x.isdigit() and int(x) >= 512,
        style=custom_style,
    ).ask()
    
    vcpus = questionary.text(
        "Number of vCPUs:",
        default="4",
        validate=lambda x: x.isdigit() and int(x) >= 1,
        style=custom_style,
    ).ask()
    
    disk_size = questionary.text(
        "Disk size in GB:",
        default="20",
        validate=lambda x: x.isdigit() and int(x) >= 10,
        style=custom_style,
    ).ask()
    
    # Network mode
    network_mode = questionary.select(
        "Network mode:",
        choices=[
            questionary.Choice("Auto (recommended)", value="auto"),
            questionary.Choice("Default", value="default"),
            questionary.Choice("User mode", value="user"),
        ],
        default="auto",
        style=custom_style,
    ).ask()
    
    # GUI
    enable_gui = questionary.confirm(
        "Enable GUI (SPICE graphics)?",
        default=True,
        style=custom_style,
    ).ask()
    
    # User session
    user_session = questionary.confirm(
        "Use user session (no root required)?",
        default=False,
        style=custom_style,
    ).ask()
    
    # What to include
    console.print("\n[bold]What to include in the VM?[/]")
    include_packages = questionary.confirm(
        "Installed packages?",
        default=True,
        style=custom_style,
    ).ask()
    
    include_snaps = questionary.confirm(
        "Snap packages?",
        default=True,
        style=custom_style,
    ).ask()
    
    include_services = questionary.confirm(
        "Running services?",
        default=True,
        style=custom_style,
    ).ask()
    
    include_home = questionary.confirm(
        "Home directory (bind-mount)?",
        default=True,
        style=custom_style,
    ).ask()
    
    # Create config
    config = {
        "version": "1",
        "vm": {
            "name": vm_name,
            "ram_mb": int(ram),
            "vcpus": int(vcpus),
            "disk_size_gb": int(disk_size),
            "gui": enable_gui,
            "network_mode": network_mode,
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
    
    # Add paths
    if include_home:
        home_path = Path.home()
        config["paths"][str(home_path)] = f"/home/ubuntu"
    
    # Detect and add packages/services if requested
    if include_packages or include_snaps or include_services:
        console.print("\n[cyan]Detecting system configuration...[/]")
        
        from clonebox.detector import SystemDetector
        detector = SystemDetector()
        sys_info = detector.detect_all()
        
        if include_packages and sys_info.get("packages", {}).get("apt"):
            # Filter packages
            user_packages = [
                pkg for pkg in sys_info["packages"]["apt"]
                if not any(pkg.startswith(prefix) for prefix in ["linux-", "libc", "libg", "libx"])
            ]
            config["packages"] = user_packages[:50]  # Limit
        
        if include_snaps and sys_info.get("packages", {}).get("snap"):
            config["snap_packages"] = sys_info["packages"]["snap"]
        
        if include_services and sys_info.get("services"):
            user_services = [
                svc["name"] for svc in sys_info["services"]
                if svc.get("enabled") and not svc["name"].startswith(("systemd-", "dbus-", "networkd-"))
            ]
            config["services"] = user_services
    
    # Save config
    with open(config_file, "w") as f:
        import yaml
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    console.print(f"\n[green]✅ Configuration saved to: {config_file}[/]")
    
    # Create VM
    if questionary.confirm(
        "Create VM now?",
        default=True,
        style=custom_style,
    ).ask():
        console.print(f"\n[cyan]Creating VM '{vm_name}'...[/]")
        vm_uuid = create_vm_from_config(config, start=True, user_session=user_session)
        console.print(f"\n[bold green]🎉 VM created and started![/]")
        console.print(f"[dim]UUID: {vm_uuid}[/]")


def interactive_start_vm():
    """Interactive VM start."""
    console.print("\n[bold cyan]Start a VM[/]\n")
    
    # Get VMs
    from clonebox.cloner import SelectiveVMCloner
    cloner = SelectiveVMCloner()
    
    try:
        vms = cloner.list_vms()
        
        if not vms:
            console.print("[dim]No VMs found. Create one first.[/]")
            return
        
        # Build choices
        choices = []
        for vm in vms:
            if vm["state"] == "running":
                choices.append(questionary.Choice(f"🟢 {vm['name']} (running)", value=vm["name"]))
            else:
                choices.append(questionary.Choice(f"🔴 {vm['name']} (stopped)", value=vm["name"]))
        
        vm_name = questionary.select(
            "Select VM to start:",
            choices=choices,
            style=custom_style,
        ).ask()
        
        if vm_name:
            open_viewer = questionary.confirm(
                "Open GUI viewer?",
                default=True,
                style=custom_style,
            ).ask()
            
            console.print(f"\n[cyan]Starting VM '{vm_name}'...[/]")
            cloner.start_vm(vm_name, open_viewer=open_viewer, console=console)
            console.print("[green]✅ VM started[/]")
            
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


def interactive_list_vms():
    """List VMs interactively."""
    console.print("\n[bold cyan]Virtual Machines[/]\n")
    
    from clonebox.cloner import SelectiveVMCloner
    cloner = SelectiveVMCloner()
    
    try:
        vms = cloner.list_vms()
        
        if not vms:
            console.print("[dim]No VMs found[/]")
            return
        
        from rich.table import Table
        table = Table()
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
        
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


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


def interactive_snapshot_menu():
    """Snapshot management menu."""
    console.print("\n[bold cyan]Snapshot Management[/]\n")
    
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
            "Select VM:",
            choices=choices,
            style=custom_style,
        ).ask()
        
        if not vm_name:
            return
        
        # Snapshot actions
        choice = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("📸 Create snapshot", value="create"),
                questionary.Choice("📋 List snapshots", value="list"),
                questionary.Choice("↩️  Restore snapshot", value="restore"),
                questionary.Choice("🗑️  Delete snapshot", value="delete"),
                questionary.Choice("🔙 Back", value="back"),
            ],
            style=custom_style,
        ).ask()
        
        if choice == "back":
            return
        
        from clonebox.snapshots import SnapshotManager
        manager = SnapshotManager()
        
        if choice == "create":
            name = questionary.text(
                "Snapshot name:",
                style=custom_style,
            ).ask()
            
            description = questionary.text(
                "Description (optional):",
                style=custom_style,
            ).ask()
            
            snapshot_id = manager.create_snapshot(
                vm_name=vm_name,
                name=name,
                description=description,
                console=console,
            )
            console.print(f"[green]✅ Snapshot created: {snapshot_id}[/]")
            
        elif choice == "list":
            snapshots = manager.list_snapshots(vm_name)
            
            if not snapshots:
                console.print(f"[dim]No snapshots found for VM '{vm_name}'[/]")
                return
            
            from rich.table import Table
            table = Table()
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Created", style="yellow")
            
            for snapshot in snapshots:
                table.add_row(
                    snapshot["id"],
                    snapshot["name"],
                    snapshot["created"],
                )
            
            console.print(table)
            
        elif choice in ["restore", "delete"]:
            snapshots = manager.list_snapshots(vm_name)
            
            if not snapshots:
                console.print(f"[dim]No snapshots found for VM '{vm_name}'[/]")
                return
            
            choices = [
                questionary.Choice(f"{s['name']} ({s['id']})", value=s["id"])
                for s in snapshots
            ]
            
            snapshot_id = questionary.select(
                f"Select snapshot to {choice}:",
                choices=choices,
                style=custom_style,
            ).ask()
            
            if snapshot_id:
                if choice == "restore":
                    manager.restore_snapshot(vm_name, snapshot_id, console=console)
                    console.print("[green]✅ Snapshot restored[/]")
                else:
                    manager.delete_snapshot(vm_name, snapshot_id, console=console)
                    console.print("[green]✅ Snapshot deleted[/]")
                    
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


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
            
            from clonebox.monitor import ResourceMonitor
            monitor = ResourceMonitor()
            
            import time
            from rich.live import Live
            from rich.table import Table
            from clonebox.monitor import format_bytes
            
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
            from rich.table import Table
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


def interactive_ssh_menu():
    """SSH key management menu."""
    console.print("\n[bold cyan]SSH Key Management[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("🔑 Generate new key pair", value="generate"),
            questionary.Choice("🔄 Sync key with VM", value="sync"),
            questionary.Choice("📋 Show public key", value="show"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    if choice == "generate":
        output_path = questionary.text(
            "Output path for key:",
            default=str(Path.cwd() / "clonebox_key"),
            style=custom_style,
        ).ask()
        
        from clonebox.cli.misc_commands import generate_password
        from clonebox.secrets import SecretsManager
        
        secrets = SecretsManager()
        key_pair = secrets.generate_ssh_key_pair(Path(output_path))
        
        console.print(f"\n[green]✅ SSH key pair generated:[/]")
        console.print(f"  Private key: {output_path}")
        console.print(f"  Public key: {output_path}.pub")
        
        if questionary.confirm("Copy public key to clipboard?", default=True, style=custom_style).ask():
            import pyperclip
            pyperclip.copy(key_pair.public_key)
            console.print("[green]✅ Public key copied to clipboard[/]")
            
    elif choice == "sync":
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
                "Select VM:",
                choices=choices,
                style=custom_style,
            ).ask()
            
            if vm_name:
                from clonebox.cli.import_export_commands import cmd_sync_key
                args = type('Args', (), {'name': vm_name, 'user': False})()
                cmd_sync_key(args)
                
        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/]")
            
    elif choice == "show":
        ssh_dir = Path.home() / ".ssh"
        pub_key_path = ssh_dir / "id_rsa.pub"
        
        if pub_key_path.exists():
            pub_key = pub_key_path.read_text().strip()
            console.print(f"\n[bold]Public key:[/]")
            console.print(pub_key)
            
            if questionary.confirm("Copy to clipboard?", default=True, style=custom_style).ask():
                import pyperclip
                pyperclip.copy(pub_key)
                console.print("[green]✅ Copied to clipboard[/]")
        else:
            console.print("[yellow]No SSH key found. Generate one first.[/]")


def interactive_import_export_menu():
    """Import/Export menu."""
    console.print("\n[bold cyan]Import/Export[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("📤 Export VM", value="export"),
            questionary.Choice("📥 Import VM", value="import"),
            questionary.Choice("🔐 Export encrypted", value="export_enc"),
            questionary.Choice("🔓 Import encrypted", value="import_enc"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    # Get VM name for export operations
    if choice in ["export", "export_enc"]:
        from clonebox.cloner import SelectiveVMCloner
        cloner = SelectiveVMCloner()
        
        try:
            vms = cloner.list_vms()
            
            if not vms:
                console.print("[dim]No VMs found[/]")
                return
            
            choices = [vm["name"] for vm in vms]
            vm_name = questionary.select(
                "Select VM to export:",
                choices=choices,
                style=custom_style,
            ).ask()
            
            if not vm_name:
                return
            
            output_path = questionary.text(
                "Output file path:",
                default=f"{vm_name}-export.tar.gz",
                style=custom_style,
            ).ask()
            
            if choice == "export":
                from clonebox.cli.import_export_commands import cmd_export
                args = type('Args', (), {
                    'name': vm_name,
                    'output': output_path,
                    'include_disk': False,
                    'include_memory': False,
                    'compress': True,
                    'user': False
                })()
                cmd_export(args)
            else:
                from clonebox.cli.import_export_commands import cmd_export_encrypted
                args = type('Args', (), {
                    'name': vm_name,
                    'output': output_path,
                    'password': None,
                    'include_disk': False,
                    'user': False
                })()
                cmd_export_encrypted(args)
                
        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/]")
            
    elif choice in ["import", "import_enc"]:
        import_path = questionary.text(
            "Path to import file:",
            style=custom_style,
        ).ask()
        
        if not import_path or not Path(import_path).exists():
            console.print("[red]❌ File not found[/]")
            return
        
        new_name = questionary.text(
            "New VM name (optional):",
            style=custom_style,
        ).ask()
        
        start = questionary.confirm(
            "Start VM after import?",
            default=True,
            style=custom_style,
        ).ask()
        
        if choice == "import":
            from clonebox.cli.import_export_commands import cmd_import
            args = type('Args', (), {
                'import_path': import_path,
                'name': new_name,
                'start': start,
                'user': False
            })()
            cmd_import(args)
        else:
            from clonebox.cli.import_export_commands import cmd_import_encrypted
            args = type('Args', (), {
                'import_path': import_path,
                'name': new_name,
                'password': None,
                'start': start,
                'user': False
            })()
            cmd_import_encrypted(args)


def interactive_remote_menu():
    """Remote management menu."""
    console.print("\n[bold cyan]Remote Management[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("📋 List remote hosts", value="list"),
            questionary.Choice("🔗 Add remote host", value="add"),
            questionary.Choice("👀 List remote VMs", value="list_vms"),
            questionary.Choice("▶️  Start remote VM", value="start"),
            questionary.Choice("⏹️  Stop remote VM", value="stop"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    if choice == "list":
        from clonebox.cli.remote_commands import cmd_list_remote
        args = type('Args', (), {})()
        cmd_list_remote(args)
        
    elif choice == "add":
        host = questionary.text(
            "Remote host (user@hostname):",
            style=custom_style,
        ).ask()
        
        if host:
            # Add to config
            from clonebox.remote import add_remote_host
            add_remote_host(host)
            console.print(f"[green]✅ Added remote host: {host}[/]")
            
    elif choice in ["list_vms", "start", "stop"]:
        host = questionary.text(
            "Remote host (user@hostname):",
            style=custom_style,
        ).ask()
        
        if not host:
            return
        
        if choice == "list_vms":
            from clonebox.cli.remote_commands import cmd_remote_list
            args = type('Args', (), {'host': host, 'user': False, 'json': False})()
            cmd_remote_list(args)
            
        elif choice in ["start", "stop"]:
            # Get VMs first
            from clonebox.remote import RemoteConnection, RemoteCloner
            conn = RemoteConnection(host)
            remote = RemoteCloner(conn)
            
            try:
                vms = remote.list_vms()
                conn.close()
                
                if not vms:
                    console.print("[dim]No VMs found on remote host[/]")
                    return
                
                choices = [vm["name"] for vm in vms]
                vm_name = questionary.select(
                    f"Select VM to {choice}:",
                    choices=choices,
                    style=custom_style,
                ).ask()
                
                if vm_name:
                    if choice == "start":
                        from clonebox.cli.remote_commands import cmd_remote_start
                        args = type('Args', (), {
                            'host': host,
                            'vm_name': vm_name,
                            'user': False,
                            'viewer': False
                        })()
                        cmd_remote_start(args)
                    else:
                        from clonebox.cli.remote_commands import cmd_remote_stop
                        args = type('Args', (), {
                            'host': host,
                            'vm_name': vm_name,
                            'user': False,
                            'force': False
                        })()
                        cmd_remote_stop(args)
                        
            except Exception as e:
                console.print(f"[red]❌ Error: {e}[/]")


def interactive_audit_menu():
    """Audit log menu."""
    console.print("\n[bold cyan]Audit Log[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("📋 List recent entries", value="list"),
            questionary.Choice("🔍 Search log", value="search"),
            questionary.Choice("❌ Show failures", value="failures"),
            questionary.Choice("📤 Export log", value="export"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    if choice == "list":
        from clonebox.cli.policy_audit_commands import cmd_audit_list
        args = type('Args', (), {
            'event_type': None,
            'outcome': None,
            'user': None,
            'vm_name': None,
            'since': None,
            'limit': 20
        })()
        cmd_audit_list(args)
        
    elif choice == "search":
        query = questionary.text(
            "Search query:",
            style=custom_style,
        ).ask()
        
        if query:
            from clonebox.cli.policy_audit_commands import cmd_audit_search
            args = type('Args', (), {
                'query': query,
                'event_type': None,
                'limit': 50
            })()
            cmd_audit_search(args)
            
    elif choice == "failures":
        from clonebox.cli.policy_audit_commands import cmd_audit_failures
        args = type('Args', (), {'since': None, 'limit': 20})()
        cmd_audit_failures(args)
        
    elif choice == "export":
        output_path = questionary.text(
            "Output file:",
            style=custom_style,
        ).ask()
        
        if output_path:
            format_choice = questionary.select(
                "Export format:",
                choices=[
                    questionary.Choice("JSON", value="json"),
                    questionary.Choice("CSV", value="csv"),
                ],
                default="json",
                style=custom_style,
            ).ask()
            
            from clonebox.cli.policy_audit_commands import cmd_audit_export
            args = type('Args', (), {
                'output': output_path,
                'since': None,
                'until': None,
                'event_type': None,
                'format': format_choice
            })()
            cmd_audit_export(args)


def interactive_plugin_menu():
    """Plugin management menu."""
    console.print("\n[bold cyan]Plugin Management[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("📋 List plugins", value="list"),
            questionary.Choice("✅ Enable plugin", value="enable"),
            questionary.Choice("❌ Disable plugin", value="disable"),
            questionary.Choice("🔍 Discover plugins", value="discover"),
            questionary.Choice("📦 Install plugin", value="install"),
            questionary.Choice("🗑️  Uninstall plugin", value="uninstall"),
            questionary.Choice("ℹ️  Plugin info", value="info"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    if choice == "list":
        from clonebox.cli.plugin_commands import cmd_plugin_list
        args = type('Args', (), {'verbose': False})()
        cmd_plugin_list(args)
        
    elif choice in ["enable", "disable", "uninstall", "info"]:
        # Get plugin list first
        from clonebox.plugins import get_plugin_manager
        manager = get_plugin_manager()
        plugins = manager.list_plugins()
        
        if not plugins:
            console.print("[dim]No plugins found[/]")
            return
        
        choices = [p["name"] for p in plugins]
        plugin_name = questionary.select(
            f"Select plugin to {choice}:",
            choices=choices,
            style=custom_style,
        ).ask()
        
        if plugin_name:
            if choice == "enable":
                from clonebox.cli.plugin_commands import cmd_plugin_enable
                args = type('Args', (), {'name': plugin_name})()
                cmd_plugin_enable(args)
            elif choice == "disable":
                from clonebox.cli.plugin_commands import cmd_plugin_disable
                args = type('Args', (), {'name': plugin_name})()
                cmd_plugin_disable(args)
            elif choice == "uninstall":
                from clonebox.cli.plugin_commands import cmd_plugin_uninstall
                args = type('Args', (), {'name': plugin_name, 'force': False})()
                cmd_plugin_uninstall(args)
            else:
                from clonebox.cli.plugin_commands import cmd_plugin_info
                args = type('Args', (), {'name': plugin_name})()
                cmd_plugin_info(args)
                
    elif choice == "discover":
        from clonebox.cli.plugin_commands import cmd_plugin_discover
        args = type('Args', (), {'paths': None, 'verbose': False})()
        cmd_plugin_discover(args)
        
    elif choice == "install":
        source = questionary.text(
            "Plugin source (file path or URL):",
            style=custom_style,
        ).ask()
        
        if source:
            global_install = questionary.confirm(
                "Install globally?",
                default=False,
                style=custom_style,
            ).ask()
            
            from clonebox.cli.plugin_commands import cmd_plugin_install
            args = type('Args', (), {'source': source, 'global_install': global_install})()
            cmd_plugin_install(args)


def interactive_compose_menu():
    """Compose menu for multi-VM management."""
    console.print("\n[bold cyan]Compose - Multi-VM Management[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("🚀 Start services", value="up"),
            questionary.Choice("⏹️  Stop services", value="down"),
            questionary.Choice("📋 Show status", value="status"),
            questionary.Choice("📜 Show logs", value="logs"),
            questionary.Choice("🔄 Restart services", value="restart"),
            questionary.Choice("💻 Execute command", value="exec"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    # Check for compose file
    compose_file = Path.cwd() / "clonebox-compose.yaml"
    if not compose_file.exists():
        compose_file = Path.cwd() / "docker-compose.yaml"  # Also check for docker-compose
    
    if not compose_file.exists():
        console.print("[dim]No compose file found in current directory[/]")
        console.print("[dim]Expected: clonebox-compose.yaml or docker-compose.yaml[/]")
        return
    
    if choice == "up":
        from clonebox.cli.compose_commands import cmd_compose_up
        args = type('Args', (), {
            'file': str(compose_file),
            'detach': True,
            'services': None
        })()
        cmd_compose_up(args)
        
    elif choice == "down":
        from clonebox.cli.compose_commands import cmd_compose_down
        args = type('Args', (), {
            'file': str(compose_file),
            'volumes': False,
            'services': None
        })()
        cmd_compose_down(args)
        
    elif choice == "status":
        from clonebox.cli.compose_commands import cmd_compose_status
        args = type('Args', (), {'file': str(compose_file)})()
        cmd_compose_status(args)
        
    elif choice == "logs":
        follow = questionary.confirm(
            "Follow log output?",
            default=False,
            style=custom_style,
        ).ask()
        
        from clonebox.cli.compose_commands import cmd_compose_logs
        args = type('Args', (), {
            'file': str(compose_file),
            'follow': follow,
            'lines': 50,
            'services': None
        })()
        cmd_compose_logs(args)
        
    elif choice == "restart":
        from clonebox.cli.compose_commands import cmd_compose_restart
        args = type('Args', (), {
            'file': str(compose_file),
            'services': None
        })()
        cmd_compose_restart(args)
        
    elif choice == "exec":
        # Load compose file to get services
        import yaml
        with open(compose_file) as f:
            compose_config = yaml.safe_load(f)
        
        services = list(compose_config.get("services", {}).keys())
        
        if not services:
            console.print("[dim]No services found in compose file[/]")
            return
        
        service = questionary.select(
            "Select service:",
            choices=services,
            style=custom_style,
        ).ask()
        
        command = questionary.text(
            "Command to execute:",
            style=custom_style,
        ).ask()
        
        if service and command:
            from clonebox.cli.compose_commands import cmd_compose_exec
            args = type('Args', (), {
                'file': str(compose_file),
                'service': service,
                'command': command.split(),
                'timeout': 30
            })()
            cmd_compose_exec(args)


def interactive_settings():
    """Settings menu."""
    console.print("\n[bold cyan]Settings[/]\n")
    
    choice = questionary.select(
        "What would you like to configure?",
        choices=[
            questionary.Choice("🔑 Default VM settings", value="vm_defaults"),
            questionary.Choice("🌐 Network settings", value="network"),
            questionary.Choice("📁 Default paths", value="paths"),
            questionary.Choice("🔧 Advanced settings", value="advanced"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    if choice == "vm_defaults":
        console.print("\n[bold]Default VM Settings[/]\n")
        
        # Load current settings
        config_dir = Path.home() / ".clonebox"
        settings_file = config_dir / "settings.yaml"
        
        settings = {}
        if settings_file.exists():
            with open(settings_file) as f:
                import yaml
                settings = yaml.safe_load(f) or {}
        
        vm_defaults = settings.get("vm_defaults", {})
        
        # Edit settings
        new_defaults = {}
        
        new_defaults["ram_mb"] = questionary.text(
            f"Default RAM (MB):",
            default=str(vm_defaults.get("ram_mb", 4096)),
            validate=lambda x: x.isdigit(),
            style=custom_style,
        ).ask()
        
        new_defaults["vcpus"] = questionary.text(
            f"Default vCPUs:",
            default=str(vm_defaults.get("vcpus", 4)),
            validate=lambda x: x.isdigit(),
            style=custom_style,
        ).ask()
        
        new_defaults["disk_size_gb"] = questionary.text(
            f"Default disk size (GB):",
            default=str(vm_defaults.get("disk_size_gb", 20)),
            validate=lambda x: x.isdigit(),
            style=custom_style,
        ).ask()
        
        new_defaults["gui"] = questionary.confirm(
            f"Enable GUI by default:",
            default=vm_defaults.get("gui", True),
            style=custom_style,
        ).ask()
        
        # Save settings
        settings["vm_defaults"] = {
            "ram_mb": int(new_defaults["ram_mb"]),
            "vcpus": int(new_defaults["vcpus"]),
            "disk_size_gb": int(new_defaults["disk_size_gb"]),
            "gui": new_defaults["gui"],
        }
        
        config_dir.mkdir(exist_ok=True)
        with open(settings_file, "w") as f:
            import yaml
            yaml.dump(settings, f, default_flow_style=False)
        
        console.print("[green]✅ Settings saved[/]")
        
    elif choice == "network":
        console.print("\n[bold]Network Settings[/]\n")
        
        console.print("[dim]Network configuration is handled per-VM in the VM config.[/]")
        console.print("[dim]Default network mode: auto[/]")
        
    elif choice == "paths":
        console.print("\n[bold]Default Paths[/]\n")
        
        config_dir = Path.home() / ".clonebox"
        console.print(f"Config directory: {config_dir}")
        console.print(f"VM images: /var/lib/libvirt/images")
        console.print(f"Base images: /var/lib/libvirt/base-images")
        
    elif choice == "advanced":
        console.print("\n[bold]Advanced Settings[/]\n")
        
        # Show current config
        config_dir = Path.home() / ".clonebox"
        settings_file = config_dir / "settings.yaml"
        
        if settings_file.exists():
            with open(settings_file) as f:
                import yaml
                settings = yaml.safe_load(f) or {}
            
            console.print("[bold]Current settings:[/]")
            console.print(str(settings))
        else:
            console.print("[dim]No settings file found[/]")
        
        # Reset option
        if questionary.confirm(
            "Reset all settings to defaults?",
            default=False,
            style=custom_style,
        ).ask():
            if settings_file.exists():
                settings_file.unlink()
                console.print("[green]✅ Settings reset[/]")
            else:
                console.print("[dim]No settings to reset[/]")
