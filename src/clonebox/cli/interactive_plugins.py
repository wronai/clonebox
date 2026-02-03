#!/usr/bin/env python3
"""
Interactive plugin management functions.
"""

import questionary
from rich.console import Console

from clonebox.cli.utils import console, custom_style


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
