from typing import Dict

from rich.table import Table


class PackageValidationMixin:
    def validate_packages(self) -> Dict:
        """Validate APT packages are installed."""
        setup_in_progress = self._setup_in_progress() is True
        self.console.print("\n[bold]📦 Validating APT Packages...[/]")

        packages = self.config.get("packages", [])
        if not packages:
            self.console.print("[dim]No APT packages configured[/]")
            return self.results["packages"]

        total_pkgs = len(packages)
        self.console.print(f"[dim]Checking {total_pkgs} packages via QGA...[/]")

        pkg_table = Table(title="Package Validation", border_style="cyan")
        pkg_table.add_column("Package", style="bold")
        pkg_table.add_column("Status", justify="center")
        pkg_table.add_column("Version", style="dim")

        for idx, package in enumerate(packages, 1):
            if idx == 1 or idx % 25 == 0 or idx == total_pkgs:
                self.console.print(f"[dim]   ...packages progress: {idx}/{total_pkgs}[/]")
            self.results["packages"]["total"] += 1

            check_cmd = f"dpkg -l | grep -E '^ii  {package}' | awk '{{print $3}}'"
            version = self._exec_in_vm(check_cmd)

            if version:
                pkg_table.add_row(package, "[green]✅ Installed[/]", version[:40])
                self.results["packages"]["passed"] += 1
                self.results["packages"]["details"].append(
                    {"package": package, "installed": True, "version": version}
                )
            else:
                if setup_in_progress:
                    pkg_table.add_row(package, "[yellow]⏳ Pending[/]", "")
                    self.results["packages"]["skipped"] += 1
                    self.results["packages"]["details"].append(
                        {"package": package, "installed": False, "version": None, "pending": True}
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
        setup_in_progress = self._setup_in_progress() is True
        self.console.print("\n[bold]📦 Validating Snap Packages...[/]")

        snap_packages = self.config.get("snap_packages", [])
        if not snap_packages:
            self.console.print("[dim]No snap packages configured[/]")
            return self.results["snap_packages"]

        total_snaps = len(snap_packages)
        self.console.print(f"[dim]Checking {total_snaps} snap packages via QGA...[/]")

        snap_table = Table(title="Snap Package Validation", border_style="cyan")
        snap_table.add_column("Package", style="bold")
        snap_table.add_column("Status", justify="center")
        snap_table.add_column("Version", style="dim")

        for idx, package in enumerate(snap_packages, 1):
            if idx == 1 or idx % 25 == 0 or idx == total_snaps:
                self.console.print(f"[dim]   ...snap progress: {idx}/{total_snaps}[/]")
            self.results["snap_packages"]["total"] += 1

            check_cmd = f"snap list | grep '^{package}' | awk '{{print $2}}'"
            version = self._exec_in_vm(check_cmd)

            if version:
                snap_table.add_row(package, "[green]✅ Installed[/]", version[:40])
                self.results["snap_packages"]["passed"] += 1
                self.results["snap_packages"]["details"].append(
                    {"package": package, "installed": True, "version": version}
                )
            else:
                if setup_in_progress:
                    snap_table.add_row(package, "[yellow]⏳ Pending[/]", "")
                    self.results["snap_packages"]["skipped"] += 1
                    self.results["snap_packages"]["details"].append(
                        {
                            "package": package,
                            "installed": False,
                            "version": None,
                            "pending": True,
                        }
                    )
                else:
                    snap_table.add_row(package, "[red]❌ Missing[/]", "")
                    self.results["snap_packages"]["failed"] += 1
                    self.results["snap_packages"]["details"].append(
                        {"package": package, "installed": False, "version": None}
                    )

        self.console.print(snap_table)
        msg = f"{self.results['snap_packages']['passed']}/{self.results['snap_packages']['total']} snap packages installed"
        if self.results["snap_packages"].get("skipped", 0) > 0:
            msg += f" ({self.results['snap_packages']['skipped']} pending)"
        self.console.print(f"[dim]{msg}[/]")

        return self.results["snap_packages"]
