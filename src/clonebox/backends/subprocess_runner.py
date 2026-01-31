"""Subprocess process runner implementation."""

import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from ..interfaces.process import ProcessResult, ProcessRunner


class SubprocessRunner(ProcessRunner):
    """Run processes using the subprocess module."""

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
        result = subprocess.run(
            command,
            capture_output=capture_output,
            timeout=timeout,
            check=check,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
        )
        return ProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def run_shell(
        self,
        command: str,
        capture_output: bool = True,
        timeout: Optional[int] = None,
    ) -> ProcessResult:
        """Run a shell command."""
        result = subprocess.run(
            command,
            shell=True,
            capture_output=capture_output,
            timeout=timeout,
            text=True,
        )
        return ProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
