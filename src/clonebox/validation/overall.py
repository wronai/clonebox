import subprocess
import time
from typing import Dict, Optional

from rich.panel import Panel
from rich.table import Table


class OverallValidationMixin:
    def validate_all(self) -> Dict:
        """Run all validations and return comprehensive results."""
        setup_in_progress = self._setup_in_progress() is True
        self.console.print("[bold cyan]🔍 Running Full Validation...[/]")

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

        if not self._check_qga_ready():
            wait_deadline = time.time() + 180
            self.console.print("[yellow]⏳ Waiting for QEMU Guest Agent (up to 180s)...[/]")
            last_log = 0
            while time.time() < wait_deadline:
                time.sleep(5)
                if self._check_qga_ready():
                    break
                elapsed = int(180 - (wait_deadline - time.time()))
                if elapsed - last_log >= 15:
                    self.console.print(f"[dim]   ...still waiting for QGA ({elapsed}s elapsed)[/]")
                    last_log = elapsed

        if not self._check_qga_ready():
            self.console.print("[yellow]⚠️  QEMU Guest Agent not responding - trying SSH fallback...[/]")
            self._exec_transport = "ssh"
            smoke = self._ssh_exec("echo ok", timeout=10)
            if smoke != "ok":
                self.console.print("[red]❌ SSH fallback failed[/]")
                try:
                    key_path = self._get_ssh_key_path()
                    ssh_port = self._get_ssh_port()
                    if key_path is None:
                        self.console.print(
                            "[dim]SSH key not found for this VM (expected: <images_dir>/<vm_name>/ssh_key)[/]"
                        )
                    else:
                        self.console.print(f"[dim]Expected SSH key: {key_path}[/]")
                    self.console.print(
                        f"[dim]Expected SSH port (passt forward): 127.0.0.1:{ssh_port} -> guest:22[/]"
                    )
                    self.console.print(
                        "[dim]SSH fallback requires libvirt user networking with passt + <portForward> in VM XML.[/]"
                    )
                except Exception:
                    pass
                self.console.print("\n[bold]🔧 Troubleshooting QGA:[/]")
                self.console.print("  1. The VM might still be booting. Wait 30-60 seconds.")
                self.console.print("  2. Ensure the agent is installed and running inside the VM:")
                self.console.print("     [dim]virsh console " + self.vm_name + "[/]")
                self.console.print("     [dim]sudo systemctl status qemu-guest-agent[/]")
                self.console.print("  3. If newly created, cloud-init might still be running.")
                self.console.print("  4. Check VM logs: [dim]clonebox logs " + self.vm_name + "[/]")
                self.console.print(
                    "\n[yellow]⚠️  Skipping deep validation as it requires a working Guest Agent or SSH access.[/]"
                )
                self.results["overall"] = "qga_not_ready"
                return self.results

            self.console.print("[green]✅ SSH fallback connected (executing validations over SSH)[/]")

        ci_status = self._exec_in_vm(
            "cloud-init status --long 2>/dev/null || cloud-init status 2>/dev/null || true", timeout=20
        )
        if ci_status:
            ci_lower = ci_status.lower()
            if "running" in ci_lower:
                self.console.print(
                    "[yellow]⏳ Cloud-init still running - deep validation will show pending states[/]"
                )
                setup_in_progress = True

        ready_msg = self._exec_in_vm("cat /var/log/clonebox-ready 2>/dev/null || true", timeout=10)
        if not setup_in_progress and not (ready_msg and "clonebox vm ready" in ready_msg.lower()):
            self.console.print(
                "[yellow]⚠️  CloneBox ready marker not found - provisioning may not have completed[/]"
            )

        self.validate_disk_space()
        self.validate_mounts()
        self.validate_packages()
        self.validate_snap_packages()
        self.validate_services()
        self.validate_apps()
        if self.smoke_test:
            self.validate_smoke_tests()

        recent_err = self._exec_in_vm("journalctl -p err -n 30 --no-pager 2>/dev/null || true", timeout=20)
        if recent_err:
            recent_err = recent_err.strip()
            if recent_err:
                self.console.print(Panel(recent_err, title="Recent system errors", border_style="red"))

        disk_failed = 1 if self.results.get("disk", {}).get("usage_pct", 0) > 90 else 0
        total_checks = (
            1
            + self.results["mounts"]["total"]
            + self.results["packages"]["total"]
            + self.results["snap_packages"]["total"]
            + self.results["services"]["total"]
            + self.results["apps"]["total"]
            + (self.results["smoke"]["total"] if self.smoke_test else 0)
        )

        total_passed = (
            (1 - disk_failed)
            + self.results["mounts"]["passed"]
            + self.results["packages"]["passed"]
            + self.results["snap_packages"]["passed"]
            + self.results["services"]["passed"]
            + self.results["apps"]["passed"]
            + (self.results["smoke"]["passed"] if self.smoke_test else 0)
        )

        total_failed = (
            disk_failed
            + self.results["mounts"]["failed"]
            + self.results["packages"]["failed"]
            + self.results["snap_packages"]["failed"]
            + self.results["services"]["failed"]
            + self.results["apps"]["failed"]
            + (self.results["smoke"]["failed"] if self.smoke_test else 0)
        )

        skipped_mounts = self.results["mounts"].get("skipped", 0)
        skipped_packages = self.results["packages"].get("skipped", 0)
        skipped_services = self.results["services"].get("skipped", 0)
        skipped_snaps = self.results["snap_packages"].get("skipped", 0)
        skipped_apps = self.results["apps"].get("skipped", 0)
        skipped_smoke = self.results["smoke"].get("skipped", 0) if self.smoke_test else 0
        total_skipped = (
            skipped_mounts + skipped_packages + skipped_services + skipped_snaps + skipped_apps + skipped_smoke
        )

        self.console.print("\n[bold]📊 Validation Summary[/]")
        summary_table = Table(border_style="cyan")
        summary_table.add_column("Category", style="bold")
        summary_table.add_column("Passed", justify="right", style="green")
        summary_table.add_column("Failed", justify="right", style="red")
        summary_table.add_column("Skipped/Pending", justify="right", style="dim")
        summary_table.add_column("Total", justify="right")

        disk_usage_pct = self.results.get("disk", {}).get("usage_pct", 0)
        disk_avail = self.results.get("disk", {}).get("avail", "?")
        disk_total = self.results.get("disk", {}).get("total", "?")

        disk_status_passed = "[green]OK[/]" if disk_usage_pct <= 90 else "—"
        disk_status_failed = "—" if disk_usage_pct <= 90 else f"[red]FULL ({disk_usage_pct}%)[/]"

        summary_table.add_row(
            "Disk Space",
            disk_status_passed,
            disk_status_failed,
            "—",
            f"{disk_usage_pct}% of {disk_total} ({disk_avail} free)",
        )

        summary_table.add_row(
            "Mounts",
            str(self.results["mounts"]["passed"]),
            str(self.results["mounts"]["failed"]),
            str(skipped_mounts) if skipped_mounts else "—",
            str(self.results["mounts"]["total"]),
        )
        summary_table.add_row(
            "APT Packages",
            str(self.results["packages"]["passed"]),
            str(self.results["packages"]["failed"]),
            str(skipped_packages) if skipped_packages else "—",
            str(self.results["packages"]["total"]),
        )
        summary_table.add_row(
            "Snap Packages",
            str(self.results["snap_packages"]["passed"]),
            str(self.results["snap_packages"]["failed"]),
            str(skipped_snaps) if skipped_snaps else "—",
            str(self.results["snap_packages"]["total"]),
        )
        summary_table.add_row(
            "Services",
            str(self.results["services"]["passed"]),
            str(self.results["services"]["failed"]),
            str(skipped_services) if skipped_services else "—",
            str(self.results["services"]["total"]),
        )
        summary_table.add_row(
            "Apps",
            str(self.results["apps"]["passed"]),
            str(self.results["apps"]["failed"]),
            str(skipped_apps) if skipped_apps else "—",
            str(self.results["apps"]["total"]),
        )
        summary_table.add_row(
            "[bold]TOTAL",
            f"[bold green]{total_passed}",
            f"[bold red]{total_failed}",
            f"[dim]{total_skipped}[/]" if total_skipped else "[dim]0[/]",
            f"[bold]{total_checks}",
        )

        self.console.print(summary_table)

        if total_failed == 0 and total_checks > 0 and total_skipped > 0:
            self.results["overall"] = "pending"
            self.console.print("\n[bold yellow]⏳ Setup in progress - some checks are pending[/]")
        elif total_failed == 0 and total_checks > 0:
            self.results["overall"] = "pass"
            self.console.print("\n[bold green]✅ All validations passed![/]")
        elif total_failed > 0:
            self.results["overall"] = "partial"
            self.console.print(f"\n[bold yellow]⚠️  {total_failed}/{total_checks} checks failed[/]")
            self.console.print("[dim]Consider rebuilding VM: clonebox clone . --user --run --replace[/]")
        else:
            self.results["overall"] = "no_checks"
            self.console.print("\n[dim]No validation checks configured[/]")

        return self.results
