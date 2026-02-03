#!/usr/bin/env python3
"""
CloneBox CLI - Interactive command-line interface for creating VMs.
"""

import argparse
import json
import os
import re
import secrets
import sys
import time
from dataclasses import asdict
from typing import Any, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path

import questionary
import yaml
from questionary import Style
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from clonebox import __version__
from clonebox.cloner import SelectiveVMCloner, VMConfig
from clonebox.container import ContainerCloner
from clonebox.detector import SystemDetector
from clonebox.models import ContainerConfig
from clonebox.profiles import merge_with_profile
from clonebox.exporter import SecureExporter, VMExporter
from clonebox.importer import SecureImporter, VMImporter
from clonebox.monitor import ResourceMonitor, format_bytes
from clonebox.p2p import P2PManager
from clonebox.snapshots import SnapshotManager, SnapshotType
from clonebox.health import HealthCheckManager, ProbeConfig, ProbeType
from clonebox.audit import get_audit_logger, AuditQuery, AuditEventType, AuditOutcome
from clonebox.orchestrator import Orchestrator, OrchestrationResult
from clonebox.plugins import get_plugin_manager, PluginHook, PluginContext
from clonebox.policies import PolicyEngine, PolicyValidationError, PolicyViolationError
from clonebox.remote import RemoteCloner, RemoteConnection

# Custom questionary style
custom_style = Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:green"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
        ("separator", "fg:gray"),
        ("instruction", "fg:gray italic"),
    ]
)

console = Console()


def print_banner():
    """Print the CloneBox banner."""
    banner = """
╔═══════════════════════════════════════════════════════════════╗
║   ____  _                    ____                             ║
║  / ___|| |  ___   _ __   ___|  _ \\  ___ __  __                ║
║ | |    | | / _ \\ | '_ \\ / _ \\ |_) |/ _ \\\\ \\/ /                ║
║ | |___ | || (_) || | | |  __/  _ <| (_) |>  <                 ║
║  \\____||_| \\___/ |_| |_|\\___|_| \\_\\\\___//_/\\_\\                ║
║                                                               ║
║  Clone your workstation to an isolated VM                     ║
╚═══════════════════════════════════════════════════════════════╝
"""
    console.print(banner, style="cyan")
    console.print(f"  Version {__version__}\n", style="dim")


def _resolve_vm_name_and_config_file(name: Optional[str]) -> Tuple[str, Optional[Path]]:
    config_file: Optional[Path] = None

    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        target_path = Path(name).expanduser().resolve()
        config_file = target_path / ".clonebox.yaml" if target_path.is_dir() else target_path
        if config_file.exists():
            config = load_clonebox_config(config_file)
            return config["vm"]["name"], config_file
        raise FileNotFoundError(f"Config not found: {config_file}")

    if not name:
        config_file = Path.cwd() / ".clonebox.yaml"
        if config_file.exists():
            config = load_clonebox_config(config_file)
            return config["vm"]["name"], config_file
        raise FileNotFoundError("No VM name specified and no .clonebox.yaml found")

    return name, None


