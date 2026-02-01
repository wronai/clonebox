"""Tests for plugin system module."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clonebox.plugins.base import (
    Plugin,
    PluginHook,
    PluginContext,
    PluginMetadata,
)
from clonebox.plugins.manager import (
    PluginManager,
    LoadedPlugin,
    get_plugin_manager,
    set_plugin_manager,
    trigger_hook,
)


class TestPluginMetadata:
    """Test PluginMetadata dataclass."""

    def test_create_metadata(self):
        """Test creating plugin metadata."""
        metadata = PluginMetadata(
            name="test-plugin",
            version="1.0.0",
            description="A test plugin",
            author="Test Author",
            hooks=[PluginHook.POST_VM_CREATE, PluginHook.PRE_VM_START],
        )

        assert metadata.name == "test-plugin"
        assert metadata.version == "1.0.0"
        assert len(metadata.hooks) == 2

    def test_metadata_to_dict(self):
        """Test converting metadata to dictionary."""
        metadata = PluginMetadata(
            name="test-plugin",
            version="1.0.0",
            hooks=[PluginHook.POST_VM_CREATE],
        )

        d = metadata.to_dict()
        assert d["name"] == "test-plugin"
        assert d["version"] == "1.0.0"
        assert "post_vm_create" in d["hooks"]


class TestPluginContext:
    """Test PluginContext dataclass."""

    def test_create_context(self):
        """Test creating plugin context."""
        ctx = PluginContext(
            hook=PluginHook.POST_VM_CREATE,
            vm_name="test-vm",
            user_session=True,
        )

        assert ctx.hook == PluginHook.POST_VM_CREATE
        assert ctx.vm_name == "test-vm"
        assert ctx.should_continue is True

    def test_add_error(self):
        """Test adding error to context."""
        ctx = PluginContext(hook=PluginHook.POST_VM_CREATE)
        ctx.add_error("Something went wrong")

        assert len(ctx.errors) == 1
        assert "Something went wrong" in ctx.errors

    def test_add_warning(self):
        """Test adding warning to context."""
        ctx = PluginContext(hook=PluginHook.POST_VM_CREATE)
        ctx.add_warning("This is a warning")

        assert len(ctx.warnings) == 1
        assert "This is a warning" in ctx.warnings

    def test_cancel_operation(self):
        """Test canceling operation."""
        ctx = PluginContext(hook=PluginHook.PRE_VM_CREATE)
        ctx.cancel("Operation canceled by plugin")

        assert ctx.should_continue is False
        assert "Operation canceled by plugin" in ctx.errors


class SamplePlugin(Plugin):
    """Sample plugin for testing."""

    def __init__(self):
        self.calls = []

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="sample-plugin",
            version="1.0.0",
            description="A sample plugin for testing",
            hooks=[
                PluginHook.POST_VM_CREATE,
                PluginHook.PRE_VM_START,
                PluginHook.ON_ERROR,
            ],
        )

    def initialize(self, config):
        self.config = config
        self.calls.append(("initialize", config))

    def shutdown(self):
        self.calls.append(("shutdown",))

    def on_post_vm_create(self, ctx: PluginContext):
        self.calls.append(("post_vm_create", ctx.vm_name))
        ctx.add_detail("plugin_processed", True)

    def on_pre_vm_start(self, ctx: PluginContext):
        self.calls.append(("pre_vm_start", ctx.vm_name))

    def on_error(self, ctx: PluginContext):
        self.calls.append(("error", ctx.extra.get("error")))


class CancelingPlugin(Plugin):
    """Plugin that cancels operations."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="canceling-plugin",
            version="1.0.0",
            hooks=[PluginHook.PRE_VM_CREATE],
        )

    def on_pre_vm_create(self, ctx: PluginContext):
        ctx.cancel("Canceled by plugin")


class TestPlugin:
    """Test Plugin base class."""

    def test_sample_plugin_metadata(self):
        """Test getting plugin metadata."""
        plugin = SamplePlugin()
        metadata = plugin.metadata

        assert metadata.name == "sample-plugin"
        assert metadata.version == "1.0.0"
        assert len(metadata.hooks) == 3

    def test_handle_hook(self):
        """Test hook dispatch."""
        plugin = SamplePlugin()
        ctx = PluginContext(hook=PluginHook.POST_VM_CREATE, vm_name="test-vm")

        plugin.handle_hook(PluginHook.POST_VM_CREATE, ctx)

        assert ("post_vm_create", "test-vm") in plugin.calls

    def test_initialize_and_shutdown(self):
        """Test plugin lifecycle."""
        plugin = SamplePlugin()
        plugin.initialize({"key": "value"})
        plugin.shutdown()

        assert ("initialize", {"key": "value"}) in plugin.calls
        assert ("shutdown",) in plugin.calls


