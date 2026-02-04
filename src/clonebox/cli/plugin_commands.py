#!/usr/bin/env python3
"""
Plugin management commands for CloneBox CLI.
"""

import json
from pathlib import Path

from rich.table import Table

from clonebox.plugins import get_plugin_manager, PluginHook, PluginContext
from clonebox.cli.utils import console


def cmd_plugin_list(args):
    """List available plugins."""
    from rich.table import Table
    from rich.panel import Panel
    
    plugin_manager = get_plugin_manager()
    
    if args.verbose:
        # Show detailed plugin information
        plugins = plugin_manager.get_all_plugins()
        
        if not plugins:
            console.print("[dim]No plugins found[/]")
            return
        
        for plugin in plugins:
            # Plugin info table
            table = Table(show_header=False)
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")
            
            table.add_row("Name", plugin["name"])
            table.add_row("Version", plugin["version"])
            table.add_row("Description", plugin["description"])
            table.add_row("Author", plugin.get("author", "Unknown"))
            table.add_row("Enabled", "✅ Yes" if plugin["enabled"] else "❌ No")
            
            if plugin.get("hooks"):
                table.add_row("Hooks", ", ".join(plugin["hooks"]))
            
            console.print(Panel(table, title=plugin["name"]))
    else:
        # Simple list
        plugins = plugin_manager.list_plugins()
        
        if not plugins:
            console.print("[dim]No plugins found[/]")
            return
        
        table = Table(title="Plugins")
        table.add_column("Name", style="cyan")
        table.add_column("Version", style="green")
        table.add_column("Status", style="yellow")
        
        for plugin in plugins:
            status = "✅ Enabled" if plugin["enabled"] else "❌ Disabled"
            status_style = "green" if plugin["enabled"] else "red"
            
            table.add_row(
                plugin["name"],
                plugin["version"],
                f"[{status_style}]{status}[/{status_style}]",
            )
        
        console.print(table)


def cmd_plugin_enable(args):
    """Enable a plugin."""
    plugin_manager = get_plugin_manager()
    
    try:
        plugin_manager.enable(args.name)
        console.print(f"[green]✅ Plugin '{args.name}' enabled[/]")
    except Exception as e:
        console.print(f"[red]❌ Failed to enable plugin: {e}[/]")


def cmd_plugin_disable(args):
    """Disable a plugin."""
    plugin_manager = get_plugin_manager()
    
    try:
        plugin_manager.disable(args.name)
        console.print(f"[green]✅ Plugin '{args.name}' disabled[/]")
    except Exception as e:
        console.print(f"[red]❌ Failed to disable plugin: {e}[/]")


def cmd_plugin_discover(args):
    """Discover available plugins in paths."""
    plugin_manager = get_plugin_manager()
    
    # Default plugin paths
    search_paths = [
        Path.home() / ".clonebox" / "plugins",
        Path("/etc/clonebox/plugins"),
        Path.cwd() / "plugins",
    ]
    
    # Add custom paths
    if args.paths:
        search_paths.extend(Path(p) for p in args.paths)
    
    discovered = []
    
    for path in search_paths:
        if path.exists():
            console.print(f"[cyan]Searching in: {path}[/]")
            found = plugin_manager.discover_plugins(path)
            discovered.extend(found)
    
    if discovered:
        console.print(f"\n[green]✅ Discovered {len(discovered)} plugins[/]")
        
        if args.verbose:
            for plugin in discovered:
                console.print(f"  • {plugin['name']} v{plugin['version']} - {plugin['description']}")
    else:
        console.print("[dim]No plugins discovered[/]")


