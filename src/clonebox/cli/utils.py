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


def load_clonebox_config(path: Path) -> dict:
    """Load and validate CloneBox configuration."""
    with open(path) as f:
        config = yaml.safe_load(f)
    
    # Load environment variables
    env_file = path.parent / ".clonebox.env"
    env_vars = load_env_file(env_file)
    
    # Expand environment variables in the config
    def expand_recursive(obj):
        if isinstance(obj, dict):
            return {k: expand_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [expand_recursive(item) for item in obj]
        else:
            return expand_env_vars(obj, env_vars)
    
    config = expand_recursive(config)
    
    # Check for unexpanded placeholders
    unexpanded = _find_unexpanded_env_placeholders(config)
    if unexpanded:
        console.print(f"[yellow]⚠️  Warning: Undefined environment variables: {', '.join(sorted(unexpanded))}[/]")
    
    # Apply profile if specified
    if "profile" in config:
        config = merge_with_profile(config, config["profile"])
    
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
