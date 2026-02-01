"""
Base classes for CloneBox plugins.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List, Callable, Type


class PluginHook(Enum):
    """Available plugin hooks."""
    # VM Lifecycle
    PRE_VM_CREATE = "pre_vm_create"
    POST_VM_CREATE = "post_vm_create"
    PRE_VM_START = "pre_vm_start"
    POST_VM_START = "post_vm_start"
    PRE_VM_STOP = "pre_vm_stop"
    POST_VM_STOP = "post_vm_stop"
    PRE_VM_DELETE = "pre_vm_delete"
    POST_VM_DELETE = "post_vm_delete"

    # Snapshot
    PRE_SNAPSHOT_CREATE = "pre_snapshot_create"
    POST_SNAPSHOT_CREATE = "post_snapshot_create"
    PRE_SNAPSHOT_RESTORE = "pre_snapshot_restore"
    POST_SNAPSHOT_RESTORE = "post_snapshot_restore"

    # Health
    PRE_HEALTH_CHECK = "pre_health_check"
    POST_HEALTH_CHECK = "post_health_check"
    ON_HEALTH_FAILURE = "on_health_failure"

    # Config
    PRE_CONFIG_LOAD = "pre_config_load"
    POST_CONFIG_LOAD = "post_config_load"
    CONFIG_VALIDATE = "config_validate"

    # Cloud-init
    CLOUD_INIT_CUSTOMIZE = "cloud_init_customize"

    # Export/Import
    PRE_EXPORT = "pre_export"
    POST_EXPORT = "post_export"
    PRE_IMPORT = "pre_import"
    POST_IMPORT = "post_import"

    # CLI
    CLI_COMMAND_REGISTER = "cli_command_register"

    # System
    ON_ERROR = "on_error"
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"


@dataclass
class PluginMetadata:
    """Metadata about a plugin."""
    name: str
    version: str
    description: str = ""
    author: str = ""
    url: str = ""
    dependencies: List[str] = field(default_factory=list)
    hooks: List[PluginHook] = field(default_factory=list)
    config_schema: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "url": self.url,
            "dependencies": self.dependencies,
            "hooks": [h.value for h in self.hooks],
        }


@dataclass
class PluginContext:
    """Context passed to plugin hooks."""
    hook: PluginHook
    vm_name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    cloner: Optional[Any] = None
    console: Optional[Any] = None
    user_session: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    # For modification by plugins
    should_continue: bool = True
    modified_config: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Add an error message."""
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)

    def cancel(self, reason: str = "") -> None:
        """Cancel the operation."""
        self.should_continue = False
        if reason:
            self.add_error(reason)

    def add_detail(self, key: str, value: Any) -> None:
        """Add a detail to the context's extra dict."""
        self.extra[key] = value


