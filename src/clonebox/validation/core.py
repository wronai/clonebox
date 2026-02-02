import base64
import json
import shutil
import subprocess
import time
import zlib
from pathlib import Path
from typing import Dict, Optional

from rich.console import Console


class VMValidatorCore:
    def __init__(
        self,
        config: dict,
        vm_name: str,
        conn_uri: str,
        console: Console = None,
        require_running_apps: bool = False,
        smoke_test: bool = False,
    ):
        self.config = config
        self.vm_name = vm_name
        self.conn_uri = conn_uri
        self.console = console or Console()
        self.require_running_apps = require_running_apps
        self.smoke_test = smoke_test
        self.results = {
            "mounts": {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "details": []},
            "packages": {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "details": []},
            "snap_packages": {
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "total": 0,
                "details": [],
            },
            "services": {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "details": []},
            "disk": {"usage_pct": 0, "avail": "0", "total": "0"},
            "apps": {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "details": []},
            "smoke": {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "details": []},
            "overall": "unknown",
        }

        self._setup_in_progress_cache: Optional[bool] = None
        self._exec_transport: str = "qga"  # qga|ssh

    def _get_ssh_key_path(self) -> Optional[Path]:
        """Return path to the SSH key generated for this VM (if present)."""
        try:
            if self.conn_uri.endswith("/session"):
                images_dir = Path.home() / ".local/share/libvirt/images"
            else:
                images_dir = Path("/var/lib/libvirt/images")
            key_path = images_dir / self.vm_name / "ssh_key"
            return key_path if key_path.exists() else None
        except Exception:
            return None

    def _get_ssh_port(self) -> int:
        """Deterministic host-side SSH port for passt port forwarding."""
        return 22000 + (zlib.crc32(self.vm_name.encode("utf-8")) % 1000)

    def _ssh_exec(self, command: str, timeout: int = 10) -> Optional[str]:
        if shutil.which("ssh") is None:
            return None
        key_path = self._get_ssh_key_path()
        if key_path is None:
            return None

        ssh_port = self._get_ssh_port()
        user = (self.config.get("vm") or {}).get("username") or "ubuntu"

        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-i",
                    str(key_path),
                    "-p",
                    str(ssh_port),
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    "-o",
                    "ConnectTimeout=5",
                    "-o",
                    "BatchMode=yes",
                    f"{user}@127.0.0.1",
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                return None
            return (result.stdout or "").strip()
        except Exception:
            return None

    def _exec_in_vm(self, command: str, timeout: int = 10) -> Optional[str]:
        """Execute command in VM using QEMU guest agent, with SSH fallback."""
        if self._exec_transport == "ssh":
            return self._ssh_exec(command, timeout=timeout)

        try:
            result = subprocess.run(
                [
                    "virsh",
                    "--connect",
                    self.conn_uri,
                    "qemu-agent-command",
                    self.vm_name,
                    f'{{"execute":"guest-exec","arguments":{{"path":"/bin/sh","arg":["-c","{command}"],"capture-output":true}}}}',
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode != 0:
                return None

            response = json.loads(result.stdout)
            if "return" not in response or "pid" not in response["return"]:
                return None

            pid = response["return"]["pid"]

            deadline = time.time() + timeout
            while time.time() < deadline:
                status_result = subprocess.run(
                    [
                        "virsh",
                        "--connect",
                        self.conn_uri,
                        "qemu-agent-command",
                        self.vm_name,
                        f'{{"execute":"guest-exec-status","arguments":{{"pid":{pid}}}}}',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if status_result.returncode != 0:
                    return None

                status_resp = json.loads(status_result.stdout)
                if "return" not in status_resp:
                    return None

                ret = status_resp["return"]
                if ret.get("exited", False):
                    if "out-data" in ret:
                        return base64.b64decode(ret["out-data"]).decode().strip()
                    return ""

                time.sleep(0.2)

            return None

        except Exception:
            return None

    def _setup_in_progress(self) -> Optional[bool]:
        if self._setup_in_progress_cache is not None:
            return self._setup_in_progress_cache

        out = self._exec_in_vm(
            "test -f /var/lib/cloud/instance/boot-finished && echo no || echo yes",
            timeout=10,
        )
        if out is None:
            self._setup_in_progress_cache = None
            return None

        self._setup_in_progress_cache = out.strip() == "yes"
        return self._setup_in_progress_cache

    def _check_qga_ready(self) -> bool:
        """Check if QEMU guest agent is responding."""
        try:
            result = subprocess.run(
                [
                    "virsh",
                    "--connect",
                    self.conn_uri,
                    "qemu-agent-command",
                    self.vm_name,
                    '{"execute":"guest-ping"}',
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False
