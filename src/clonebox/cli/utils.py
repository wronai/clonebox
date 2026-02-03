#!/usr/bin/env python3
"""
Shared utilities for CloneBox CLI.
"""

import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import questionary
import yaml
from questionary import Style
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from clonebox import __version__
from clonebox.cloner import SelectiveVMCloner
from clonebox.models import VMConfig
from clonebox.profiles import merge_with_profile

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
CLONEBOX_CONFIG_FILE = ".clonebox.yaml"


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
    """Check if QEMU Guest Agent is responding."""
    import subprocess
    
    try:
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "qemu-agent-command", vm_name, '{"execute": "guest-ping"}'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except:
        return False


def _qga_exec(vm_name: str, conn_uri: str, command: str, timeout: int = 10) -> Optional[str]:
    """Execute command in VM via QEMU Guest Agent."""
    import subprocess
    import json
    
    try:
        cmd = json.dumps({"execute": "guest-exec", "arguments": {
            "path": "/bin/sh",
            "arg": ["-c", command],
            "capture-output": True
        }})
        
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "qemu-agent-command", vm_name, cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        if result.returncode != 0:
            return None
            
        response = json.loads(result.stdout)
        pid = response.get("return", {}).get("pid")
        if not pid:
            return None
            
        # Wait for command to complete
        time.sleep(0.5)
        cmd = json.dumps({"execute": "guest-exec-status", "arguments": {"pid": pid}})
        
        result = subprocess.run(
            ["virsh", "--connect", conn_uri, "qemu-agent-command", vm_name, cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        if result.returncode != 0:
            return None
            
        response = json.loads(result.stdout)
        if response.get("return", {}).get("exited"):
            output = response["return"].get("out-data", "")
            if output:
                import base64
                return base64.b64decode(output).decode("utf-8", errors="ignore")
                
    except:
        pass
        
    return None


def load_env_file(env_path: Path) -> dict:
    """Load environment variables from .env file."""
    env_vars = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env_vars[key] = value
    return env_vars


def expand_env_vars(value, env_vars: dict):
    """Expand environment variables in a value."""
    if isinstance(value, str):
        # Find all ${VAR} or $VAR patterns
        placeholders = re.findall(r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)', value)
        
        for full_match, var_name in placeholders:
            var_name = var_name or full_match
            if var_name in env_vars:
                value = value.replace(f"${{{full_match}}}" if full_match else f"${var_name}", env_vars[var_name])
        
    return value


def _find_unexpanded_env_placeholders(value) -> set:
    """Find environment variable placeholders that weren't expanded."""
    placeholders = set()
    if isinstance(value, str):
        matches = re.findall(r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)', value)
        for full_match, var_name in matches:
            placeholders.add(var_name or full_match)
    return placeholders


def deduplicate_list(items: list, key=None) -> list:
    """Deduplicate a list, optionally by a key."""
    seen = set()
    result = []
    
    for item in items:
        if key:
            identifier = key(item)
        else:
            identifier = item
            
        if identifier not in seen:
            seen.add(identifier)
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
    from datetime import datetime
    from pathlib import Path
    
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


def load_clonebox_config(path: Path) -> dict:
    """Load and validate CloneBox configuration."""
    config_file = path / CLONEBOX_CONFIG_FILE if path.is_dir() else path

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    # Load .env file from same directory
    config_dir = config_file.parent
    env_file = config_dir / ".clonebox.env"
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
    """Execute command in VM via QEMU Guest Agent with retry logic."""
    max_retries = 30
    for i in range(max_retries):
        if _qga_ping(vm_name, conn_uri):
            return _qga_exec(vm_name, conn_uri, command)
        time.sleep(2)
    return None


def monitor_cloud_init_status(vm_name: str, user_session: bool = False, timeout: int = 1800):
    """Monitor cloud-init status in the VM."""
    conn_uri = "qemu:///session" if user_session else "qemu:///system"
    start_time = time.time()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Waiting for cloud-init to complete...", total=None)
        
        while time.time() - start_time < timeout:
            status = _qga_exec(vm_name, conn_uri, "cloud-init status", timeout=5)
            
            if status:
                if "status: done" in status.lower():
                    progress.update(task, description="✅ cloud-init completed successfully")
                    return True
                elif "error" in status.lower():
                    progress.update(task, description="❌ cloud-init failed")
                    console.print(f"\n[red]cloud-init error:[/]\n{status}")
                    return False
            
            progress.update(task, description=f"Waiting for cloud-init... ({int(time.time() - start_time)}s)")
            time.sleep(5)
    
    progress.update(task, description="⏱️ Timeout waiting for cloud-init")
    console.print(f"\n[yellow]cloud-init did not complete within {timeout} seconds[/]")
    return False


def create_vm_from_config(config, start=False, user_session=False, replace=False, approved=False):
    """Create VM from configuration dictionary."""
    vm_config = VMConfig(
        name=config["vm"]["name"],
        ram_mb=config["vm"]["ram_mb"],
        vcpus=config["vm"]["vcpus"],
        disk_size_gb=config["vm"]["disk_size_gb"],
        gui=config["vm"]["gui"],
        base_image=config["vm"].get("base_image"),
        network_mode=config["vm"].get("network_mode", "auto"),
        username=config["vm"].get("username", "ubuntu"),
        password=config["vm"].get("password", "ubuntu"),
        paths=config.get("paths", {}),
        packages=config.get("packages", []),
        snap_packages=config.get("snap_packages", []),
        services=config.get("services", []),
        post_commands=config.get("post_commands", []),
        copy_paths=config.get("copy_paths", {}),
        user_session=user_session,
        web_services=config.get("web_services", []),
        resources=config.get("resources", {}),
        auth_method=config["vm"].get("auth_method", "ssh_key"),
        shutdown_after_setup=config.get("shutdown_after_setup", False),
    )
    
    cloner = SelectiveVMCloner(user_session=user_session)
    vm_uuid = cloner.create_vm(vm_config, replace=replace, approved=approved, console=console)
    
    if start:
        cloner.start_vm(vm_config.name, console=console)
        
        # Monitor cloud-init if it's a fresh VM
        if not replace:
            monitor_cloud_init_status(vm_config.name, user_session)
    
    return vm_uuid