class TestPluginManager:
    """Test PluginManager class."""

    @pytest.fixture
    def plugin_dir(self, tmp_path):
        """Create a plugin directory with sample plugin."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()

        # Create a sample plugin file
        plugin_code = '''
from clonebox.plugins.base import Plugin, PluginMetadata, PluginHook, PluginContext

class FilePlugin(Plugin):
    @property
    def metadata(self):
        return PluginMetadata(
            name="file-plugin",
            version="1.0.0",
            hooks=[PluginHook.POST_VM_CREATE],
        )

    def on_post_vm_create(self, ctx: PluginContext):
        ctx.extra["file_plugin_called"] = True
'''
        (plugin_dir / "file_plugin.py").write_text(plugin_code)
        return plugin_dir

    def test_manager_init(self, tmp_path):
        """Test manager initialization."""
        manager = PluginManager(plugin_dirs=[tmp_path])

        assert tmp_path in manager.plugin_dirs

    def test_discover_plugins(self, plugin_dir):
        """Test discovering plugins."""
        manager = PluginManager(plugin_dirs=[plugin_dir])
        discovered = manager.discover()

        assert len(discovered) > 0
        assert any("file_plugin" in name for name in discovered)

    def test_load_plugin_class(self):
        """Test loading plugin from class."""
        manager = PluginManager(plugin_dirs=[])

        # Register plugin directly
        plugin = SamplePlugin()
        manager._plugins["sample-plugin"] = LoadedPlugin(
            plugin=plugin,
            metadata=plugin.metadata,
            config={},
            enabled=True,
            load_order=1,
        )

        # Register hooks
        for hook in plugin.metadata.hooks:
            manager._hooks[hook].append("sample-plugin")

        assert manager.has_plugin("sample-plugin")
        assert manager.get_plugin("sample-plugin") is plugin

    def test_trigger_hook(self):
        """Test triggering a hook."""
        manager = PluginManager(plugin_dirs=[])

        # Register plugin
        plugin = SamplePlugin()
        manager._plugins["sample-plugin"] = LoadedPlugin(
            plugin=plugin,
            metadata=plugin.metadata,
            config={},
            enabled=True,
            load_order=1,
        )
        manager._hooks[PluginHook.POST_VM_CREATE].append("sample-plugin")

        ctx = PluginContext(hook=PluginHook.POST_VM_CREATE, vm_name="test-vm")
        result = manager.trigger(PluginHook.POST_VM_CREATE, ctx)

        assert ("post_vm_create", "test-vm") in plugin.calls
        assert result.should_continue is True

    def test_trigger_cancel_stops_chain(self):
        """Test that canceling stops the plugin chain."""
        manager = PluginManager(plugin_dirs=[])

        # Register canceling plugin first
        canceling = CancelingPlugin()
        manager._plugins["canceling-plugin"] = LoadedPlugin(
            plugin=canceling,
            metadata=canceling.metadata,
            config={},
            enabled=True,
            load_order=1,
        )
        manager._hooks[PluginHook.PRE_VM_CREATE].append("canceling-plugin")

        # Register sample plugin second
        sample = SamplePlugin()
        manager._plugins["sample-plugin"] = LoadedPlugin(
            plugin=sample,
            metadata=sample.metadata,
            config={},
            enabled=True,
            load_order=2,
        )
        manager._hooks[PluginHook.PRE_VM_CREATE].append("sample-plugin")

        ctx = PluginContext(hook=PluginHook.PRE_VM_CREATE)
        result = manager.trigger(PluginHook.PRE_VM_CREATE, ctx)

        assert result.should_continue is False
        # Sample plugin should not have been called
        assert all(call[0] != "pre_vm_create" for call in sample.calls)

    def test_enable_disable_plugin(self):
        """Test enabling/disabling plugins."""
        manager = PluginManager(plugin_dirs=[])

        plugin = SamplePlugin()
        manager._plugins["sample-plugin"] = LoadedPlugin(
            plugin=plugin,
            metadata=plugin.metadata,
            config={},
            enabled=True,
            load_order=1,
        )

        manager.disable("sample-plugin")
        assert manager._plugins["sample-plugin"].enabled is False

        manager.enable("sample-plugin")
        assert manager._plugins["sample-plugin"].enabled is True

    def test_disabled_plugin_not_triggered(self):
        """Test that disabled plugins are not triggered."""
        manager = PluginManager(plugin_dirs=[])

        plugin = SamplePlugin()
        manager._plugins["sample-plugin"] = LoadedPlugin(
            plugin=plugin,
            metadata=plugin.metadata,
            config={},
            enabled=False,  # Disabled
            load_order=1,
        )
        manager._hooks[PluginHook.POST_VM_CREATE].append("sample-plugin")

        ctx = PluginContext(hook=PluginHook.POST_VM_CREATE)
        manager.trigger(PluginHook.POST_VM_CREATE, ctx)

        # Plugin should not have been called
        assert len(plugin.calls) == 0

    def test_list_plugins(self):
        """Test listing plugins."""
        manager = PluginManager(plugin_dirs=[])

        plugin = SamplePlugin()
        manager._plugins["sample-plugin"] = LoadedPlugin(
            plugin=plugin,
            metadata=plugin.metadata,
            config={},
            enabled=True,
            load_order=1,
        )

        plugins = manager.list_plugins()

        assert len(plugins) == 1
        assert plugins[0]["name"] == "sample-plugin"
        assert plugins[0]["enabled"] is True

    def test_unload_plugin(self):
        """Test unloading a plugin."""
        manager = PluginManager(plugin_dirs=[])

        plugin = SamplePlugin()
        manager._plugins["sample-plugin"] = LoadedPlugin(
            plugin=plugin,
            metadata=plugin.metadata,
            config={},
            enabled=True,
            load_order=1,
        )
        for hook in plugin.metadata.hooks:
            manager._hooks[hook].append("sample-plugin")

        manager.unload("sample-plugin")

        assert "sample-plugin" not in manager._plugins
        assert ("shutdown",) in plugin.calls


class TestGlobalPluginManager:
    """Test global plugin manager functions."""

    def test_get_plugin_manager(self):
        """Test getting global manager."""
        manager = get_plugin_manager()
        assert isinstance(manager, PluginManager)

    def test_set_plugin_manager(self, tmp_path):
        """Test setting global manager."""
        custom_manager = PluginManager(plugin_dirs=[tmp_path])
        set_plugin_manager(custom_manager)

        manager = get_plugin_manager()
        assert tmp_path in manager.plugin_dirs

    def test_trigger_hook_convenience(self):
        """Test trigger_hook convenience function."""
        # Reset to clean manager
        manager = PluginManager(plugin_dirs=[])
        set_plugin_manager(manager)

        ctx = trigger_hook(PluginHook.POST_VM_CREATE, vm_name="test-vm")

        assert isinstance(ctx, PluginContext)
        assert ctx.vm_name == "test-vm"


class TestPluginHooks:
    """Test all plugin hooks are properly handled."""

    def test_all_hooks_exist(self):
        """Test that all hooks are defined."""
        expected_hooks = [
            "PRE_VM_CREATE", "POST_VM_CREATE",
            "PRE_VM_START", "POST_VM_START",
            "PRE_VM_STOP", "POST_VM_STOP",
            "PRE_VM_DELETE", "POST_VM_DELETE",
            "PRE_SNAPSHOT_CREATE", "POST_SNAPSHOT_CREATE",
            "PRE_SNAPSHOT_RESTORE", "POST_SNAPSHOT_RESTORE",
            "PRE_HEALTH_CHECK", "POST_HEALTH_CHECK", "ON_HEALTH_FAILURE",
            "PRE_CONFIG_LOAD", "POST_CONFIG_LOAD", "CONFIG_VALIDATE",
            "CLOUD_INIT_CUSTOMIZE",
            "PRE_EXPORT", "POST_EXPORT",
            "PRE_IMPORT", "POST_IMPORT",
            "CLI_COMMAND_REGISTER",
            "ON_ERROR", "ON_STARTUP", "ON_SHUTDOWN",
        ]

        for hook_name in expected_hooks:
            assert hasattr(PluginHook, hook_name)

    def test_plugin_has_handler_for_each_hook(self):
        """Test that Plugin base class has handler for each hook."""
        plugin = SamplePlugin()

        # Each hook should have a corresponding handler method
        handler_methods = [
            "on_pre_vm_create", "on_post_vm_create",
            "on_pre_vm_start", "on_post_vm_start",
            "on_pre_vm_stop", "on_post_vm_stop",
            "on_pre_vm_delete", "on_post_vm_delete",
            "on_pre_snapshot_create", "on_post_snapshot_create",
            "on_pre_snapshot_restore", "on_post_snapshot_restore",
            "on_pre_health_check", "on_post_health_check", "on_health_failure",
            "on_pre_config_load", "on_post_config_load", "on_config_validate",
            "on_cloud_init_customize",
            "on_pre_export", "on_post_export",
            "on_pre_import", "on_post_import",
            "on_cli_command_register",
            "on_error", "on_startup", "on_shutdown",
        ]

        for method_name in handler_methods:
            assert hasattr(plugin, method_name)
            assert callable(getattr(plugin, method_name))
