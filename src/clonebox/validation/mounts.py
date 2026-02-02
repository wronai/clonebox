from typing import Dict

from rich.table import Table


class MountValidationMixin:
    def validate_mounts(self) -> Dict:
        """Validate all mount points and copied data paths."""
        setup_in_progress = self._setup_in_progress_cache is True
        self.console.print("\n[bold]💾 Validating Mounts & Data...[/]")

        paths = self.config.get("paths", {})
        copy_paths = self.config.get("copy_paths", None)
        if not isinstance(copy_paths, dict) or not copy_paths:
            copy_paths = self.config.get("app_data_paths", {})

        if not paths and not copy_paths:
            self.console.print("[dim]No mounts or data paths configured[/]")
            return self.results["mounts"]

        mount_output = self._exec_in_vm("mount | grep 9p")
        mounted_paths = []
        if mount_output:
            for line in mount_output.split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    mounted_paths.append(parts[2])

        mount_table = Table(title="Data Validation", border_style="cyan")
        mount_table.add_column("Guest Path", style="bold")
        mount_table.add_column("Type", justify="center")
        mount_table.add_column("Status", justify="center")
        mount_table.add_column("Files", justify="right")

        for host_path, guest_path in paths.items():
            self.results["mounts"]["total"] += 1

            is_mounted = any(guest_path in mp for mp in mounted_paths)

            accessible = False
            file_count = "?"

            if is_mounted:
                test_result = self._exec_in_vm(f"test -d {guest_path} && echo 'yes' || echo 'no'")
                accessible = test_result == "yes"

                if accessible:
                    count_str = self._exec_in_vm(f"ls -A {guest_path} 2>/dev/null | wc -l")
                    if count_str and count_str.isdigit():
                        file_count = count_str

            if is_mounted and accessible:
                status_icon = "[green]✅ Mounted[/]"
                self.results["mounts"]["passed"] += 1
                status = "pass"
            elif is_mounted:
                status_icon = "[red]❌ Inaccessible[/]"
                self.results["mounts"]["failed"] += 1
                status = "mounted_but_inaccessible"
            elif setup_in_progress:
                status_icon = "[yellow]⏳ Pending[/]"
                status = "pending"
                self.results["mounts"]["skipped"] += 1
            else:
                status_icon = "[red]❌ Not Mounted[/]"
                self.results["mounts"]["failed"] += 1
                status = "not_mounted"

            mount_table.add_row(guest_path, "Bind Mount", status_icon, str(file_count))
            self.results["mounts"]["details"].append(
                {
                    "path": guest_path,
                    "type": "mount",
                    "mounted": is_mounted,
                    "accessible": accessible,
                    "files": file_count,
                    "status": status,
                }
            )

        for host_path, guest_path in copy_paths.items():
            self.results["mounts"]["total"] += 1

            exists = False
            file_count = "?"

            test_result = self._exec_in_vm(f"test -d {guest_path} && echo 'yes' || echo 'no'")
            exists = test_result == "yes"

            if exists:
                count_str = self._exec_in_vm(f"ls -A {guest_path} 2>/dev/null | wc -l")
                if count_str and count_str.isdigit():
                    file_count = count_str

            if exists:
                status_icon = "[green]✅ Copied[/]"
                self.results["mounts"]["passed"] += 1
                status = "pass"
            elif setup_in_progress:
                status_icon = "[yellow]⏳ Pending[/]"
                status = "pending"
                self.results["mounts"]["skipped"] += 1
            else:
                status_icon = "[red]❌ Missing[/]"
                self.results["mounts"]["failed"] += 1
                status = "missing"

            mount_table.add_row(guest_path, "Imported", status_icon, str(file_count))
            self.results["mounts"]["details"].append(
                {
                    "path": guest_path,
                    "type": "copy",
                    "mounted": False,
                    "accessible": exists,
                    "files": file_count,
                    "status": status,
                }
            )

        self.console.print(mount_table)
        self.console.print(
            f"[dim]{self.results['mounts']['passed']}/{self.results['mounts']['total']} paths valid[/]"
        )

        return self.results["mounts"]
