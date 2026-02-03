#!/usr/bin/env python3
"""
CloneBox CLI package.
"""

from .parsers import main
from .utils import (
    CLONEBOX_CONFIG_FILE,
    console,
    custom_style,
    deduplicate_list,
    generate_clonebox_yaml,
    load_clonebox_config,
)

# Re-export for tests
import questionary
from clonebox.cloner import SelectiveVMCloner
from clonebox.detector import SystemDetector
from clonebox.cli.vm_commands import cmd_detect
from clonebox.cli.misc_commands import cmd_clone
from clonebox.cli.utils import create_vm_from_config
from clonebox.audit import AuditQuery
from clonebox.cli.compose_commands import (
    cmd_compose_up,
    cmd_compose_down,
    cmd_compose_status,
    cmd_compose_logs,
)
from clonebox.orchestrator import Orchestrator
from clonebox.plugins.manager import get_plugin_manager
from clonebox.remote import RemoteCloner
from clonebox.cli.monitoring_commands import cmd_logs
from clonebox.cli.misc_commands import cmd_set_password
from rich.progress import Progress

__all__ = [
    "main",
    "CLONEBOX_CONFIG_FILE",
    "console",
    "custom_style",
    "deduplicate_list",
    "generate_clonebox_yaml",
    "load_clonebox_config",
    "SelectiveVMCloner",
    "SystemDetector",
    "cmd_detect",
    "cmd_clone",
    "create_vm_from_config",
    "Progress",
    "questionary",
    "AuditQuery",
    "cmd_compose_up",
    "cmd_compose_down",
    "cmd_compose_status",
    "cmd_compose_logs",
    "Orchestrator",
    "get_plugin_manager",
    "RemoteCloner",
    "cmd_logs",
    "cmd_set_password",
]
