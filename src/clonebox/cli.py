#!/usr/bin/env python3
"""
CloneBox CLI - Interactive command-line interface for creating VMs.
"""

import argparse
import json
import os
import re
import sys
import time
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
        return result.returncode == 0
    except Exception:
        return False


def _qga_exec(vm_name: str, conn_uri: str, command: str, timeout: int = 10) -> Optional[str]:
    import subprocess
    import base64
    import time

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
            if verbose and domifaddr.stderr.strip():
                console.print(f"[dim]{domifaddr.stderr.strip()}[/]")
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
            "[yellow]⏳ Cloud-init status: Unknown (QEMU guest agent not connected yet)[/]"
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
        console.print("[dim]Health status: Not available yet (QEMU guest agent not ready)[/]")
    else:
        health_status = _qga_exec(
            vm_name, conn_uri, "cat /var/log/clonebox-health-status 2>/dev/null || true", timeout=10
        )
        result["health"]["raw"] = health_status
        if health_status and "HEALTH_STATUS=OK" in health_status:
            result["health"]["status"] = "ok"
            console.print("[green]✅ Health: All checks passed[/]")
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
        cloner = SelectiveVMCloner(user_session=user_session)

        # Check prerequisites
        checks = cloner.check_prerequisites()
        if not all(checks.values()):
            console.print("[yellow]⚠️  Prerequisites check:[/]")
            for check, passed in checks.items():
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
        config_file = target_path / ".clonebox.yaml" if target_path.is_dir() else target_path
        if config_file.exists():
            config = load_clonebox_config(config_file)
            name = config["vm"]["name"]
        else:
            console.print(f"[red]❌ Config not found: {config_file}[/]")
            return

    if not args.yes:
        if not questionary.confirm(
            f"Delete VM '{name}' and its storage?", default=False, style=custom_style
        ).ask():
            console.print("[yellow]Cancelled.[/]")
            return


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
        config_file = target_path / ".clonebox.yaml" if target_path.is_dir() else target_path
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
    console.print("[bold]2. VM State Check[/]")
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
                    try:
                        from .cli import _qga_ping, _qga_exec
                    except ImportError:
                        from clonebox.cli import _qga_ping, _qga_exec
                    if _qga_ping(vm_name, conn_uri):
                        try:
                            ip_out = _qga_exec(
                                vm_name,
                                conn_uri,
                                "ip -4 -o addr show scope global | awk '{print $4}'",
                                timeout=5,
                            )
                            if ip_out and ip_out.strip():
                                console.print(
                                    f"[green]✅ VM has network access (IP via QGA: {ip_out.strip()})[/]"
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
    if not quick and state == "running":
        console.print("[bold]3. Cloud-init Status[/]")
        try:
            # Try to get cloud-init status via QEMU guest agent
            result = subprocess.run(
                [
                    "virsh",
                    "--connect",
                    conn_uri,
                    "qemu-agent-command",
                    vm_name,
                    '{"execute":"guest-exec","arguments":{"path":"cloud-init","arg":["status"],"capture-output":true}}',
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                try:
                    response = json.loads(result.stdout)
                    if "return" in response:
                        pid = response["return"]["pid"]
                        # Get output
                        result2 = subprocess.run(
                            [
                                "virsh",
                                "--connect",
                                conn_uri,
                                "qemu-agent-command",
                                vm_name,
                                f'{{"execute":"guest-exec-status","arguments":{"pid":{pid}}}}',
                            ],
                            capture_output=True,
                            text=True,
                            timeout=15,
                        )
                        if result2.returncode == 0:
                            resp2 = json.loads(result2.stdout)
                            if "return" in resp2 and resp2["return"]["exited"]:
                                output = resp2["return"]["out-data"]
                                if output:
                                    import base64

                                    status = base64.b64decode(output).decode()
                                    if "done" in status.lower():
                                        console.print("[green]✅ Cloud-init completed[/]")
                                    elif "running" in status.lower():
                                        console.print("[yellow]⚠️  Cloud-init still running[/]")
                                    else:
                                        console.print(
                                            f"[yellow]⚠️  Cloud-init status: {status.strip()}[/]"
                                        )
                except:
                    pass
        except:
            console.print(
                "[yellow]⚠️  Could not check cloud-init (QEMU agent may not be running)[/]"
            )

    console.print()

    # Test 4: Check mounts (if running)
    if not quick and state == "running":
        console.print("[bold]4. Mount Points Check[/]")
        all_paths = config.get("paths", {}).copy()
        all_paths.update(config.get("app_data_paths", {}))

        if all_paths:
            for idx, (host_path, guest_path) in enumerate(all_paths.items()):
                try:
                    # Use the same QGA helper as diagnose/status
                    is_accessible = _qga_exec(
                        vm_name, conn_uri, f"test -d {guest_path} && echo yes || echo no", timeout=5
                    )
                    if is_accessible == "yes":
                        console.print(f"[green]✅ {guest_path}[/]")
                    else:
                        console.print(f"[red]❌ {guest_path} (not accessible)[/]")
                except Exception:
                    console.print(f"[yellow]⚠️  {guest_path} (could not check)[/]")
        else:
            console.print("[dim]No mount points configured[/]")

    console.print()

    # Test 5: Run health check (if running and not quick)
    if not quick and state == "running":
        console.print("[bold]5. Health Check[/]")
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
            if result.returncode == 0:
                console.print("[green]✅ Health check triggered[/]")
                console.print("   View results in VM: cat /var/log/clonebox-health.log")
            else:
                console.print("[yellow]⚠️  Health check script not found[/]")
                console.print("   VM may not have been created with health checks")
        except Exception as e:
            console.print(f"[yellow]⚠️  Could not run health check: {e}[/]")

    console.print()

    # Run full validation if requested
    if validate_all and state == "running":
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
                env_vars[key.strip()] = value.strip()

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
            paths_by_type[p.type].append(p.path)

    if deduplicate:
        for ptype in paths_by_type:
            paths_by_type[ptype] = deduplicate_list(paths_by_type[ptype])

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
    for host_path in paths_by_type["project"][:5]:  # Limit projects
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
    ram_mb = min(4096, int(sys_info["memory_available_gb"] * 1024 * 0.5))
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

    if chrome_profile.exists() and "google-chrome" not in [d.get("app", "") for d in app_data_dirs]:
        if "chromium" not in all_snap_packages:
            all_snap_packages.append("chromium")

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
                "projects": list(paths_by_type["project"]),
                "configs": list(paths_by_type["config"][:5]),
                "data": list(paths_by_type["data"][:5]),
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

    return config


def monitor_cloud_init_status(vm_name: str, user_session: bool = False, timeout: int = 900):
    """Monitor cloud-init status in VM and show progress."""
    import subprocess
    import time

    conn_uri = "qemu:///session" if user_session else "qemu:///system"
    start_time = time.time()
    shutdown_count = 0  # Count consecutive shutdown detections
    restart_detected = False

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Starting VM and initializing...", total=None)

        while time.time() - start_time < timeout:
            try:
                elapsed = int(time.time() - start_time)
                minutes = elapsed // 60
                seconds = elapsed % 60

                # Check VM state
                result = subprocess.run(
                    ["virsh", "--connect", conn_uri, "domstate", vm_name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                vm_state = result.stdout.strip().lower()

                if "shut off" in vm_state or "shutting down" in vm_state:
                    # VM is shutting down - count consecutive detections
                    shutdown_count += 1
                    if shutdown_count >= 3 and not restart_detected:
                        # Confirmed shutdown after 3 consecutive checks
                        restart_detected = True
                        progress.update(
                            task,
                            description="[yellow]⟳ VM restarting after package installation...",
                        )
                    time.sleep(3)
                    continue
                else:
                    # VM is running - reset shutdown counter
                    if shutdown_count > 0 and shutdown_count < 3:
                        # Was a brief glitch, not a real shutdown
                        shutdown_count = 0

                if restart_detected and "running" in vm_state and shutdown_count >= 3:
                    # VM restarted successfully - GUI should be ready
                    progress.update(
                        task, description=f"[green]✓ GUI ready! Total time: {minutes}m {seconds}s"
                    )
                    time.sleep(2)
                    break

                # Estimate remaining time (total ~12-15 minutes for full desktop install)
                if elapsed < 60:
                    remaining = "~12-15 minutes"
                elif elapsed < 300:
                    remaining = f"~{12 - minutes} minutes"
                elif elapsed < 600:
                    remaining = f"~{10 - minutes} minutes"
                elif elapsed < 800:
                    remaining = "finishing soon..."
                else:
                    remaining = "almost done"

                if restart_detected:
                    progress.update(
                        task,
                        description=f"[cyan]Starting GUI... ({minutes}m {seconds}s, {remaining})",
                    )
                else:
                    progress.update(
                        task,
                        description=f"[cyan]Installing desktop packages... ({minutes}m {seconds}s, {remaining})",
                    )

            except (subprocess.TimeoutExpired, Exception) as e:
                elapsed = int(time.time() - start_time)
                minutes = elapsed // 60
                seconds = elapsed % 60
                progress.update(
                    task, description=f"[cyan]Configuring VM... ({minutes}m {seconds}s)"
                )

            time.sleep(3)

        # Final status
        if time.time() - start_time >= timeout:
            progress.update(
                task, description="[yellow]⚠ Monitoring timeout - VM continues in background"
            )


def create_vm_from_config(
    config: dict,
    start: bool = False,
    user_session: bool = False,
    replace: bool = False,
) -> str:
    """Create VM from YAML config dict."""
    # Merge paths and app_data_paths
    all_paths = config.get("paths", {}).copy()
    all_paths.update(config.get("app_data_paths", {}))

    vm_config = VMConfig(
        name=config["vm"]["name"],
        ram_mb=config["vm"].get("ram_mb", 4096),
        vcpus=config["vm"].get("vcpus", 4),
        disk_size_gb=config["vm"].get("disk_size_gb", 10),
        gui=config["vm"].get("gui", True),
        base_image=config["vm"].get("base_image"),
        paths=all_paths,
        packages=config.get("packages", []),
        snap_packages=config.get("snap_packages", []),
        services=config.get("services", []),
        post_commands=config.get("post_commands", []),
        user_session=user_session,
        network_mode=config["vm"].get("network_mode", "auto"),
        username=config["vm"].get("username", "ubuntu"),
        password=config["vm"].get("password", "ubuntu"),
    )

    cloner = SelectiveVMCloner(user_session=user_session)

    # Check prerequisites and show detailed info
    checks = cloner.check_prerequisites()

    if not checks["images_dir_writable"]:
        console.print(f"[yellow]⚠️  Storage directory: {checks['images_dir']}[/]")
        if "images_dir_error" in checks:
            console.print(f"[red]{checks['images_dir_error']}[/]")
            raise PermissionError(checks["images_dir_error"])

    console.print(f"[dim]Session: {checks['session_type']}, Storage: {checks['images_dir']}[/]")

    vm_uuid = cloner.create_vm(vm_config, console=console, replace=replace)

    if start:
        cloner.start_vm(vm_config.name, open_viewer=vm_config.gui, console=console)

        # Monitor cloud-init progress if GUI is enabled
        if vm_config.gui:
            console.print("\n[bold cyan]📊 Monitoring setup progress...[/]")
            try:
                monitor_cloud_init_status(vm_config.name, user_session=user_session)
            except KeyboardInterrupt:
                console.print("\n[yellow]Monitoring stopped. VM continues setup in background.[/]")
            except Exception as e:
                console.print(
                    f"\n[dim]Note: Could not monitor status ({e}). VM continues setup in background.[/]"
                )

    return vm_uuid


def cmd_clone(args):
    """Generate clone config from path and optionally create VM."""
    target_path = Path(args.path).resolve()
    dry_run = getattr(args, "dry_run", False)

    if not target_path.exists():
        console.print(f"[red]❌ Path does not exist: {target_path}[/]")
        return

    if dry_run:
        console.print(f"[bold cyan]🔍 DRY RUN - Analyzing: {target_path}[/]\n")
    else:
        console.print(f"[bold cyan]📦 Generating clone config for: {target_path}[/]\n")

    # Detect system state
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Scanning system...", total=None)
        detector = SystemDetector()
        snapshot = detector.detect_all()

    # Generate config
    vm_name = args.name or f"clone-{target_path.name}"
    yaml_content = generate_clonebox_yaml(
        snapshot,
        detector,
        deduplicate=args.dedupe,
        target_path=str(target_path),
        vm_name=vm_name,
        network_mode=args.network,
        base_image=getattr(args, "base_image", None),
        disk_size_gb=getattr(args, "disk_size_gb", None),
    )

    profile_name = getattr(args, "profile", None)
    if profile_name:
        merged_config = merge_with_profile(yaml.safe_load(yaml_content), profile_name)
        if isinstance(merged_config, dict):
            vm_section = merged_config.get("vm")
            if isinstance(vm_section, dict):
                vm_packages = vm_section.pop("packages", None)
                if isinstance(vm_packages, list):
                    packages = merged_config.get("packages")
                    if not isinstance(packages, list):
                        packages = []
                    for p in vm_packages:
                        if p not in packages:
                            packages.append(p)
                    merged_config["packages"] = packages

            if "container" in merged_config:
                merged_config.pop("container", None)

            yaml_content = yaml.dump(
                merged_config,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    # Dry run - show what would be created and exit
    if dry_run:
        config = yaml.safe_load(yaml_content)
        console.print(
            Panel(
                f"[bold]VM Name:[/] {config['vm']['name']}\n"
                f"[bold]RAM:[/] {config['vm'].get('ram_mb', 4096)} MB\n"
                f"[bold]vCPUs:[/] {config['vm'].get('vcpus', 4)}\n"
                f"[bold]Network:[/] {config['vm'].get('network_mode', 'auto')}\n"
                f"[bold]Paths:[/] {len(config.get('paths', {}))} mounts\n"
                f"[bold]Packages:[/] {len(config.get('packages', []))} packages\n"
                f"[bold]Services:[/] {len(config.get('services', []))} services",
                title="[bold cyan]Would create VM[/]",
                border_style="cyan",
            )
        )
        console.print("\n[dim]Config preview:[/]")
        console.print(Panel(yaml_content, title="[bold].clonebox.yaml[/]", border_style="dim"))
        console.print("\n[yellow]ℹ️  Dry run complete. No changes made.[/]")
        return

    # Save config file
    config_file = (
        target_path / CLONEBOX_CONFIG_FILE
        if target_path.is_dir()
        else target_path.parent / CLONEBOX_CONFIG_FILE
    )
    config_file.write_text(yaml_content)
    console.print(f"[green]✅ Config saved: {config_file}[/]\n")

    # Show config
    console.print(Panel(yaml_content, title="[bold].clonebox.yaml[/]", border_style="cyan"))

    # Open in editor if requested
    if args.edit:
        editor = os.environ.get("EDITOR", "nano")
        console.print(f"[cyan]Opening {editor}...[/]")
        os.system(f"{editor} {config_file}")
        # Reload after edit
        yaml_content = config_file.read_text()

    # Ask to create VM
    if args.run:
        create_now = True
    else:
        create_now = questionary.confirm(
            "Create VM with this config?", default=True, style=custom_style
        ).ask()

    if create_now:
        # Load config with environment variable expansion
        config = load_clonebox_config(config_file.parent)
        user_session = getattr(args, "user", False)

        console.print("\n[bold cyan]🔧 Creating VM...[/]\n")
        if user_session:
            console.print("[cyan]Using user session (qemu:///session) - no root required[/]")

        try:
            vm_uuid = create_vm_from_config(
                config,
                start=True,
                user_session=user_session,
                replace=getattr(args, "replace", False),
            )
            console.print(f"\n[bold green]🎉 VM '{config['vm']['name']}' is running![/]")
            console.print(f"[dim]UUID: {vm_uuid}[/]")

            # Show GUI startup info if GUI is enabled
            if config.get("vm", {}).get("gui", False):
                username = config["vm"].get("username", "ubuntu")
                password = config["vm"].get("password", "ubuntu")
                console.print("\n[bold yellow]⏰ GUI Setup Process:[/]")
                console.print("  [yellow]•[/] Installing desktop environment (~5-10 minutes)")
                console.print("  [yellow]•[/] Running health checks on all components")
                console.print("  [yellow]•[/] Automatic restart after installation")
                console.print("  [yellow]•[/] GUI login screen will appear")
                console.print(
                    f"  [yellow]•[/] Login: [cyan]{username}[/] / [cyan]{'*' * len(password)}[/] (from .env)"
                )
                console.print("\n[dim]💡 Progress will be monitored automatically below[/]")

            # Show health check info
            console.print("\n[bold]📊 Health Check (inside VM):[/]")
            console.print("  [cyan]cat /var/log/clonebox-health.log[/]  # View full report")
            console.print("  [cyan]cat /var/log/clonebox-health-status[/]  # Quick status")
            console.print("  [cyan]clonebox-health[/]  # Re-run health check")

            # Show mount instructions
            all_paths = config.get("paths", {}).copy()
            all_paths.update(config.get("app_data_paths", {}))
            if all_paths:
                console.print("\n[bold]📁 Mounted paths (automatic):[/]")
                for idx, (host, guest) in enumerate(list(all_paths.items())[:5]):
                    console.print(f"  [dim]{host}[/] → [cyan]{guest}[/]")
                if len(all_paths) > 5:
                    console.print(f"  [dim]... and {len(all_paths) - 5} more paths[/]")
        except PermissionError as e:
            console.print(f"[red]❌ Permission Error:[/]\n{e}")
            console.print("\n[yellow]💡 Try running with --user flag:[/]")
            console.print(f"  [cyan]clonebox clone {target_path} --user[/]")
        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/]")
    else:
        console.print("\n[dim]To create VM later, run:[/]")
        console.print(f"  [cyan]clonebox start {target_path}[/]")


def cmd_detect(args):
    """Detect and show system state."""
    console.print("[bold cyan]🔍 Detecting system state...[/]\n")

    detector = SystemDetector()
    snapshot = detector.detect_all()

    # JSON output
    if args.json:
        result = {
            "services": [{"name": s.name, "status": s.status} for s in snapshot.running_services],
            "applications": [
                {"name": a.name, "pid": a.pid, "cwd": a.working_dir} for a in snapshot.applications
            ],
            "paths": [
                {"path": p.path, "type": p.type, "size_mb": p.size_mb} for p in snapshot.paths
            ],
        }
        print(json.dumps(result, indent=2))
        return

    # YAML output
    if args.yaml:
        result = generate_clonebox_yaml(snapshot, detector, deduplicate=args.dedupe)

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(result)
            console.print(f"[green]✅ Config saved to: {output_path}[/]")
        else:
            print(result)
        return

    # Services
    services = detector.detect_services()
    running = [s for s in services if s.status == "running"]

    if running:
        table = Table(title="Running Services", border_style="green")
        table.add_column("Service")
        table.add_column("Status")
        table.add_column("Enabled")

        for svc in running:
            table.add_row(svc.name, f"[green]{svc.status}[/]", "✓" if svc.enabled else "")

        console.print(table)

    # Applications
    apps = detector.detect_applications()

    if apps:
        console.print()
        table = Table(title="Running Applications", border_style="blue")
        table.add_column("Name")
        table.add_column("PID")
        table.add_column("Memory")
        table.add_column("Working Dir")

        for app in apps[:15]:
            table.add_row(
                app.name,
                str(app.pid),
                f"{app.memory_mb:.0f} MB",
                app.working_dir[:40] if app.working_dir else "",
            )

        console.print(table)

    # Paths
    paths = detector.detect_paths()

    if paths:
        console.print()
        table = Table(title="Detected Paths", border_style="yellow")
        table.add_column("Type")
        table.add_column("Path")
        table.add_column("Size")

        for p in paths[:20]:
            table.add_row(
                f"[cyan]{p.type}[/]", p.path, f"{p.size_mb:.0f} MB" if p.size_mb > 0 else "-"
            )

        console.print(table)


def cmd_monitor(args) -> None:
    """Real-time resource monitoring for VMs and containers."""
    conn_uri = "qemu:///session" if getattr(args, "user", False) else "qemu:///system"
    refresh = getattr(args, "refresh", 2.0)
    once = getattr(args, "once", False)

    monitor = ResourceMonitor(conn_uri)

    try:
        while True:
            # Clear screen for live update
            if not once:
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
                    mem_pct = (vm.memory_used_mb / vm.memory_total_mb * 100) if vm.memory_total_mb > 0 else 0
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
                    mem_pct = (c.memory_used_mb / c.memory_limit_mb * 100) if c.memory_limit_mb > 0 else 0
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


def cmd_exec(args) -> None:
    """Execute command in VM via QEMU Guest Agent."""
    vm_name, config_file = _resolve_vm_name_and_config_file(args.name)
    conn_uri = "qemu:///session" if getattr(args, "user", False) else "qemu:///system"
    command = args.command
    timeout = getattr(args, "timeout", 30)

    if not _qga_ping(vm_name, conn_uri):
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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="clonebox", description="Clone your workstation environment to an isolated VM"
    )
    parser.add_argument("--version", action="version", version=f"clonebox {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Interactive mode (default)
    parser.set_defaults(func=lambda args: interactive_mode())

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

    # Export command - package VM for migration
    export_parser = subparsers.add_parser("export", help="Export VM and data for migration")
    export_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    export_parser.add_argument(
        "-u", "--user", action="store_true", help="Use user session (qemu:///session)"
    )
    export_parser.add_argument(
        "-o", "--output", help="Output archive filename (default: <vmname>-export.tar.gz)"
    )
    export_parser.add_argument(
        "--include-data",
        "-d",
        action="store_true",
        help="Include shared data (browser profiles, configs) in export",
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
    monitor_parser.add_argument(
        "--once", action="store_true", help="Show stats once and exit"
    )
    monitor_parser.set_defaults(func=cmd_monitor)

    # Exec command - execute command in VM
    exec_parser = subparsers.add_parser("exec", help="Execute command in VM via QEMU Guest Agent")
    exec_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    exec_parser.add_argument(
        "command", help="Command to execute in VM"
    )
    exec_parser.add_argument(
        "-u", "--user", action="store_true", help="Use user session (qemu:///session)"
    )
    exec_parser.add_argument(
        "--timeout", "-t", type=int, default=30, help="Command timeout in seconds (default: 30)"
    )
    exec_parser.set_defaults(func=cmd_exec)

    # === P2P Secure Transfer Commands ===

    # Keygen command - generate encryption key
    keygen_parser = subparsers.add_parser("keygen", help="Generate encryption key for secure transfers")
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
    export_enc_parser.add_argument(
        "-o", "--output", help="Output file (default: <vmname>.enc)"
    )
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
    import_enc_parser.add_argument(
        "--user-data", action="store_true", help="Import user data"
    )
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
    export_remote_parser.add_argument(
        "-o", "--output", required=True, help="Local output file"
    )
    export_remote_parser.add_argument(
        "--encrypted", "-e", action="store_true", help="Use encrypted export"
    )
    export_remote_parser.add_argument(
        "--user-data", action="store_true", help="Include user data"
    )
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
    import_remote_parser.add_argument(
        "--user-data", action="store_true", help="Import user data"
    )
    import_remote_parser.set_defaults(func=cmd_import_remote)

    # Sync-key command
    sync_key_parser = subparsers.add_parser(
        "sync-key", help="Sync encryption key to remote host"
    )
    sync_key_parser.add_argument("host", help="Remote host (user@hostname)")
    sync_key_parser.set_defaults(func=cmd_sync_key)

    # List-remote command
    list_remote_parser = subparsers.add_parser(
        "list-remote", help="List VMs on remote host"
    )
    list_remote_parser.add_argument("host", help="Remote host (user@hostname)")
    list_remote_parser.set_defaults(func=cmd_list_remote)

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
