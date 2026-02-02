from typing import Dict

from rich.table import Table


class ServiceValidationMixin:
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
        setup_in_progress = self._setup_in_progress() is True
        self.console.print("\n[bold]⚙️  Validating Services...[/]")

        services = self.config.get("services", [])
        if not services:
            self.console.print("[dim]No services configured[/]")
            return self.results["services"]

        total_svcs = len(services)
        self.console.print(f"[dim]Checking {total_svcs} services via QGA...[/]")

        if "skipped" not in self.results["services"]:
            self.results["services"]["skipped"] = 0

        svc_table = Table(title="Service Validation", border_style="cyan")
        svc_table.add_column("Service", style="bold")
        svc_table.add_column("Enabled", justify="center")
        svc_table.add_column("Running", justify="center")
        svc_table.add_column("PID", justify="right", style="dim")
        svc_table.add_column("Note", style="dim")

        for idx, service in enumerate(services, 1):
            if idx == 1 or idx % 25 == 0 or idx == total_svcs:
                self.console.print(f"[dim]   ...services progress: {idx}/{total_svcs}[/]")
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
                pid_out = self._exec_in_vm(f"systemctl show -p MainPID --value {service} 2>/dev/null")
                if pid_out is None:
                    pid_value = "?"
                else:
                    pid_value = pid_out.strip() or "?"
            else:
                pid_value = "—"

            enabled_icon = (
                "[green]✅[/]" if is_enabled else ("[yellow]⏳[/]" if setup_in_progress else "[yellow]⚠️[/]")
            )
            running_icon = (
                "[green]✅[/]" if is_running else ("[yellow]⏳[/]" if setup_in_progress else "[red]❌[/]")
            )

            svc_table.add_row(service, enabled_icon, running_icon, pid_value, "")

            if is_enabled and is_running:
                self.results["services"]["passed"] += 1
            elif setup_in_progress:
                self.results["services"]["skipped"] += 1
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
