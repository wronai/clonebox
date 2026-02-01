"""
VM validation module - validates VM state against YAML configuration.
"""

import subprocess
import json
import base64
import time
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


class VMValidator:
    """Validates VM configuration against expected state from YAML."""

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
            "mounts": {"passed": 0, "failed": 0, "total": 0, "details": []},
            "packages": {"passed": 0, "failed": 0, "total": 0, "details": []},
            "snap_packages": {"passed": 0, "failed": 0, "total": 0, "details": []},
            "services": {"passed": 0, "failed": 0, "total": 0, "details": []},
            "apps": {"passed": 0, "failed": 0, "total": 0, "details": []},
            "smoke": {"passed": 0, "failed": 0, "total": 0, "details": []},
            "overall": "unknown",
        }

    def _exec_in_vm(self, command: str, timeout: int = 10) -> Optional[str]:
        """Execute command in VM using QEMU guest agent."""
        try:
            # Execute command
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

            # Wait a bit for command to complete
            time.sleep(0.3)

            # Get result
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
            if not ret.get("exited", False):
                return None

            if "out-data" in ret:
                return base64.b64decode(ret["out-data"]).decode().strip()

            return ""

        except Exception:
            return None

    def validate_mounts(self) -> Dict:
        """Validate all mount points are accessible and contain data."""
        self.console.print("\n[bold]💾 Validating Mount Points...[/]")

        all_paths = self.config.get("paths", {}).copy()
        all_paths.update(self.config.get("app_data_paths", {}))

        if not all_paths:
            self.console.print("[dim]No mount points configured[/]")
            return self.results["mounts"]

        # Get mounted filesystems
        mount_output = self._exec_in_vm("mount | grep 9p")
        mounted_paths = []
        if mount_output:
            mounted_paths = [line.split()[2] for line in mount_output.split("\n") if line.strip()]

        mount_table = Table(title="Mount Validation", border_style="cyan")
        mount_table.add_column("Guest Path", style="bold")
        mount_table.add_column("Mounted", justify="center")
        mount_table.add_column("Accessible", justify="center")
        mount_table.add_column("Files", justify="right")

        for host_path, guest_path in all_paths.items():
            self.results["mounts"]["total"] += 1

            # Check if mounted
            is_mounted = any(guest_path in mp for mp in mounted_paths)

            # Check if accessible
            accessible = False
            file_count = "?"

            if is_mounted:
                test_result = self._exec_in_vm(f"test -d {guest_path} && echo 'yes' || echo 'no'")
                accessible = test_result == "yes"

                if accessible:
                    # Get file count
                    count_str = self._exec_in_vm(f"ls -A {guest_path} 2>/dev/null | wc -l")
                    if count_str and count_str.isdigit():
                        file_count = count_str

            # Determine status
            if is_mounted and accessible:
                mount_status = "[green]✅[/]"
                access_status = "[green]✅[/]"
                self.results["mounts"]["passed"] += 1
                status = "pass"
            elif is_mounted:
                mount_status = "[green]✅[/]"
                access_status = "[red]❌[/]"
                self.results["mounts"]["failed"] += 1
                status = "mounted_but_inaccessible"
            else:
                mount_status = "[red]❌[/]"
                access_status = "[dim]N/A[/]"
                self.results["mounts"]["failed"] += 1
                status = "not_mounted"

            mount_table.add_row(guest_path, mount_status, access_status, str(file_count))

            self.results["mounts"]["details"].append(
                {
                    "path": guest_path,
                    "mounted": is_mounted,
                    "accessible": accessible,
                    "files": file_count,
                    "status": status,
                }
            )

        self.console.print(mount_table)
        self.console.print(
            f"[dim]{self.results['mounts']['passed']}/{self.results['mounts']['total']} mounts working[/]"
        )

        return self.results["mounts"]

    def validate_packages(self) -> Dict:
        """Validate APT packages are installed."""
        self.console.print("\n[bold]📦 Validating APT Packages...[/]")

        packages = self.config.get("packages", [])
        if not packages:
            self.console.print("[dim]No APT packages configured[/]")
            return self.results["packages"]

        pkg_table = Table(title="Package Validation", border_style="cyan")
        pkg_table.add_column("Package", style="bold")
        pkg_table.add_column("Status", justify="center")
        pkg_table.add_column("Version", style="dim")

        for package in packages:
            self.results["packages"]["total"] += 1

            # Check if installed
            check_cmd = f"dpkg -l | grep -E '^ii  {package}' | awk '{{print $3}}'"
            version = self._exec_in_vm(check_cmd)

            if version:
                pkg_table.add_row(package, "[green]✅ Installed[/]", version[:40])
                self.results["packages"]["passed"] += 1
                self.results["packages"]["details"].append(
                    {"package": package, "installed": True, "version": version}
                )
            else:
                pkg_table.add_row(package, "[red]❌ Missing[/]", "")
                self.results["packages"]["failed"] += 1
                self.results["packages"]["details"].append(
                    {"package": package, "installed": False, "version": None}
                )

        self.console.print(pkg_table)
        self.console.print(
            f"[dim]{self.results['packages']['passed']}/{self.results['packages']['total']} packages installed[/]"
        )

        return self.results["packages"]

    def validate_snap_packages(self) -> Dict:
        """Validate snap packages are installed."""
        self.console.print("\n[bold]📦 Validating Snap Packages...[/]")

        snap_packages = self.config.get("snap_packages", [])
        if not snap_packages:
            self.console.print("[dim]No snap packages configured[/]")
            return self.results["snap_packages"]

        snap_table = Table(title="Snap Package Validation", border_style="cyan")
        snap_table.add_column("Package", style="bold")
        snap_table.add_column("Status", justify="center")
        snap_table.add_column("Version", style="dim")

        for package in snap_packages:
            self.results["snap_packages"]["total"] += 1

            # Check if installed
            check_cmd = f"snap list | grep '^{package}' | awk '{{print $2}}'"
            version = self._exec_in_vm(check_cmd)

            if version:
                snap_table.add_row(package, "[green]✅ Installed[/]", version[:40])
                self.results["snap_packages"]["passed"] += 1
                self.results["snap_packages"]["details"].append(
                    {"package": package, "installed": True, "version": version}
                )
            else:
                snap_table.add_row(package, "[red]❌ Missing[/]", "")
                self.results["snap_packages"]["failed"] += 1
                self.results["snap_packages"]["details"].append(
                    {"package": package, "installed": False, "version": None}
                )

        self.console.print(snap_table)
        self.console.print(
            f"[dim]{self.results['snap_packages']['passed']}/{self.results['snap_packages']['total']} snap packages installed[/]"
        )

        return self.results["snap_packages"]

    # Services that should NOT be validated in VM (host-specific)
    VM_EXCLUDED_SERVICES = {
        "libvirtd",
        "virtlogd",
        "libvirt-guests",
        "qemu-guest-agent",
        "bluetooth",
        "bluez",
        "upower",
        "thermald",
        "tlp",
        "power-profiles-daemon",
        "gdm",
        "gdm3",
        "sddm",
        "lightdm",
        "snap.cups.cups-browsed",
        "snap.cups.cupsd",
        "ModemManager",
        "wpa_supplicant",
        "accounts-daemon",
        "colord",
        "switcheroo-control",
    }

    def validate_services(self) -> Dict:
        """Validate services are enabled and running."""
        self.console.print("\n[bold]⚙️  Validating Services...[/]")

        services = self.config.get("services", [])
        if not services:
            self.console.print("[dim]No services configured[/]")
            return self.results["services"]

        if "skipped" not in self.results["services"]:
            self.results["services"]["skipped"] = 0

        svc_table = Table(title="Service Validation", border_style="cyan")
        svc_table.add_column("Service", style="bold")
        svc_table.add_column("Enabled", justify="center")
        svc_table.add_column("Running", justify="center")
        svc_table.add_column("PID", justify="right", style="dim")
        svc_table.add_column("Note", style="dim")

        for service in services:
            if service in self.VM_EXCLUDED_SERVICES:
                svc_table.add_row(service, "[dim]—[/]", "[dim]—[/]", "[dim]—[/]", "host-only")
                self.results["services"]["skipped"] += 1
                self.results["services"]["details"].append(
                    {
                        "service": service,
                        "enabled": None,
                        "running": None,
                        "skipped": True,
                        "reason": "host-specific service",
                    }
                )
                continue

            self.results["services"]["total"] += 1

            enabled_cmd = f"systemctl is-enabled {service} 2>/dev/null"
            enabled_status = self._exec_in_vm(enabled_cmd)
            is_enabled = enabled_status == "enabled"

            running_cmd = f"systemctl is-active {service} 2>/dev/null"
            running_status = self._exec_in_vm(running_cmd)
            is_running = running_status == "active"

            pid_value = ""
            if is_running:
                pid_out = self._exec_in_vm(
                    f"systemctl show -p MainPID --value {service} 2>/dev/null"
                )
                if pid_out is None:
                    pid_value = "?"
                else:
                    pid_value = pid_out.strip() or "?"
            else:
                pid_value = "—"

            enabled_icon = "[green]✅[/]" if is_enabled else "[yellow]⚠️[/]"
            running_icon = "[green]✅[/]" if is_running else "[red]❌[/]"

            svc_table.add_row(service, enabled_icon, running_icon, pid_value, "")

            if is_enabled and is_running:
                self.results["services"]["passed"] += 1
            else:
                self.results["services"]["failed"] += 1

            self.results["services"]["details"].append(
                {
                    "service": service,
                    "enabled": is_enabled,
                    "running": is_running,
                    "pid": None if pid_value in ("", "—", "?") else pid_value,
                    "skipped": False,
                }
            )

        self.console.print(svc_table)
        skipped = self.results["services"].get("skipped", 0)
        msg = f"{self.results['services']['passed']}/{self.results['services']['total']} services active"
        if skipped > 0:
            msg += f" ({skipped} host-only skipped)"
        self.console.print(f"[dim]{msg}[/]")

        return self.results["services"]

    def validate_apps(self) -> Dict:
        packages = self.config.get("packages", [])
        snap_packages = self.config.get("snap_packages", [])
        app_data_paths = self.config.get("app_data_paths", {})
        vm_user = self.config.get("vm", {}).get("username", "ubuntu")

        snap_app_specs = {
            "pycharm-community": {
                "process_patterns": ["pycharm-community", "pycharm", "jetbrains"],
                "required_interfaces": [
                    "desktop",
                    "desktop-legacy",
                    "x11",
                    "wayland",
                    "home",
                    "network",
                ],
            },
            "chromium": {
                "process_patterns": ["chromium", "chromium-browser"],
                "required_interfaces": [
                    "desktop",
                    "desktop-legacy",
                    "x11",
                    "wayland",
                    "home",
                    "network",
                ],
            },
            "firefox": {
                "process_patterns": ["firefox"],
                "required_interfaces": [
                    "desktop",
                    "desktop-legacy",
                    "x11",
                    "wayland",
                    "home",
                    "network",
                ],
            },
            "code": {
                "process_patterns": ["code"],
                "required_interfaces": [
                    "desktop",
                    "desktop-legacy",
                    "x11",
                    "wayland",
                    "home",
                    "network",
                ],
            },
        }

        expected = []

        if "firefox" in packages:
            expected.append("firefox")

        for snap_pkg in snap_packages:
            if snap_pkg in snap_app_specs:
                expected.append(snap_pkg)

        for _, guest_path in app_data_paths.items():
            if guest_path == "/home/ubuntu/.config/google-chrome":
                expected.append("google-chrome")
                break

        expected = sorted(set(expected))
        if not expected:
            return self.results["apps"]

        self.console.print("\n[bold]🧩 Validating Apps...[/]")
        table = Table(title="App Validation", border_style="cyan")
        table.add_column("App", style="bold")
        table.add_column("Installed", justify="center")
        table.add_column("Profile", justify="center")
        table.add_column("Running", justify="center")
        table.add_column("PID", justify="right", style="dim")
        table.add_column("Note", style="dim")

        def _pgrep_pattern(pattern: str) -> str:
            if not pattern:
                return pattern
            return f"[{pattern[0]}]{pattern[1:]}"

        def _check_any_process_running(patterns: List[str]) -> Optional[bool]:
            for pattern in patterns:
                p = _pgrep_pattern(pattern)
                out = self._exec_in_vm(
                    f"pgrep -u {vm_user} -f '{p}' >/dev/null 2>&1 && echo yes || echo no",
                    timeout=10,
                )
                if out is None:
                    return None
                if out == "yes":
                    return True
            return False

        def _find_first_pid(patterns: List[str]) -> Optional[str]:
            for pattern in patterns:
                p = _pgrep_pattern(pattern)
                out = self._exec_in_vm(
                    f"pgrep -u {vm_user} -f '{p}' 2>/dev/null | head -n 1 || true",
                    timeout=10,
                )
                if out is None:
                    return None
                pid = out.strip()
                if pid:
                    return pid
            return ""

        def _collect_app_logs(app_name: str) -> str:
            chunks: List[str] = []

            def add(cmd: str, title: str, timeout: int = 20):
                out = self._exec_in_vm(cmd, timeout=timeout)
                if out is None:
                    return
                out = out.strip()
                if not out:
                    return
                chunks.append(f"{title}\n$ {cmd}\n{out}")

            if app_name in snap_app_specs:
                add(f"snap connections {app_name} 2>/dev/null | head -n 40", "Snap connections")
                add(f"snap logs {app_name} -n 80 2>/dev/null | tail -n 60", "Snap logs")

                if app_name == "pycharm-community":
                    add(
                        "tail -n 80 /home/ubuntu/snap/pycharm-community/common/.config/JetBrains/*/log/idea.log 2>/dev/null || true",
                        "idea.log",
                    )

            if app_name == "google-chrome":
                add(
                    "journalctl -n 200 --no-pager 2>/dev/null | grep -i chrome | tail -n 60 || true",
                    "Journal (chrome)",
                )
            if app_name == "firefox":
                add(
                    "journalctl -n 200 --no-pager 2>/dev/null | grep -i firefox | tail -n 60 || true",
                    "Journal (firefox)",
                )

            return "\n\n".join(chunks)

        def _snap_missing_interfaces(snap_name: str, required: List[str]) -> Optional[List[str]]:
            out = self._exec_in_vm(
                f"snap connections {snap_name} 2>/dev/null | awk 'NR>1{{print $1, $3}}'",
                timeout=15,
            )
            if out is None:
                return None

            connected = set()
            for line in out.splitlines():
                parts = line.split()
                if len(parts) < 2:
                    continue
                iface, slot = parts[0], parts[1]
                if slot != "-":
                    connected.add(iface)

            missing = [i for i in required if i not in connected]
            return missing

        def _check_dir_nonempty(path: str) -> bool:
            out = self._exec_in_vm(
                f"test -d {path} && [ $(ls -A {path} 2>/dev/null | wc -l) -gt 0 ] && echo yes || echo no",
                timeout=10,
            )
            return out == "yes"

        for app in expected:
            self.results["apps"]["total"] += 1
            installed = False
            profile_ok = False
            running: Optional[bool] = None
            pid: Optional[str] = None
            note = ""

            if app == "firefox":
                installed = (
                    self._exec_in_vm("command -v firefox >/dev/null 2>&1 && echo yes || echo no")
                    == "yes"
                )
                if _check_dir_nonempty("/home/ubuntu/snap/firefox/common/.mozilla/firefox"):
                    profile_ok = True
                elif _check_dir_nonempty("/home/ubuntu/.mozilla/firefox"):
                    profile_ok = True

                if installed:
                    running = _check_any_process_running(["firefox"])
                    pid = _find_first_pid(["firefox"]) if running else ""

            elif app in snap_app_specs:
                installed = (
                    self._exec_in_vm(f"snap list {app} >/dev/null 2>&1 && echo yes || echo no")
                    == "yes"
                )
                if app == "pycharm-community":
                    profile_ok = _check_dir_nonempty(
                        "/home/ubuntu/snap/pycharm-community/common/.config/JetBrains"
                    )
                else:
                    profile_ok = True

                if installed:
                    patterns = snap_app_specs[app]["process_patterns"]
                    running = _check_any_process_running(patterns)
                    pid = _find_first_pid(patterns) if running else ""
                    if running is False:
                        missing_ifaces = _snap_missing_interfaces(
                            app,
                            snap_app_specs[app]["required_interfaces"],
                        )
                        if missing_ifaces:
                            note = f"missing interfaces: {', '.join(missing_ifaces)}"
                        elif missing_ifaces == []:
                            note = "not running"
                        else:
                            note = "interfaces unknown"

            elif app == "google-chrome":
                installed = (
                    self._exec_in_vm(
                        "(command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1) && echo yes || echo no"
                    )
                    == "yes"
                )
                profile_ok = _check_dir_nonempty("/home/ubuntu/.config/google-chrome")

                if installed:
                    running = _check_any_process_running(["google-chrome", "google-chrome-stable"])
                    pid = (
                        _find_first_pid(["google-chrome", "google-chrome-stable"])
                        if running
                        else ""
                    )

            if self.require_running_apps and installed and profile_ok and running is None:
                note = note or "running unknown"

            running_icon = (
                "[dim]—[/]"
                if not installed
                else (
                    "[green]✅[/]"
                    if running is True
                    else "[yellow]⚠️[/]" if running is False else "[dim]?[/]"
                )
            )

            pid_value = "—" if not installed else ("?" if pid is None else (pid or "—"))

            table.add_row(
                app,
                "[green]✅[/]" if installed else "[red]❌[/]",
                "[green]✅[/]" if profile_ok else "[red]❌[/]",
                running_icon,
                pid_value,
                note,
            )

            should_pass = installed and profile_ok
            if self.require_running_apps and installed and profile_ok:
                should_pass = running is True

            if should_pass:
                self.results["apps"]["passed"] += 1
            else:
                self.results["apps"]["failed"] += 1

            self.results["apps"]["details"].append(
                {
                    "app": app,
                    "installed": installed,
                    "profile": profile_ok,
                    "running": running,
                    "pid": pid,
                    "note": note,
                }
            )

            if installed and profile_ok and running in (False, None):
                logs = _collect_app_logs(app)
                if logs:
                    self.console.print(Panel(logs, title=f"Logs: {app}", border_style="yellow"))

        self.console.print(table)
        return self.results["apps"]

    def validate_smoke_tests(self) -> Dict:
        packages = self.config.get("packages", [])
        snap_packages = self.config.get("snap_packages", [])
        app_data_paths = self.config.get("app_data_paths", {})
        vm_user = self.config.get("vm", {}).get("username", "ubuntu")

        expected = []

        if "firefox" in packages:
            expected.append("firefox")

        for snap_pkg in snap_packages:
            if snap_pkg in {"pycharm-community", "chromium", "firefox", "code"}:
                expected.append(snap_pkg)

        for _, guest_path in app_data_paths.items():
            if guest_path == "/home/ubuntu/.config/google-chrome":
                expected.append("google-chrome")
                break

        if "docker" in (self.config.get("services", []) or []) or "docker.io" in packages:
            expected.append("docker")

        expected = sorted(set(expected))
        if not expected:
            return self.results["smoke"]

        def _installed(app: str) -> Optional[bool]:
            if app in {"pycharm-community", "chromium", "firefox", "code"}:
                out = self._exec_in_vm(
                    f"snap list {app} >/dev/null 2>&1 && echo yes || echo no", timeout=10
                )
                return None if out is None else out.strip() == "yes"

            if app == "google-chrome":
                out = self._exec_in_vm(
                    "(command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1) && echo yes || echo no",
                    timeout=10,
                )
                return None if out is None else out.strip() == "yes"

            if app == "docker":
                out = self._exec_in_vm(
                    "command -v docker >/dev/null 2>&1 && echo yes || echo no", timeout=10
                )
                return None if out is None else out.strip() == "yes"

            if app == "firefox":
                out = self._exec_in_vm(
                    "command -v firefox >/dev/null 2>&1 && echo yes || echo no", timeout=10
                )
                return None if out is None else out.strip() == "yes"

            out = self._exec_in_vm(
                f"command -v {app} >/dev/null 2>&1 && echo yes || echo no", timeout=10
            )
            return None if out is None else out.strip() == "yes"

        def _run_test(app: str) -> Optional[bool]:
            uid_out = self._exec_in_vm(f"id -u {vm_user} 2>/dev/null || true", timeout=10)
            vm_uid = (uid_out or "").strip()
            if not vm_uid.isdigit():
                vm_uid = "1000"

            runtime_dir = f"/run/user/{vm_uid}"
            self._exec_in_vm(
                f"mkdir -p {runtime_dir} && chown {vm_uid}:{vm_uid} {runtime_dir} && chmod 700 {runtime_dir}",
                timeout=10,
            )

            user_env = (
                f"sudo -u {vm_user} env HOME=/home/{vm_user} USER={vm_user} LOGNAME={vm_user} XDG_RUNTIME_DIR={runtime_dir}"
            )

            if app == "pycharm-community":
                out = self._exec_in_vm(
                    "/snap/pycharm-community/current/jbr/bin/java -version >/dev/null 2>&1 && echo yes || echo no",
                    timeout=20,
                )
                return None if out is None else out.strip() == "yes"

            if app == "chromium":
                out = self._exec_in_vm(
                    f"{user_env} timeout 20 chromium --headless=new --no-sandbox --disable-gpu --dump-dom about:blank >/dev/null 2>&1 && echo yes || echo no",
                    timeout=30,
                )
                return None if out is None else out.strip() == "yes"

            if app == "firefox":
                out = self._exec_in_vm(
                    f"{user_env} timeout 20 firefox --headless --screenshot /tmp/clonebox-firefox.png about:blank >/dev/null 2>&1 && rm -f /tmp/clonebox-firefox.png && echo yes || echo no",
                    timeout=30,
                )
                return None if out is None else out.strip() == "yes"

            if app == "google-chrome":
                out = self._exec_in_vm(
                    f"{user_env} timeout 20 google-chrome --headless=new --no-sandbox --disable-gpu --dump-dom about:blank >/dev/null 2>&1 && echo yes || echo no",
                    timeout=30,
                )
                return None if out is None else out.strip() == "yes"

            if app == "docker":
                out = self._exec_in_vm(
                    "timeout 20 docker info >/dev/null 2>&1 && echo yes || echo no", timeout=30
                )
                return None if out is None else out.strip() == "yes"

            out = self._exec_in_vm(
                f"timeout 20 {app} --version >/dev/null 2>&1 && echo yes || echo no", timeout=30
            )
            return None if out is None else out.strip() == "yes"

        self.console.print("\n[bold]🧪 Smoke Tests (installed ≠ works)...[/]")
        table = Table(title="Smoke Tests", border_style="cyan")
        table.add_column("App", style="bold")
        table.add_column("Installed", justify="center")
        table.add_column("Launch", justify="center")
        table.add_column("Note", style="dim")

        for app in expected:
            self.results["smoke"]["total"] += 1
            installed = _installed(app)
            launched: Optional[bool] = None
            note = ""

            if installed is True:
                launched = _run_test(app)
                if launched is None:
                    note = "test failed to execute"
            elif installed is False:
                note = "not installed"
            else:
                note = "install status unknown"

            installed_icon = (
                "[green]✅[/]"
                if installed is True
                else "[red]❌[/]" if installed is False else "[dim]?[/]"
            )
            launch_icon = (
                "[green]✅[/]"
                if launched is True
                else (
                    "[red]❌[/]"
                    if launched is False
                    else ("[dim]—[/]" if installed is not True else "[dim]?[/]")
                )
            )

            table.add_row(app, installed_icon, launch_icon, note)

            passed = installed is True and launched is True
            if passed:
                self.results["smoke"]["passed"] += 1
            else:
                self.results["smoke"]["failed"] += 1

            self.results["smoke"]["details"].append(
                {
                    "app": app,
                    "installed": installed,
                    "launched": launched,
                    "note": note,
                }
            )

        self.console.print(table)
        return self.results["smoke"]

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

    def validate_all(self) -> Dict:
        """Run all validations and return comprehensive results."""
        self.console.print("[bold cyan]🔍 Running Full Validation...[/]")

        # Check if VM is running
        try:
            result = subprocess.run(
                ["virsh", "--connect", self.conn_uri, "domstate", self.vm_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            vm_state = result.stdout.strip()

            if "running" not in vm_state.lower():
                self.console.print(f"[yellow]⚠️  VM is not running (state: {vm_state})[/]")
                self.console.print("[dim]Start VM with: clonebox start .[/]")
                self.results["overall"] = "vm_not_running"
                return self.results
        except Exception as e:
            self.console.print(f"[red]❌ Cannot check VM state: {e}[/]")
            self.results["overall"] = "error"
            return self.results

        # Check QEMU Guest Agent
        if not self._check_qga_ready():
            self.console.print("[red]❌ QEMU Guest Agent not responding[/]")
            self.console.print("\n[bold]🔧 Troubleshooting QGA:[/]")
            self.console.print("  1. The VM might still be booting. Wait 30-60 seconds.")
            self.console.print("  2. Ensure the agent is installed and running inside the VM:")
            self.console.print("     [dim]virsh console " + self.vm_name + "[/]")
            self.console.print("     [dim]sudo systemctl status qemu-guest-agent[/]")
            self.console.print("  3. If newly created, cloud-init might still be running.")
            self.console.print("  4. Check VM logs: [dim]clonebox logs " + self.vm_name + "[/]")
            self.console.print(f"\n[yellow]⚠️  Skipping deep validation as it requires a working Guest Agent.[/]")
            self.results["overall"] = "qga_not_ready"
            return self.results

        ci_status = self._exec_in_vm("cloud-init status --long 2>/dev/null || cloud-init status 2>/dev/null || true", timeout=20)
        if ci_status:
            ci_lower = ci_status.lower()
            if "running" in ci_lower:
                self.console.print("[yellow]⏳ Cloud-init still running - skipping deep validation for now[/]")
                self.results["overall"] = "cloud_init_running"
                return self.results

        ready_msg = self._exec_in_vm(
            "cat /var/log/clonebox-ready 2>/dev/null || true",
            timeout=10,
        )
        if not (ready_msg and "clonebox vm ready" in ready_msg.lower()):
            self.console.print(
                "[yellow]⚠️  CloneBox ready marker not found - provisioning may not have completed[/]"
            )

        # Run all validations
        self.validate_mounts()
        self.validate_packages()
        self.validate_snap_packages()
        self.validate_services()
        self.validate_apps()
        if self.smoke_test:
            self.validate_smoke_tests()

        recent_err = self._exec_in_vm(
            "journalctl -p err -n 30 --no-pager 2>/dev/null || true", timeout=20
        )
        if recent_err:
            recent_err = recent_err.strip()
            if recent_err:
                self.console.print(
                    Panel(recent_err, title="Recent system errors", border_style="red")
                )

        # Calculate overall status
        total_checks = (
            self.results["mounts"]["total"]
            + self.results["packages"]["total"]
            + self.results["snap_packages"]["total"]
            + self.results["services"]["total"]
            + self.results["apps"]["total"]
            + (self.results["smoke"]["total"] if self.smoke_test else 0)
        )

        total_passed = (
            self.results["mounts"]["passed"]
            + self.results["packages"]["passed"]
            + self.results["snap_packages"]["passed"]
            + self.results["services"]["passed"]
            + self.results["apps"]["passed"]
            + (self.results["smoke"]["passed"] if self.smoke_test else 0)
        )

        total_failed = (
            self.results["mounts"]["failed"]
            + self.results["packages"]["failed"]
            + self.results["snap_packages"]["failed"]
            + self.results["services"]["failed"]
            + self.results["apps"]["failed"]
            + (self.results["smoke"]["failed"] if self.smoke_test else 0)
        )

        # Get skipped services count
        skipped_services = self.results["services"].get("skipped", 0)

        # Print summary
        self.console.print("\n[bold]📊 Validation Summary[/]")
        summary_table = Table(border_style="cyan")
        summary_table.add_column("Category", style="bold")
        summary_table.add_column("Passed", justify="right", style="green")
        summary_table.add_column("Failed", justify="right", style="red")
        summary_table.add_column("Skipped", justify="right", style="dim")
        summary_table.add_column("Total", justify="right")

        summary_table.add_row(
            "Mounts",
            str(self.results["mounts"]["passed"]),
            str(self.results["mounts"]["failed"]),
            "—",
            str(self.results["mounts"]["total"]),
        )
        summary_table.add_row(
            "APT Packages",
            str(self.results["packages"]["passed"]),
            str(self.results["packages"]["failed"]),
            "—",
            str(self.results["packages"]["total"]),
        )
        summary_table.add_row(
            "Snap Packages",
            str(self.results["snap_packages"]["passed"]),
            str(self.results["snap_packages"]["failed"]),
            "—",
            str(self.results["snap_packages"]["total"]),
        )
        summary_table.add_row(
            "Services",
            str(self.results["services"]["passed"]),
            str(self.results["services"]["failed"]),
            str(skipped_services),
            str(self.results["services"]["total"]),
        )
        summary_table.add_row(
            "Apps",
            str(self.results["apps"]["passed"]),
            str(self.results["apps"]["failed"]),
            "—",
            str(self.results["apps"]["total"]),
        )
        summary_table.add_row(
            "[bold]TOTAL",
            f"[bold green]{total_passed}",
            f"[bold red]{total_failed}",
            f"[dim]{skipped_services}[/]",
            f"[bold]{total_checks}",
        )

        self.console.print(summary_table)

        # Determine overall status
        if total_failed == 0 and total_checks > 0:
            self.results["overall"] = "pass"
            self.console.print("\n[bold green]✅ All validations passed![/]")
        elif total_failed > 0:
            self.results["overall"] = "partial"
            self.console.print(f"\n[bold yellow]⚠️  {total_failed}/{total_checks} checks failed[/]")
            self.console.print(
                "[dim]Consider rebuilding VM: clonebox clone . --user --run --replace[/]"
            )
        else:
            self.results["overall"] = "no_checks"
            self.console.print("\n[dim]No validation checks configured[/]")

        return self.results
