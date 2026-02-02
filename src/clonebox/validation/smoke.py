from typing import Dict, Optional

from rich.table import Table


class SmokeValidationMixin:
    def validate_smoke_tests(self) -> Dict:
        setup_in_progress = self._setup_in_progress() is True
        packages = self.config.get("packages", [])
        snap_packages = self.config.get("snap_packages", [])
        copy_paths = self.config.get("copy_paths", None)
        if not isinstance(copy_paths, dict) or not copy_paths:
            copy_paths = self.config.get("app_data_paths", {})
        vm_user = self.config.get("vm", {}).get("username", "ubuntu")

        expected = []

        if "firefox" in packages:
            expected.append("firefox")

        for snap_pkg in snap_packages:
            if snap_pkg in {"pycharm-community", "chromium", "firefox", "code"}:
                expected.append(snap_pkg)

        for _, guest_path in copy_paths.items():
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
                out = self._exec_in_vm(f"snap list {app} >/dev/null 2>&1 && echo yes || echo no", timeout=10)
                return None if out is None else out.strip() == "yes"

            if app == "google-chrome":
                out = self._exec_in_vm(
                    "(command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1) && echo yes || echo no",
                    timeout=10,
                )
                return None if out is None else out.strip() == "yes"

            if app == "docker":
                out = self._exec_in_vm("command -v docker >/dev/null 2>&1 && echo yes || echo no", timeout=10)
                return None if out is None else out.strip() == "yes"

            if app == "firefox":
                out = self._exec_in_vm("command -v firefox >/dev/null 2>&1 && echo yes || echo no", timeout=10)
                return None if out is None else out.strip() == "yes"

            out = self._exec_in_vm(f"command -v {app} >/dev/null 2>&1 && echo yes || echo no", timeout=10)
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
                    f"{user_env} timeout 20 firefox --headless --version >/dev/null 2>&1 && echo yes || echo no",
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
                out = self._exec_in_vm("timeout 20 docker info >/dev/null 2>&1 && echo yes || echo no", timeout=30)
                return None if out is None else out.strip() == "yes"

            out = self._exec_in_vm(f"timeout 20 {app} --version >/dev/null 2>&1 && echo yes || echo no", timeout=30)
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
            pending = False

            if installed is True:
                launched = _run_test(app)
                if launched is None:
                    note = "test failed to execute"
                elif launched is False and setup_in_progress:
                    pending = True
                    note = note or "setup in progress"
            elif installed is False:
                if setup_in_progress:
                    pending = True
                    note = "setup in progress"
                else:
                    note = "not installed"
            else:
                note = "install status unknown"

            installed_icon = (
                "[green]✅[/]"
                if installed is True
                else ("[yellow]⏳[/]" if pending else "[red]❌[/]")
                if installed is False
                else "[dim]?[/]"
            )
            launch_icon = (
                "[green]✅[/]"
                if launched is True
                else ("[yellow]⏳[/]" if pending else "[red]❌[/]")
                if launched is False
                else ("[dim]—[/]" if installed is not True else "[dim]?[/]")
            )

            table.add_row(app, installed_icon, launch_icon, note)

            passed = installed is True and launched is True
            if pending:
                self.results["smoke"]["skipped"] += 1
            elif passed:
                self.results["smoke"]["passed"] += 1
            else:
                self.results["smoke"]["failed"] += 1

            self.results["smoke"]["details"].append(
                {
                    "app": app,
                    "installed": installed,
                    "launched": launched,
                    "note": note,
                    "pending": pending,
                }
            )

        self.console.print(table)
        return self.results["smoke"]
