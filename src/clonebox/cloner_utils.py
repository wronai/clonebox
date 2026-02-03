#!/usr/bin/env python3
"""
Utility functions for VM cloning operations.
"""

import subprocess
import time
import json
import os
from pathlib import Path


def log(msg):
    """Log a message with timestamp."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)


def get_running_processes():
    """Get list of running processes."""
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=10)
        return result.stdout
    except:
        return ""


def is_app_running(app_name, ps_output):
    """Check if an application is running."""
    patterns = {
        "pycharm-community": ["pycharm", "idea"],
        "chromium": ["chromium"],
        "firefox": ["firefox", "firefox-esr"],
        "google-chrome": ["chrome", "google-chrome"],
        "code": ["code", "vscode"],
    }
    for pattern in patterns.get(app_name, [app_name]):
        if pattern.lower() in ps_output.lower():
            return True
    return False


def restart_app(app_name):
    """Restart an application service."""
    log(f"Restarting {app_name}...")
    try:
        subprocess.run(
            ["sudo", "-u", "ubuntu", "systemctl", "--user", "restart", f"{app_name}.service"],
            timeout=30, capture_output=True
        )
        return True
    except Exception as e:
        log(f"Failed to restart {app_name}: {e}")
        return False


def check_mounts():
    """Check and mount filesystems if needed."""
    try:
        with open("/etc/fstab", "r") as f:
            fstab = f.read()
        for line in fstab.split("\n"):
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("mount"):
                mp = parts[1]
                result = subprocess.run(["mountpoint", "-q", mp], capture_output=True)
                if result.returncode != 0:
                    log(f"Mount {mp} not active, attempting remount...")
                    subprocess.run(["mount", mp], capture_output=True)
    except Exception as e:
        log(f"Mount check failed: {e}")


def write_status(status):
    """Write status to file."""
    try:
        with open("/var/run/clonebox-monitor-status.json", "w") as f:
            json.dump(status, f)
    except:
        pass


def main():
    """Main monitor service function."""
    log("CloneBox Monitor started")
    
    REQUIRED_APPS = []  # This should be configured based on VM config
    CHECK_INTERVAL = 60  # seconds
    LOG_FILE = "/var/log/clonebox-monitor.log"
    STATUS_FILE = "/var/run/clonebox-monitor-status.json"
    
    while True:
        status = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "apps": {}, "mounts_ok": True}
        
        # Check mounts
        check_mounts()
        
        # Check apps (only if GUI session is active)
        if os.path.exists("/run/user/1000"):
            ps_output = get_running_processes()
            for app in REQUIRED_APPS:
                running = is_app_running(app, ps_output)
                status["apps"][app] = "running" if running else "stopped"
                # Don't auto-restart apps - user may have closed them intentionally
        
        write_status(status)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
