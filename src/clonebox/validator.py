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
from rich.table import Table


class VMValidator:
    """Validates VM configuration against expected state from YAML."""
    
    def __init__(self, config: dict, vm_name: str, conn_uri: str, console: Console = None):
        self.config = config
        self.vm_name = vm_name
        self.conn_uri = conn_uri
        self.console = console or Console()
        self.results = {
            "mounts": {"passed": 0, "failed": 0, "total": 0, "details": []},
            "packages": {"passed": 0, "failed": 0, "total": 0, "details": []},
            "snap_packages": {"passed": 0, "failed": 0, "total": 0, "details": []},
            "services": {"passed": 0, "failed": 0, "total": 0, "details": []},
            "overall": "unknown"
        }
    
    def _exec_in_vm(self, command: str, timeout: int = 10) -> Optional[str]:
        """Execute command in VM using QEMU guest agent."""
        try:
            # Execute command
            result = subprocess.run(
                ["virsh", "--connect", self.conn_uri, "qemu-agent-command", self.vm_name,
                 f'{{"execute":"guest-exec","arguments":{{"path":"/bin/sh","arg":["-c","{command}"],"capture-output":true}}}}'],
                capture_output=True, text=True, timeout=timeout
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
                ["virsh", "--connect", self.conn_uri, "qemu-agent-command", self.vm_name,
                 f'{{"execute":"guest-exec-status","arguments":{{"pid":{pid}}}}}'],
                capture_output=True, text=True, timeout=5
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
            mounted_paths = [line.split()[2] for line in mount_output.split('\n') if line.strip()]
        
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
            
            self.results["mounts"]["details"].append({
                "path": guest_path,
                "mounted": is_mounted,
                "accessible": accessible,
                "files": file_count,
                "status": status
            })
        
        self.console.print(mount_table)
        self.console.print(f"[dim]{self.results['mounts']['passed']}/{self.results['mounts']['total']} mounts working[/]")
        
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
                self.results["packages"]["details"].append({
                    "package": package,
                    "installed": True,
                    "version": version
                })
            else:
                pkg_table.add_row(package, "[red]❌ Missing[/]", "")
                self.results["packages"]["failed"] += 1
                self.results["packages"]["details"].append({
                    "package": package,
                    "installed": False,
                    "version": None
                })
        
        self.console.print(pkg_table)
        self.console.print(f"[dim]{self.results['packages']['passed']}/{self.results['packages']['total']} packages installed[/]")
        
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
                self.results["snap_packages"]["details"].append({
                    "package": package,
                    "installed": True,
                    "version": version
                })
            else:
                snap_table.add_row(package, "[red]❌ Missing[/]", "")
                self.results["snap_packages"]["failed"] += 1
                self.results["snap_packages"]["details"].append({
                    "package": package,
                    "installed": False,
                    "version": None
                })
        
        self.console.print(snap_table)
        self.console.print(f"[dim]{self.results['snap_packages']['passed']}/{self.results['snap_packages']['total']} snap packages installed[/]")
        
        return self.results["snap_packages"]
    
    # Services that should NOT be validated in VM (host-specific)
    VM_EXCLUDED_SERVICES = {
        "libvirtd", "virtlogd", "libvirt-guests", "qemu-guest-agent",
        "bluetooth", "bluez", "upower", "thermald", "tlp", "power-profiles-daemon",
        "gdm", "gdm3", "sddm", "lightdm",
        "snap.cups.cups-browsed", "snap.cups.cupsd",
        "ModemManager", "wpa_supplicant",
        "accounts-daemon", "colord", "switcheroo-control",
    }

    def validate_services(self) -> Dict:
        """Validate services are enabled and running."""
        self.console.print("\n[bold]⚙️  Validating Services...[/]")
        
        services = self.config.get("services", [])
        if not services:
            self.console.print("[dim]No services configured[/]")
            return self.results["services"]
        
        # Initialize skipped counter
        if "skipped" not in self.results["services"]:
            self.results["services"]["skipped"] = 0
        
        svc_table = Table(title="Service Validation", border_style="cyan")
        svc_table.add_column("Service", style="bold")
        svc_table.add_column("Enabled", justify="center")
        svc_table.add_column("Running", justify="center")
        svc_table.add_column("Note", style="dim")
        
        for service in services:
            # Check if service should be skipped (host-specific)
            if service in self.VM_EXCLUDED_SERVICES:
                svc_table.add_row(service, "[dim]—[/]", "[dim]—[/]", "host-only")
                self.results["services"]["skipped"] += 1
                self.results["services"]["details"].append({
                    "service": service,
                    "enabled": None,
                    "running": None,
                    "skipped": True,
                    "reason": "host-specific service"
                })
                continue
            
            self.results["services"]["total"] += 1
            
            # Check if enabled
            enabled_cmd = f"systemctl is-enabled {service} 2>/dev/null"
            enabled_status = self._exec_in_vm(enabled_cmd)
            is_enabled = enabled_status == "enabled"
            
            # Check if running
            running_cmd = f"systemctl is-active {service} 2>/dev/null"
            running_status = self._exec_in_vm(running_cmd)
            is_running = running_status == "active"
            
            enabled_icon = "[green]✅[/]" if is_enabled else "[yellow]⚠️[/]"
            running_icon = "[green]✅[/]" if is_running else "[red]❌[/]"
            
            svc_table.add_row(service, enabled_icon, running_icon, "")
            
            if is_enabled and is_running:
                self.results["services"]["passed"] += 1
            else:
                self.results["services"]["failed"] += 1
            
            self.results["services"]["details"].append({
                "service": service,
                "enabled": is_enabled,
                "running": is_running,
                "skipped": False
            })
        
        self.console.print(svc_table)
        skipped = self.results["services"].get("skipped", 0)
        msg = f"{self.results['services']['passed']}/{self.results['services']['total']} services active"
        if skipped > 0:
            msg += f" ({skipped} host-only skipped)"
        self.console.print(f"[dim]{msg}[/]")
        
        return self.results["services"]
    
    def validate_all(self) -> Dict:
        """Run all validations and return comprehensive results."""
        self.console.print("[bold cyan]🔍 Running Full Validation...[/]")
        
        # Check if VM is running
        try:
            result = subprocess.run(
                ["virsh", "--connect", self.conn_uri, "domstate", self.vm_name],
                capture_output=True, text=True, timeout=5
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
        
        # Run all validations
        self.validate_mounts()
        self.validate_packages()
        self.validate_snap_packages()
        self.validate_services()
        
        # Calculate overall status
        total_checks = (
            self.results["mounts"]["total"] +
            self.results["packages"]["total"] +
            self.results["snap_packages"]["total"] +
            self.results["services"]["total"]
        )
        
        total_passed = (
            self.results["mounts"]["passed"] +
            self.results["packages"]["passed"] +
            self.results["snap_packages"]["passed"] +
            self.results["services"]["passed"]
        )
        
        total_failed = (
            self.results["mounts"]["failed"] +
            self.results["packages"]["failed"] +
            self.results["snap_packages"]["failed"] +
            self.results["services"]["failed"]
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
        
        summary_table.add_row("Mounts", str(self.results["mounts"]["passed"]), 
                             str(self.results["mounts"]["failed"]), "—",
                             str(self.results["mounts"]["total"]))
        summary_table.add_row("APT Packages", str(self.results["packages"]["passed"]), 
                             str(self.results["packages"]["failed"]), "—",
                             str(self.results["packages"]["total"]))
        summary_table.add_row("Snap Packages", str(self.results["snap_packages"]["passed"]), 
                             str(self.results["snap_packages"]["failed"]), "—",
                             str(self.results["snap_packages"]["total"]))
        summary_table.add_row("Services", str(self.results["services"]["passed"]), 
                             str(self.results["services"]["failed"]), 
                             str(skipped_services),
                             str(self.results["services"]["total"]))
        summary_table.add_row("[bold]TOTAL", f"[bold green]{total_passed}", 
                             f"[bold red]{total_failed}", 
                             f"[dim]{skipped_services}[/]",
                             f"[bold]{total_checks}")
        
        self.console.print(summary_table)
        
        # Determine overall status
        if total_failed == 0 and total_checks > 0:
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
