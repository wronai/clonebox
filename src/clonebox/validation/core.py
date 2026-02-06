import base64
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

from rich.console import Console

from clonebox.paths import ssh_key_path as _ssh_key_path, resolve_ssh_port
from clonebox.ssh import ssh_exec as _shared_ssh_exec

log = logging.getLogger(__name__)


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

    @property
    def _user_session(self) -> bool:
        return self.conn_uri.endswith("/session")

    def _get_ssh_key_path(self) -> Optional[Path]:
        """Return path to the SSH key generated for this VM (if present)."""
        return _ssh_key_path(self.vm_name, self._user_session)

    def _get_ssh_port(self) -> int:
        """Host-side SSH port for passt port forwarding."""
        return resolve_ssh_port(self.vm_name, self._user_session)

    def _ssh_exec(self, command: str, timeout: int = 10) -> Optional[str]:
        """Execute command via SSH."""
        user = (self.config.get("vm") or {}).get("username") or "ubuntu"
        return _shared_ssh_exec(
            port=self._get_ssh_port(),
            key=self._get_ssh_key_path(),
            command=command,
            username=user,
            timeout=timeout,
            connect_timeout=5,
        )

    def _exec_in_vm(self, command: str, timeout: int = 10) -> Optional[str]:
        """Execute command in VM using QEMU guest agent, with SSH fallback."""
        log.debug(f"Exec in VM: {command[:50]}..." if len(command) > 50 else f"Exec in VM: {command}")
        
        if self._exec_transport == "ssh":
            log.debug("Using SSH transport")
            return self._ssh_exec(command, timeout=timeout)

        log.debug("Using QEMU guest agent transport")
        
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
                log.debug(f"QGA guest-exec failed (exit {result.returncode}): {result.stderr.strip()[:100]}")
                # Fallback to SSH
                log.debug("Falling back to SSH transport")
                ssh_result = self._ssh_exec(command, timeout=timeout)
                if ssh_result is not None:
                    self._exec_transport = "ssh"  # Switch to SSH for future calls
                    log.debug("Switched to SSH transport for future calls")
                return ssh_result

            response = json.loads(result.stdout)
            if "return" not in response or "pid" not in response["return"]:
                log.debug(f"Invalid QGA response: {result.stdout[:100]}")
                return None

            pid = response["return"]["pid"]
            log.debug(f"QGA command started with PID {pid}")

            deadline = time.time() + timeout
            poll_count = 0
            while time.time() < deadline:
                poll_count += 1
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
                    log.debug(f"QGA status check failed after {poll_count} polls")
                    return None

                status_resp = json.loads(status_result.stdout)
                if "return" not in status_resp:
                    log.debug(f"Invalid QGA status response: {status_result.stdout[:100]}")
                    return None

                ret = status_resp["return"]
                if ret.get("exited", False):
                    exit_code = ret.get("exitcode", 0)
                    log.debug(f"QGA command completed (exit {exit_code}) after {poll_count} polls")
                    if "out-data" in ret:
                        output = base64.b64decode(ret["out-data"]).decode().strip()
                        log.debug(f"QGA output: {output[:50]}..." if len(output) > 50 else f"QGA output: {output}")
                        return output
                    return ""

                time.sleep(0.2)

            log.debug(f"QGA command timed out after {poll_count} polls")
            return None

        except json.JSONDecodeError as e:
            log.debug(f"Failed to parse QGA response: {e}")
            # Fallback to SSH
            return self._ssh_exec(command, timeout=timeout)
        except subprocess.TimeoutExpired:
            log.debug(f"QGA command timed out after {timeout}s")
            return None
        except Exception as e:
            log.debug(f"QGA exec failed: {e}")
            # Fallback to SSH
            return self._ssh_exec(command, timeout=timeout)

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
