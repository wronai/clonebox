#!/usr/bin/env python3
"""
Interactive VM management functions.
"""

import secrets
import string
from pathlib import Path
from typing import Dict, List

import questionary
from rich.console import Console

from clonebox.cli.utils import console, custom_style, CLONEBOX_CONFIG_FILE, load_clonebox_config, create_vm_from_config


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
