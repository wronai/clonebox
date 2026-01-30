"""
CloneBox - Clone your workstation environment to an isolated VM.

Selectively clone applications, paths and services to a new virtual machine
with bind mounts instead of full disk cloning.
"""

__version__ = "0.1.12"
__author__ = "CloneBox Team"

from clonebox.cloner import SelectiveVMCloner
from clonebox.detector import SystemDetector

__all__ = ["SelectiveVMCloner", "SystemDetector", "__version__"]