class Plugin(ABC):
    """
    Base class for CloneBox plugins.

    Plugins can hook into various points of CloneBox's lifecycle to:
    - Modify configuration before VM creation
    - Add custom cloud-init scripts
    - Perform actions after VM operations
    - Add custom CLI commands
    - Integrate with external systems

    Example:
        class MyPlugin(Plugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="my-plugin",
                    version="1.0.0",
                    description="My custom plugin",
                    hooks=[PluginHook.POST_VM_CREATE],
                )

            def on_post_vm_create(self, ctx: PluginContext) -> None:
                # Do something after VM is created
                print(f"VM {ctx.vm_name} created!")
    """

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        pass

    def initialize(self, config: Dict[str, Any]) -> None:
        """
        Initialize the plugin with configuration.
        Called when plugin is loaded.
        """
        pass

    def shutdown(self) -> None:
        """
        Cleanup when plugin is unloaded.
        """
        pass

    # VM Lifecycle hooks
    def on_pre_vm_create(self, ctx: PluginContext) -> None:
        """Called before VM creation."""
        pass

    def on_post_vm_create(self, ctx: PluginContext) -> None:
        """Called after VM creation."""
        pass

    def on_pre_vm_start(self, ctx: PluginContext) -> None:
        """Called before VM start."""
        pass

    def on_post_vm_start(self, ctx: PluginContext) -> None:
        """Called after VM start."""
        pass

    def on_pre_vm_stop(self, ctx: PluginContext) -> None:
        """Called before VM stop."""
        pass

    def on_post_vm_stop(self, ctx: PluginContext) -> None:
        """Called after VM stop."""
        pass

    def on_pre_vm_delete(self, ctx: PluginContext) -> None:
        """Called before VM deletion."""
        pass

    def on_post_vm_delete(self, ctx: PluginContext) -> None:
        """Called after VM deletion."""
        pass

    # Snapshot hooks
    def on_pre_snapshot_create(self, ctx: PluginContext) -> None:
        """Called before snapshot creation."""
        pass

    def on_post_snapshot_create(self, ctx: PluginContext) -> None:
        """Called after snapshot creation."""
        pass

    def on_pre_snapshot_restore(self, ctx: PluginContext) -> None:
        """Called before snapshot restore."""
        pass

    def on_post_snapshot_restore(self, ctx: PluginContext) -> None:
        """Called after snapshot restore."""
        pass

    # Health hooks
    def on_pre_health_check(self, ctx: PluginContext) -> None:
        """Called before health check."""
        pass

    def on_post_health_check(self, ctx: PluginContext) -> None:
        """Called after health check."""
        pass

    def on_health_failure(self, ctx: PluginContext) -> None:
        """Called when health check fails."""
        pass

    # Config hooks
    def on_pre_config_load(self, ctx: PluginContext) -> None:
        """Called before config is loaded."""
        pass

    def on_post_config_load(self, ctx: PluginContext) -> None:
        """Called after config is loaded. Can modify ctx.modified_config."""
        pass

    def on_config_validate(self, ctx: PluginContext) -> None:
        """Called to validate config. Add errors to ctx.errors if invalid."""
        pass

    # Cloud-init hooks
    def on_cloud_init_customize(self, ctx: PluginContext) -> None:
        """
        Called to customize cloud-init.
        Modify ctx.extra['cloud_init'] to add custom cloud-init content.
        """
        pass

    # Export/Import hooks
    def on_pre_export(self, ctx: PluginContext) -> None:
        """Called before VM export."""
        pass

    def on_post_export(self, ctx: PluginContext) -> None:
        """Called after VM export."""
        pass

    def on_pre_import(self, ctx: PluginContext) -> None:
        """Called before VM import."""
        pass

    def on_post_import(self, ctx: PluginContext) -> None:
        """Called after VM import."""
        pass

    # CLI hooks
    def on_cli_command_register(self, ctx: PluginContext) -> None:
        """
        Called to register custom CLI commands.
        Add commands to ctx.extra['commands'].
        """
        pass

    # System hooks
    def on_error(self, ctx: PluginContext) -> None:
        """Called when an error occurs."""
        pass

    def on_startup(self, ctx: PluginContext) -> None:
        """Called on CloneBox startup."""
        pass

    def on_shutdown(self, ctx: PluginContext) -> None:
        """Called on CloneBox shutdown."""
        pass

    def handle_hook(self, hook: PluginHook, ctx: PluginContext) -> None:
        """Dispatch hook to appropriate handler method."""
        handler_map: Dict[PluginHook, Callable[[PluginContext], None]] = {
            PluginHook.PRE_VM_CREATE: self.on_pre_vm_create,
            PluginHook.POST_VM_CREATE: self.on_post_vm_create,
            PluginHook.PRE_VM_START: self.on_pre_vm_start,
            PluginHook.POST_VM_START: self.on_post_vm_start,
            PluginHook.PRE_VM_STOP: self.on_pre_vm_stop,
            PluginHook.POST_VM_STOP: self.on_post_vm_stop,
            PluginHook.PRE_VM_DELETE: self.on_pre_vm_delete,
            PluginHook.POST_VM_DELETE: self.on_post_vm_delete,
            PluginHook.PRE_SNAPSHOT_CREATE: self.on_pre_snapshot_create,
            PluginHook.POST_SNAPSHOT_CREATE: self.on_post_snapshot_create,
            PluginHook.PRE_SNAPSHOT_RESTORE: self.on_pre_snapshot_restore,
            PluginHook.POST_SNAPSHOT_RESTORE: self.on_post_snapshot_restore,
            PluginHook.PRE_HEALTH_CHECK: self.on_pre_health_check,
            PluginHook.POST_HEALTH_CHECK: self.on_post_health_check,
            PluginHook.ON_HEALTH_FAILURE: self.on_health_failure,
            PluginHook.PRE_CONFIG_LOAD: self.on_pre_config_load,
            PluginHook.POST_CONFIG_LOAD: self.on_post_config_load,
            PluginHook.CONFIG_VALIDATE: self.on_config_validate,
            PluginHook.CLOUD_INIT_CUSTOMIZE: self.on_cloud_init_customize,
            PluginHook.PRE_EXPORT: self.on_pre_export,
            PluginHook.POST_EXPORT: self.on_post_export,
            PluginHook.PRE_IMPORT: self.on_pre_import,
            PluginHook.POST_IMPORT: self.on_post_import,
            PluginHook.CLI_COMMAND_REGISTER: self.on_cli_command_register,
            PluginHook.ON_ERROR: self.on_error,
            PluginHook.ON_STARTUP: self.on_startup,
            PluginHook.ON_SHUTDOWN: self.on_shutdown,
        }

        handler = handler_map.get(hook)
        if handler:
            handler(ctx)
