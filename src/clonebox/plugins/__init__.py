"""
CloneBox Plugin System.

Provides extensibility through hooks and custom plugins.
"""
from clonebox.plugins.base import (
    Plugin,
    PluginHook,
    PluginContext,
    PluginMetadata,
)
from clonebox.plugins.manager import (
    PluginManager,
    get_plugin_manager,
)

__all__ = [
    "Plugin",
    "PluginHook",
    "PluginContext",
    "PluginMetadata",
    "PluginManager",
    "get_plugin_manager",
]
