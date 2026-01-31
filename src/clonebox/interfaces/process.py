"""Abstract interface for process execution."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ProcessResult:
    """Result of process execution."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


class ProcessRunner(ABC):
    """Abstract interface for process execution."""

    @abstractmethod
    def run(
        self,
        command: List[str],
        capture_output: bool = True,
        timeout: Optional[int] = None,
        check: bool = True,
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> ProcessResult:
        """Run a command."""
        pass

    @abstractmethod
    def run_shell(
        self,
        command: str,
        capture_output: bool = True,
        timeout: Optional[int] = None,
    ) -> ProcessResult:
        """Run a shell command."""
        pass
