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
from clonebox.cloner import SelectiveVMCloner
from clonebox.detector import SystemDetector
from clonebox.cli.vm_commands import cmd_detect
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
    "Progress",
]