def cmd_plugin_install(args):
    """Install a plugin from file or URL."""
    plugin_manager = get_plugin_manager()
    
    if args.source.startswith("http"):
        # Install from URL
        console.print(f"[cyan]Installing plugin from URL: {args.source}[/]")
        
        import requests
        try:
            response = requests.get(args.source)
            response.raise_for_status()
            
            # Save to temporary file
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = tmp.name
            
            # Install from temporary file
            plugin_manager.install_plugin(tmp_path, global_install=args.global_install)
            Path(tmp_path).unlink()  # Clean up
            
        except Exception as e:
            console.print(f"[red]❌ Failed to download plugin: {e}[/]")
            return
    else:
        # Install from local file
        plugin_path = Path(args.source)
        
        if not plugin_path.exists():
            console.print(f"[red]❌ Plugin file not found: {plugin_path}[/]")
            return
        
        console.print(f"[cyan]Installing plugin from: {plugin_path}[/]")
        plugin_manager.install_plugin(plugin_path, global_install=args.global_install)
    
    console.print("[green]✅ Plugin installed successfully[/]")


def cmd_plugin_uninstall(args):
    """Uninstall a plugin."""
    plugin_manager = get_plugin_manager()
    
    if not args.force:
        import questionary
        if not questionary.confirm(
            f"Uninstall plugin '{args.name}'?", 
            default=False, 
            style=custom_style
        ).ask():
            return
    
    try:
        plugin_manager.uninstall_plugin(args.name)
        console.print(f"[green]✅ Plugin '{args.name}' uninstalled[/]")
    except Exception as e:
        console.print(f"[red]❌ Failed to uninstall plugin: {e}[/]")


def cmd_plugin_info(args):
    """Show detailed plugin information."""
    plugin_manager = get_plugin_manager()
    
    plugin = plugin_manager.get_plugin_info(args.name)
    
    if not plugin:
        console.print(f"[red]❌ Plugin not found: {args.name}[/]")
        return
    
    from rich.panel import Panel
    from rich.table import Table
    
    # Plugin info table
    table = Table(show_header=False)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Name", plugin["name"])
    table.add_row("Version", plugin["version"])
    table.add_row("Description", plugin["description"])
    table.add_row("Author", plugin.get("author", "Unknown"))
    table.add_row("License", plugin.get("license", "Unknown"))
    table.add_row("Homepage", plugin.get("homepage", ""))
    table.add_row("Enabled", "✅ Yes" if plugin["enabled"] else "❌ No")
    table.add_row("Path", plugin["path"])
    
    if plugin.get("hooks"):
        table.add_row("Hooks", ", ".join(plugin["hooks"]))
    
    if plugin.get("dependencies"):
        table.add_row("Dependencies", ", ".join(plugin["dependencies"]))
    
    console.print(Panel(table, title=plugin["name"]))
    
    # Show configuration schema if available
    if plugin.get("config_schema"):
        console.print("\n[bold]Configuration Schema:[/]")
        console.print(json.dumps(plugin["config_schema"], indent=2))


def cmd_plugin_run(args):
    """Run a plugin hook manually."""
    plugin_manager = get_plugin_manager()
    
    # Parse hook name
    try:
        hook = PluginHook(args.hook)
    except ValueError:
        console.print(f"[red]❌ Invalid hook: {args.hook}[/]")
        console.print("[dim]Available hooks:[/]")
        for h in PluginHook:
            console.print(f"  • {h.value}")
        return
    
    # Create context
    context = PluginContext(
        vm_name=args.vm_name,
        user=args.user,
        config=args.config,
    )
    
    # Run hook
    console.print(f"[cyan]Running hook: {hook.value}[/]")
    
    try:
        results = plugin_manager.run_hook(hook, context)
        
        if results:
            console.print(f"\n[green]✅ Hook executed successfully[/]")
            
            if args.verbose:
                from rich.table import Table
                table = Table(title="Plugin Results")
                table.add_column("Plugin", style="cyan")
                table.add_column("Result", style="green")
                table.add_column("Duration", style="yellow")
                
                for result in results:
                    table.add_row(
                        result["plugin"],
                        "✅ Success" if result["success"] else "❌ Failed",
                        f"{result['duration']:.2f}s",
                    )
                
                console.print(table)
        else:
            console.print("[dim]No plugins responded to this hook[/]")
            
    except Exception as e:
        console.print(f"[red]❌ Hook execution failed: {e}[/]")
