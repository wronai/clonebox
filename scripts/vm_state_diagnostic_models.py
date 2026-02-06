import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if os.path.isdir(_src) and _src not in sys.path:
    sys.path.insert(0, _src)

try:
    from clonebox.paths import vm_dir as _vm_dir
    _HAS_PKG = True
except ImportError:
    _HAS_PKG = False


class TestStatus(Enum):
    PASS = "✅ PASS"
    FAIL = "❌ FAIL"
    SKIP = "⏭️ SKIP"
    WAIT = "⏳ WAIT"
    WARN = "⚠️ WARN"
    INFO = "ℹ️ INFO"


@dataclass
class TestResult:
    name: str
    question: str
    status: TestStatus
    answer: str
    details: Dict[str, Any] = field(default_factory=dict)
    diagnosis: str = ""
    suggestion: str = ""
    blocking: bool = False  # If True, failures block dependent tests


@dataclass
class DiagnosticContext:
    vm_name: str
    conn_uri: str = "qemu:///session"
    vm_dir: Path = None
    results: List[TestResult] = field(default_factory=list)

    # Cached state
    vm_exists: bool = False
    vm_running: bool = False
    ssh_port: Optional[int] = None
    ssh_key_path: Optional[Path] = None
    passt_active: bool = False
    qga_responding: bool = False
    ssh_works: bool = False
    has_ipv4: bool = False
    cloud_init_done: bool = False

    # Browser state
    browsers_detected: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    firefox_profile_ok: bool = False
    chrome_profile_ok: bool = False
    chromium_profile_ok: bool = False

    def __post_init__(self):
        if self.vm_dir is None:
            if _HAS_PKG:
                self.vm_dir = _vm_dir(self.vm_name)
            else:
                self.vm_dir = Path.home() / ".local/share/libvirt/images" / self.vm_name
