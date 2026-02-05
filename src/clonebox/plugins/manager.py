"""
Plugin manager for CloneBox.
Handles plugin discovery, loading, and lifecycle.
"""
import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List, Type, Set
import threading
import yaml

from clonebox.plugins.base import Plugin, PluginHook, PluginContext, PluginMetadata


@dataclass
class LoadedPlugin:
    """Information about a loaded plugin."""
    plugin: Plugin
    metadata: PluginMetadata
    config: Dict[str, Any]
    enabled: bool = True
    load_order: int = 0


class PluginManager:
    """
    Manages CloneBox plugins.

    Plugins can be loaded from:
    - Built-in plugins (clonebox.plugins.builtin.*)
    - User plugins (~/.clonebox.d/plugins/)
    - Project plugins (.clonebox.d/plugins/)
    - Python packages (clonebox_plugin_*)

    Usage:
        manager = PluginManager()
        manager.discover()
        manager.load_all()

        # Trigger a hook
        ctx = PluginContext(hook=PluginHook.POST_VM_CREATE, vm_name="my-vm")
        manager.trigger(PluginHook.POST_VM_CREATE, ctx)
    """

    DEFAULT_PLUGIN_DIRS = [
        Path.home() / ".clonebox.d" / "plugins",
        Path(".clonebox.d") / "plugins",
    ]

    def __init__(
        self,
        plugin_dirs: Optional[List[Path]] = None,
        config_path: Optional[Path] = None,
    ):
        self._plugins: Dict[str, LoadedPlugin] = {}
        self._hooks: Dict[PluginHook, List[str]] = {hook: [] for hook in PluginHook}
        self._lock = threading.Lock()
        self._load_order = 0

        # Plugin directories
        self.plugin_dirs = plugin_dirs or self.DEFAULT_PLUGIN_DIRS

        # Plugin configuration
        self.config_path = config_path or Path.home() / ".clonebox.d" / "plugins.yaml"
        self._plugin_config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load plugin configuration."""
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return {}
        return {}

    def _save_config(self) -> None:
        """Save plugin configuration."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            yaml.dump(self._plugin_config, f, default_flow_style=False)

    def discover(self) -> List[str]:
        """
        Discover available plugins.
        Returns list of discovered plugin names.
        """
        discovered: List[str] = []

        # Discover from plugin directories
        for plugin_dir in self.plugin_dirs:
            if plugin_dir.exists() and plugin_dir.is_dir():
                for item in plugin_dir.iterdir():
                    if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
                        name = item.stem
                        discovered.append(f"file:{name}")
                    elif item.is_dir() and (item / "__init__.py").exists():
                        discovered.append(f"file:{item.name}")

        # Discover installed packages (clonebox_plugin_*)
        try:
            import pkg_resources
            for ep in pkg_resources.iter_entry_points("clonebox.plugins"):
                discovered.append(f"pkg:{ep.name}")
        except ImportError:
            pass

        return discovered

    def load(self, plugin_name: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Load a specific plugin.

        Args:
            plugin_name: Plugin name (can be prefixed with file: or pkg:)
            config: Plugin-specific configuration

        Returns:
            True if loaded successfully
        """
        with self._lock:
            if plugin_name in self._plugins:
                return True  # Already loaded

            try:
                plugin_class = self._import_plugin(plugin_name)
                if plugin_class is None:
                    return False

                plugin = plugin_class()
                metadata = plugin.metadata

                # Get config
                plugin_config = config or self._plugin_config.get(metadata.name, {})

                # Check dependencies
                for dep in metadata.dependencies:
                    if dep not in self._plugins:
                        # Try to load dependency
                        if not self.load(dep):
                            raise RuntimeError(f"Missing dependency: {dep}")

                # Initialize plugin
                plugin.initialize(plugin_config)

                # Register plugin
                self._load_order += 1
                loaded = LoadedPlugin(
                    plugin=plugin,
                    metadata=metadata,
                    config=plugin_config,
                    enabled=True,
                    load_order=self._load_order,
                )
                self._plugins[metadata.name] = loaded

                # Register hooks
                for hook in metadata.hooks:
                    self._hooks[hook].append(metadata.name)

                return True

            except Exception as e:
                import sys
                print(f"Failed to load plugin {plugin_name}: {e}", file=sys.stderr)
                return False

    def _import_plugin(self, plugin_name: str) -> Optional[Type[Plugin]]:
        """Import a plugin class."""
        if plugin_name.startswith("file:"):
            return self._import_file_plugin(plugin_name[5:])
        elif plugin_name.startswith("pkg:"):
            return self._import_package_plugin(plugin_name[4:])
        else:
            # Try both
            plugin_class = self._import_package_plugin(plugin_name)
            if plugin_class:
                return plugin_class
            return self._import_file_plugin(plugin_name)

    def _import_file_plugin(self, name: str) -> Optional[Type[Plugin]]:
        """Import plugin from file."""
        for plugin_dir in self.plugin_dirs:
            # Try as single file
            plugin_file = plugin_dir / f"{name}.py"
            if plugin_file.exists():
                return self._load_module_from_file(name, plugin_file)

            # Try as package
            plugin_pkg = plugin_dir / name / "__init__.py"
            if plugin_pkg.exists():
                return self._load_module_from_file(name, plugin_pkg)

        return None

    def _load_module_from_file(self, name: str, path: Path) -> Optional[Type[Plugin]]:
        """Load a module from file and find Plugin class."""
        try:
            spec = importlib.util.spec_from_file_location(f"clonebox_plugin_{name}", path)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

            # Find Plugin subclass
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Plugin)
                    and attr is not Plugin
                ):
                    return attr

            return None

        except Exception:
            return None

    def _import_package_plugin(self, name: str) -> Optional[Type[Plugin]]:
        """Import plugin from installed package."""
        try:
            import pkg_resources
            for ep in pkg_resources.iter_entry_points("clonebox.plugins"):
                if ep.name == name:
                    plugin_class = ep.load()
                    if issubclass(plugin_class, Plugin):
                        return plugin_class
        except ImportError:
            pass

        # Try direct import
        try:
            module = importlib.import_module(f"clonebox_plugin_{name}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Plugin)
                    and attr is not Plugin
                ):
                    return attr
        except ImportError:
            pass

        return None

    def load_all(self, only_enabled: bool = True) -> int:
        """
        Load all discovered plugins.

        Args:
            only_enabled: Only load plugins marked as enabled in config

        Returns:
            Number of plugins loaded
        """
        discovered = self.discover()
        loaded_count = 0

        # Get enabled plugins from config
        enabled = set(self._plugin_config.get("enabled", []))
        disabled = set(self._plugin_config.get("disabled", []))

        for plugin_name in discovered:
            # Extract base name
            base_name = plugin_name.split(":", 1)[-1]

            # Check if enabled/disabled
            if only_enabled:
                if base_name in disabled:
                    continue
                if enabled and base_name not in enabled:
                    continue

            if self.load(plugin_name):
                loaded_count += 1

        return loaded_count

    def unload(self, plugin_name: str) -> bool:
        """Unload a plugin."""
        with self._lock:
            if plugin_name not in self._plugins:
                return False

            loaded = self._plugins[plugin_name]

            # Check for dependents
            for name, other in self._plugins.items():
                if plugin_name in other.metadata.dependencies:
                    raise RuntimeError(f"Cannot unload: {name} depends on {plugin_name}")

            # Shutdown plugin
            try:
                loaded.plugin.shutdown()
            except Exception:
                pass

            # Remove from hooks
            for hook in loaded.metadata.hooks:
                if plugin_name in self._hooks[hook]:
                    self._hooks[hook].remove(plugin_name)

            # Remove plugin
            del self._plugins[plugin_name]

            return True

    def unload_all(self) -> None:
        """Unload all plugins in reverse load order."""
        # Sort by load order descending
        plugins = sorted(
            self._plugins.values(),
            key=lambda p: p.load_order,
            reverse=True,
        )

        for loaded in plugins:
            try:
                self.unload(loaded.metadata.name)
            except Exception:
                pass

    def trigger(self, hook: PluginHook, ctx: PluginContext) -> PluginContext:
        """
        Trigger a hook on all registered plugins.

        Args:
            hook: The hook to trigger
            ctx: Context to pass to plugins

        Returns:
            The context (possibly modified by plugins)
        """
        ctx.hook = hook

        for plugin_name in self._hooks.get(hook, []):
            if not ctx.should_continue:
                break

            loaded = self._plugins.get(plugin_name)
            if loaded and loaded.enabled:
                try:
                    loaded.plugin.handle_hook(hook, ctx)
                except Exception as e:
                    ctx.add_warning(f"Plugin {plugin_name} error: {e}")

        return ctx

    def enable(self, plugin_name: str) -> bool:
        """Enable a plugin."""
        with self._lock:
            if plugin_name in self._plugins:
                self._plugins[plugin_name].enabled = True

            # Update config
            disabled = set(self._plugin_config.get("disabled", []))
            disabled.discard(plugin_name)
            self._plugin_config["disabled"] = list(disabled)

            enabled = set(self._plugin_config.get("enabled", []))
            enabled.add(plugin_name)
            self._plugin_config["enabled"] = list(enabled)

            self._save_config()
            return True

    def disable(self, plugin_name: str) -> bool:
        """Disable a plugin."""
        with self._lock:
            if plugin_name in self._plugins:
                self._plugins[plugin_name].enabled = False

            # Update config
            enabled = set(self._plugin_config.get("enabled", []))
            enabled.discard(plugin_name)
            self._plugin_config["enabled"] = list(enabled)

            disabled = set(self._plugin_config.get("disabled", []))
            disabled.add(plugin_name)
            self._plugin_config["disabled"] = list(disabled)

            self._save_config()
            return True

    def install(self, source: str) -> bool:
        """
        Install a plugin from a source.

        Sources:
        - PyPI package name: "clonebox-plugin-kubernetes"
        - Git URL: "git+https://github.com/user/plugin.git"
        - Local path: "/path/to/plugin"

        Returns True if installation succeeded.
        """
        import subprocess

        # Handle local path
        if Path(source).exists():
            target_dir = self.plugin_dirs[0]  # User plugins dir
            target_dir.mkdir(parents=True, exist_ok=True)
            source_path = Path(source)

            if source_path.is_file() and source_path.suffix == ".py":
                # Single file plugin
                import shutil
                shutil.copy(source_path, target_dir / source_path.name)
                return True
            elif source_path.is_dir():
                # Directory plugin
                import shutil
                target = target_dir / source_path.name
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source_path, target)
                return True

        # Handle pip installable (PyPI or git)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--user", source],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for pip install
            )
            return result.returncode == 0
        except Exception:
            return False

    def uninstall(self, name: str) -> bool:
        """
        Uninstall a plugin.

        Returns True if uninstallation succeeded.
        """
        import subprocess

        # Check if it's a local plugin
        for plugin_dir in self.plugin_dirs:
            plugin_path = plugin_dir / f"{name}.py"
            plugin_pkg = plugin_dir / name

            if plugin_path.exists():
                plugin_path.unlink()
                return True
            if plugin_pkg.exists() and plugin_pkg.is_dir():
                import shutil
                shutil.rmtree(plugin_pkg)
                return True

        # Try pip uninstall
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", f"clonebox-plugin-{name}"],
                capture_output=True,
                text=True,
                timeout=60,  # 1 minute timeout for pip uninstall
            )
            if result.returncode == 0:
                return True

            # Try with original name
            result = subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", name],
                capture_output=True,
                text=True,
                timeout=60,  # 1 minute timeout
            )
            return result.returncode == 0
        except Exception:
            return False

    def list_plugins(self) -> List[Dict[str, Any]]:
        """List all loaded plugins."""
        return [
            {
                **loaded.metadata.to_dict(),
                "enabled": loaded.enabled,
                "load_order": loaded.load_order,
            }
            for loaded in sorted(self._plugins.values(), key=lambda p: p.load_order)
        ]

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """Get a loaded plugin by name."""
        loaded = self._plugins.get(name)
        return loaded.plugin if loaded else None

    def has_plugin(self, name: str) -> bool:
        """Check if a plugin is loaded."""
        return name in self._plugins


# Global plugin manager
_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    """Get the global plugin manager."""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager


def set_plugin_manager(manager: PluginManager) -> None:
    """Set the global plugin manager (useful for testing)."""
    global _plugin_manager
    _plugin_manager = manager


def trigger_hook(hook: PluginHook, **kwargs: Any) -> PluginContext:
    """
    Convenience function to trigger a hook.

    Usage:
        ctx = trigger_hook(PluginHook.POST_VM_CREATE, vm_name="my-vm")
    """
    ctx = PluginContext(hook=hook, **kwargs)
    return get_plugin_manager().trigger(hook, ctx)
