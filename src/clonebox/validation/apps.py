from typing import Dict, List, Optional

from rich.panel import Panel
from rich.table import Table


class AppValidationMixin:
    def validate_apps(self) -> Dict:
        setup_in_progress = self._setup_in_progress() is True
        packages = self.config.get("packages", [])
        snap_packages = self.config.get("snap_packages", [])
        copy_paths = self.config.get("copy_paths", None)
        if not isinstance(copy_paths, dict) or not copy_paths:
            copy_paths = self.config.get("app_data_paths", {})
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

        for _, guest_path in copy_paths.items():
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
                add(
                    "ls -la /home/ubuntu/.mozilla/firefox 2>/dev/null | head -n 50 || true",
                    "Profile dir (classic)",
                )
                add(
                    "ls -la /home/ubuntu/snap/firefox/common/.mozilla/firefox 2>/dev/null | head -n 50 || true",
                    "Profile dir (snap)",
                )
                add(
                    "test -f /home/ubuntu/.mozilla/firefox/profiles.ini && head -n 50 /home/ubuntu/.mozilla/firefox/profiles.ini 2>/dev/null || true",
                    "profiles.ini (classic)",
                )
                add(
                    "test -f /home/ubuntu/snap/firefox/common/.mozilla/firefox/profiles.ini && head -n 50 /home/ubuntu/snap/firefox/common/.mozilla/firefox/profiles.ini 2>/dev/null || true",
                    "profiles.ini (snap)",
                )
                add(
                    "find /home/ubuntu/.mozilla/firefox /home/ubuntu/snap/firefox/common/.mozilla/firefox -maxdepth 2 -type f -name '*.sqlite' 2>/dev/null | head -n 20 || true",
                    "Profile sqlite quick check",
                )
                add(
                    "find /home/ubuntu/snap/firefox/common/.mozilla/firefox -maxdepth 3 -type f -name 'parent.lock' -o -name '.parentlock' -o -name 'lock' 2>/dev/null | head -n 50 || true",
                    "Lock files (snap)",
                )
                add(
                    "find /home/ubuntu/.mozilla/firefox -maxdepth 3 -type f -name 'parent.lock' -o -name '.parentlock' -o -name 'lock' 2>/dev/null | head -n 50 || true",
                    "Lock files (classic)",
                )
                add(
                    "ls -la '/home/ubuntu/snap/firefox/common/.mozilla/firefox/Crash Reports' 2>/dev/null | tail -n 30 || true",
                    "Crash Reports (snap)",
                )
                add(
                    "find '/home/ubuntu/snap/firefox/common/.mozilla/firefox/Crash Reports' -maxdepth 1 -type f -name '*.dmp' -o -name '*.extra' 2>/dev/null | tail -n 20 || true",
                    "Crash dumps list (snap)",
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
            pending = False

            if app == "firefox":
                installed = (
                    self._exec_in_vm("command -v firefox >/dev/null 2>&1 && echo yes || echo no") == "yes"
                )
                if _check_dir_nonempty("/home/ubuntu/snap/firefox/common/.mozilla/firefox"):
                    profile_ok = True
                elif _check_dir_nonempty("/home/ubuntu/.mozilla/firefox"):
                    profile_ok = True

                if installed:
                    running = _check_any_process_running(["firefox"])
                    pid = _find_first_pid(["firefox"]) if running else ""

                    if running is False:
                        # Heuristics / hints
                        missing_ifaces = _snap_missing_interfaces(
                            "firefox",
                            snap_app_specs.get("firefox", {}).get("required_interfaces", []),
                        )
                        if missing_ifaces:
                            note = note or f"missing interfaces: {', '.join(missing_ifaces)}"
                        else:
                            # profile path hint
                            snap_prof = _check_dir_nonempty(
                                "/home/ubuntu/snap/firefox/common/.mozilla/firefox"
                            )
                            classic_prof = _check_dir_nonempty("/home/ubuntu/.mozilla/firefox")
                            if not (snap_prof or classic_prof):
                                note = note or "profile not present"
                            else:
                                # If profile exists, check for lock files (common after copying from a running browser)
                                has_locks = self._exec_in_vm(
                                    "find /home/ubuntu/snap/firefox/common/.mozilla/firefox /home/ubuntu/.mozilla/firefox"
                                    " -maxdepth 3 -type f"
                                    " \\( -name parent.lock -o -name .parentlock -o -name lock \\)"
                                    " 2>/dev/null | head -n 1 | wc -l",
                                    timeout=15,
                                )
                                if (has_locks or "0").strip() not in {"", "0"}:
                                    note = note or "profile has lock files"

            elif app in snap_app_specs:
                installed = (
                    self._exec_in_vm(f"snap list {app} >/dev/null 2>&1 && echo yes || echo no") == "yes"
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
                        _find_first_pid(["google-chrome", "google-chrome-stable"]) if running else ""
                    )

            if self.require_running_apps and installed and profile_ok and running is None:
                note = note or "running unknown"

            if setup_in_progress and not installed:
                pending = True
                note = note or "setup in progress"
            elif setup_in_progress and not profile_ok:
                pending = True
                note = note or "profile import in progress"

            running_icon = (
                "[dim]—[/]"
                if not installed
                else (
                    "[green]✅[/]" if running is True else "[yellow]⚠️[/]" if running is False else "[dim]?[/]"
                )
            )

            pid_value = "—" if not installed else ("?" if pid is None else (pid or "—"))

            installed_icon = "[green]✅[/]" if installed else ("[yellow]⏳[/]" if pending else "[red]❌[/]")
            profile_icon = "[green]✅[/]" if profile_ok else ("[yellow]⏳[/]" if pending else "[red]❌[/]")

            table.add_row(app, installed_icon, profile_icon, running_icon, pid_value, note)

            should_pass = installed and profile_ok
            if self.require_running_apps and installed and profile_ok:
                should_pass = running is True

            if pending:
                self.results["apps"]["skipped"] += 1
            elif should_pass:
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
                    "pending": pending,
                }
            )

            if installed and profile_ok and running in (False, None):
                logs = _collect_app_logs(app)
                if logs:
                    self.console.print(Panel(logs, title=f"Logs: {app}", border_style="yellow"))

        self.console.print(table)
        return self.results["apps"]
