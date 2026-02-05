#!/usr/bin/env python3
"""
Browser profile detection and copying for CloneBox.
Handles copying browser profiles from host to VM.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Browser profile paths on Linux (host)
BROWSER_PROFILE_PATHS = {
    "chrome": {
        "config": Path.home() / ".config" / "google-chrome",
        "cache": Path.home() / ".cache" / "google-chrome",
    },
    "chromium": {
        "config": Path.home() / ".config" / "chromium",
        "cache": Path.home() / ".cache" / "chromium",
    },
    "firefox": {
        "config": Path.home() / ".mozilla" / "firefox",
        "cache": Path.home() / ".cache" / "mozilla",
    },
    "edge": {
        "config": Path.home() / ".config" / "microsoft-edge",
        "cache": Path.home() / ".cache" / "microsoft-edge",
    },
    "brave": {
        "config": Path.home() / ".config" / "BraveSoftware",
        "cache": Path.home() / ".cache" / "BraveSoftware",
    },
    "opera": {
        "config": Path.home() / ".config" / "opera",
        "cache": Path.home() / ".cache" / "opera",
    },
}

# Destination paths in VM (guest)
VM_BROWSER_PROFILE_PATHS = {
    "chrome": "/home/ubuntu/.config/google-chrome",
    "chromium": "/home/ubuntu/.config/chromium",
    "firefox": "/home/ubuntu/.mozilla/firefox",
    "edge": "/home/ubuntu/.config/microsoft-edge",
    "brave": "/home/ubuntu/.config/BraveSoftware",
    "opera": "/home/ubuntu/.config/opera",
}


def detect_browser_profiles() -> Dict[str, Dict[str, Path]]:
    """Detect available browser profiles on the host system.
    
    Returns:
        Dictionary mapping browser names to their config and cache paths.
    """
    detected = {}
    for browser, paths in BROWSER_PROFILE_PATHS.items():
        existing_paths = {}
        for key, path in paths.items():
            if path.exists():
                existing_paths[key] = path
        if existing_paths:
            detected[browser] = existing_paths
    return detected


def get_profile_size(browser: str, paths: Dict[str, Path]) -> Tuple[int, str]:
    """Get total size of browser profile.
    
    Args:
        browser: Browser name
        paths: Dictionary of path_type -> Path
        
    Returns:
        Tuple of (size_in_bytes, human_readable_size)
    """
    total_size = 0
    for path in paths.values():
        if path.exists():
            try:
                result = subprocess.run(
                    ["du", "-sb", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    size = int(result.stdout.split()[0])
                    total_size += size
            except (subprocess.TimeoutExpired, ValueError):
                pass
    
    # Convert to human readable
    if total_size < 1024:
        human_size = f"{total_size} B"
    elif total_size < 1024 * 1024:
        human_size = f"{total_size / 1024:.1f} KB"
    elif total_size < 1024 * 1024 * 1024:
        human_size = f"{total_size / (1024 * 1024):.1f} MB"
    else:
        human_size = f"{total_size / (1024 * 1024 * 1024):.1f} GB"
    
    return total_size, human_size


def copy_browser_profile(
    browser: str,
    vm_dir: Path,
    progress_callback: Optional[callable] = None,
) -> Optional[Path]:
    """Copy browser profile from host to VM staging directory.
    
    Args:
        browser: Browser name to copy
        vm_dir: VM directory where profiles should be staged
        progress_callback: Optional callback(current, total, message)
        
    Returns:
        Path to staged profile directory, or None if browser not found
    """
    if browser not in BROWSER_PROFILE_PATHS:
        return None
    
    paths = BROWSER_PROFILE_PATHS[browser]
    
    # Check if profile exists
    if not paths["config"].exists():
        return None
    
    # Create staging directory
    profile_stage_dir = vm_dir / "browser_profiles" / browser
    profile_stage_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy config directory
    config_dest = profile_stage_dir / "config"
    if paths["config"].exists():
        if progress_callback:
            progress_callback(0, 2, f"Copying {browser} config...")
        try:
            shutil.copytree(paths["config"], config_dest, dirs_exist_ok=True)
        except Exception as e:
            print(f"Warning: Failed to copy {browser} config: {e}")
    
    # Copy cache directory (optional, can be large)
    cache_dest = profile_stage_dir / "cache"
    if paths["cache"].exists():
        if progress_callback:
            progress_callback(1, 2, f"Copying {browser} cache...")
        try:
            shutil.copytree(paths["cache"], cache_dest, dirs_exist_ok=True)
        except Exception as e:
            print(f"Warning: Failed to copy {browser} cache: {e}")
    
    if progress_callback:
        progress_callback(2, 2, f"{browser} profile copied")
    
    return profile_stage_dir


def stage_browser_profiles(
    requested_browsers: List[str],
    vm_dir: Path,
    skip_cache: bool = False,
) -> Dict[str, Path]:
    """Stage browser profiles for copying to VM.
    
    Args:
        requested_browsers: List of browser names to copy (or ['all'] for all detected)
        vm_dir: VM directory for staging
        skip_cache: If True, skip copying cache directories (saves space)
        
    Returns:
        Dictionary of {browser_name: staged_path}
    """
    staged = {}
    
    # Detect available browsers
    detected = detect_browser_profiles()
    
    if "all" in requested_browsers:
        browsers_to_copy = list(detected.keys())
    else:
        browsers_to_copy = [b for b in requested_browsers if b in detected]
    
    for browser in browsers_to_copy:
        if browser not in detected:
            print(f"Browser profile '{browser}' not found on host, skipping")
            continue
        
        # Get profile size
        size_bytes, size_human = get_profile_size(browser, detected[browser])
        print(f"Copying {browser} profile ({size_human})...")
        
        # Copy to staging
        staged_path = copy_browser_profile(browser, vm_dir)
        if staged_path:
            staged[browser] = staged_path
    
    return staged


def generate_browser_profile_setup_script(
    staged_profiles: Dict[str, Path],
    vm_username: str = "ubuntu",
) -> str:
    """Generate cloud-init script to setup browser profiles in VM.
    
    Args:
        staged_profiles: Dictionary of {browser_name: staged_path}
        vm_username: VM username for ownership
        
    Returns:
        Shell script content for runcmd
    """
    script_lines = [
        "echo '[clonebox] Setting up browser profiles...' > /dev/ttyS0",
    ]
    
    for browser, staged_path in staged_profiles.items():
        if browser not in VM_BROWSER_PROFILE_PATHS:
            continue
        
        dest_path = VM_BROWSER_PROFILE_PATHS[browser]
        
        # Create destination directory and set ownership
        script_lines.extend([
            f"mkdir -p {dest_path}",
            f"chown -R {vm_username}:{vm_username} {dest_path}",
        ])
        
        # Copy from cloud-init mounted location (if using ISO)
        # or from SSH-copied location
        script_lines.extend([
            f"if [ -d /mnt/clonebox-profiles/{browser} ]; then",
            f"  echo '[clonebox] Copying {browser} profile from ISO...' > /dev/ttyS0",
            f"  cp -r /mnt/clonebox-profiles/{browser}/config/* {dest_path}/ 2>/dev/null || true",
            f"  chown -R {vm_username}:{vm_username} {dest_path}",
            "fi",
        ])
    
    script_lines.append(
        "echo '[clonebox] Browser profiles setup complete' > /dev/ttyS0"
    )
    
    return "\n".join(script_lines)


def copy_profiles_to_vm_via_ssh(
    staged_profiles: Dict[str, Path],
    ssh_port: int,
    ssh_key: Path,
    vm_username: str = "ubuntu",
) -> bool:
    """Copy staged browser profiles to running VM via SSH.
    
    Args:
        staged_profiles: Dictionary of {browser_name: staged_path}
        ssh_port: SSH port for VM
        ssh_key: Path to SSH key
        vm_username: VM username
        
    Returns:
        True if all profiles copied successfully
    """
    import subprocess
    
    all_success = True
    
    for browser, staged_path in staged_profiles.items():
        if browser not in VM_BROWSER_PROFILE_PATHS:
            continue
        
        dest_path = VM_BROWSER_PROFILE_PATHS[browser]
        
        # Create destination directory
        mkdir_result = subprocess.run(
            [
                "ssh", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
                "-p", str(ssh_port), "-i", str(ssh_key),
                f"{vm_username}@127.0.0.1",
                f"mkdir -p {dest_path}"
            ],
            capture_output=True,
        )
        
        if mkdir_result.returncode != 0:
            print(f"Failed to create {browser} directory in VM")
            all_success = False
            continue
        
        # Copy profile using scp
        config_src = staged_path / "config"
        if config_src.exists():
            scp_result = subprocess.run(
                [
                    "scp", "-r", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
                    "-P", str(ssh_port), "-i", str(ssh_key),
                    f"{config_src}/*",
                    f"{vm_username}@127.0.0.1:{dest_path}/"
                ],
                capture_output=True,
            )
            
            if scp_result.returncode == 0:
                print(f"✓ {browser} profile copied to VM")
            else:
                print(f"✗ Failed to copy {browser} profile")
                all_success = False
    
    return all_success
