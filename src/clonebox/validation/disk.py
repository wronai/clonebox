from typing import Dict, List, Optional, Tuple

from rich.table import Table


class DiskValidationMixin:
    def validate_disk_space(self) -> Dict:
        """Validate disk space on root filesystem."""
        setup_in_progress = self._setup_in_progress() is True
        self.console.print("\n[bold]💾 Validating Disk Space...[/]")

        df_output = self._exec_in_vm("df -h / --output=pcent,avail,size | tail -n 1", timeout=20)
        if not df_output:
            self.console.print("[red]❌ Could not check disk space[/]")
            return {"status": "error"}

        try:
            parts = df_output.split()
            usage_pct = int(parts[0].replace("%", ""))
            avail = parts[1]
            total = parts[2]

            self.results["disk"] = {"usage_pct": usage_pct, "avail": avail, "total": total}

            if usage_pct > 90:
                self.console.print(
                    f"[red]❌ Disk nearly full: {usage_pct}% used ({avail} available of {total})[/]"
                )
                status = "fail"
            elif usage_pct > 85:
                self.console.print(
                    f"[yellow]⚠️  Disk usage high: {usage_pct}% used ({avail} available of {total})[/]"
                )
                status = "warning"
            else:
                self.console.print(
                    f"[green]✅ Disk space OK: {usage_pct}% used ({avail} available of {total})[/]"
                )
                status = "pass"

            if usage_pct > 80:
                self._print_disk_usage_breakdown()

            return self.results["disk"]
        except Exception as e:
            self.console.print(f"[red]❌ Error parsing df output: {e}[/]")
            return {"status": "error"}

    def _print_disk_usage_breakdown(self) -> None:
        def _parse_du_lines(out: Optional[str]) -> List[Tuple[str, str]]:
            if not out:
                return []
            rows: List[Tuple[str, str]] = []
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) != 2:
                    continue
                size, path = parts
                rows.append((path, size))
            return rows

        def _dir_size(path: str, timeout: int = 30) -> Optional[str]:
            out = self._exec_in_vm(
                f"du -x -s -h {path} 2>/dev/null | head -n 1 | cut -f1", timeout=timeout
            )
            return out.strip() if out else None

        self.console.print("\n[bold]📁 Disk usage breakdown (largest directories)[/]")

        top_level = self._exec_in_vm(
            "du -x -h --max-depth=1 / 2>/dev/null | sort -hr | head -n 15",
            timeout=60,
        )
        top_rows = _parse_du_lines(top_level)

        if top_rows:
            table = Table(title="Disk Usage: / (Top 15)", border_style="cyan")
            table.add_column("Path", style="bold")
            table.add_column("Size", justify="right")
            for path, size in top_rows:
                table.add_row(path, size)
            self.console.print(table)
        else:
            self.console.print("[dim]Could not compute top-level directory sizes (du may be busy)[/]")

        var_sz = _dir_size("/var")
        home_sz = _dir_size("/home")
        if var_sz or home_sz:
            sum_table = Table(title="Disk Usage: Key Directories", border_style="cyan")
            sum_table.add_column("Path", style="bold")
            sum_table.add_column("Size", justify="right")
            for p in [
                "/var",
                "/var/lib",
                "/var/log",
                "/var/cache",
                "/var/lib/snapd",
                "/home",
                "/home/ubuntu",
                "/tmp",
            ]:
                sz = _dir_size(p, timeout=30)
                if sz:
                    sum_table.add_row(p, sz)
            self.console.print(sum_table)

        var_breakdown = self._exec_in_vm(
            "du -x -h --max-depth=1 /var 2>/dev/null | sort -hr | head -n 12",
            timeout=60,
        )
        var_rows = _parse_du_lines(var_breakdown)
        if var_rows:
            vtable = Table(title="Disk Usage: /var (Top 12)", border_style="cyan")
            vtable.add_column("Path", style="bold")
            vtable.add_column("Size", justify="right")
            for path, size in var_rows:
                vtable.add_row(path, size)
            self.console.print(vtable)

        home_breakdown = self._exec_in_vm(
            "du -x -h --max-depth=2 /home/ubuntu 2>/dev/null | sort -hr | head -n 12",
            timeout=60,
        )
        home_rows = _parse_du_lines(home_breakdown)
        if home_rows:
            htable = Table(title="Disk Usage: /home/ubuntu (Top 12)", border_style="cyan")
            htable.add_column("Path", style="bold")
            htable.add_column("Size", justify="right")
            for path, size in home_rows:
                htable.add_row(path, size)
            self.console.print(htable)

        copy_paths = self.config.get("copy_paths", None)
        if not isinstance(copy_paths, dict) or not copy_paths:
            copy_paths = self.config.get("app_data_paths", {})
        if copy_paths:
            ctable = Table(title="Disk Usage: Configured Imported Paths", border_style="cyan")
            ctable.add_column("Guest Path", style="bold")
            ctable.add_column("Size", justify="right")
            for _, guest_path in copy_paths.items():
                sz = _dir_size(guest_path, timeout=30)
                if sz:
                    ctable.add_row(str(guest_path), sz)
                else:
                    ctable.add_row(str(guest_path), "—")
            self.console.print(ctable)
