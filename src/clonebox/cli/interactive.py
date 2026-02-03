#!/usr/bin/env python3
"""
Interactive mode for CloneBox CLI.
"""

import questionary
from rich.console import Console

from clonebox import __version__
from clonebox.cli.utils import console, custom_style, print_banner

# Import interactive module functions
from clonebox.cli.interactive_vm import interactive_create_vm, interactive_start_vm, interactive_list_vms
from clonebox.cli.interactive_container import interactive_container_menu
from clonebox.cli.interactive_snapshots import interactive_snapshot_menu
from clonebox.cli.interactive_monitor import interactive_monitor, interactive_health_check
from clonebox.cli.interactive_ssh import interactive_ssh_menu
from clonebox.cli.interactive_import_export import interactive_import_export_menu
from clonebox.cli.interactive_remote import interactive_remote_menu
from clonebox.cli.interactive_audit import interactive_audit_menu
from clonebox.cli.interactive_plugins import interactive_plugin_menu
from clonebox.cli.interactive_compose import interactive_compose_menu
from clonebox.cli.interactive_settings import interactive_settings


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
