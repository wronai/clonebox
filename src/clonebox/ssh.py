"""
Shared SSH helpers for CloneBox.

Consolidates the SSH command building, execution, and connectivity
testing that was previously duplicated across cloner.py, validation/core.py,
browser_profiles.py, and cli/misc_commands.py.
"""

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

import structlog

from clonebox.paths import resolve_ssh_port, ssh_key_path

log = structlog.get_logger(__name__)

# ── default SSH flags (used everywhere) ──────────────────────────────────────

DEFAULT_SSH_OPTS: List[str] = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "BatchMode=yes",
]


# ── command builder ──────────────────────────────────────────────────────────

def build_ssh_command(
    port: int,
    key: Optional[Path] = None,
    username: str = "ubuntu",
    host: str = "127.0.0.1",
    connect_timeout: int = 10,
    log_level: Optional[str] = None,
    extra_opts: Optional[List[str]] = None,
) -> List[str]:
    """Build a reusable SSH base command list.

    >>> cmd = build_ssh_command(22196, Path("/tmp/key"))
    >>> cmd[:2]
    ['ssh', '-o']
    """
    cmd: List[str] = ["ssh"] + list(DEFAULT_SSH_OPTS)
    cmd.extend(["-o", f"ConnectTimeout={connect_timeout}"])
    if log_level:
        cmd.extend(["-o", f"LogLevel={log_level}"])
    if key is not None:
        cmd.extend(["-i", str(key)])
    cmd.extend(["-p", str(port)])
    if extra_opts:
        cmd.extend(extra_opts)
    cmd.append(f"{username}@{host}")
    return cmd


# ── single-command execution ─────────────────────────────────────────────────

def ssh_exec(
    port: int,
    key: Optional[Path],
    command: str,
    username: str = "ubuntu",
    host: str = "127.0.0.1",
    timeout: int = 20,
    connect_timeout: int = 10,
) -> Optional[str]:
    """Execute *command* on *host* via SSH and return stripped stdout.

    Returns ``None`` on any error (non-zero exit, timeout, missing ssh binary).
    """
    if shutil.which("ssh") is None:
        log.warning("ssh_client_not_found")
        return None

    cmd = build_ssh_command(
        port=port, key=key, username=username, host=host,
        connect_timeout=connect_timeout,
    )
    cmd.append(command)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log.debug("ssh_timeout", command=command[:60], timeout=timeout)
        return None
    except Exception as exc:
        log.debug("ssh_exec_error", error=str(exc))
        return None

    if result.returncode != 0:
        log.debug("ssh_nonzero", rc=result.returncode, stderr=result.stderr.strip()[:120])
        return None
    return (result.stdout or "").strip()


def ssh_run(
    port: int,
    key: Optional[Path],
    command: str,
    username: str = "ubuntu",
    host: str = "127.0.0.1",
    timeout: int = 20,
    connect_timeout: int = 10,
) -> subprocess.CompletedProcess:
    """Like :func:`ssh_exec` but returns the full ``CompletedProcess``."""
    cmd = build_ssh_command(
        port=port, key=key, username=username, host=host,
        connect_timeout=connect_timeout,
    )
    cmd.append(command)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ── convenience: resolve port + key from VM name, then exec ──────────────────

def vm_ssh_exec(
    vm_name: str,
    command: str,
    username: str = "ubuntu",
    user_session: bool = True,
    timeout: int = 20,
) -> Optional[str]:
    """Resolve SSH port & key for *vm_name* automatically, then execute."""
    port = resolve_ssh_port(vm_name, user_session)
    key = ssh_key_path(vm_name, user_session)
    return ssh_exec(port=port, key=key, command=command,
                    username=username, timeout=timeout)
