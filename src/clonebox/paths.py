"""
Canonical path helpers for CloneBox VM directories, SSH keys, and ports.

Every module that needs to locate VM artifacts (disk images, SSH keys,
serial logs, port files) should import from here instead of computing
paths inline.
"""

import os
import zlib
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


# ── libvirt connection URI ───────────────────────────────────────────────────

def conn_uri(user_session: bool = True) -> str:
    """Return the libvirt connection URI for the given session type."""
    return "qemu:///session" if user_session else "qemu:///system"


# ── directory roots ──────────────────────────────────────────────────────────

def user_images_dir() -> Path:
    """~/.local/share/libvirt/images (user-session VMs)."""
    return Path(
        os.getenv("CLONEBOX_USER_IMAGES_DIR",
                   str(Path.home() / ".local/share/libvirt/images"))
    )


def system_images_dir() -> Path:
    """/var/lib/libvirt/images (system-session VMs)."""
    return Path(os.getenv("CLONEBOX_SYSTEM_IMAGES_DIR", "/var/lib/libvirt/images"))


def images_dir(user_session: bool = True) -> Path:
    """Return the appropriate images root for the given session type."""
    return user_images_dir() if user_session else system_images_dir()


def vm_dir(vm_name: str, user_session: bool = True) -> Path:
    """Per-VM directory that holds disk, ssh_key, serial.log, etc."""
    return images_dir(user_session) / vm_name


# ── SSH artefacts ────────────────────────────────────────────────────────────

def ssh_key_path(vm_name: str, user_session: bool = True) -> Optional[Path]:
    """Return the SSH private key path if it exists on disk."""
    p = vm_dir(vm_name, user_session) / "ssh_key"
    return p if p.exists() else None


def ssh_port_file(vm_name: str, user_session: bool = True) -> Path:
    """Path to the file that persists the allocated SSH forward port."""
    return vm_dir(vm_name, user_session) / "ssh_port"


def serial_log_path(vm_name: str, user_session: bool = True) -> Path:
    """Path to the QEMU serial log for a VM."""
    return vm_dir(vm_name, user_session) / "serial.log"


# ── SSH port resolution ─────────────────────────────────────────────────────

def fallback_ssh_port(vm_name: str) -> int:
    """Deterministic fallback port derived from the VM name (22000–22999)."""
    return 22000 + (zlib.crc32(vm_name.encode("utf-8")) % 1000)


def resolve_ssh_port(vm_name: str, user_session: bool = True) -> int:
    """Resolve the SSH forward port for *vm_name*.

    Resolution order:
      1. ``<vm_dir>/ssh_port`` file
      2. Legacy ``~/.local/share/clonebox/<vm_name>.ssh_port``
      3. Deterministic fallback ``22000 + crc32(name) % 1000``
    """
    # 1. Primary location
    pf = ssh_port_file(vm_name, user_session)
    if pf.exists():
        try:
            port = int(pf.read_text().strip())
            if 1 <= port <= 65535:
                return port
        except Exception as exc:
            log.debug("bad_ssh_port_file", path=str(pf), error=str(exc))

    # 2. Legacy location
    alt = Path.home() / ".local/share/clonebox" / f"{vm_name}.ssh_port"
    if alt.exists():
        try:
            port = int(alt.read_text().strip())
            if 1 <= port <= 65535:
                return port
        except Exception as exc:
            log.debug("bad_alt_ssh_port_file", path=str(alt), error=str(exc))

    # 3. Fallback
    fb = fallback_ssh_port(vm_name)
    log.debug("ssh_port_fallback", vm_name=vm_name, port=fb)
    return fb


def save_ssh_port(vm_name: str, port: int, user_session: bool = True) -> None:
    """Persist the SSH forward port for later retrieval."""
    d = vm_dir(vm_name, user_session)
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "ssh_port").write_text(str(port))
    except PermissionError:
        alt = Path.home() / ".local/share/clonebox"
        alt.mkdir(parents=True, exist_ok=True)
        (alt / f"{vm_name}.ssh_port").write_text(str(port))
        log.warning("ssh_port_saved_alt", path=str(alt / f"{vm_name}.ssh_port"))
    except Exception as exc:
        log.error("ssh_port_save_failed", error=str(exc))
