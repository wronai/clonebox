#!/usr/bin/env python3
"""
Interactive settings functions.
"""

import yaml
from pathlib import Path

import questionary
from rich.console import Console

from clonebox.cli.utils import console, custom_style


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