def _qga_ping(vm_name: str, conn_uri: str) -> bool:
    import subprocess
    import json
    import time

    try:
        for _ in range(5):
            try:
                result = subprocess.run(
                    [
                        "virsh",
                        "--connect",
                        conn_uri,
                        "qemu-agent-command",
                        vm_name,
                        json.dumps({"execute": "guest-ping"}),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return True
            except subprocess.TimeoutExpired:
                pass
            time.sleep(1)
        return False
    except Exception:
        return False


def _qga_exec(vm_name: str, conn_uri: str, command: str, timeout: int = 10) -> Optional[str]:
    import subprocess
    import base64
    import time
    import json

    try:
        payload = {
            "execute": "guest-exec",
            "arguments": {
                "path": "/bin/sh",
                "arg": ["-c", command],
                "capture-output": True,
            },
        }
        exec_result = subprocess.run(
            [
                "virsh",
                "--connect",
                conn_uri,
                "qemu-agent-command",
                vm_name,
                json.dumps(payload),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if exec_result.returncode != 0:
            return None

        resp = json.loads(exec_result.stdout)
        pid = resp.get("return", {}).get("pid")
        if not pid:
            return None

        deadline = time.time() + timeout
        while time.time() < deadline:
            status_payload = {"execute": "guest-exec-status", "arguments": {"pid": pid}}
            status_result = subprocess.run(
                [
                    "virsh",
                    "--connect",
                    conn_uri,
                    "qemu-agent-command",
                    vm_name,
                    json.dumps(status_payload),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if status_result.returncode != 0:
                return None

            status_resp = json.loads(status_result.stdout)
            ret = status_resp.get("return", {})
            if not ret.get("exited", False):
                time.sleep(0.3)
                continue

            out_data = ret.get("out-data")
            if out_data:
                return base64.b64decode(out_data).decode().strip()
            return ""

        return None
    except Exception:
        return None


def run_vm_diagnostics(
    vm_name: str,
    conn_uri: str,
    config_file: Optional[Path],
    *,
    verbose: bool = False,
    json_output: bool = False,
) -> dict:
    import subprocess

    result: dict = {
        "vm": {"name": vm_name, "conn_uri": conn_uri},
        "state": {},
        "network": {},
        "qga": {},
        "cloud_init": {},
        "mounts": {},
        "health": {},
    }

    console.print(f"[bold cyan]🧪 Diagnostics: {vm_name}[/]\n")

    guest_agent_ready = _qga_ping(vm_name, conn_uri)
    result["qga"]["ready"] = guest_agent_ready

    try:
        domstate = subprocess.run(
            ["virsh", "--connect", conn_uri, "domstate", vm_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        result["state"] = {
            "returncode": domstate.returncode,
            "stdout": domstate.stdout.strip(),
            "stderr": domstate.stderr.strip(),
        }
        if domstate.returncode == 0 and domstate.stdout.strip():
            console.print(f"[green]✅ VM State: {domstate.stdout.strip()}[/]")
        else:
            console.print("[red]❌ VM State: unable to read[/]")
            if verbose and domstate.stderr.strip():
                console.print(f"[dim]{domstate.stderr.strip()}[/]")
    except subprocess.TimeoutExpired:
        result["state"] = {"error": "timeout"}
        console.print("[red]❌ VM State: timeout[/]")
        if json_output:
            console.print_json(json.dumps(result))
        return result

    console.print("\n[bold]🔍 Checking VM network...[/]")
    try:
        domifaddr = subprocess.run(
            ["virsh", "--connect", conn_uri, "domifaddr", vm_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        result["network"] = {
            "returncode": domifaddr.returncode,
            "stdout": domifaddr.stdout.strip(),
            "stderr": domifaddr.stderr.strip(),
        }
        if domifaddr.stdout.strip():
            console.print(f"[dim]{domifaddr.stdout.strip()}[/]")
        else:
            console.print("[yellow]⚠️  No interface address detected via virsh domifaddr[/]")
            # Fallback: try to get IP via QEMU Guest Agent (useful for slirp/user networking)
            if guest_agent_ready:
                try:
                    ip_out = _qga_exec(
                        vm_name,
                        conn_uri,
                        "ip -4 -o addr show scope global | awk '{print $4}'",
                        timeout=5,
                    )
                    if ip_out and ip_out.strip():
                        console.print(f"[green]IP (via QGA): {ip_out.strip()}[/]")
                        result["network"]["qga_ip"] = ip_out.strip()
                    else:
                        console.print("[dim]IP: not available via QGA[/]")
                except Exception as e:
                    console.print(f"[dim]IP: QGA query failed ({e})[/]")
            else:
                console.print("[dim]IP: QEMU Guest Agent not connected[/]")
    except Exception as e:
        result["network"] = {"error": str(e)}
        console.print(f"[yellow]⚠️  Cannot get IP: {e}[/]")

    if verbose:
        console.print("\n[bold]🤖 QEMU Guest Agent...[/]")
        console.print(f"{'[green]✅' if guest_agent_ready else '[red]❌'} QGA connected")

        if not guest_agent_ready:
            try:
                dumpxml = subprocess.run(
                    ["virsh", "--connect", conn_uri, "dumpxml", vm_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                has_qga_channel = False
                if dumpxml.returncode == 0:
                    has_qga_channel = "org.qemu.guest_agent.0" in dumpxml.stdout
                result["qga"]["dumpxml_returncode"] = dumpxml.returncode
                result["qga"]["has_channel"] = has_qga_channel
                if dumpxml.stderr.strip():
                    result["qga"]["dumpxml_stderr"] = dumpxml.stderr.strip()

                console.print(
                    f"[dim]Guest agent channel in VM XML: {'present' if has_qga_channel else 'missing'}[/]"
                )
            except Exception as e:
                result["qga"]["dumpxml_error"] = str(e)

            try:
                ping_attempt = subprocess.run(
                    [
                        "virsh",
                        "--connect",
                        conn_uri,
                        "qemu-agent-command",
                        vm_name,
                        json.dumps({"execute": "guest-ping"}),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                result["qga"]["ping_returncode"] = ping_attempt.returncode
                result["qga"]["ping_stdout"] = ping_attempt.stdout.strip()
                result["qga"]["ping_stderr"] = ping_attempt.stderr.strip()
                if ping_attempt.stderr.strip():
                    console.print(
                        f"[dim]qemu-agent-command stderr: {ping_attempt.stderr.strip()}[/]"
                    )
            except Exception as e:
                result["qga"]["ping_error"] = str(e)

            console.print(
                "[dim]If channel is present, the agent inside VM may not be running yet.[/]"
            )
            console.print(
                "[dim]Inside VM try: sudo systemctl status qemu-guest-agent && sudo systemctl restart qemu-guest-agent[/]"
            )

    console.print("\n[bold]☁️  Checking cloud-init status...[/]")
    cloud_init_complete = False
    if not guest_agent_ready:
        result["cloud_init"] = {"status": "unknown", "reason": "qga_not_ready"}
        console.print(
            "[yellow]⏳ Cloud-init status: Unknown (QEMU Guest Agent not connected yet)[/]"
        )
    else:
        ready_msg = _qga_exec(
            vm_name, conn_uri, "cat /var/log/clonebox-ready 2>/dev/null || true", timeout=10
        )
        result["cloud_init"]["clonebox_ready_file"] = ready_msg
        if ready_msg and "CloneBox VM ready" in ready_msg:
            cloud_init_complete = True
            result["cloud_init"]["status"] = "complete"
            console.print("[green]✅ Cloud-init: Complete[/]")
        else:
            ci_status = _qga_exec(
                vm_name, conn_uri, "cloud-init status 2>/dev/null || true", timeout=10
            )
            result["cloud_init"]["cloud_init_status"] = ci_status
            result["cloud_init"]["status"] = "running"
            console.print("[yellow]⏳ Cloud-init: Still running[/]")
            if verbose and ci_status:
                console.print(f"[dim]{ci_status}[/]")

    console.print("\n[bold]💾 Checking mount status...[/]")
    if not cloud_init_complete:
        console.print("[dim]Mounts may not be ready until cloud-init completes.[/]")

    mounts_detail: list = []
    result["mounts"]["details"] = mounts_detail
    if not guest_agent_ready:
        console.print("[yellow]⏳ QEMU guest agent not connected yet - cannot verify mounts.[/]")
        result["mounts"]["status"] = "unknown"
    else:
        if not config_file:
            config_file = Path.cwd() / ".clonebox.yaml"

        if not config_file.exists():
            console.print("[dim]No .clonebox.yaml found - cannot check mounts[/]")
            result["mounts"]["status"] = "no_config"
        else:
            config = load_clonebox_config(config_file)
            all_paths = config.get("paths", {}).copy()
            all_paths.update(config.get("app_data_paths", {}))
            result["mounts"]["expected"] = list(all_paths.values())
            mount_output = _qga_exec(vm_name, conn_uri, "mount | grep 9p || true", timeout=10) or ""
            mounted_paths = [line.split()[2] for line in mount_output.split("\n") if line.strip()]
            result["mounts"]["mounted_paths"] = mounted_paths

            mount_table = Table(title="Mount Points", border_style="cyan", show_header=True)
            mount_table.add_column("Guest Path", style="bold")
            mount_table.add_column("Mounted", justify="center")
            mount_table.add_column("Accessible", justify="center")
            mount_table.add_column("Files", justify="right")

            working_mounts = 0
            total_mounts = 0
            for _, guest_path in all_paths.items():
                total_mounts += 1
                is_mounted = any(guest_path == mp or guest_path in mp for mp in mounted_paths)
                accessible = False
                file_count: str = "?"

                if is_mounted:
                    test_out = _qga_exec(
                        vm_name, conn_uri, f"test -d {guest_path} && echo yes || echo no", timeout=5
                    )
                    accessible = test_out == "yes"
                    if accessible:
                        count_str = _qga_exec(
                            vm_name, conn_uri, f"ls -A {guest_path} 2>/dev/null | wc -l", timeout=5
                        )
                        if count_str and count_str.strip().isdigit():
                            file_count = count_str.strip()

                if is_mounted and accessible:
                    working_mounts += 1

                mount_table.add_row(
                    guest_path,
                    "[green]✅[/]" if is_mounted else "[red]❌[/]",
                    (
                        "[green]✅[/]"
                        if accessible
                        else ("[red]❌[/]" if is_mounted else "[dim]N/A[/]")
                    ),
                    file_count,
                )
                mounts_detail.append(
                    {
                        "guest_path": guest_path,
                        "mounted": is_mounted,
                        "accessible": accessible,
                        "files": file_count,
                    }
                )

            result["mounts"]["working"] = working_mounts
            result["mounts"]["total"] = total_mounts
            result["mounts"]["status"] = "ok" if working_mounts == total_mounts else "partial"

            console.print(mount_table)
            console.print(f"[dim]{working_mounts}/{total_mounts} mounts working[/]")

    console.print("\n[bold]🏥 Health Check Status...[/]")
    if not guest_agent_ready:
        result["health"]["status"] = "unknown"
        console.print("[dim]Health status: Not available yet (QEMU Guest Agent not ready)[/]")
    else:
        health_status = _qga_exec(
            vm_name, conn_uri, "cat /var/log/clonebox-health-status 2>/dev/null || true", timeout=10
        )
        result["health"]["raw"] = health_status
        if health_status and "HEALTH_STATUS=OK" in health_status:
            result["health"]["status"] = "ok"
            console.print("[green]✅ Health: All checks passed[/]")
        elif health_status and "HEALTH_STATUS=PENDING" in health_status:
            result["health"]["status"] = "pending"
            console.print("[yellow]⏳ Health: Setup in progress[/]")
        elif health_status and "HEALTH_STATUS=FAILED" in health_status:
            result["health"]["status"] = "failed"
            console.print("[red]❌ Health: Some checks failed[/]")
        else:
            result["health"]["status"] = "not_run"
            console.print("[yellow]⏳ Health check not yet run[/]")
            if verbose and health_status:
                console.print(f"[dim]{health_status}[/]")

    if json_output:
        console.print_json(json.dumps(result))
    return result


def cmd_watch(args):
    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = "qemu:///session" if user_session else "qemu:///system"
    refresh = getattr(args, "refresh", 1.0)
    max_wait = getattr(args, "timeout", 600)

    try:
        vm_name, _ = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return

    console.print(f"[bold cyan]👀 Watching boot diagnostics: {vm_name}[/]")
    console.print("[dim]Waiting for QEMU Guest Agent...[/]")

    start = time.time()
    while time.time() - start < max_wait:
        if _qga_ping(vm_name, conn_uri):
            break
        time.sleep(min(refresh, 2.0))

    if not _qga_ping(vm_name, conn_uri):
        console.print(
            "[yellow]⚠️  QEMU Guest Agent not connected - cannot watch diagnostic status yet[/]"
        )
        console.print(
            f"[dim]Try: clonebox status {name or vm_name} {'--user' if user_session else ''} --verbose[/]"
        )
        return

    def _read_status() -> Tuple[Optional[Dict[str, Any]], str]:
        status_raw = _qga_exec(
            vm_name, conn_uri, "cat /var/run/clonebox-status.json 2>/dev/null || true", timeout=10
        )
        log_tail = (
            _qga_exec(
                vm_name,
                conn_uri,
                "tail -n 40 /var/log/clonebox-boot.log 2>/dev/null || true",
                timeout=10,
            )
            or ""
        )

        status_obj: Optional[Dict[str, Any]] = None
        if status_raw:
            try:
                status_obj = json.loads(status_raw)
            except Exception:
                status_obj = None
        return status_obj, log_tail

    with Live(refresh_per_second=max(1, int(1 / max(refresh, 0.2))), console=console) as live:
        while True:
            status_obj, log_tail = _read_status()
            phase = (status_obj or {}).get("phase") if status_obj else None
            current_task = (status_obj or {}).get("current_task") if status_obj else None

            header = f"phase={phase or 'unknown'}"
            if current_task:
                header += f" | {current_task}"

            stats = ""
            if status_obj:
                stats = f"passed={status_obj.get('passed', 0)} failed={status_obj.get('failed', 0)} repaired={status_obj.get('repaired', 0)} total={status_obj.get('total', 0)}"

            body = "\n".join([s for s in [header, stats, "", log_tail.strip()] if s])
            live.update(
                Panel(
                    body or "(no output yet)", title="CloneBox boot diagnostic", border_style="cyan"
                )
            )

            if phase == "complete":
                break

            if time.time() - start >= max_wait:
                break

            time.sleep(refresh)


def cmd_repair(args):
    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = "qemu:///session" if user_session else "qemu:///system"
    timeout = getattr(args, "timeout", 600)
    follow = getattr(args, "watch", False)

    try:
        vm_name, _ = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return

    if not _qga_ping(vm_name, conn_uri):
        console.print("[yellow]⚠️  QEMU Guest Agent not connected - cannot trigger repair[/]")
        console.print("[dim]Inside VM you can run: sudo /usr/local/bin/clonebox-boot-diagnostic[/]")
        return

    console.print(f"[cyan]🔧 Running boot diagnostic/repair in VM: {vm_name}[/]")
    out = _qga_exec(
        vm_name, conn_uri, "/usr/local/bin/clonebox-boot-diagnostic || true", timeout=timeout
    )
    if out is None:
        console.print(
            "[yellow]⚠️  Repair triggered but output not available via QGA (check VM console/log)[/]"
        )
    elif out.strip():
        console.print(Panel(out.strip()[-3000:], title="Command output", border_style="cyan"))

    if follow:
        cmd_watch(
            argparse.Namespace(
                name=name,
                user=user_session,
                refresh=getattr(args, "refresh", 1.0),
                timeout=timeout,
            )
        )


def cmd_logs(args):
    """View logs from VM."""
    import subprocess
    import sys
    
    name = args.name
    user_session = getattr(args, "user", False)
    
    try:
        vm_name, _ = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return
    
    # Path to the logs script
    script_dir = Path(__file__).parent.parent.parent / "scripts"
    logs_script = script_dir / "clonebox-logs.sh"
    
    if not logs_script.exists():
        console.print(f"[red]❌ Logs script not found: {logs_script}[/]")
        return
    
    # Run the logs script
    try:
        console.print(f"[cyan]📋 Opening logs for VM: {vm_name}[/]")
        subprocess.run(
            [str(logs_script), vm_name, "true" if user_session else "false", "true" if getattr(args, "all", False) else "false"],
            check=True
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]❌ Failed to view logs: {e}[/]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")


def cmd_set_password(args):
    """Set password for VM user."""
    import subprocess
    import sys
    
    name = args.name
    user_session = getattr(args, "user", False)
    
    try:
        vm_name, _ = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return
    
    # Path to the set-password script
    script_dir = Path(__file__).parent.parent.parent / "scripts"
    set_password_script = script_dir / "set-vm-password.sh"
    
    if not set_password_script.exists():
        console.print(f"[red]❌ Set password script not found: {set_password_script}[/]")
        return
    
    # Run the set-password script interactively
    try:
        console.print(f"[cyan]🔐 Setting password for VM: {vm_name}[/]")
        subprocess.run(
            [str(set_password_script), vm_name, "true" if user_session else "false"]
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]❌ Failed to set password: {e}[/]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")


def interactive_mode():
    """Run the interactive VM creation wizard."""
    print_banner()

    console.print("[bold cyan]🔍 Detecting system state...[/]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Scanning services, apps, and paths...", total=None)
        detector = SystemDetector()
        snapshot = detector.detect_all()
        sys_info = detector.get_system_info()
        docker_containers = detector.detect_docker_containers()

    # Show system info
    console.print(
        Panel(
            f"[bold]Hostname:[/] {sys_info['hostname']}\n"
            f"[bold]User:[/] {sys_info['user']}\n"
            f"[bold]CPU:[/] {sys_info['cpu_count']} cores\n"
            f"[bold]RAM:[/] {sys_info['memory_available_gb']:.1f} / {sys_info['memory_total_gb']:.1f} GB available\n"
            f"[bold]Disk:[/] {sys_info['disk_free_gb']:.1f} / {sys_info['disk_total_gb']:.1f} GB free",
            title="[bold cyan]System Info[/]",
            border_style="cyan",
        )
    )

    console.print()

    # === VM Name ===
    vm_name = questionary.text("VM name:", default="clonebox-vm", style=custom_style).ask()

    if not vm_name:
        console.print("[red]Cancelled.[/]")
        return

    # === RAM ===
    max_ram = int(sys_info["memory_available_gb"] * 1024 * 0.75)  # 75% of available
    default_ram = min(4096, max_ram)

    ram_mb = questionary.text(
        f"RAM (MB) [max recommended: {max_ram}]:", default=str(default_ram), style=custom_style
    ).ask()
    ram_mb = int(ram_mb) if ram_mb else default_ram

    # === vCPUs ===
    max_vcpus = sys_info["cpu_count"]
    default_vcpus = max(2, max_vcpus // 2)

    vcpus = questionary.text(
        f"vCPUs [max: {max_vcpus}]:", default=str(default_vcpus), style=custom_style
    ).ask()
    vcpus = int(vcpus) if vcpus else default_vcpus

    # === Services Selection ===
    console.print("\n[bold cyan]📦 Select services to include in VM:[/]")

    service_choices = []
    for svc in snapshot.running_services:
        label = f"{svc.name} ({svc.status})"
        if svc.description:
            label += f" - {svc.description[:40]}"
        service_choices.append(questionary.Choice(label, value=svc.name))

    selected_services = []
    if service_choices:
        selected_services = (
            questionary.checkbox(
                "Services (space to select, enter to confirm):",
                choices=service_choices,
                style=custom_style,
            ).ask()
            or []
        )
    else:
        console.print("[dim]  No interesting services detected[/]")

    # === Applications/Processes Selection ===
    console.print("\n[bold cyan]🚀 Select applications to track:[/]")

    app_choices = []
    for app in snapshot.running_apps[:20]:  # Limit to top 20
        label = f"{app.name} (PID: {app.pid}, {app.memory_mb:.0f} MB)"
        if app.working_dir:
            label += f" @ {app.working_dir[:30]}"
        app_choices.append(questionary.Choice(label, value=app))

    selected_apps = []
    if app_choices:
        selected_apps = (
            questionary.checkbox(
                "Applications (will add their working dirs):",
                choices=app_choices,
                style=custom_style,
            ).ask()
            or []
        )
    else:
        console.print("[dim]  No interesting applications detected[/]")

    # === Docker Containers ===
    if docker_containers:
        console.print("\n[bold cyan]🐳 Docker containers detected:[/]")

        container_choices = [
            questionary.Choice(f"{c['name']} ({c['image']}) - {c['status']}", value=c["name"])
            for c in docker_containers
        ]

        selected_containers = (
            questionary.checkbox(
                "Containers (will share docker socket):",
                choices=container_choices,
                style=custom_style,
            ).ask()
            or []
        )

        # If any docker selected, add docker socket
        if selected_containers:
            if "docker" not in selected_services:
                selected_services.append("docker")

    # === Paths Selection ===
    console.print("\n[bold cyan]📁 Select paths to mount in VM:[/]")

    # Group paths by type
    path_groups = {}
    for p in snapshot.paths:
        if p.type not in path_groups:
            path_groups[p.type] = []
        path_groups[p.type].append(p)

    path_choices = []
    for ptype in ["project", "config", "data"]:
        if ptype in path_groups:
            for p in path_groups[ptype]:
                size_str = f"{p.size_mb:.0f} MB" if p.size_mb > 0 else "?"
                label = f"[{ptype}] {p.path} ({size_str})"
                if p.description:
                    label += f" - {p.description}"
                path_choices.append(questionary.Choice(label, value=p.path))

    selected_paths = []
    if path_choices:
        selected_paths = (
            questionary.checkbox(
                "Paths (will be bind-mounted read-write):", choices=path_choices, style=custom_style
            ).ask()
            or []
        )

    # Add working directories from selected applications
    for app in selected_apps:
        if app.working_dir and app.working_dir not in selected_paths:
            selected_paths.append(app.working_dir)

    # === Additional Packages ===
    console.print("\n[bold cyan]📦 Additional packages to install:[/]")

    common_packages = [
        "build-essential",
        "git",
        "curl",
        "wget",
        "vim",
        "htop",
        "python3",
        "python3-pip",
        "python3-venv",
        "nodejs",
        "npm",
        "docker.io",
        "docker-compose",
        "nginx",
        "postgresql",
        "redis",
    ]

    pkg_choices = [questionary.Choice(pkg, value=pkg) for pkg in common_packages]

    selected_packages = (
        questionary.checkbox(
            "Packages (space to select):", choices=pkg_choices, style=custom_style
        ).ask()
        or []
    )

    # Add custom packages
    custom_pkgs = questionary.text(
        "Additional packages (space-separated):", default="", style=custom_style
    ).ask()

    if custom_pkgs:
        selected_packages.extend(custom_pkgs.split())

    # === Base Image ===
    base_image = questionary.text(
        "Base image path (optional, leave empty for blank disk):", default="", style=custom_style
    ).ask()

    # === GUI ===
    enable_gui = questionary.confirm(
        "Enable SPICE graphics (GUI)?", default=True, style=custom_style
    ).ask()

    # === Summary ===
    console.print("\n")

    # Build paths mapping
    paths_mapping = {}
    for idx, host_path in enumerate(selected_paths):
        guest_path = f"/mnt/host{idx}"
        paths_mapping[host_path] = guest_path

    # Summary table
    summary_table = Table(title="VM Configuration Summary", border_style="cyan")
    summary_table.add_column("Setting", style="bold")
    summary_table.add_column("Value")

    summary_table.add_row("Name", vm_name)
    summary_table.add_row("RAM", f"{ram_mb} MB")
    summary_table.add_row("vCPUs", str(vcpus))
    summary_table.add_row("Disk", f"{20 if enable_gui else 10} GB")
    summary_table.add_row("Services", ", ".join(selected_services) or "None")
    summary_table.add_row(
        "Packages",
        ", ".join(selected_packages[:5]) + ("..." if len(selected_packages) > 5 else "") or "None",
    )
    summary_table.add_row("Paths", f"{len(paths_mapping)} bind mounts")
    summary_table.add_row("GUI", "Yes (SPICE)" if enable_gui else "No")

    console.print(summary_table)

    if paths_mapping:
        console.print("\n[bold]Bind mounts:[/]")
        for host, guest in paths_mapping.items():
            console.print(f"  [cyan]{host}[/] → [green]{guest}[/]")

    console.print()

    # === Confirm ===
    if not questionary.confirm(
        "Create VM with these settings?", default=True, style=custom_style
    ).ask():
        console.print("[yellow]Cancelled.[/]")
        return

    # === Create VM ===
    console.print("\n[bold cyan]🔧 Creating VM...[/]\n")

    config = VMConfig(
        name=vm_name,
        ram_mb=ram_mb,
        vcpus=vcpus,
        disk_size_gb=20 if enable_gui else 10,
        gui=enable_gui,
        base_image=base_image if base_image else None,
        paths=paths_mapping,
        packages=selected_packages,
        services=selected_services,
    )

    try:
        cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))

        # Check prerequisites
        checks = cloner.check_prerequisites(config)
        required_keys = [
            "libvirt_connected",
            "kvm_available",
            "images_dir_writable",
            "genisoimage_installed",
            "qemu_img_installed",
        ]
        if checks.get("default_network_required", True):
            required_keys.append("default_network")
        if getattr(config, "gui", False):
            required_keys.append("virt_viewer_installed")

        required_checks = {
            k: checks.get(k)
            for k in required_keys
            if isinstance(checks.get(k), bool)
        }

        if required_checks and not all(required_checks.values()):
            console.print("[yellow]⚠️  Prerequisites check:[/]")
            for check, passed in required_checks.items():
                icon = "✅" if passed else "❌"
                console.print(f"   {icon} {check}")

            if not checks["libvirt_connected"]:
                console.print("\n[red]Cannot proceed without libvirt connection.[/]")
                console.print("Try: [cyan]sudo systemctl start libvirtd[/]")
                return

        vm_uuid = cloner.create_vm(config, console=console)

        # Ask to start
        if questionary.confirm("Start VM now?", default=True, style=custom_style).ask():
            cloner.start_vm(vm_name, open_viewer=enable_gui, console=console)
            console.print("\n[bold green]🎉 VM is running![/]")
            console.print(f"\n[dim]UUID: {vm_uuid}[/]")

            if paths_mapping:
                console.print("\n[bold]Inside the VM, mount shared folders with:[/]")
                for idx, (host, guest) in enumerate(paths_mapping.items()):
                    console.print(f"  [cyan]sudo mount -t 9p -o trans=virtio mount{idx} {guest}[/]")
    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/]")
        raise


def cmd_init(args):
    """Initialize a new CloneBox configuration."""
    from pathlib import Path
    
    config_path = Path(args.path) if args.path else Path.cwd() / CLONEBOX_CONFIG_FILE
    
    # If path is a directory, use .clonebox.yaml
    if config_path.is_dir():
        config_path = config_path / CLONEBOX_CONFIG_FILE
    
    # Check if config already exists
    if config_path.exists() and not args.force:
        console.print(f"[red]❌ Configuration already exists: {config_path}[/]")
        console.print("[dim]Use --force to overwrite[/]")
        return
    
    # Create default configuration
    default_config = {
        "version": "1",
        "generated": datetime.now().isoformat(),
        "vm": {
            "name": args.name or "clonebox-vm",
            "ram_mb": args.ram or 4096,
            "vcpus": args.vcpus or 4,
            "disk_size_gb": args.disk_size_gb or 20,
            "gui": not args.no_gui,
            "base_image": args.base_image,
            "network_mode": args.network or "auto",
            "username": "ubuntu",
            "password": "ubuntu",
        },
        "paths": {},
        "packages": [],
        "snap_packages": [],
        "services": [],
        "post_commands": [],
        "copy_paths": {},
    }
    
    # Save configuration
    with open(config_path, "w") as f:
        yaml.dump(default_config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    console.print(f"[green]✅ Initialized CloneBox configuration: {config_path}[/]")
    console.print("\n[dim]Next steps:[/]")
    console.print(f"  1. Edit the configuration: [cyan]nano {config_path}[/]")
    console.print(f"  2. Create VM: [cyan]clonebox create -c {config_path}[/]")
    console.print(f"  3. Or use: [cyan]clonebox start {config_path.parent}[/]")


def cmd_create(args):
    """Create VM from JSON config."""
    config_data = json.loads(args.config)

    config = VMConfig(
        name=args.name,
        ram_mb=args.ram,
        vcpus=args.vcpus,
        disk_size_gb=getattr(args, "disk_size_gb", 10),
        gui=not args.no_gui,
        base_image=args.base_image,
        paths=config_data.get("paths", {}),
        packages=config_data.get("packages", []),
        services=config_data.get("services", []),
    )

    cloner = SelectiveVMCloner()
    vm_uuid = cloner.create_vm(config, console=console)

    if args.start:
        cloner.start_vm(args.name, open_viewer=not args.no_gui, console=console)

    console.print(f"[green]✅ VM created: {vm_uuid}[/]")


def cmd_start(args):
    """Start a VM or create from .clonebox.yaml."""
    name = args.name

    # Check if it's a path (contains / or . or ~)
    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        # Treat as path - load .clonebox.yaml
        target_path = Path(name).expanduser().resolve()

        if target_path.is_dir():
            config_file = target_path / CLONEBOX_CONFIG_FILE
        else:
            config_file = target_path

        if not config_file.exists():
            console.print(f"[red]❌ Config not found: {config_file}[/]")
            console.print(f"[dim]Run 'clonebox clone {target_path}' first to generate config[/]")
            return

        console.print(f"[bold cyan]📦 Loading config: {config_file}[/]\n")

        config = load_clonebox_config(config_file)
        vm_name = config["vm"]["name"]

        # Check if VM already exists
        cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))
        try:
            existing_vms = [v["name"] for v in cloner.list_vms()]
            if vm_name in existing_vms:
                console.print(f"[cyan]VM '{vm_name}' exists, starting...[/]")
                cloner.start_vm(vm_name, open_viewer=not args.no_viewer, console=console)
                return
        except:
            pass

        # Create new VM from config
        console.print(f"[cyan]Creating VM '{vm_name}' from config...[/]\n")
        vm_uuid = create_vm_from_config(
            config, start=True, user_session=getattr(args, "user", False)
        )
        console.print(f"\n[bold green]🎉 VM '{vm_name}' is running![/]")
        console.print(f"[dim]UUID: {vm_uuid}[/]")

        if config.get("paths"):
            console.print("\n[bold]Inside VM, mount paths with:[/]")
            for idx, (host, guest) in enumerate(config["paths"].items()):
                console.print(f"  [cyan]sudo mount -t 9p -o trans=virtio mount{idx} {guest}[/]")
        return

    # Default: treat as VM name
    if not name:
        # No argument - check current directory for .clonebox.yaml
        config_file = Path.cwd() / CLONEBOX_CONFIG_FILE
        if config_file.exists():
            console.print(f"[cyan]Found {CLONEBOX_CONFIG_FILE} in current directory[/]")
            args.name = "."
            return cmd_start(args)
        else:
            console.print(
                "[red]❌ No VM name specified and no .clonebox.yaml in current directory[/]"
            )
            console.print("[dim]Usage: clonebox start <vm-name> or clonebox start .[/]")
            return

    cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))
    open_viewer = getattr(args, "viewer", False) or not getattr(args, "no_viewer", False)
    cloner.start_vm(name, open_viewer=open_viewer, console=console)


def cmd_open(args):
    """Open VM viewer window."""
    import subprocess

    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = "qemu:///session" if user_session else "qemu:///system"

    # If name is a path, load config
    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        target_path = Path(name).expanduser().resolve()
        config_file = target_path / ".clonebox.yaml" if target_path.is_dir() else target_path
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print(f"[red]❌ Config not found: {config_file}[/]")
            return
    elif name == "." or not name:
        config_file = Path.cwd() / ".clonebox.yaml"
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print(
                "[red]❌ No VM name specified and no .clonebox.yaml in current directory[/]"
            )
            console.print("[dim]Usage: clonebox open <vm-name> or clonebox open .[/]")
            return

    # Check if VM is running
    try:
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "domstate", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        state = result.stdout.strip()

        if state != "running":
            console.print(f"[yellow]⚠️  VM '{name}' is not running (state: {state})[/]")
            if questionary.confirm(
                f"Start VM '{name}' and open viewer?", default=True, style=custom_style
            ).ask():
                cloner = SelectiveVMCloner(user_session=user_session)
                cloner.start_vm(name, open_viewer=True, console=console)
            else:
                console.print("[dim]Use 'clonebox start' to start the VM first.[/]")
            return
    except Exception as e:
        console.print(f"[red]❌ Error checking VM state: {e}[/]")
        return

    # Open virt-viewer
    console.print(f"[cyan]Opening viewer for VM: {name}[/]")
    try:
        subprocess.run(["virt-viewer", "--connect", conn_uri, name], check=True)
    except FileNotFoundError:
        console.print("[red]❌ virt-viewer not found[/]")
        console.print("Install with: sudo apt install virt-viewer")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]❌ Failed to open viewer: {e}[/]")


def cmd_stop(args):
    """Stop a VM."""
    name = args.name

    # If name is a path, load config
    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        target_path = Path(name).expanduser().resolve()
        config_file = target_path / ".clonebox.yaml" if target_path.is_dir() else target_path
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print(f"[red]❌ Config not found: {config_file}[/]")
            return

    cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))
    cloner.stop_vm(name, force=args.force, console=console)


def cmd_restart(args):
    """Restart a VM (stop and start)."""
    name = args.name

    # If name is a path, load config
    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        target_path = Path(name).expanduser().resolve()
        config_file = target_path / ".clonebox.yaml" if target_path.is_dir() else target_path
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print(f"[red]❌ Config not found: {config_file}[/]")
            return

    cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))

    # Stop the VM
    console.print("[bold yellow]🔄 Stopping VM...[/]")
    cloner.stop_vm(name, force=args.force, console=console)

    # Wait a moment
    time.sleep(2)

    # Start the VM
    console.print("[bold green]🚀 Starting VM...[/]")
    cloner.start_vm(name, wait_for_agent=True, console=console)

    console.print("[bold green]✅ VM restarted successfully![/]")
    if getattr(args, "open", False):
        cloner.open_gui(name, console=console)


def cmd_delete(args):
    """Delete a VM."""
    name = args.name

    # If name is a path, load config
    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        target_path = Path(name).expanduser().resolve()

        if target_path.is_dir():
            config_file = target_path / CLONEBOX_CONFIG_FILE
        else:
            config_file = target_path

        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print(f"[red]❌ Config not found: {config_file}[/]")
            return
    elif not name or name == ".":
        config_file = Path.cwd() / ".clonebox.yaml"
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print("[red]❌ No .clonebox.yaml found in current directory[/]")
            console.print("[dim]Usage: clonebox delete . or clonebox delete <vm-name>[/]")
            return

    policy_start = None
    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        policy_start = Path(name).expanduser().resolve()

    policy = PolicyEngine.load_effective(start=policy_start)
    if policy is not None:
        try:
            policy.assert_operation_approved(
                AuditEventType.VM_DELETE.value,
                approved=getattr(args, "approve", False),
            )
        except PolicyViolationError as e:
            console.print(f"[red]❌ {e}[/]")
            sys.exit(1)

    if not args.yes:
        if not questionary.confirm(
            f"Delete VM '{name}' and its storage?", default=False, style=custom_style
        ).ask():
            console.print("[yellow]Cancelled.[/]")
            return

    cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))
    delete_storage = not getattr(args, "keep_storage", False)
    console.print(f"[cyan]🗑️ Deleting VM: {name}[/]")
    try:
        ok = cloner.delete_vm(
            name, delete_storage=delete_storage, console=console, approved=getattr(args, "approve", False)
        )
        if not ok:
            sys.exit(1)
    except Exception as e:
        console.print(f"[red]❌ Failed to delete VM: {e}[/]")
        sys.exit(1)


def cmd_list(args):
    """List all VMs."""
    cloner = SelectiveVMCloner(user_session=getattr(args, "user", False))
    vms = cloner.list_vms()

    if getattr(args, "json", False):
        print(json.dumps(vms, indent=2))
        return

    if not vms:
        console.print("[dim]No VMs found.[/]")
        return

    table = Table(title="Virtual Machines", border_style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("State")
    table.add_column("UUID", style="dim")

    for vm in vms:
        state_style = "green" if vm["state"] == "running" else "dim"
        table.add_row(vm["name"], f"[{state_style}]{vm['state']}[/]", vm["uuid"][:8])

    console.print(table)


def cmd_container_up(args):
    """Start a container sandbox."""
    mounts = {}
    for m in getattr(args, "mount", []) or []:
        if ":" not in m:
            raise ValueError(f"Invalid mount: {m} (expected HOST:CONTAINER)")
        host, container_path = m.split(":", 1)
        mounts[host] = container_path

    cfg_kwargs: dict = {
        "engine": getattr(args, "engine", "auto"),
        "image": getattr(args, "image", "ubuntu:22.04"),
        "workspace": Path(getattr(args, "path", ".")),
        "extra_mounts": mounts,
        "env_from_dotenv": not getattr(args, "no_dotenv", False),
        "packages": getattr(args, "package", []) or [],
        "ports": getattr(args, "port", []) or [],
    }
    if getattr(args, "name", None):
        cfg_kwargs["name"] = args.name

    profile_name = getattr(args, "profile", None)
    if profile_name:
        merged = merge_with_profile({"container": cfg_kwargs}, profile_name)
        if isinstance(merged, dict) and isinstance(merged.get("container"), dict):
            cfg_kwargs = merged["container"]

    cfg = ContainerConfig(**cfg_kwargs)

    cloner = ContainerCloner(engine=cfg.engine)
    detach = getattr(args, "detach", False)
    cloner.up(cfg, detach=detach, remove=not detach)


def cmd_container_ps(args):
    """List containers."""
    cloner = ContainerCloner(engine=getattr(args, "engine", "auto"))
    items = cloner.ps(all=getattr(args, "all", False))

    if getattr(args, "json", False):
        print(json.dumps(items, indent=2))
        return

    if not items:
        console.print("[dim]No containers found.[/]")
        return

    table = Table(title="Containers", border_style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Image")
    table.add_column("Status")
    table.add_column("Ports")

    for c in items:
        table.add_row(
            str(c.get("name", "")),
            str(c.get("image", "")),
            str(c.get("status", "")),
            str(c.get("ports", "")),
        )

    console.print(table)


def cmd_container_stop(args):
    """Stop a container."""
    cloner = ContainerCloner(engine=getattr(args, "engine", "auto"))
    cloner.stop(args.name)


def cmd_container_rm(args):
    """Remove a container."""
    cloner = ContainerCloner(engine=getattr(args, "engine", "auto"))
    cloner.rm(args.name, force=getattr(args, "force", False))


def cmd_container_down(args):
    """Stop and remove a container."""
    cloner = ContainerCloner(engine=getattr(args, "engine", "auto"))
    cloner.stop(args.name)
    cloner.rm(args.name, force=True)


def cmd_dashboard(args):
    """Run the local CloneBox dashboard."""
    try:
        from clonebox.dashboard import run_dashboard
    except Exception as e:
        console.print("[red]❌ Dashboard dependencies are not installed.[/]")
        console.print("[dim]Install with: pip install 'clonebox[dashboard]'[/]")
        console.print(f"[dim]{e}[/]")
        return

    run_dashboard(port=getattr(args, "port", 8080))


def cmd_diagnose(args):
    """Run detailed VM diagnostics (standalone)."""
    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = "qemu:///session" if user_session else "qemu:///system"

    try:
        vm_name, config_file = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return

    run_vm_diagnostics(
        vm_name,
        conn_uri,
        config_file,
        verbose=getattr(args, "verbose", False),
        json_output=getattr(args, "json", False),
    )


def cmd_status(args):
    """Check VM installation status and health from workstation."""
    import subprocess

    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = "qemu:///session" if user_session else "qemu:///system"

    try:
        vm_name, config_file = _resolve_vm_name_and_config_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        return

    run_vm_diagnostics(vm_name, conn_uri, config_file, verbose=False, json_output=False)

    # Show useful commands
    console.print("\n[bold]📋 Useful commands:[/]")
    console.print(f"  [cyan]virt-viewer --connect {conn_uri} {vm_name}[/]  # Open GUI")
    console.print(f"  [cyan]virsh --connect {conn_uri} console {vm_name}[/]  # Console access")
    console.print("  [dim]Inside VM:[/]")
    console.print("    [cyan]cat /var/log/clonebox-health.log[/]  # Full health report")
    console.print("    [cyan]sudo cloud-init status[/]  # Cloud-init status")
    console.print("    [cyan]clonebox-health[/]  # Re-run health check")
    console.print("  [dim]On host:[/]")
    console.print(
        "    [cyan]clonebox test . --user --validate[/]  # Full validation (mounts/packages/services)"
    )

    # Run full health check if requested
    if getattr(args, "health", False):
        console.print("\n[bold]🔄 Running full health check...[/]")
        try:
            result = subprocess.run(
                [
                    "virsh",
                    "--connect",
                    conn_uri,
                    "qemu-agent-command",
                    vm_name,
                    '{"execute":"guest-exec","arguments":{"path":"/usr/local/bin/clonebox-health","capture-output":true}}',
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            console.print("[green]Health check triggered. View results with:[/]")
            console.print(f"  [cyan]virsh --connect {conn_uri} console {vm_name}[/]")
            console.print("  Then run: [cyan]cat /var/log/clonebox-health.log[/]")
        except Exception as e:
            console.print(f"[yellow]⚠️  Could not trigger health check: {e}[/]")


def cmd_export(args):
    """Export VM and data for migration to another workstation."""
    import subprocess
    import tarfile
    import shutil

    name = args.name
    user_session = getattr(args, "user", False)
    conn_uri = "qemu:///session" if user_session else "qemu:///system"
    include_data = getattr(args, "include_data", False)
    output = getattr(args, "output", None)

    # If name is a path, load config
    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        target_path = Path(name).expanduser().resolve()

        if target_path.is_dir():
            config_file = target_path / CLONEBOX_CONFIG_FILE
        else:
            config_file = target_path

        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print(f"[red]❌ Config not found: {config_file}[/]")
            return
    elif not name or name == ".":
        config_file = Path.cwd() / ".clonebox.yaml"
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print("[red]❌ No .clonebox.yaml found in current directory[/]")
            console.print("[dim]Usage: clonebox export . or clonebox export <vm-name>[/]")
            return

    console.print(f"[bold cyan]📦 Exporting VM: {name}[/]\n")

    # Get actual disk location from virsh
    try:
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "domblklist", name, "--details"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            console.print(f"[red]❌ VM '{name}' not found[/]")
            return

        # Parse disk paths from output
        disk_path = None
        cloudinit_path = None
        for line in result.stdout.split("\n"):
            if "disk" in line and ".qcow2" in line:
                parts = line.split()
                if len(parts) >= 4:
                    disk_path = Path(parts[3])
            elif "cdrom" in line or ".iso" in line:
                parts = line.split()
                if len(parts) >= 4:
                    cloudinit_path = Path(parts[3])

        if not disk_path or not disk_path.exists():
            console.print(f"[red]❌ VM disk not found[/]")
            return

        console.print(f"[dim]Disk location: {disk_path}[/]")

    except Exception as e:
        console.print(f"[red]❌ Error getting VM disk: {e}[/]")
        return

    # Create export directory
    export_name = output or f"{name}-export.tar.gz"
    if not export_name.endswith(".tar.gz"):
        export_name += ".tar.gz"

    export_path = Path(export_name).resolve()
    temp_dir = Path(f"/tmp/clonebox-export-{name}")

    try:
        # Clean up temp dir if exists
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True)

        # Stop VM if running
        console.print("[cyan]Stopping VM for export...[/]")
        subprocess.run(
            ["virsh", "--connect", conn_uri, "shutdown", name], capture_output=True, timeout=30
        )
        import time

        time.sleep(5)
        subprocess.run(
            ["virsh", "--connect", conn_uri, "destroy", name], capture_output=True, timeout=10
        )

        # Export VM XML
        console.print("[cyan]Exporting VM definition...[/]")
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "dumpxml", name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        (temp_dir / "vm.xml").write_text(result.stdout)

        # Copy disk image
        console.print("[cyan]Copying disk image (this may take a while)...[/]")
        if disk_path and disk_path.exists():
            shutil.copy2(disk_path, temp_dir / "disk.qcow2")
            console.print(
                f"[green]✅ Disk copied: {disk_path.stat().st_size / (1024**3):.2f} GB[/]"
            )
        else:
            console.print("[yellow]⚠️  Disk image not found[/]")

        # Copy cloud-init ISO
        if cloudinit_path and cloudinit_path.exists():
            shutil.copy2(cloudinit_path, temp_dir / "cloud-init.iso")
            console.print("[green]✅ Cloud-init ISO copied[/]")

        # Copy config file
        config_file = Path.cwd() / ".clonebox.yaml"
        if config_file.exists():
            shutil.copy2(config_file, temp_dir / ".clonebox.yaml")

        # Copy .env file (without sensitive data warning)
        env_file = Path.cwd() / ".env"
        if env_file.exists():
            shutil.copy2(env_file, temp_dir / ".env")

        # Include shared data if requested
        if include_data:
            console.print("[cyan]Bundling shared data (browser profiles, configs)...[/]")
            data_dir = temp_dir / "data"
            data_dir.mkdir()

            # Load config to get paths
            if config_file.exists():
                config = load_clonebox_config(config_file)
                all_paths = config.get("paths", {}).copy()
                all_paths.update(config.get("app_data_paths", {}))

                for idx, (host_path, guest_path) in enumerate(all_paths.items()):
                    host_p = Path(host_path)
                    if host_p.exists():
                        dest = data_dir / f"mount{idx}"
                        console.print(f"  [dim]Copying {host_path}...[/]")
                        try:
                            if host_p.is_dir():
                                shutil.copytree(
                                    host_p,
                                    dest,
                                    symlinks=True,
                                    ignore=shutil.ignore_patterns("*.pyc", "__pycache__", ".git"),
                                )
                            else:
                                shutil.copy2(host_p, dest)
                        except Exception as e:
                            console.print(f"  [yellow]⚠️  Skipped {host_path}: {e}[/]")

                # Save path mapping
                import json

                (data_dir / "paths.json").write_text(json.dumps(all_paths, indent=2))

        # Create tarball
        console.print(f"[cyan]Creating archive: {export_path}[/]")
        with tarfile.open(export_path, "w:gz") as tar:
            tar.add(temp_dir, arcname=name)

        # Get size
        size_mb = export_path.stat().st_size / 1024 / 1024

        console.print(f"\n[bold green]✅ Export complete![/]")
        console.print(f"   File: [cyan]{export_path}[/]")
        console.print(f"   Size: [cyan]{size_mb:.1f} MB[/]")
        console.print(f"\n[bold]To import on another workstation:[/]")
        console.print(f"   [cyan]clonebox import {export_path.name}[/]")

    finally:
        # Cleanup
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        # Restart VM
        console.print("\n[cyan]Restarting VM...[/]")
        subprocess.run(
            ["virsh", "--connect", conn_uri, "start", name], capture_output=True, timeout=30
        )


def cmd_import(args):
    """Import VM from export archive."""
    import subprocess
    import tarfile
    import shutil

    archive_path = Path(args.archive).resolve()
    user_session = getattr(args, "user", False)
    conn_uri = "qemu:///session" if user_session else "qemu:///system"

    if not archive_path.exists():
        console.print(f"[red]❌ Archive not found: {archive_path}[/]")
        return

    console.print(f"[bold cyan]📥 Importing VM from: {archive_path}[/]\n")

    # Determine storage path
    if user_session:
        storage_base = Path.home() / ".local/share/libvirt/images"
    else:
        storage_base = Path("/var/lib/libvirt/images")

    storage_base.mkdir(parents=True, exist_ok=True)

    temp_dir = Path(f"/tmp/clonebox-import-{archive_path.stem}")

    try:
        # Extract archive
        console.print("[cyan]Extracting archive...[/]")
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True)

        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(temp_dir)

        # Find extracted VM directory
        vm_dirs = list(temp_dir.iterdir())
        if not vm_dirs:
            console.print("[red]❌ Empty archive[/]")
            return

        extracted_dir = vm_dirs[0]
        vm_name = extracted_dir.name

        console.print(f"[cyan]VM Name: {vm_name}[/]")

        # Create VM storage directory
        vm_storage = storage_base / vm_name
        if vm_storage.exists():
            if not getattr(args, "replace", False):
                console.print(
                    f"[red]❌ VM '{vm_name}' already exists. Use --replace to overwrite.[/]"
                )
                return
            policy = PolicyEngine.load_effective(start=vm_storage)
            if policy is not None:
                try:
                    policy.assert_operation_approved(
                        AuditEventType.VM_DELETE.value,
                        approved=getattr(args, "approve", False),
                    )
                except PolicyViolationError as e:
                    console.print(f"[red]❌ {e}[/]")
                    sys.exit(1)
            shutil.rmtree(vm_storage)

        vm_storage.mkdir(parents=True)

        # Copy disk image
        console.print("[cyan]Copying disk image...[/]")
        disk_src = extracted_dir / "disk.qcow2"
        if disk_src.exists():
            shutil.copy2(disk_src, vm_storage / f"{vm_name}.qcow2")

        # Copy cloud-init ISO
        cloudinit_src = extracted_dir / "cloud-init.iso"
        if cloudinit_src.exists():
            shutil.copy2(cloudinit_src, vm_storage / "cloud-init.iso")

        # Copy config files to current directory
        config_src = extracted_dir / ".clonebox.yaml"
        if config_src.exists():
            shutil.copy2(config_src, Path.cwd() / ".clonebox.yaml")
            console.print("[green]✅ Copied .clonebox.yaml[/]")

        env_src = extracted_dir / ".env"
        if env_src.exists():
            shutil.copy2(env_src, Path.cwd() / ".env")
            console.print("[green]✅ Copied .env[/]")

        # Restore data if included
        data_dir = extracted_dir / "data"
        if data_dir.exists():
            import json

            paths_file = data_dir / "paths.json"
            if paths_file.exists():
                paths_mapping = json.loads(paths_file.read_text())
                console.print("\n[cyan]Restoring shared data...[/]")

                for idx, (host_path, guest_path) in enumerate(paths_mapping.items()):
                    src = data_dir / f"mount{idx}"
                    if src.exists():
                        dest = Path(host_path)
                        console.print(f"  [dim]Restoring to {host_path}...[/]")
                        try:
                            if dest.exists():
                                console.print(f"    [yellow]⚠️  Skipped (already exists)[/]")
                            else:
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                if src.is_dir():
                                    shutil.copytree(src, dest)
                                else:
                                    shutil.copy2(src, dest)
                        except Exception as e:
                            console.print(f"    [yellow]⚠️  Error: {e}[/]")

        # Modify and define VM XML
        console.print("\n[cyan]Defining VM...[/]")
        xml_src = extracted_dir / "vm.xml"
        if xml_src.exists():
            xml_content = xml_src.read_text()

            # Update paths in XML to new storage location
            # This is a simple replacement - may need more sophisticated handling
            xml_content = xml_content.replace(f"/home/", f"{Path.home()}/")

            # Write modified XML
            modified_xml = temp_dir / "vm-modified.xml"
            modified_xml.write_text(xml_content)

            # Define VM
            result = subprocess.run(
                ["virsh", "--connect", conn_uri, "define", str(modified_xml)],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                console.print(f"[green]✅ VM '{vm_name}' defined successfully![/]")
            else:
                console.print(f"[yellow]⚠️  VM definition warning: {result.stderr}[/]")

        console.print(f"\n[bold green]✅ Import complete![/]")
        console.print(f"\n[bold]To start the VM:[/]")
        console.print(f"   [cyan]clonebox start . {'--user' if user_session else ''}[/]")

    finally:
        # Cleanup
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def cmd_test(args):
    """Test VM configuration and health."""
    import subprocess
    import json
    import time
    from clonebox.validator import VMValidator

    name = args.name
    user_session = getattr(args, "user", False)
    quick = getattr(args, "quick", False)
    verbose = getattr(args, "verbose", False)
    validate_all = getattr(args, "validate", False)
    require_running_apps = getattr(args, "require_running_apps", False)
    smoke_test = getattr(args, "smoke_test", False)
    conn_uri = "qemu:///session" if user_session else "qemu:///system"

    # If name is a path, load config
    if name and (name.startswith(".") or name.startswith("/") or name.startswith("~")):
        target_path = Path(name).expanduser().resolve()
        config_file = target_path / ".clonebox.yaml" if target_path.is_dir() else target_path
        if not config_file.exists():
            console.print(f"[red]❌ Config not found: {config_file}[/]")
            return
    else:
        config_file = Path.cwd() / ".clonebox.yaml"
        if not config_file.exists():
            console.print("[red]❌ No .clonebox.yaml found in current directory[/]")
            return

    console.print(f"[bold cyan]🧪 Testing VM configuration: {config_file}[/]\n")

    # Load config
    try:
        config = load_clonebox_config(config_file)
        vm_name = config["vm"]["name"]
        console.print(f"[green]✅ Config loaded successfully[/]")
        console.print(f"   VM Name: {vm_name}")
        console.print(f"   RAM: {config['vm']['ram_mb']}MB")
        console.print(f"   vCPUs: {config['vm']['vcpus']}")
        console.print(f"   GUI: {'Yes' if config['vm']['gui'] else 'No'}")
    except Exception as e:
        console.print(f"[red]❌ Failed to load config: {e}[/]")
        return

    console.print()

    if user_session:
        try:
            vm_dir = Path.home() / ".local/share/libvirt/images" / vm_name
            ssh_key_path = vm_dir / "ssh_key"
            ssh_port_path = vm_dir / "ssh_port"
            serial_log_path = vm_dir / "serial.log"

            if ssh_key_path.exists() and ssh_port_path.exists():
                ssh_port = (ssh_port_path.read_text() or "").strip()
                if ssh_port:
                    console.print(
                        f"[dim]SSH (passthrough): ssh -i {ssh_key_path} -p {ssh_port} ubuntu@127.0.0.1[/]"
                    )

            console.print(f"[dim]Host serial log: {serial_log_path}[/]")
            console.print(f"[dim]Follow: tail -f {serial_log_path}[/]")
        except Exception:
            pass

    # Test 1: Check VM exists
    console.print("[bold]1. VM Existence Check[/]")
    try:
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "dominfo", vm_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            console.print("[green]✅ VM is defined in libvirt[/]")
            if verbose:
                for line in result.stdout.split("\n"):
                    if ":" in line:
                        console.print(f"   {line}")
        else:
            console.print("[red]❌ VM not found in libvirt[/]")
            console.print("   Run: clonebox create .clonebox.yaml --start")
            return
    except Exception as e:
        console.print(f"[red]❌ Error checking VM: {e}[/]")
        return

    console.print()

    # Test 2: Check VM state
    cloud_init_running = False
    try:
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "domstate", vm_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        state = result.stdout.strip()

        if state == "running":
            console.print("[green]✅ VM is running[/]")

            # Give QEMU Guest Agent some time to come up (common during early boot)
            qga_ready = _qga_ping(vm_name, conn_uri)
            if not qga_ready:
                console.print("[yellow]⏳ Waiting for QEMU Guest Agent (up to 60s)...[/]")
                qga_wait_start = time.time()
                for attempt in range(12):  # ~60s
                    time.sleep(5)
                    qga_ready = _qga_ping(vm_name, conn_uri)
                    elapsed = int(time.time() - qga_wait_start)
                    if qga_ready:
                        console.print(f"[green]✅ QEMU Guest Agent connected after {elapsed}s[/]")
                        break
                    if attempt % 2 == 1:
                        console.print(f"[dim]   ...still waiting ({elapsed}s elapsed)[/]")

                if not qga_ready:
                    console.print("[yellow]⚠️  QEMU Guest Agent still not connected[/]")
                    console.print(
                        f"[dim]Tip: you can watch live cloud-init output via serial console: virsh --connect {conn_uri} console {vm_name}[/]"
                    )

                    if user_session:
                        try:
                            serial_log_path = Path.home() / ".local/share/libvirt/images" / vm_name / "serial.log"
                            console.print(f"[dim]Tip: host serial log (cloud-init output): {serial_log_path}[/]")
                            console.print(f"[dim]     tail -f {serial_log_path}[/]")
                        except Exception:
                            pass

            # Check cloud-init status immediately if QGA is ready
            if qga_ready:
                console.print("[dim]   Checking cloud-init status via QGA...[/]")
                status = _qga_exec(
                    vm_name, conn_uri, "cloud-init status 2>/dev/null || true", timeout=15
                )
                if status and "running" in status.lower():
                    cloud_init_running = True
                    console.print("[yellow]⏳ Setup in progress (cloud-init is running)[/]")

            # Test network if running
            console.print("\n   Checking network...")
            try:
                result = subprocess.run(
                    ["virsh", "--connect", conn_uri, "domifaddr", vm_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if "192.168" in result.stdout or "10.0" in result.stdout:
                    console.print("[green]✅ VM has network access[/]")
                    if verbose:
                        for line in result.stdout.split("\n"):
                            if "192.168" in line or "10.0" in line:
                                console.print(f"   IP: {line.split()[-1]}")
                else:
                    console.print("[yellow]⚠️  No IP address detected via virsh domifaddr[/]")
                    # Fallback: try to get IP via QEMU Guest Agent (useful for slirp/user networking)
                    if qga_ready:
                        try:
                            ip_out = _qga_exec(
                                vm_name,
                                conn_uri,
                                "ip -4 -o addr show scope global | awk '{print $4}'",
                                timeout=5,
                            )
                            if ip_out and ip_out.strip():
                                ip_clean = ip_out.strip().replace("\n", ", ")
                                console.print(
                                    f"[green]✅ VM has network access (IP via QGA: {ip_clean})[/]"
                                )
                            else:
                                console.print("[yellow]⚠️  IP not available via QGA[/]")
                        except Exception as e:
                            console.print(f"[yellow]⚠️  Could not get IP via QGA ({e})[/]")
                    else:
                        console.print("[dim]IP: QEMU Guest Agent not connected[/]")
            except:
                console.print("[yellow]⚠️  Could not check network[/]")
        else:
            console.print(f"[yellow]⚠️  VM is not running (state: {state})[/]")
            console.print("   Run: clonebox start .")
    except Exception as e:
        console.print(f"[red]❌ Error checking VM state: {e}[/]")

    console.print()

    # Test 3: Check cloud-init status (if running)
    cloud_init_complete: Optional[bool] = None
    if not quick and state == "running":
        console.print("[bold]3. Cloud-init Status[/]")
        try:
            if not qga_ready:
                console.print("[yellow]⚠️  Cloud-init status unknown (QEMU Guest Agent not connected)[/]")
            else:
                status = _qga_exec(
                    vm_name, conn_uri, "cloud-init status 2>/dev/null || true", timeout=15
                )
                if status is None:
                    console.print("[yellow]⚠️  Could not check cloud-init (QGA command failed)[/]")
                    cloud_init_complete = None
                elif "done" in status.lower():
                    console.print("[green]✅ Cloud-init completed[/]")
                    cloud_init_complete = True
                elif "running" in status.lower():
                    console.print("[yellow]⚠️  Cloud-init still running[/]")
                    cloud_init_complete = False
                    cloud_init_running = True
                elif status.strip():
                    console.print(f"[yellow]⚠️  Cloud-init status: {status.strip()}[/]")
                    cloud_init_complete = None
                else:
                    console.print("[yellow]⚠️  Cloud-init status: unknown[/]")
                    cloud_init_complete = None
        except Exception:
            console.print("[yellow]⚠️  Could not check cloud-init (QEMU agent may not be running)[/]")
            cloud_init_complete = None

    console.print()

    # Test 4: Check mounts (if running)
    if not quick and state == "running":
        console.print("[bold]4. Mount Points Check[/]")
        paths = config.get("paths", {})
        copy_paths = config.get("copy_paths", None)
        if not isinstance(copy_paths, dict) or not copy_paths:
            copy_paths = config.get("app_data_paths", {})

        if paths or copy_paths:
            if not _qga_ping(vm_name, conn_uri):
                console.print("[yellow]⚠️  QEMU guest agent not connected - cannot verify mounts[/]")
            else:
                # Check bind mounts
                for idx, (host_path, guest_path) in enumerate(paths.items()):
                    try:
                        # Use the same QGA helper as diagnose/status
                        is_accessible = _qga_exec(
                            vm_name, conn_uri, f"test -d {guest_path} && echo yes || echo no", timeout=5
                        )
                        if is_accessible == "yes":
                            console.print(f"[green]✅ {guest_path} (mount)[/]")
                        else:
                            if cloud_init_running:
                                console.print(f"[yellow]⏳ {guest_path} (mount pending)[/]")
                            else:
                                console.print(f"[red]❌ {guest_path} (mount inaccessible)[/]")
                    except Exception:
                        console.print(f"[yellow]⚠️  {guest_path} (could not check)[/]")
                
                # Check copied paths
                for idx, (host_path, guest_path) in enumerate(copy_paths.items()):
                    try:
                        is_accessible = _qga_exec(
                            vm_name, conn_uri, f"test -d {guest_path} && echo yes || echo no", timeout=5
                        )
                        if is_accessible == "yes":
                            console.print(f"[green]✅ {guest_path} (copied)[/]")
                        else:
                            if cloud_init_running:
                                console.print(f"[yellow]⏳ {guest_path} (copy pending)[/]")
                            else:
                                console.print(f"[red]❌ {guest_path} (copy missing)[/]")
                    except Exception:
                        console.print(f"[yellow]⚠️  {guest_path} (could not check)[/]")
        else:
            console.print("[dim]No mount points configured[/]")

    console.print()

    # Test 5: Run health check (if running and not quick)
    if not quick and state == "running":
        console.print("[bold]5. Health Check[/]")
        try:
            if not qga_ready:
                console.print("[yellow]⚠️  QEMU Guest Agent not connected - cannot run health check[/]")
            else:
                exists = _qga_exec(
                    vm_name, conn_uri, "test -x /usr/local/bin/clonebox-health && echo yes || echo no", timeout=10
                )
                if exists and exists.strip() == "yes":
                    _qga_exec(
                        vm_name, conn_uri, "/usr/local/bin/clonebox-health >/dev/null 2>&1 || true", timeout=60
                    )
                    health_status = _qga_exec(
                        vm_name, conn_uri, "cat /var/log/clonebox-health-status 2>/dev/null || true", timeout=10
                    )
                    if health_status and "HEALTH_STATUS=OK" in health_status:
                        console.print("[green]✅ Health check passed[/]")
                        console.print("   View results in VM: cat /var/log/clonebox-health.log")
                    elif health_status and "HEALTH_STATUS=PENDING" in health_status:
                        console.print("[yellow]⚠️  Health check pending (setup in progress)[/]")
                        if cloud_init_running:
                            console.print("   Cloud-init is still running; re-check after it completes")
                        console.print("   View logs in VM: cat /var/log/clonebox-health.log")
                    elif health_status and "HEALTH_STATUS=FAILED" in health_status:
                        console.print("[yellow]⚠️  Health check reports failures[/]")
                        if cloud_init_running:
                            console.print("   Cloud-init is still running; some failures may be transient")
                        console.print("   View logs in VM: cat /var/log/clonebox-health.log")
                    else:
                        console.print("[yellow]⚠️  Health check status not available yet[/]")
                        console.print("   View logs in VM: cat /var/log/clonebox-health.log")
        except Exception as e:
            console.print(f"[yellow]⚠️  Could not run health check: {e}[/]")

    console.print()

    # Run full validation if requested
    if validate_all and state == "running":
        console.print("[bold cyan]🔎 Starting deep validation (--validate)[/]")
        console.print("[dim]This can take a few minutes on first boot (waiting for QGA/cloud-init, checking packages/services).[/]")
        validator = VMValidator(
            config,
            vm_name,
            conn_uri,
            console,
            require_running_apps=require_running_apps,
            smoke_test=smoke_test,
        )
        results = validator.validate_all()

        # Exit with error code if validations failed
        if results["overall"] == "partial":
            return 1
    else:
        # Summary
        console.print("[bold]Test Summary[/]")
        console.print("VM configuration is valid and VM is accessible.")
        console.print("\n[dim]For full validation including packages, services, and mounts:[/]")
        console.print("[dim]  clonebox test . --user --validate[/]")
        console.print("\n[dim]For detailed health report, run in VM:[/]")
        console.print("[dim]  cat /var/log/clonebox-health.log[/]")

    return 0


CLONEBOX_CONFIG_FILE = ".clonebox.yaml"
CLONEBOX_ENV_FILE = ".env"


def load_env_file(env_path: Path) -> dict:
    """Load environment variables from .env file."""
    env_vars = {}
    if not env_path.exists():
        return env_vars

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip().strip("'\"")

    return env_vars


def expand_env_vars(value, env_vars: dict):
    """Expand environment variables in string values like ${VAR_NAME}."""
    if isinstance(value, str):
        # Replace ${VAR_NAME} with value from env_vars or os.environ
        def replacer(match):
            var_name = match.group(1)
            return env_vars.get(var_name, os.environ.get(var_name, match.group(0)))

        return re.sub(r"\$\{([^}]+)\}", replacer, value)
    elif isinstance(value, dict):
        return {k: expand_env_vars(v, env_vars) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(item, env_vars) for item in value]
    return value


def _find_unexpanded_env_placeholders(value) -> set:
    if isinstance(value, str):
        return set(re.findall(r"\$\{([^}]+)\}", value))
    if isinstance(value, dict):
        found = set()
        for v in value.values():
            found |= _find_unexpanded_env_placeholders(v)
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            found |= _find_unexpanded_env_placeholders(item)
        return found
    return set()


def deduplicate_list(items: list, key=None) -> list:
    """Remove duplicates from list, preserving order."""
    seen = set()
    result = []
    for item in items:
        k = key(item) if key else item
        if k not in seen:
            seen.add(k)
            result.append(item)
    return result


def generate_clonebox_yaml(
    snapshot,
    detector,
    deduplicate: bool = True,
    target_path: str = None,
    vm_name: str = None,
    network_mode: str = "auto",
    base_image: Optional[str] = None,
    disk_size_gb: Optional[int] = None,
) -> str:
    """Generate YAML config from system snapshot."""
    sys_info = detector.get_system_info()

    # Services that should NOT be cloned to VM (host-specific)
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

    # Collect services (excluding host-specific ones)
    services = [s.name for s in snapshot.running_services if s.name not in VM_EXCLUDED_SERVICES]
    if deduplicate:
        services = deduplicate_list(services)

    # Collect paths with types
    paths_by_type = {"project": [], "config": [], "data": []}
    for p in snapshot.paths:
        if p.type in paths_by_type:
            paths_by_type[p.type].append(p)

    if deduplicate:
        for ptype in paths_by_type:
            paths_by_type[ptype] = deduplicate_list(paths_by_type[ptype], key=lambda x: x.path)

    # Collect working directories from running apps
    working_dirs = []
    for app in snapshot.applications:
        if app.working_dir and app.working_dir != "/" and app.working_dir.startswith("/home"):
            working_dirs.append(app.working_dir)

    if deduplicate:
        working_dirs = deduplicate_list(working_dirs)

    # If target_path specified, prioritize it
    if target_path:
        target_path = Path(target_path).resolve()
        target_str = str(target_path)
        if target_str not in paths_by_type["project"]:
            paths_by_type["project"].insert(0, target_str)

    # Build paths mapping
    paths_mapping = {}
    idx = 0
    for host_path_obj in paths_by_type["project"][:5]:  # Limit projects
        host_path = host_path_obj.path if hasattr(host_path_obj, 'path') else host_path_obj
        paths_mapping[host_path] = f"/mnt/project{idx}"
        idx += 1

    for host_path in working_dirs[:3]:  # Limit working dirs
        if host_path not in paths_mapping:
            paths_mapping[host_path] = f"/mnt/workdir{idx}"
            idx += 1

    # Add default user folders (Downloads, Documents)
    home_dir = Path.home()
    default_folders = [
        (home_dir / "Downloads", "/home/ubuntu/Downloads"),
        (home_dir / "Documents", "/home/ubuntu/Documents"),
    ]
    for host_folder, guest_folder in default_folders:
        if host_folder.exists() and str(host_folder) not in paths_mapping:
            paths_mapping[str(host_folder)] = guest_folder

    # Detect and add app-specific data directories for running applications
    # This includes browser profiles, IDE settings, credentials, extensions, etc.
    app_data_dirs = detector.detect_app_data_dirs(snapshot.applications)
    app_data_mapping = {}
    for app_data in app_data_dirs:
        host_path = app_data["path"]
        if host_path not in paths_mapping:
            # Map to same relative path in VM user home
            rel_path = host_path.replace(str(home_dir), "").lstrip("/")
            guest_path = f"/home/ubuntu/{rel_path}"
            app_data_mapping[host_path] = guest_path

    post_commands = []

    chrome_profile = home_dir / ".config" / "google-chrome"
    if chrome_profile.exists():
        host_path = str(chrome_profile)
        if host_path not in paths_mapping and host_path not in app_data_mapping:
            app_data_mapping[host_path] = "/home/ubuntu/.config/google-chrome"

        post_commands.append(
            "command -v google-chrome >/dev/null 2>&1 || ("
            "curl -fsSL -o /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && "
            "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/google-chrome.deb"
            ")"
        )

    # Determine VM name
    if not vm_name:
        if target_path:
            vm_name = f"clone-{target_path.name}"
        else:
            vm_name = f"clone-{sys_info['hostname']}"

    # Calculate recommended resources
    ram_mb = min(8192, int(sys_info["memory_available_gb"] * 1024 * 0.5))
    vcpus = max(2, sys_info["cpu_count"] // 2)

    if disk_size_gb is None:
        disk_size_gb = 20

    # Auto-detect packages from running applications and services
    app_packages = detector.suggest_packages_for_apps(snapshot.applications)
    service_packages = detector.suggest_packages_for_services(snapshot.running_services)

    # Combine with base packages (apt only)
    base_packages = [
        "build-essential",
        "git",
        "curl",
        "vim",
    ]

    # Merge apt packages and deduplicate
    all_apt_packages = base_packages + app_packages["apt"] + service_packages["apt"]
    if deduplicate:
        all_apt_packages = deduplicate_list(all_apt_packages)

    # Merge snap packages and deduplicate
    all_snap_packages = app_packages["snap"] + service_packages["snap"]
    if deduplicate:
        all_snap_packages = deduplicate_list(all_snap_packages)

    if "pycharm-community" in all_snap_packages:
        remapped = {}
        for host_path, guest_path in app_data_mapping.items():
            if guest_path == "/home/ubuntu/.config/JetBrains":
                remapped[host_path] = "/home/ubuntu/snap/pycharm-community/common/.config/JetBrains"
            elif guest_path == "/home/ubuntu/.local/share/JetBrains":
                remapped[host_path] = (
                    "/home/ubuntu/snap/pycharm-community/common/.local/share/JetBrains"
                )
            elif guest_path == "/home/ubuntu/.cache/JetBrains":
                remapped[host_path] = "/home/ubuntu/snap/pycharm-community/common/.cache/JetBrains"
            else:
                remapped[host_path] = guest_path
        app_data_mapping = remapped

    if "firefox" in all_apt_packages:
        remapped = {}
        for host_path, guest_path in app_data_mapping.items():
            if guest_path == "/home/ubuntu/.mozilla/firefox":
                remapped[host_path] = "/home/ubuntu/snap/firefox/common/.mozilla/firefox"
            elif guest_path == "/home/ubuntu/.cache/mozilla/firefox":
                remapped[host_path] = "/home/ubuntu/snap/firefox/common/.cache/mozilla/firefox"
            else:
                remapped[host_path] = guest_path
        app_data_mapping = remapped

    # Build config
    config = {
        "version": "1",
        "generated": datetime.now().isoformat(),
        "vm": {
            "name": vm_name,
            "ram_mb": ram_mb,
            "vcpus": vcpus,
            "disk_size_gb": disk_size_gb,
            "gui": True,
            "base_image": base_image,
            "network_mode": network_mode,
            "username": "ubuntu",
            "password": "${VM_PASSWORD}",
        },
        "services": services,
        "packages": all_apt_packages,
        "snap_packages": all_snap_packages,
        "post_commands": post_commands,
        "paths": paths_mapping,
        "app_data_paths": app_data_mapping,  # App-specific config/data directories
        "detected": {
            "running_apps": [
                {"name": a.name, "cwd": a.working_dir or "", "memory_mb": round(a.memory_mb)}
                for a in snapshot.applications[:10]
            ],
            "app_data_dirs": [
                {"path": d["path"], "app": d["app"], "size_mb": d["size_mb"]}
                for d in app_data_dirs[:15]
            ],
            "all_paths": {
                "projects": [{"path": p.path if hasattr(p, 'path') else p, "type": p.type if hasattr(p, 'type') else 'project', "size_mb": p.size_mb if hasattr(p, 'size_mb') else 0} for p in paths_by_type["project"]],
                "configs": [{"path": p.path, "type": p.type, "size_mb": p.size_mb} for p in paths_by_type["config"][:5]],
                "data": [{"path": p.path, "type": p.type, "size_mb": p.size_mb} for p in paths_by_type["data"][:5]],
            },
        },
    }

    return yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_clonebox_config(path: Path) -> dict:
    """Load .clonebox.yaml config file and expand environment variables from .env."""
    config_file = path / CLONEBOX_CONFIG_FILE if path.is_dir() else path

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    # Load .env file from same directory
    config_dir = config_file.parent
    env_file = config_dir / CLONEBOX_ENV_FILE
    env_vars = load_env_file(env_file)

    # Load YAML config
    with open(config_file) as f:
        config = yaml.safe_load(f)

    # Expand environment variables in config
    config = expand_env_vars(config, env_vars)

    unresolved = _find_unexpanded_env_placeholders(config)
    if unresolved:
        unresolved_sorted = ", ".join(sorted(unresolved))
        raise ValueError(
            f"Unresolved environment variables in config: {unresolved_sorted}. "
            f"Set them in {env_file} or in the process environment."
        )

    return config


def _exec_in_vm_qga(vm_name: str, conn_uri: str, command: str) -> Optional[str]:
    """Internal helper to execute command via QGA and get output."""
    import subprocess
    import json
    import base64
    import time
    
    try:
        # 1. Start execution
        cmd_json = {
            "execute": "guest-exec",
            "arguments": {
                "path": "/bin/sh",
                "arg": ["-c", command],
                "capture-output": True
            }
        }
        
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "qemu-agent-command", vm_name, json.dumps(cmd_json)],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return None
            
        resp = json.loads(result.stdout)
        pid = resp.get("return", {}).get("pid")
        if not pid:
            return None
            
        # 2. Wait and get status (quick check)
        status_json = {"execute": "guest-exec-status", "arguments": {"pid": pid}}
        
        for _ in range(3): # Try a few times
            status_result = subprocess.run(
                ["virsh", "--connect", conn_uri, "qemu-agent-command", vm_name, json.dumps(status_json)],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if status_result.returncode != 0:
                continue
                
            status_resp = json.loads(status_result.stdout)
            ret = status_resp.get("return", {})
            
            if ret.get("exited"):
                if "out-data" in ret:
                    return base64.b64decode(ret["out-data"]).decode().strip()
                return ""
            
            time.sleep(0.5)
            
        return None
    except Exception:
        return None


def monitor_cloud_init_status(vm_name: str, user_session: bool = False, timeout: int = 1800):
    """Monitor cloud-init status in VM and show progress."""
    import subprocess
    import time

    conn_uri = "qemu:///session" if user_session else "qemu:///system"
    start_time = time.time()
    shutdown_count = 0  # Count consecutive shutdown detections
    restart_detected = False
    last_phases = []
    seen_lines = set()

    refresh = 1.0
    once = False
    monitor = ResourceMonitor(conn_uri=conn_uri)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Starting VM and initializing...", total=None)

            while time.time() - start_time < timeout:
                # Clear screen for live update
                if not progress.finished:
                    console.clear()

                console.print("[bold cyan]📊 CloneBox Resource Monitor[/]")
                console.print()

                # VM Stats
                vm_stats = monitor.get_all_vm_stats()
                if vm_stats:
                    table = Table(title="🖥️ Virtual Machines", border_style="cyan")
                    table.add_column("Name", style="bold")
                    table.add_column("State")
                    table.add_column("CPU %")
                    table.add_column("Memory")
                    table.add_column("Disk")
                    table.add_column("Network I/O")

                    for vm in vm_stats:
                        state_color = "green" if vm.state == "running" else "yellow"
                        cpu_color = "red" if vm.cpu_percent > 80 else "green"
                        mem_pct = (
                            (vm.memory_used_mb / vm.memory_total_mb * 100)
                            if vm.memory_total_mb > 0
                            else 0
                        )
                        mem_color = "red" if mem_pct > 80 else "green"

                        table.add_row(
                            vm.name,
                            f"[{state_color}]{vm.state}[/]",
                            f"[{cpu_color}]{vm.cpu_percent:.1f}%[/]",
                            f"[{mem_color}]{vm.memory_used_mb}/{vm.memory_total_mb} MB[/]",
                            f"{vm.disk_used_gb:.1f}/{vm.disk_total_gb:.1f} GB",
                            f"↓{format_bytes(vm.network_rx_bytes)} ↑{format_bytes(vm.network_tx_bytes)}",
                        )
                    console.print(table)
                else:
                    console.print("[dim]No VMs found.[/]")

                console.print()

                # Container Stats
                container_stats = monitor.get_container_stats()
                if container_stats:
                    table = Table(title="🐳 Containers", border_style="blue")
                    table.add_column("Name", style="bold")
                    table.add_column("State")
                    table.add_column("CPU %")
                    table.add_column("Memory")
                    table.add_column("Network I/O")
                    table.add_column("PIDs")

                    for c in container_stats:
                        cpu_color = "red" if c.cpu_percent > 80 else "green"
                        mem_pct = (
                            (c.memory_used_mb / c.memory_limit_mb * 100)
                            if c.memory_limit_mb > 0
                            else 0
                        )
                        mem_color = "red" if mem_pct > 80 else "green"

                        table.add_row(
                            c.name,
                            f"[green]{c.state}[/]",
                            f"[{cpu_color}]{c.cpu_percent:.1f}%[/]",
                            f"[{mem_color}]{c.memory_used_mb}/{c.memory_limit_mb} MB[/]",
                            f"↓{format_bytes(c.network_rx_bytes)} ↑{format_bytes(c.network_tx_bytes)}",
                            str(c.pids),
                        )
                    console.print(table)
                else:
                    console.print("[dim]No containers running.[/]")

                if once:
                    break

                console.print(f"\n[dim]Refreshing every {refresh}s. Press Ctrl+C to exit.[/]")
                time.sleep(refresh)

    except KeyboardInterrupt:
        console.print("\n[yellow]Monitoring stopped.[/]")
    finally:
        monitor.close()


def create_vm_from_config(config, start=False, user_session=False, replace=False, approved=False):
    """Create VM from configuration dict."""
    vm_config_dict = config.get("vm", {})
    
    # Create VMConfig object
    vm_config = VMConfig(
        name=vm_config_dict.get("name", "clonebox-vm"),
        ram_mb=vm_config_dict.get("ram_mb", 8192),
        vcpus=vm_config_dict.get("vcpus", 4),
        disk_size_gb=vm_config_dict.get("disk_size_gb", 20),
        gui=vm_config_dict.get("gui", True),
        base_image=vm_config_dict.get("base_image"),
        network_mode=vm_config_dict.get("network_mode", "auto"),
        username=vm_config_dict.get("username", "ubuntu"),
        password=vm_config_dict.get("password", "ubuntu"),
        user_session=user_session,
        paths=config.get("paths", {}),
        packages=config.get("packages", []),
        snap_packages=config.get("snap_packages", []),
        services=config.get("services", []),
        post_commands=config.get("post_commands", []),
        copy_paths=(config.get("copy_paths") or config.get("app_data_paths") or {}),
        resources=config.get("resources", {}),
    )
    
    cloner = SelectiveVMCloner(user_session=user_session)
    
    # Check prerequisites
    checks = cloner.check_prerequisites(vm_config)
    required_keys = [
        "libvirt_connected",
        "kvm_available",
        "images_dir_writable",
        "genisoimage_installed",
        "qemu_img_installed",
    ]
    if checks.get("default_network_required", True):
        required_keys.append("default_network")
    if getattr(vm_config, "gui", False):
        required_keys.append("virt_viewer_installed")

    required_checks = {k: checks.get(k) for k in required_keys if isinstance(checks.get(k), bool)}

    if required_checks and not all(required_checks.values()):
        console.print("[yellow]⚠️  Prerequisites check:[/]")
        for check, passed in required_checks.items():
            icon = "✅" if passed else "❌"
            console.print(f"   {icon} {check}")
    
    # Create VM
    vm_uuid = cloner.create_vm(
        vm_config,
        replace=replace,
        console=console,
        approved=approved,
    )
    
    if start:
        cloner.start_vm(vm_config.name, open_viewer=True, console=console)
    
    return vm_uuid


def cmd_clone(args) -> None:
    """Generate clone config from path and optionally create VM."""
    from clonebox.detector import SystemDetector
    
    target_path = Path(args.path).expanduser().resolve() if args.path else Path.cwd()
    
    if not target_path.exists():
        console.print(f"[red]❌ Path does not exist: {target_path}[/]")
        return
    
    console.print(f"[cyan]🔍 Analyzing system for cloning...[/]")
    
    # Detect system state
    detector = SystemDetector()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning system...", total=None)
        
        # Take snapshot
        snapshot = detector.detect_all()
        
        # Detect Docker containers
        containers = detector.detect_docker_containers()
        
        progress.update(task, description="Finalizing...")
    
    # Generate config
    yaml_content = generate_clonebox_yaml(
        snapshot,
        detector,
        deduplicate=args.dedupe,
        target_path=str(target_path) if args.path else None,
        vm_name=args.name,
        network_mode=args.network,
        base_image=args.base_image,
        disk_size_gb=args.disk_size_gb,
    )
    
    # Save config file
    config_file = target_path / CLONEBOX_CONFIG_FILE
    
    if config_file.exists() and not args.replace:
        console.print(f"[yellow]⚠️  Config file already exists: {config_file}[/]")
        if not questionary.confirm(
            "Overwrite existing config?", default=False, style=custom_style
        ).ask():
            console.print("[dim]Cancelled.[/]")
            return
    
    with open(config_file, "w") as f:
        f.write(yaml_content)
    
    console.print(f"[green]✅ Config saved to: {config_file}[/]")
    
    # Edit if requested
    if args.edit:
        editor = os.environ.get("EDITOR", "nano")
        os.system(f"{editor} {config_file}")
    
    # Run VM if requested
    if args.run:
        console.print("[cyan]🚀 Creating VM from config...[/]")
        config = load_clonebox_config(config_file)
        vm_uuid = create_vm_from_config(
            config, start=True, user_session=args.user, replace=args.replace, approved=args.approve
        )
        console.print(f"[green]✅ VM created: {vm_uuid}[/]")


def cmd_detect(args) -> None:
    """Detect and show system state."""
    from clonebox.detector import SystemDetector
    
    console.print("[cyan]🔍 Detecting system state...[/]")
    
    try:
        detector = SystemDetector()
        
        # Detect system info
        sys_info = detector.get_system_info()
        
        # Detect all services, apps, and paths
        snapshot = detector.detect_all()
        
        # Detect Docker containers
        containers = detector.detect_docker_containers()
        
        # Prepare output
        output = {
            "system": sys_info,
            "services": [
                {
                    "name": s.name,
                    "status": s.status,
                    "enabled": s.enabled,
                    "description": s.description,
                }
                for s in snapshot.running_services
            ],
            "applications": [
                {
                    "name": a.name,
                    "pid": a.pid,
                    "memory_mb": round(a.memory_mb, 2),
                    "working_dir": a.working_dir or "",
                }
                for a in snapshot.applications
            ],
            "paths": [
                {"path": p.path, "type": p.type, "size_mb": p.size_mb}
                for p in snapshot.paths
            ],
            "docker_containers": [
                {
                    "name": c["name"],
                    "status": c["status"],
                    "image": c["image"],
                    "ports": c.get("ports", ""),
                }
                for c in containers
            ],
        }
        
        # Apply deduplication if requested
        if args.dedupe:
            output["services"] = deduplicate_list(output["services"], key=lambda x: x["name"])
            output["applications"] = deduplicate_list(output["applications"], key=lambda x: (x["name"], x["pid"]))
            output["paths"] = deduplicate_list(output["paths"], key=lambda x: x["path"])
        
        # Format output
        if args.json:
            content = json.dumps(output, indent=2)
        elif args.yaml:
            content = yaml.dump(output, default_flow_style=False, allow_unicode=True)
        else:
            # Pretty print
            content = format_detection_output(output, sys_info)
        
        # Save to file or print
        if args.output:
            with open(args.output, "w") as f:
                f.write(content)
            console.print(f"[green]✅ Output saved to: {args.output}[/]")
        else:
            console.print(content)
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        import traceback
        traceback.print_exc()


def format_detection_output(output, sys_info):
    """Format detection output for console display."""
    from rich.table import Table
    from rich.text import Text
    
    # System info
    system_text = Text()
    system_text.append(f"Hostname: {sys_info['hostname']}\n", style="bold")
    system_text.append(f"User: {sys_info['user']}\n")
    system_text.append(f"CPU: {sys_info['cpu_count']} cores\n")
    system_text.append(
        f"Memory: {sys_info['memory_total_gb']:.1f} GB total, {sys_info['memory_available_gb']:.1f} GB available\n"
    )
    system_text.append(
        f"Disk: {sys_info['disk_total_gb']:.1f} GB total, {sys_info['disk_free_gb']:.1f} GB free"
    )
    
    # Services table
    services_table = Table(title="Services", show_header=True, header_style="bold magenta")
    services_table.add_column("Name", style="cyan")
    services_table.add_column("Status", style="green")
    services_table.add_column("Enabled", style="yellow")
    services_table.add_column("Description", style="dim")
    
    for svc in output["services"]:
        status_style = "green" if svc["status"] == "running" else "red"
        enabled_text = "✓" if svc["enabled"] else "✗"
        services_table.add_row(
            svc["name"],
            Text(svc["status"], style=status_style),
            enabled_text,
            svc["description"] or "-",
        )
    
    # Applications table
    apps_table = Table(title="Applications", show_header=True, header_style="bold magenta")
    apps_table.add_column("Name", style="cyan")
    apps_table.add_column("PID", justify="right")
    apps_table.add_column("Memory (MB)", justify="right")
    apps_table.add_column("Working Dir", style="dim")
    
    for app in output["applications"]:
        apps_table.add_row(
            app["name"],
            str(app["pid"]),
            f"{app['memory_mb']:.1f}",
            app["working_dir"] or "-",
        )
    
    # Combine output
    result = Panel(system_text, title="System Information", border_style="blue")
    result += "\n\n"
    result += services_table
    result += "\n\n"
    result += apps_table
    
    return result


def cmd_monitor(args) -> None:
    """Real-time resource monitoring."""
    from clonebox.cloner import SelectiveVMCloner
    
    user_session = getattr(args, "user", False)
    refresh = getattr(args, "refresh", 2.0)
    once = getattr(args, "once", False)
    
    cloner = SelectiveVMCloner(user_session=user_session)
    
    try:
        vms = cloner.list_vms()
        
        if not vms:
            console.print("[dim]No VMs found.[/]")
            return
        
        # Create monitor
        monitor = ResourceMonitor(conn_uri="qemu:///session" if user_session else "qemu:///system")
        
        if once:
            # Show stats once
            table = Table(title="VM Resource Usage", show_header=True, header_style="bold magenta")
            table.add_column("VM Name", style="cyan")
            table.add_column("CPU %", justify="right")
            table.add_column("Memory", justify="right")
            table.add_column("Disk I/O", justify="right")
            table.add_column("Network I/O", justify="right")
            
            for vm in vms:
                if vm["state"] == "running":
                    stats = monitor.get_vm_stats(vm["name"])
                    table.add_row(
                        vm["name"],
                        f"{stats.get('cpu_percent', 0):.1f}%",
                        format_bytes(stats.get("memory_usage", 0)),
                        f"{stats.get('disk_read', 0)}/{stats.get('disk_write', 0)} MB/s",
                        f"{stats.get('net_rx', 0)}/{stats.get('net_tx', 0)} MB/s",
                    )
                else:
                    table.add_row(vm["name"], "[dim]not running[/]", "-", "-", "-")
            
            console.print(table)
        else:
            # Continuous monitoring
            console.print(f"[cyan]Monitoring VMs (refresh every {refresh}s). Press Ctrl+C to exit.[/]\n")
            
            try:
                while True:
                    # Clear screen
                    console.clear()
                    
                    # Create table
                    table = Table(
                        title=f"VM Resource Usage - {datetime.now().strftime('%H:%M:%S')}",
                        show_header=True,
                        header_style="bold magenta",
                    )
                    table.add_column("VM Name", style="cyan")
                    table.add_column("State", style="green")
                    table.add_column("CPU %", justify="right")
                    table.add_column("Memory", justify="right")
                    table.add_column("Disk I/O", justify="right")
                    table.add_column("Network I/O", justify="right")
                    
                    for vm in vms:
                        if vm["state"] == "running":
                            stats = monitor.get_vm_stats(vm["name"])
                            table.add_row(
                                vm["name"],
                                vm["state"],
                                f"{stats.get('cpu_percent', 0):.1f}%",
                                format_bytes(stats.get("memory_usage", 0)),
                                f"{stats.get('disk_read', 0):.1f}/{stats.get('disk_write', 0):.1f} MB/s",
                                f"{stats.get('net_rx', 0):.1f}/{stats.get('net_tx', 0):.1f} MB/s",
                            )
                        else:
                            table.add_row(vm["name"], f"[dim]{vm['state']}[/]", "-", "-", "-", "-")
                    
                    console.print(table)
                    time.sleep(refresh)
                    
            except KeyboardInterrupt:
                console.print("\n[yellow]Monitoring stopped.[/]")
    
    finally:
        monitor.close()


def cmd_exec(args) -> None:
    """Execute command in VM via QEMU Guest Agent."""
    vm_name, config_file = _resolve_vm_name_and_config_file(args.name)
    user_session = getattr(args, "user", False)
    timeout = getattr(args, "timeout", 30)

    # When using argparse.REMAINDER for `command`, any flags placed after the VM name
    # may end up inside args.command. Recover common exec flags from the remainder.
    command_tokens = args.command
    if not isinstance(command_tokens, list):
        command_tokens = [str(command_tokens)] if command_tokens is not None else []

    if "--" in command_tokens:
        sep_idx = command_tokens.index("--")
        pre_tokens = command_tokens[:sep_idx]
        post_tokens = command_tokens[sep_idx + 1 :]
    else:
        pre_tokens = command_tokens
        post_tokens = []

    i = 0
    while i < len(pre_tokens):
        tok = pre_tokens[i]
        if tok in ("-u", "--user"):
            user_session = True
            i += 1
            continue
        if tok in ("-t", "--timeout"):
            if i + 1 < len(pre_tokens):
                try:
                    timeout = int(pre_tokens[i + 1])
                except ValueError:
                    pass
                i += 2
                continue
        break

    remaining_pre = pre_tokens[i:]
    if post_tokens:
        command_tokens = remaining_pre + post_tokens
    else:
        command_tokens = remaining_pre

    command = " ".join(command_tokens).strip()
    if not command:
        console.print("[red]❌ No command specified[/]")
        return

    conn_uri = "qemu:///session" if user_session else "qemu:///system"
    other_conn_uri = "qemu:///system" if conn_uri == "qemu:///session" else "qemu:///session"

    qga_ready = _qga_ping(vm_name, conn_uri)
    if not qga_ready:
        alt_ready = _qga_ping(vm_name, other_conn_uri)
        if alt_ready:
            conn_uri = other_conn_uri
            qga_ready = True
    if not qga_ready:
        for _ in range(12):  # ~60s
            time.sleep(5)
            qga_ready = _qga_ping(vm_name, conn_uri)
            if not qga_ready:
                alt_ready = _qga_ping(vm_name, other_conn_uri)
                if alt_ready:
                    conn_uri = other_conn_uri
                    qga_ready = True
            if qga_ready:
                break

    if not qga_ready:
        console.print(f"[red]❌ Cannot connect to VM '{vm_name}' via QEMU Guest Agent[/]")
        console.print("[dim]Make sure the VM is running and qemu-guest-agent is installed.[/]")
        return

    console.print(f"[cyan]▶ Executing in {vm_name}:[/] {command}")

    result = _qga_exec(vm_name, conn_uri, command, timeout=timeout)

    if result is None:
        console.print("[red]❌ Command execution failed or timed out[/]")
    elif result == "":
        console.print("[dim](no output)[/]")
    else:
        console.print(result)


def cmd_snapshot_create(args) -> None:
    """Create VM snapshot."""
    vm_name, config_file = _resolve_vm_name_and_config_file(args.vm_name)
    conn_uri = "qemu:///session" if getattr(args, "user", False) else "qemu:///system"

    snap_name = args.name or f"snap-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    description = getattr(args, "description", None)

    console.print(f"[cyan]📸 Creating snapshot: {snap_name}[/]")

    try:
        manager = SnapshotManager(conn_uri)
        snapshot = manager.create(
            vm_name=vm_name,
            name=snap_name,
            description=description,
            snapshot_type=SnapshotType.DISK_ONLY,
        )
        console.print(f"[green]✅ Snapshot created: {snapshot.name}[/]")
    except Exception as e:
        console.print(f"[red]❌ Failed to create snapshot: {e}[/]")
    finally:
        manager.close()


def cmd_snapshot_list(args) -> None:
    """List VM snapshots."""
    vm_name, config_file = _resolve_vm_name_and_config_file(args.vm_name)
    conn_uri = "qemu:///session" if getattr(args, "user", False) else "qemu:///system"

    try:
        manager = SnapshotManager(conn_uri)
        snapshots = manager.list(vm_name)

        if not snapshots:
            console.print("[dim]No snapshots found.[/]")
            return

        table = Table(title=f"📸 Snapshots for {vm_name}", border_style="cyan")
        table.add_column("Name", style="bold")
        table.add_column("Created")
        table.add_column("Type")
        table.add_column("Description")

        for snap in snapshots:
            table.add_row(
                snap.name,
                snap.created_at.strftime("%Y-%m-%d %H:%M"),
                snap.snapshot_type.value,
                snap.description or "-",
            )

        console.print(table)
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")
    finally:
        manager.close()


def cmd_snapshot_restore(args) -> None:
    """Restore VM to snapshot."""
    vm_name, config_file = _resolve_vm_name_and_config_file(args.vm_name)
    conn_uri = "qemu:///session" if getattr(args, "user", False) else "qemu:///system"

    policy = PolicyEngine.load_effective(start=config_file)
    if policy is not None:
        try:
            policy.assert_operation_approved(
                AuditEventType.VM_SNAPSHOT_RESTORE.value,
                approved=getattr(args, "approve", False),
            )
        except PolicyViolationError as e:
            console.print(f"[red]❌ {e}[/]")
            sys.exit(1)

    console.print(f"[cyan]🔄 Restoring snapshot: {args.name}[/]")

    try:
        manager = SnapshotManager(conn_uri)
        manager.restore(vm_name, args.name, force=getattr(args, "force", False))
        console.print(f"[green]✅ Restored to snapshot: {args.name}[/]")
    except Exception as e:
        console.print(f"[red]❌ Failed to restore: {e}[/]")
    finally:
        manager.close()


def cmd_snapshot_delete(args) -> None:
    """Delete VM snapshot."""
    vm_name, config_file = _resolve_vm_name_and_config_file(args.vm_name)
    conn_uri = "qemu:///session" if getattr(args, "user", False) else "qemu:///system"

    console.print(f"[cyan]🗑️ Deleting snapshot: {args.name}[/]")

    try:
        manager = SnapshotManager(conn_uri)
        manager.delete(vm_name, args.name)
        console.print(f"[green]✅ Snapshot deleted: {args.name}[/]")
    except Exception as e:
        console.print(f"[red]❌ Failed to delete: {e}[/]")
    finally:
        manager.close()


def cmd_health(args) -> None:
    """Run health checks for VM."""
    vm_name, config_file = _resolve_vm_name_and_config_file(args.name)

    console.print(f"[cyan]🏥 Running health checks for: {vm_name}[/]")

    manager = HealthCheckManager()

    # Load probes from config or use defaults
    probes = []
    if config_file and config_file.exists():
        import yaml

        config = yaml.safe_load(config_file.read_text())
        health_checks = config.get("health_checks", [])
        for hc in health_checks:
            probes.append(ProbeConfig.from_dict(hc))

        # Also create probes for services
        services = config.get("services", [])
        if services:
            probes.extend(manager.create_default_probes(services))

    if not probes:
        console.print(
            "[yellow]No health checks configured. Add 'health_checks' to .clonebox.yaml[/]"
        )
        return

    state = manager.check(vm_name, probes)

    # Display results
    status_color = "green" if state.overall_status.value == "healthy" else "red"
    console.print(
        f"\n[bold]Overall Status:[/] [{status_color}]{state.overall_status.value.upper()}[/]"
    )

    table = Table(title="Health Check Results", border_style="cyan")
    table.add_column("Probe", style="bold")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Message")

    for result in state.check_results:
        status_color = "green" if result.is_healthy else "red"
        table.add_row(
            result.probe_name,
            f"[{status_color}]{result.status.value}[/]",
            f"{result.duration_ms:.0f}ms",
            result.message or result.error or "-",
        )

    console.print(table)


def cmd_keygen(args) -> None:
    """Generate encryption key for secure P2P transfers."""
    key_path = SecureExporter.generate_key()
    console.print(f"[green]🔑 Encryption key generated: {key_path}[/]")
    console.print("[dim]Share this key with team members for encrypted transfers.[/]")


def cmd_export_encrypted(args) -> None:
    """Export VM with AES-256 encryption."""
    vm_name, config_file = _resolve_vm_name_and_config_file(args.name)
    conn_uri = "qemu:///session" if getattr(args, "user", False) else "qemu:///system"
    output = Path(args.output) if args.output else Path(f"{vm_name}.enc")

    console.print(f"[cyan]🔒 Exporting encrypted: {vm_name} → {output}[/]")

    try:
        exporter = SecureExporter(conn_uri)
        exporter.export_encrypted(
            vm_name=vm_name,
            output_path=output,
            include_user_data=getattr(args, "user_data", False),
            include_app_data=getattr(args, "include_data", False),
        )
        console.print(f"[green]✅ Encrypted export complete: {output}[/]")
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
        console.print("[yellow]Run: clonebox keygen[/]")
    finally:
        exporter.close()


def cmd_import_encrypted(args) -> None:
    """Import VM with AES-256 decryption."""
    archive = Path(args.archive)
    conn_uri = "qemu:///session" if getattr(args, "user", False) else "qemu:///system"

    console.print(f"[cyan]🔓 Importing encrypted: {archive}[/]")

    try:
        importer = SecureImporter(conn_uri)
        vm_name = importer.import_decrypted(
            encrypted_path=archive,
            import_user_data=getattr(args, "user_data", False),
            import_app_data=getattr(args, "include_data", False),
            new_name=getattr(args, "name", None),
        )
        console.print(f"[green]✅ Import complete: {vm_name}[/]")
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/]")
    finally:
        importer.close()


def cmd_export_remote(args) -> None:
    """Export VM from remote host."""
    p2p = P2PManager()

    console.print(f"[cyan]📤 Remote export: {args.host}:{args.vm_name}[/]")

    try:
        output = Path(args.output)
        p2p.export_remote(
            host=args.host,
            vm_name=args.vm_name,
            output=output,
            encrypted=getattr(args, "encrypted", False),
            include_user_data=getattr(args, "user_data", False),
            include_app_data=getattr(args, "include_data", False),
        )
        console.print(f"[green]✅ Remote export complete: {output}[/]")
    except RuntimeError as e:
        console.print(f"[red]❌ {e}[/]")


def cmd_import_remote(args) -> None:
    """Import VM to remote host."""
    p2p = P2PManager()
    archive = Path(args.archive)

    console.print(f"[cyan]📥 Remote import: {archive} → {args.host}[/]")

    try:
        p2p.import_remote(
            host=args.host,
            archive_path=archive,
            encrypted=getattr(args, "encrypted", False),
            import_user_data=getattr(args, "user_data", False),
            new_name=getattr(args, "name", None),
        )
        console.print(f"[green]✅ Remote import complete[/]")
    except RuntimeError as e:
        console.print(f"[red]❌ {e}[/]")


def cmd_sync_key(args) -> None:
    """Sync encryption key to remote host."""
    p2p = P2PManager()

    console.print(f"[cyan]🔑 Syncing key to: {args.host}[/]")

    try:
        p2p.sync_key(args.host)
        console.print(f"[green]✅ Key synced to {args.host}[/]")
    except (FileNotFoundError, RuntimeError) as e:
        console.print(f"[red]❌ {e}[/]")


def cmd_list_remote(args) -> None:
    """List VMs on remote host."""
    p2p = P2PManager()

    console.print(f"[cyan]🔍 Listing VMs on: {args.host}[/]")

    vms = p2p.list_remote_vms(args.host)
    if vms:
        for vm in vms:
            console.print(f"  • {vm}")
    else:
        console.print("[yellow]No VMs found on remote host.[/]")


def cmd_policy_validate(args) -> None:
    """Validate a policy file."""
    try:
        file_arg = getattr(args, "file", None)
        if file_arg:
            policy_path = Path(file_arg).expanduser().resolve()
        else:
            policy_path = PolicyEngine.find_policy_file()

        if not policy_path:
            console.print("[red]❌ Policy file not found[/]")
            sys.exit(1)

        PolicyEngine.load(policy_path)
        console.print(f"[green]✅ Policy valid: {policy_path}[/]")
    except (PolicyValidationError, FileNotFoundError) as e:
        console.print(f"[red]❌ Policy invalid: {e}[/]")
        sys.exit(1)


def cmd_policy_apply(args) -> None:
    """Apply a policy file as project or global policy."""
    try:
        src = Path(args.file).expanduser().resolve()
        PolicyEngine.load(src)

        scope = getattr(args, "scope", "project")
        if scope == "global":
            dest = Path.home() / ".clonebox.d" / "policy.yaml"
            dest.parent.mkdir(parents=True, exist_ok=True)
        else:
            dest = Path.cwd() / ".clonebox-policy.yaml"

        dest.write_text(src.read_text())
        console.print(f"[green]✅ Policy applied: {dest}[/]")
    except (PolicyValidationError, FileNotFoundError) as e:
        console.print(f"[red]❌ Failed to apply policy: {e}[/]")
        sys.exit(1)


# === Audit Commands ===


def cmd_audit_list(args) -> None:
    """List audit events."""
    query = AuditQuery()

    # Build filters
    event_type = None
    if hasattr(args, "type") and args.type:
        try:
            event_type = AuditEventType(args.type)
        except ValueError:
            console.print(f"[red]Unknown event type: {args.type}[/]")
            return

    outcome = None
    if hasattr(args, "outcome") and args.outcome:
        try:
            outcome = AuditOutcome(args.outcome)
        except ValueError:
            console.print(f"[red]Unknown outcome: {args.outcome}[/]")
            return

    limit = getattr(args, "limit", 50)
    target = getattr(args, "target", None)

    events = query.query(
        event_type=event_type,
        target_name=target,
        outcome=outcome,
        limit=limit,
    )

    if not events:
        console.print("[yellow]No audit events found.[/]")
        return

    if getattr(args, "json", False):
        console.print_json(json.dumps([e.to_dict() for e in events], default=str))
        return

    table = Table(title="Audit Events", border_style="cyan")
    table.add_column("Time", style="dim")
    table.add_column("Event")
    table.add_column("Target")
    table.add_column("Outcome")
    table.add_column("User")

    for event in reversed(events[-limit:]):
        outcome_style = {
            "success": "green",
            "failure": "red",
            "partial": "yellow",
            "denied": "red bold",
            "skipped": "dim",
        }.get(event.outcome.value, "white")

        target_str = event.target_name or "-"
        table.add_row(
            event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            event.event_type.value,
            target_str,
            f"[{outcome_style}]{event.outcome.value}[/]",
            event.user,
        )

    console.print(table)


def cmd_audit_show(args) -> None:
    """Show audit event details."""
    query = AuditQuery()
    events = query.query(limit=1000)

    for event in events:
        if event.event_id == args.event_id:
            console.print_json(json.dumps(event.to_dict(), indent=2, default=str))
            return

    console.print(f"[red]Event not found: {args.event_id}[/]")


def cmd_audit_failures(args) -> None:
    """Show recent failures."""
    query = AuditQuery()
    events = query.get_failures(limit=getattr(args, "limit", 20))

    if not events:
        console.print("[green]No failures recorded.[/]")
        return

    table = Table(title="Recent Failures", border_style="red")
    table.add_column("Time", style="dim")
    table.add_column("Event")
    table.add_column("Target")
    table.add_column("Error")

    for event in reversed(events):
        table.add_row(
            event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            event.event_type.value,
            event.target_name or "-",
            (event.error_message or "-")[:50],
        )

    console.print(table)


def cmd_audit_search(args) -> None:
    """Search audit events."""
    from datetime import datetime, timedelta

    query = AuditQuery()

    # Parse event type
    event_type = None
    if hasattr(args, "event") and args.event:
        try:
            event_type = AuditEventType(args.event)
        except ValueError:
            console.print(f"[red]Unknown event type: {args.event}[/]")
            return

    # Parse time range
    start_time = None
    if hasattr(args, "since") and args.since:
        since = args.since.lower()
        now = datetime.now()
        if "hour" in since:
            hours = int(since.split()[0]) if since[0].isdigit() else 1
            start_time = now - timedelta(hours=hours)
        elif "day" in since:
            days = int(since.split()[0]) if since[0].isdigit() else 1
            start_time = now - timedelta(days=days)
        elif "week" in since:
            weeks = int(since.split()[0]) if since[0].isdigit() else 1
            start_time = now - timedelta(weeks=weeks)

    user = getattr(args, "user_filter", None)
    target = getattr(args, "target", None)
    limit = getattr(args, "limit", 100)

    events = query.query(
        event_type=event_type,
        target_name=target,
        user=user,
        start_time=start_time,
        limit=limit,
    )

    if not events:
        console.print("[yellow]No matching audit events found.[/]")
        return

    console.print(f"[bold]Found {len(events)} events:[/]")

    for event in events:
        outcome_color = "green" if event.outcome.value == "success" else "red"
        console.print(
            f"  [{outcome_color}]{event.outcome.value}[/] "
            f"{event.timestamp.strftime('%Y-%m-%d %H:%M')} "
            f"[cyan]{event.event_type.value}[/] "
            f"{event.target_name or '-'}"
        )


def cmd_audit_export(args) -> None:
    """Export audit events to file."""
    query = AuditQuery()
    events = query.query(limit=getattr(args, "limit", 10000))

    if not events:
        console.print("[yellow]No audit events to export.[/]")
        return

    output_format = getattr(args, "format", "json")
    output_file = getattr(args, "output", None)

    if output_format == "json":
        data = [e.to_dict() for e in events]
        content = json.dumps(data, indent=2, default=str)
    else:
        # CSV format
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["timestamp", "event_type", "outcome", "target", "user", "error"])
        for e in events:
            writer.writerow([
                e.timestamp.isoformat(),
                e.event_type.value,
                e.outcome.value,
                e.target_name or "",
                e.user,
                e.error_message or "",
            ])
        content = output.getvalue()

    if output_file:
        Path(output_file).write_text(content)
        console.print(f"[green]✅ Exported {len(events)} events to {output_file}[/]")
    else:
        console.print(content)


# === Orchestration Commands ===


def cmd_compose_up(args) -> None:
    """Start VMs from compose file."""
    compose_file = Path(args.file) if hasattr(args, "file") and args.file else Path("clonebox-compose.yaml")

    if not compose_file.exists():
        console.print(f"[red]Compose file not found: {compose_file}[/]")
        return

    user_session = getattr(args, "user", False)
    services = args.services if hasattr(args, "services") and args.services else None

    console.print(f"[cyan]🚀 Starting VMs from: {compose_file}[/]")

    try:
        orch = Orchestrator.from_file(compose_file, user_session=user_session)
        result = orch.up(services=services, console=console)

        if result.success:
            console.print("[green]✅ All VMs started successfully[/]")
        else:
            console.print("[yellow]⚠️ Some VMs failed to start:[/]")
            for name, error in result.errors.items():
                console.print(f"  [red]{name}:[/] {error}")

        console.print(f"[dim]Duration: {result.duration_seconds:.1f}s[/]")

    except Exception as e:
        console.print(f"[red]❌ Orchestration failed: {e}[/]")


def cmd_compose_down(args) -> None:
    """Stop VMs from compose file."""
    compose_file = Path(args.file) if hasattr(args, "file") and args.file else Path("clonebox-compose.yaml")

    if not compose_file.exists():
        console.print(f"[red]Compose file not found: {compose_file}[/]")
        return

    user_session = getattr(args, "user", False)
    services = args.services if hasattr(args, "services") and args.services else None
    force = getattr(args, "force", False)

    console.print(f"[cyan]🛑 Stopping VMs from: {compose_file}[/]")

    try:
        orch = Orchestrator.from_file(compose_file, user_session=user_session)
        result = orch.down(services=services, force=force, console=console)

        if result.success:
            console.print("[green]✅ All VMs stopped successfully[/]")
        else:
            console.print("[yellow]⚠️ Some VMs failed to stop:[/]")
            for name, error in result.errors.items():
                console.print(f"  [red]{name}:[/] {error}")

    except Exception as e:
        console.print(f"[red]❌ Stop failed: {e}[/]")


def cmd_compose_status(args) -> None:
    """Show status of VMs from compose file."""
    compose_file = Path(args.file) if hasattr(args, "file") and args.file else Path("clonebox-compose.yaml")

    if not compose_file.exists():
        console.print(f"[red]Compose file not found: {compose_file}[/]")
        return

    user_session = getattr(args, "user", False)

    try:
        orch = Orchestrator.from_file(compose_file, user_session=user_session)
        status = orch.status()

        if getattr(args, "json", False):
            console.print_json(json.dumps(status, default=str))
            return

        table = Table(title=f"Compose Status: {compose_file.name}", border_style="cyan")
        table.add_column("VM")
        table.add_column("State")
        table.add_column("Actual")
        table.add_column("Health")
        table.add_column("Depends On")

        for name, info in status.items():
            state = info["orchestration_state"]
            actual = info["actual_state"]
            health = "✅" if info["health_check_passed"] else "⏳"
            deps = ", ".join(info["depends_on"]) or "-"

            state_style = {
                "running": "green",
                "healthy": "green bold",
                "stopped": "dim",
                "failed": "red",
                "pending": "yellow",
            }.get(state, "white")

            table.add_row(
                name,
                f"[{state_style}]{state}[/]",
                actual,
                health,
                deps,
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]❌ Failed to get status: {e}[/]")


def cmd_compose_logs(args) -> None:
    """Show aggregated logs from VMs."""
    compose_file = Path(args.file) if hasattr(args, "file") and args.file else Path("clonebox-compose.yaml")

    if not compose_file.exists():
        console.print(f"[red]Compose file not found: {compose_file}[/]")
        return

    user_session = getattr(args, "user", False)
    follow = getattr(args, "follow", False)
    lines = getattr(args, "lines", 50)
    service = getattr(args, "service", None)

    try:
        orch = Orchestrator.from_file(compose_file, user_session=user_session)

        if service:
            # Logs for specific service
            logs = orch.logs(service, follow=follow, lines=lines)
            if logs:
                console.print(f"[bold]Logs for {service}:[/]")
                console.print(logs)
            else:
                console.print(f"[yellow]No logs available for {service}[/]")
        else:
            # Logs for all services
            for name in orch.plan.vms.keys():
                logs = orch.logs(name, follow=False, lines=lines)
                if logs:
                    console.print(f"\n[bold cyan]━━━ {name} ━━━[/]")
                    console.print(logs)

    except Exception as e:
        console.print(f"[red]❌ Failed to get logs: {e}[/]")


# === Plugin Commands ===


def cmd_plugin_list(args) -> None:
    """List installed plugins."""
    manager = get_plugin_manager()

    # Load plugins if not already loaded
    if not manager.list_plugins():
        manager.load_all()

    plugins = manager.list_plugins()

    if not plugins:
        console.print("[yellow]No plugins installed.[/]")
        console.print("[dim]Plugin directories:[/]")
        for d in manager.plugin_dirs:
            console.print(f"  {d}")
        return

    table = Table(title="Installed Plugins", border_style="cyan")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Enabled")
    table.add_column("Description")

    for plugin in plugins:
        enabled = "[green]✅[/]" if plugin["enabled"] else "[red]❌[/]"
        table.add_row(
            plugin["name"],
            plugin["version"],
            enabled,
            (plugin.get("description", "") or "")[:40],
        )

    console.print(table)


def cmd_plugin_enable(args) -> None:
    """Enable a plugin."""
    manager = get_plugin_manager()
    manager.load_all()

    if manager.enable(args.name):
        console.print(f"[green]✅ Plugin '{args.name}' enabled[/]")
    else:
        console.print(f"[red]Plugin '{args.name}' not found[/]")


def cmd_plugin_disable(args) -> None:
    """Disable a plugin."""
    manager = get_plugin_manager()
    manager.load_all()

    if manager.disable(args.name):
        console.print(f"[yellow]⚠️ Plugin '{args.name}' disabled[/]")
    else:
        console.print(f"[red]Plugin '{args.name}' not found[/]")


def cmd_plugin_discover(args) -> None:
    """Discover available plugins."""
    manager = get_plugin_manager()
    discovered = manager.discover()

    if not discovered:
        console.print("[yellow]No plugins discovered.[/]")
        console.print("[dim]Plugin directories:[/]")
        for d in manager.plugin_dirs:
            console.print(f"  {d}")
        return

    console.print("[bold]Discovered plugins:[/]")
    for name in discovered:
        console.print(f"  • {name}")


def cmd_plugin_install(args) -> None:
    """Install a plugin."""
    manager = get_plugin_manager()
    source = args.source

    console.print(f"[cyan]📦 Installing plugin from: {source}[/]")

    if manager.install(source):
        console.print("[green]✅ Plugin installed successfully[/]")
        console.print("[dim]Run 'clonebox plugin discover' to see available plugins[/]")
    else:
        console.print(f"[red]❌ Failed to install plugin from: {source}[/]")


def cmd_plugin_uninstall(args) -> None:
    """Uninstall a plugin."""
    manager = get_plugin_manager()
    name = args.name

    console.print(f"[cyan]🗑️  Uninstalling plugin: {name}[/]")

    if manager.uninstall(name):
        console.print(f"[green]✅ Plugin '{name}' uninstalled successfully[/]")
    else:
        console.print(f"[red]❌ Failed to uninstall plugin: {name}[/]")


# === Remote Management Commands ===


def cmd_remote_list(args) -> None:
    """List VMs on remote host."""
    host = args.host
    user_session = getattr(args, "user", False)

    console.print(f"[cyan]🔍 Connecting to: {host}[/]")

    try:
        remote = RemoteCloner(host, verify=True)

        if not remote.is_clonebox_installed():
            console.print("[red]❌ CloneBox is not installed on remote host[/]")
            return

        vms = remote.list_vms(user_session=user_session)

        if not vms:
            console.print("[yellow]No VMs found on remote host.[/]")
            return

        table = Table(title=f"VMs on {host}", border_style="cyan")
        table.add_column("Name")
        table.add_column("Status")

        for vm in vms:
            name = vm.get("name", str(vm))
            status = vm.get("state", vm.get("status", "-"))
            table.add_row(name, status)

        console.print(table)

    except ConnectionError as e:
        console.print(f"[red]❌ Connection failed: {e}[/]")
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


def cmd_remote_status(args) -> None:
    """Get VM status on remote host."""
    host = args.host
    vm_name = args.vm_name
    user_session = getattr(args, "user", False)

    console.print(f"[cyan]🔍 Getting status of {vm_name} on {host}[/]")

    try:
        remote = RemoteCloner(host, verify=True)
        status = remote.get_status(vm_name, user_session=user_session)

        if getattr(args, "json", False):
            console.print_json(json.dumps(status, default=str))
        else:
            for key, value in status.items():
                console.print(f"  [bold]{key}:[/] {value}")

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


def cmd_remote_start(args) -> None:
    """Start VM on remote host."""
    host = args.host
    vm_name = args.vm_name
    user_session = getattr(args, "user", False)

    console.print(f"[cyan]🚀 Starting {vm_name} on {host}[/]")

    try:
        remote = RemoteCloner(host, verify=True)
        remote.start_vm(vm_name, user_session=user_session)
        console.print(f"[green]✅ VM {vm_name} started[/]")

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


def cmd_remote_stop(args) -> None:
    """Stop VM on remote host."""
    host = args.host
    vm_name = args.vm_name
    user_session = getattr(args, "user", False)
    force = getattr(args, "force", False)

    console.print(f"[cyan]🛑 Stopping {vm_name} on {host}[/]")

    try:
        remote = RemoteCloner(host, verify=True)
        remote.stop_vm(vm_name, force=force, user_session=user_session)
        console.print(f"[green]✅ VM {vm_name} stopped[/]")

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


def cmd_remote_delete(args) -> None:
    """Delete VM on remote host."""
    host = args.host
    vm_name = args.vm_name
    user_session = getattr(args, "user", False)
    keep_storage = getattr(args, "keep_storage", False)

    policy = PolicyEngine.load_effective()
    if policy is not None:
        try:
            policy.assert_operation_approved(
                AuditEventType.VM_DELETE.value,
                approved=getattr(args, "approve", False),
            )
        except PolicyViolationError as e:
            console.print(f"[red]❌ {e}[/]")
            sys.exit(1)

    if not getattr(args, "yes", False):
        confirm = questionary.confirm(
            f"Delete VM '{vm_name}' on {host}?",
            default=False,
            style=custom_style,
        ).ask()
        if not confirm:
            console.print("[yellow]Aborted.[/]")
            return

    console.print(f"[cyan]🗑️ Deleting {vm_name} on {host}[/]")

    try:
        remote = RemoteCloner(host, verify=True)
        remote.delete_vm(vm_name, keep_storage=keep_storage, user_session=user_session)
        console.print(f"[green]✅ VM {vm_name} deleted[/]")

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


def cmd_remote_exec(args) -> None:
    """Execute command in VM on remote host."""
    host = args.host
    vm_name = args.vm_name
    command = " ".join(args.command) if args.command else "echo ok"
    user_session = getattr(args, "user", False)
    timeout = getattr(args, "timeout", 30)

    try:
        remote = RemoteCloner(host, verify=True)
        output = remote.exec_in_vm(vm_name, command, timeout=timeout, user_session=user_session)
        console.print(output)

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


def cmd_remote_health(args) -> None:
    """Run health check on remote VM."""
    host = args.host
    vm_name = args.vm_name
    user_session = getattr(args, "user", False)

    console.print(f"[cyan]🏥 Running health check on {vm_name}@{host}[/]")

    try:
        remote = RemoteCloner(host, verify=True)
        result = remote.health_check(vm_name, user_session=user_session)

        if result["success"]:
            console.print("[green]✅ Health check passed[/]")
        else:
            console.print("[red]❌ Health check failed[/]")

        if result.get("output"):
            console.print(result["output"])

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/]")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="clonebox", description="Clone your workstation environment to an isolated VM"
    )
    parser.add_argument("--version", action="version", version=f"clonebox {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Interactive mode (default)
    parser.set_defaults(func=lambda args: interactive_mode())

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize a new CloneBox configuration")
    init_parser.add_argument(
        "path", nargs="?", default=None, help="Path for config file (default: ./.clonebox.yaml)"
    )
    init_parser.add_argument("--name", "-n", help="VM name (default: clonebox-vm)")
    init_parser.add_argument("--ram", type=int, help="RAM in MB (default: 4096)")
    init_parser.add_argument("--vcpus", type=int, help="Number of vCPUs (default: 4)")
    init_parser.add_argument("--disk-size-gb", type=int, help="Root disk size in GB (default: 20)")
    init_parser.add_argument("--base-image", help="Path to base qcow2 image")
    init_parser.add_argument("--no-gui", action="store_true", help="Disable SPICE graphics")
    init_parser.add_argument("--network", help="Network mode (default: auto)")
    init_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing config")
    init_parser.set_defaults(func=cmd_init)

    # Create command
    create_parser = subparsers.add_parser("create", help="Create VM from config")
    create_parser.add_argument("--name", "-n", default="clonebox-vm", help="VM name")
    create_parser.add_argument(
        "--config",
        "-c",
        required=True,
        help='JSON config: {"paths": {}, "packages": [], "services": []}',
    )
    create_parser.add_argument("--ram", type=int, default=4096, help="RAM in MB")
    create_parser.add_argument("--vcpus", type=int, default=4, help="Number of vCPUs")
    create_parser.add_argument(
        "--disk-size-gb",
        type=int,
        default=10,
        help="Root disk size in GB (default: 10)",
    )
    create_parser.add_argument("--base-image", help="Path to base qcow2 image")
    create_parser.add_argument("--no-gui", action="store_true", help="Disable SPICE graphics")
    create_parser.add_argument("--start", "-s", action="store_true", help="Start VM after creation")
    create_parser.set_defaults(func=cmd_create)

    # Start command
    start_parser = subparsers.add_parser("start", help="Start a VM")
    start_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    start_parser.add_argument("--no-viewer", action="store_true", help="Don't open virt-viewer")
    start_parser.add_argument("--viewer", action="store_true", help="Open virt-viewer GUI")
    start_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    start_parser.set_defaults(func=cmd_start)

    # Open command - open VM viewer
    open_parser = subparsers.add_parser("open", help="Open VM viewer window")
    open_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    open_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    open_parser.set_defaults(func=cmd_open)

    # Stop command
    stop_parser = subparsers.add_parser("stop", help="Stop a VM")
    stop_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    stop_parser.add_argument("--force", "-f", action="store_true", help="Force stop")
    stop_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    stop_parser.set_defaults(func=cmd_stop)

    # Restart command
    restart_parser = subparsers.add_parser("restart", help="Restart a VM (stop and start)")
    restart_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    restart_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force stop if VM is stuck",
    )
    restart_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    restart_parser.add_argument(
        "--open",
        action="store_true",
        help="Open GUI after restart",
    )
    restart_parser.set_defaults(func=cmd_restart)

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a VM")
    delete_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    delete_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    delete_parser.add_argument("--keep-storage", action="store_true", help="Keep disk images")
    delete_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    delete_parser.add_argument(
        "--approve",
        action="store_true",
        help="Approve policy-gated operation",
    )
    delete_parser.set_defaults(func=cmd_delete)

    # List command
    list_parser = subparsers.add_parser("list", aliases=["ls"], help="List VMs")
    list_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    list_parser.add_argument("--json", action="store_true", help="Output JSON")
    list_parser.set_defaults(func=cmd_list)

    # Container command
    container_parser = subparsers.add_parser("container", help="Manage container sandboxes")
    container_parser.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default="auto",
        help="Container engine: auto (default), podman, docker",
    )
    container_parser.set_defaults(func=lambda args, p=container_parser: p.print_help())
    container_sub = container_parser.add_subparsers(
        dest="container_command", help="Container commands"
    )

    container_up = container_sub.add_parser("up", help="Start container")
    container_up.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default=argparse.SUPPRESS,
        help="Container engine: auto (default), podman, docker",
    )
    container_up.add_argument("path", nargs="?", default=".", help="Workspace path")
    container_up.add_argument("--name", help="Container name")
    container_up.add_argument("--image", default="ubuntu:22.04", help="Container image")
    container_up.add_argument("--detach", action="store_true", help="Run container in background")
    container_up.add_argument(
        "--profile",
        help="Profile name (loads ~/.clonebox.d/<name>.yaml, .clonebox.d/<name>.yaml, or built-in templates)",
    )
    container_up.add_argument(
        "--mount",
        action="append",
        default=[],
        help="Extra mount HOST:CONTAINER (repeatable)",
    )
    container_up.add_argument(
        "--port",
        action="append",
        default=[],
        help="Port mapping (e.g. 8080:80) (repeatable)",
    )
    container_up.add_argument(
        "--package",
        action="append",
        default=[],
        help="APT package to install in image (repeatable)",
    )
    container_up.add_argument(
        "--no-dotenv",
        action="store_true",
        help="Do not load env vars from workspace .env",
    )
    container_up.set_defaults(func=cmd_container_up)

    container_ps = container_sub.add_parser("ps", aliases=["ls"], help="List containers")
    container_ps.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default=argparse.SUPPRESS,
        help="Container engine: auto (default), podman, docker",
    )
    container_ps.add_argument("-a", "--all", action="store_true", help="Show all containers")
    container_ps.add_argument("--json", action="store_true", help="Output JSON")
    container_ps.set_defaults(func=cmd_container_ps)

    container_stop = container_sub.add_parser("stop", help="Stop container")
    container_stop.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default=argparse.SUPPRESS,
        help="Container engine: auto (default), podman, docker",
    )
    container_stop.add_argument("name", help="Container name")
    container_stop.set_defaults(func=cmd_container_stop)

    container_rm = container_sub.add_parser("rm", help="Remove container")
    container_rm.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default=argparse.SUPPRESS,
        help="Container engine: auto (default), podman, docker",
    )
    container_rm.add_argument("name", help="Container name")
    container_rm.add_argument("-f", "--force", action="store_true", help="Force remove")
    container_rm.set_defaults(func=cmd_container_rm)

    container_down = container_sub.add_parser("down", help="Stop and remove container")
    container_down.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default=argparse.SUPPRESS,
        help="Container engine: auto (default), podman, docker",
    )
    container_down.add_argument("name", help="Container name")
    container_down.set_defaults(func=cmd_container_down)

    # Dashboard command
    dashboard_parser = subparsers.add_parser("dashboard", help="Run local dashboard")
    dashboard_parser.add_argument(
        "--port", type=int, default=8080, help="Port to bind (default: 8080)"
    )
    dashboard_parser.set_defaults(func=cmd_dashboard)

    # Detect command
    detect_parser = subparsers.add_parser("detect", help="Detect system state")
    detect_parser.add_argument("--json", action="store_true", help="Output as JSON")
    detect_parser.add_argument("--yaml", action="store_true", help="Output as YAML config")
    detect_parser.add_argument("--dedupe", action="store_true", help="Remove duplicate entries")
    detect_parser.add_argument("-o", "--output", help="Save output to file")
    detect_parser.set_defaults(func=cmd_detect)

    # Clone command
    clone_parser = subparsers.add_parser("clone", help="Generate clone config from path")
    clone_parser.add_argument(
        "path", nargs="?", default=".", help="Path to clone (default: current dir)"
    )
    clone_parser.add_argument("--name", "-n", help="VM name (default: directory name)")
    clone_parser.add_argument(
        "--run", "-r", action="store_true", help="Create and start VM immediately"
    )
    clone_parser.add_argument(
        "--edit", "-e", action="store_true", help="Open config in editor before creating"
    )
    clone_parser.add_argument(
        "--dedupe", action="store_true", default=True, help="Remove duplicate entries"
    )
    clone_parser.add_argument(
        "--user",
        "-u",
        action="store_true",
        help="Use user session (qemu:///session) - no root required, stores in ~/.local/share/libvirt/",
    )
    clone_parser.add_argument(
        "--network",
        choices=["auto", "default", "user"],
        default="auto",
        help="Network mode: auto (default), default (libvirt network), user (slirp)",
    )
    clone_parser.add_argument(
        "--base-image",
        help="Path to a bootable qcow2 image to use as a base disk",
    )
    clone_parser.add_argument(
        "--disk-size-gb",
        type=int,
        default=None,
        help="Root disk size in GB (default: 20 for generated configs)",
    )
    clone_parser.add_argument(
        "--profile",
        help="Profile name (loads ~/.clonebox.d/<name>.yaml, .clonebox.d/<name>.yaml, or built-in templates)",
    )
    clone_parser.add_argument(
        "--replace",
        action="store_true",
        help="If VM already exists, stop+undefine it and recreate (also deletes its storage)",
    )
    clone_parser.add_argument(
        "--approve",
        action="store_true",
        help="Approve policy-gated operation (required for --replace if policy demands)",
    )
    clone_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without making any changes",
    )
    clone_parser.set_defaults(func=cmd_clone)

    # Status command - check VM health from workstation
    status_parser = subparsers.add_parser("status", help="Check VM installation status and health")
    status_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    status_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session)",
    )
    status_parser.add_argument("--health", "-H", action="store_true", help="Run full health check")
    status_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed diagnostics (QGA, stderr, etc.)"
    )
    status_parser.set_defaults(func=cmd_status)

    # Diagnose command - detailed diagnostics from workstation
    diagnose_parser = subparsers.add_parser(
        "diagnose", aliases=["diag"], help="Run detailed VM diagnostics"
    )
    diagnose_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    diagnose_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session)",
    )
    diagnose_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show more low-level details"
    )
    diagnose_parser.add_argument("--json", action="store_true", help="Print diagnostics as JSON")
    diagnose_parser.set_defaults(func=cmd_diagnose)

    watch_parser = subparsers.add_parser(
        "watch", help="Watch boot diagnostic output from VM (via QEMU Guest Agent)"
    )
    watch_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    watch_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session)",
    )
    watch_parser.add_argument(
        "--refresh",
        type=float,
        default=1.0,
        help="Refresh interval in seconds (default: 1.0)",
    )
    watch_parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Max seconds to wait (default: 600)",
    )
    watch_parser.set_defaults(func=cmd_watch)

    repair_parser = subparsers.add_parser(
        "repair", help="Trigger boot diagnostic/repair inside VM (via QEMU Guest Agent)"
    )
    repair_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    repair_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session)",
    )
    repair_parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Max seconds to wait for repair (default: 600)",
    )
    repair_parser.add_argument(
        "--watch",
        action="store_true",
        help="After triggering repair, watch status/log output",
    )
    repair_parser.add_argument(
        "--refresh",
        type=float,
        default=1.0,
        help="Refresh interval for --watch (default: 1.0)",
    )
    repair_parser.set_defaults(func=cmd_repair)

    # Logs command - view VM logs
    logs_parser = subparsers.add_parser("logs", help="View logs from VM")
    logs_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    logs_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session)",
    )
    logs_parser.add_argument(
        "--all",
        action="store_true",
        help="Show all logs at once without interactive menu",
    )
    logs_parser.set_defaults(func=cmd_logs)

    # Set-password command - set password for VM user
    set_password_parser = subparsers.add_parser("set-password", help="Set password for VM user")
    set_password_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    set_password_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session)",
    )
    set_password_parser.set_defaults(func=cmd_set_password)

    # Export command - package VM for migration
    export_parser = subparsers.add_parser("export", help="Export VM and data for migration")
    export_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    export_parser.add_argument(
        "-u", "--user", action="store_true", help="Use user session (qemu:///session)"
    )
    export_parser.add_argument("-o", "--output", help="Output archive filename (default: <vmname>-export.tar.gz)")
    export_parser.add_argument(
        "--include-data",
        "-d",
        action="store_true",
        help="Include shared data (browser profiles, configs)",
    )
    export_parser.set_defaults(func=cmd_export)

    # Import command - restore VM from export
    import_parser = subparsers.add_parser("import", help="Import VM from export archive")
    import_parser.add_argument("archive", help="Path to export archive (.tar.gz)")
    import_parser.add_argument(
        "-u", "--user", action="store_true", help="Use user session (qemu:///session)"
    )
    import_parser.add_argument(
        "--replace", action="store_true", help="Replace existing VM if exists"
    )
    import_parser.add_argument(
        "--approve",
        action="store_true",
        help="Approve policy-gated operation (required for --replace if policy demands)",
    )
    import_parser.set_defaults(func=cmd_import)

    # Test command - validate VM configuration
    test_parser = subparsers.add_parser("test", help="Test VM configuration and health")
    test_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    test_parser.add_argument(
        "-u", "--user", action="store_true", help="Use user session (qemu:///session)"
    )
    test_parser.add_argument(
        "--quick", action="store_true", help="Quick test (no deep health checks)"
    )
    test_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    test_parser.add_argument(
        "--validate", action="store_true", help="Run full validation (mounts, packages, services)"
    )
    test_parser.add_argument(
        "--require-running-apps",
        action="store_true",
        help="Fail validation if expected apps are installed but not currently running",
    )
    test_parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run smoke tests (installed ≠ works): headless launch checks for key apps",
    )
    test_parser.set_defaults(func=cmd_test)

    # Monitor command - real-time resource monitoring
    monitor_parser = subparsers.add_parser("monitor", help="Real-time resource monitoring")
    monitor_parser.add_argument(
        "-u", "--user", action="store_true", help="Use user session (qemu:///session)"
    )
    monitor_parser.add_argument(
        "--refresh", "-r", type=float, default=2.0, help="Refresh interval in seconds (default: 2)"
    )
    monitor_parser.add_argument("--once", action="store_true", help="Show stats once and exit")
    monitor_parser.set_defaults(func=cmd_monitor)

    # Exec command - execute command in VM
    exec_parser = subparsers.add_parser("exec", help="Execute command in VM via QEMU Guest Agent")
    exec_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    exec_parser.add_argument(
        "command", nargs=argparse.REMAINDER, help="Command to execute in VM"
    )
    exec_parser.add_argument(
        "-u", "--user", action="store_true", help="Use user session (qemu:///session)"
    )
    exec_parser.add_argument(
        "--timeout", "-t", type=int, default=30, help="Command timeout in seconds (default: 30)"
    )
    exec_parser.set_defaults(func=cmd_exec)

    # === Snapshot Commands ===
    snapshot_parser = subparsers.add_parser("snapshot", help="Manage VM snapshots")
    snapshot_sub = snapshot_parser.add_subparsers(dest="snapshot_command", help="Snapshot commands")

    snap_create = snapshot_sub.add_parser("create", help="Create snapshot")
    snap_create.add_argument("vm_name", help="VM name or '.' to use .clonebox.yaml")
    snap_create.add_argument("--name", "-n", help="Snapshot name (auto-generated if not provided)")
    snap_create.add_argument("--description", "-d", help="Snapshot description")
    snap_create.add_argument("-u", "--user", action="store_true", help="Use user session")
    snap_create.set_defaults(func=cmd_snapshot_create)

    snap_list = snapshot_sub.add_parser("list", aliases=["ls"], help="List snapshots")
    snap_list.add_argument("vm_name", help="VM name or '.' to use .clonebox.yaml")
    snap_list.add_argument("-u", "--user", action="store_true", help="Use user session")
    snap_list.set_defaults(func=cmd_snapshot_list)

    snap_restore = snapshot_sub.add_parser("restore", help="Restore to snapshot")
    snap_restore.add_argument("vm_name", help="VM name or '.' to use .clonebox.yaml")
    snap_restore.add_argument("--name", "-n", required=True, help="Snapshot name to restore")
    snap_restore.add_argument("-u", "--user", action="store_true", help="Use user session")
    snap_restore.add_argument(
        "-f", "--force", action="store_true", help="Force restore even if running"
    )
    snap_restore.add_argument(
        "--approve",
        action="store_true",
        help="Approve policy-gated operation",
    )
    snap_restore.set_defaults(func=cmd_snapshot_restore)

    snap_delete = snapshot_sub.add_parser("delete", aliases=["rm"], help="Delete snapshot")
    snap_delete.add_argument("vm_name", help="VM name or '.' to use .clonebox.yaml")
    snap_delete.add_argument("--name", "-n", required=True, help="Snapshot name to delete")
    snap_delete.add_argument("-u", "--user", action="store_true", help="Use user session")
    snap_delete.set_defaults(func=cmd_snapshot_delete)

    # === Health Check Commands ===
    health_parser = subparsers.add_parser("health", help="Run health checks for VM")
    health_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    health_parser.add_argument("-u", "--user", action="store_true", help="Use user session")
    health_parser.set_defaults(func=cmd_health)

    # === P2P Secure Transfer Commands ===

    # Keygen command - generate encryption key
    keygen_parser = subparsers.add_parser(
        "keygen", help="Generate encryption key for secure transfers"
    )
    keygen_parser.set_defaults(func=cmd_keygen)

    # Export-encrypted command
    export_enc_parser = subparsers.add_parser(
        "export-encrypted", help="Export VM with AES-256 encryption"
    )
    export_enc_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    export_enc_parser.add_argument(
        "-u", "--user", action="store_true", help="Use user session (qemu:///session)"
    )
    export_enc_parser.add_argument("-o", "--output", help="Output file (default: <vmname>.enc)")
    export_enc_parser.add_argument(
        "--user-data", action="store_true", help="Include user data (SSH keys, configs)"
    )
    export_enc_parser.add_argument(
        "--include-data", "-d", action="store_true", help="Include app data"
    )
    export_enc_parser.set_defaults(func=cmd_export_encrypted)

    # Import-encrypted command
    import_enc_parser = subparsers.add_parser(
        "import-encrypted", help="Import VM with AES-256 decryption"
    )
    import_enc_parser.add_argument("archive", help="Path to encrypted archive (.enc)")
    import_enc_parser.add_argument(
        "-u", "--user", action="store_true", help="Use user session (qemu:///session)"
    )
    import_enc_parser.add_argument("--name", "-n", help="New name for imported VM")
    import_enc_parser.add_argument("--user-data", action="store_true", help="Import user data")
    import_enc_parser.add_argument(
        "--include-data", "-d", action="store_true", help="Import app data"
    )
    import_enc_parser.set_defaults(func=cmd_import_encrypted)

    # Export-remote command
    export_remote_parser = subparsers.add_parser(
        "export-remote", help="Export VM from remote host via SSH"
    )
    export_remote_parser.add_argument("host", help="Remote host (user@hostname)")
    export_remote_parser.add_argument("vm_name", help="VM name on remote host")
    export_remote_parser.add_argument("-o", "--output", required=True, help="Local output file")
    export_remote_parser.add_argument(
        "--encrypted", "-e", action="store_true", help="Use encrypted export"
    )
    export_remote_parser.add_argument("--user-data", action="store_true", help="Include user data")
    export_remote_parser.add_argument(
        "--include-data", "-d", action="store_true", help="Include app data"
    )
    export_remote_parser.set_defaults(func=cmd_export_remote)

    # Import-remote command
    import_remote_parser = subparsers.add_parser(
        "import-remote", help="Import VM to remote host via SSH"
    )
    import_remote_parser.add_argument("archive", help="Local archive to upload")
    import_remote_parser.add_argument("host", help="Remote host (user@hostname)")
    import_remote_parser.add_argument("--name", "-n", help="New name for VM on remote")
    import_remote_parser.add_argument(
        "--encrypted", "-e", action="store_true", help="Use encrypted import"
    )
    import_remote_parser.add_argument("--user-data", action="store_true", help="Import user data")
    import_remote_parser.set_defaults(func=cmd_import_remote)

    # Sync-key command
    sync_key_parser = subparsers.add_parser("sync-key", help="Sync encryption key to remote host")
    sync_key_parser.add_argument("host", help="Remote host (user@hostname)")
    sync_key_parser.set_defaults(func=cmd_sync_key)

    # List-remote command
    list_remote_parser = subparsers.add_parser("list-remote", help="List VMs on remote host")
    list_remote_parser.add_argument("host", help="Remote host (user@hostname)")
    list_remote_parser.set_defaults(func=cmd_list_remote)

    # === Audit Commands ===
    audit_parser = subparsers.add_parser("audit", help="View audit logs")
    audit_sub = audit_parser.add_subparsers(dest="audit_command", help="Audit commands")

    audit_list = audit_sub.add_parser("list", aliases=["ls"], help="List audit events")
    audit_list.add_argument("--type", "-t", help="Filter by event type (e.g., vm.create)")
    audit_list.add_argument("--target", help="Filter by target name")
    audit_list.add_argument("--outcome", "-o", choices=["success", "failure", "partial"], help="Filter by outcome")
    audit_list.add_argument("--limit", "-n", type=int, default=50, help="Max events to show")
    audit_list.add_argument("--json", action="store_true", help="Output as JSON")
    audit_list.set_defaults(func=cmd_audit_list)

    audit_show = audit_sub.add_parser("show", help="Show audit event details")
    audit_show.add_argument("event_id", help="Event ID to show")
    audit_show.set_defaults(func=cmd_audit_show)

    audit_failures = audit_sub.add_parser("failures", help="Show recent failures")
    audit_failures.add_argument("--limit", "-n", type=int, default=20, help="Max events to show")
    audit_failures.set_defaults(func=cmd_audit_failures)

    audit_search = audit_sub.add_parser("search", help="Search audit events")
    audit_search.add_argument("--event", "-e", help="Event type (e.g., vm.create)")
    audit_search.add_argument("--since", "-s", help="Time range (e.g., '1 hour ago', '7 days')")
    audit_search.add_argument("--user-filter", help="Filter by user")
    audit_search.add_argument("--target", help="Filter by target name")
    audit_search.add_argument("--limit", "-n", type=int, default=100, help="Max events to show")
    audit_search.set_defaults(func=cmd_audit_search)

    audit_export = audit_sub.add_parser("export", help="Export audit events to file")
    audit_export.add_argument("--format", "-f", choices=["json", "csv"], default="json", help="Output format")
    audit_export.add_argument("--output", "-o", help="Output file (stdout if not specified)")
    audit_export.add_argument("--limit", "-n", type=int, default=10000, help="Max events to export")
    audit_export.set_defaults(func=cmd_audit_export)

    # === Compose/Orchestration Commands ===
    compose_parser = subparsers.add_parser("compose", help="Multi-VM orchestration")
    compose_sub = compose_parser.add_subparsers(dest="compose_command", help="Compose commands")

    compose_up = compose_sub.add_parser("up", help="Start VMs from compose file")
    compose_up.add_argument("-f", "--file", default="clonebox-compose.yaml", help="Compose file")
    compose_up.add_argument("-u", "--user", action="store_true", help="Use user session")
    compose_up.add_argument("services", nargs="*", help="Specific services to start")
    compose_up.set_defaults(func=cmd_compose_up)

    compose_down = compose_sub.add_parser("down", help="Stop VMs from compose file")
    compose_down.add_argument("-f", "--file", default="clonebox-compose.yaml", help="Compose file")
    compose_down.add_argument("-u", "--user", action="store_true", help="Use user session")
    compose_down.add_argument("--force", action="store_true", help="Force stop")
    compose_down.add_argument("services", nargs="*", help="Specific services to stop")
    compose_down.set_defaults(func=cmd_compose_down)

    compose_status = compose_sub.add_parser("status", aliases=["ps"], help="Show compose status")
    compose_status.add_argument("-f", "--file", default="clonebox-compose.yaml", help="Compose file")
    compose_status.add_argument("-u", "--user", action="store_true", help="Use user session")
    compose_status.add_argument("--json", action="store_true", help="Output as JSON")
    compose_status.set_defaults(func=cmd_compose_status)

    compose_logs = compose_sub.add_parser("logs", help="Show aggregated logs from VMs")
    compose_logs.add_argument("-f", "--file", default="clonebox-compose.yaml", help="Compose file")
    compose_logs.add_argument("-u", "--user", action="store_true", help="Use user session")
    compose_logs.add_argument("--follow", action="store_true", help="Follow log output")
    compose_logs.add_argument("--lines", "-n", type=int, default=50, help="Number of lines to show")
    compose_logs.add_argument("service", nargs="?", help="Specific service to show logs for")
    compose_logs.set_defaults(func=cmd_compose_logs)

    # === Plugin Commands ===
    plugin_parser = subparsers.add_parser("plugin", help="Manage plugins")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command", help="Plugin commands")

    plugin_list = plugin_sub.add_parser("list", aliases=["ls"], help="List plugins")
    plugin_list.set_defaults(func=cmd_plugin_list)

    plugin_enable = plugin_sub.add_parser("enable", help="Enable a plugin")
    plugin_enable.add_argument("name", help="Plugin name")
    plugin_enable.set_defaults(func=cmd_plugin_enable)

    plugin_disable = plugin_sub.add_parser("disable", help="Disable a plugin")
    plugin_disable.add_argument("name", help="Plugin name")
    plugin_disable.set_defaults(func=cmd_plugin_disable)

    plugin_discover = plugin_sub.add_parser("discover", help="Discover available plugins")
    plugin_discover.set_defaults(func=cmd_plugin_discover)

    plugin_install = plugin_sub.add_parser("install", help="Install a plugin")
    plugin_install.add_argument("source", help="Plugin source (PyPI package, git URL, or local path)")
    plugin_install.set_defaults(func=cmd_plugin_install)

    plugin_uninstall = plugin_sub.add_parser("uninstall", aliases=["remove"], help="Uninstall a plugin")
    plugin_uninstall.add_argument("name", help="Plugin name")
    plugin_uninstall.set_defaults(func=cmd_plugin_uninstall)

    policy_parser = subparsers.add_parser("policy", help="Manage security policies")
    policy_parser.set_defaults(func=lambda args, p=policy_parser: p.print_help())
    policy_sub = policy_parser.add_subparsers(dest="policy_command", help="Policy commands")

    policy_validate = policy_sub.add_parser("validate", help="Validate policy file")
    policy_validate.add_argument(
        "--file",
        "-f",
        help="Policy file (default: auto-detect .clonebox-policy.yaml/.yml or ~/.clonebox.d/policy.yaml)",
    )
    policy_validate.set_defaults(func=cmd_policy_validate)

    policy_apply = policy_sub.add_parser("apply", help="Apply policy file")
    policy_apply.add_argument("--file", "-f", required=True, help="Policy file to apply")
    policy_apply.add_argument(
        "--scope",
        choices=["project", "global"],
        default="project",
        help="Apply scope: project writes .clonebox-policy.yaml in CWD, global writes ~/.clonebox.d/policy.yaml",
    )
    policy_apply.set_defaults(func=cmd_policy_apply)

    # === Remote Management Commands ===
    remote_parser = subparsers.add_parser("remote", help="Manage VMs on remote hosts")
    remote_sub = remote_parser.add_subparsers(dest="remote_command", help="Remote commands")

    remote_list = remote_sub.add_parser("list", aliases=["ls"], help="List VMs on remote host")
    remote_list.add_argument("host", help="Remote host (user@hostname)")
    remote_list.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_list.set_defaults(func=cmd_remote_list)

    remote_status = remote_sub.add_parser("status", help="Get VM status on remote host")
    remote_status.add_argument("host", help="Remote host (user@hostname)")
    remote_status.add_argument("vm_name", help="VM name")
    remote_status.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_status.add_argument("--json", action="store_true", help="Output as JSON")
    remote_status.set_defaults(func=cmd_remote_status)

    remote_start = remote_sub.add_parser("start", help="Start VM on remote host")
    remote_start.add_argument("host", help="Remote host (user@hostname)")
    remote_start.add_argument("vm_name", help="VM name")
    remote_start.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_start.set_defaults(func=cmd_remote_start)

    remote_stop = remote_sub.add_parser("stop", help="Stop VM on remote host")
    remote_stop.add_argument("host", help="Remote host (user@hostname)")
    remote_stop.add_argument("vm_name", help="VM name")
    remote_stop.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_stop.add_argument("-f", "--force", action="store_true", help="Force stop")
    remote_stop.set_defaults(func=cmd_remote_stop)

    remote_delete = remote_sub.add_parser("delete", aliases=["rm"], help="Delete VM on remote host")
    remote_delete.add_argument("host", help="Remote host (user@hostname)")
    remote_delete.add_argument("vm_name", help="VM name")
    remote_delete.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_delete.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    remote_delete.add_argument("--keep-storage", action="store_true", help="Keep disk images")
    remote_delete.add_argument(
        "--approve",
        action="store_true",
        help="Approve policy-gated operation",
    )
    remote_delete.set_defaults(func=cmd_remote_delete)

    remote_exec = remote_sub.add_parser("exec", help="Execute command in VM on remote host")
    remote_exec.add_argument("host", help="Remote host (user@hostname)")
    remote_exec.add_argument("vm_name", help="VM name")
    remote_exec.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute")
    remote_exec.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_exec.add_argument("-t", "--timeout", type=int, default=30, help="Command timeout")
    remote_exec.set_defaults(func=cmd_remote_exec)

    remote_health = remote_sub.add_parser("health", help="Run health check on remote VM")
    remote_health.add_argument("host", help="Remote host (user@hostname)")
    remote_health.add_argument("vm_name", help="VM name")
    remote_health.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_health.set_defaults(func=cmd_remote_health)

    args = parser.parse_args()

    if hasattr(args, "func"):
        try:
            args.func(args)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
            sys.exit(1)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
