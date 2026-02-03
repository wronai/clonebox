from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


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

    def __post_init__(self):
        if self.vm_dir is None:
            self.vm_dir = Path.home() / ".local/share/libvirt/images" / self.vm_name
