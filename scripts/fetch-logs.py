#!/usr/bin/env python3
"""Fetch logs from VM using QEMU Guest Agent or SSH.

Uses shared helpers from the clonebox package when available,
falls back to inline implementations for standalone use.
"""

import subprocess
import json
import sys
import base64
import time
import os

# Allow importing from the clonebox package (one level up)
_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if os.path.isdir(_src):
    sys.path.insert(0, _src)

try:
    from clonebox.ssh import ssh_exec as _pkg_ssh_exec
    from clonebox.paths import resolve_ssh_port, ssh_key_path

    def ssh_exec(vm_name, command, timeout=20):
        port = resolve_ssh_port(vm_name, user_session=True)
        key = ssh_key_path(vm_name, user_session=True)
        return _pkg_ssh_exec(port=port, key=key, command=command, timeout=timeout)
except ImportError:
    # Standalone fallback (no clonebox package installed)
    import zlib

    def ssh_exec(vm_name, command, timeout=20):
        key_path = os.path.expanduser(f"~/.local/share/libvirt/images/{vm_name}/ssh_key")
        if not os.path.exists(key_path):
            return None
        port_path = os.path.expanduser(f"~/.local/share/libvirt/images/{vm_name}/ssh_port")
        try:
            ssh_port = int(open(port_path).read().strip()) if os.path.exists(port_path) else None
        except Exception:
            ssh_port = None
        if not ssh_port:
            ssh_port = 22000 + (zlib.crc32(vm_name.encode("utf-8")) % 1000)
        try:
            result = subprocess.run(
                ["ssh", "-i", key_path, "-p", str(ssh_port),
                 "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                 "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                 f"ubuntu@127.0.0.1", command],
                capture_output=True, text=True, timeout=timeout)
            return (result.stdout or "").strip() if result.returncode == 0 else None
        except Exception:
            return None


def qga_exec(vm_name, conn_uri, command, timeout=10):
    """Execute command via QEMU Guest Agent."""
    try:
        payload = json.dumps({"execute": "guest-exec", "arguments": {
            "path": "/bin/sh", "arg": ["-c", command], "capture-output": True}})
        r = subprocess.run(
            ["virsh", "--connect", conn_uri, "qemu-agent-command", vm_name, payload],
            capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return None
        pid = json.loads(r.stdout).get("return", {}).get("pid")
        if not pid:
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            sr = subprocess.run(
                ["virsh", "--connect", conn_uri, "qemu-agent-command", vm_name,
                 json.dumps({"execute": "guest-exec-status", "arguments": {"pid": pid}})],
                capture_output=True, text=True, timeout=5)
            if sr.returncode != 0:
                return None
            ret = json.loads(sr.stdout).get("return", {})
            if not ret.get("exited", False):
                time.sleep(0.3)
                continue
            out = ret.get("out-data")
            return base64.b64decode(out).decode().strip() if out else ""
        return None
    except Exception as e:
        return f"Error: {e}"

def main():
    if len(sys.argv) < 4:
        print("Usage: fetch-logs.py <vm_name> <conn_uri> <output_dir>")
        sys.exit(1)
    
    vm_name = sys.argv[1]
    conn_uri = sys.argv[2]
    output_dir = sys.argv[3]
    
    # Create output directory
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    # Fetch logs
    logs = {
        "clonebox-boot.log": "cat /var/log/clonebox-boot.log 2>/dev/null || echo 'Log not found'",
        "clonebox-monitor.log": "cat /var/log/clonebox-monitor.log 2>/dev/null || echo 'Log not found'",
        "cloud-init-output.log": "tail -100 /var/log/cloud-init-output.log 2>/dev/null || echo 'Log not found'",
        "cloud-init.log": "tail -100 /var/log/cloud-init.log 2>/dev/null || echo 'Log not found'",
    }
    
    for filename, command in logs.items():
        print(f"Fetching {filename}...")
        output = qga_exec(vm_name, conn_uri, command, timeout=30)
        if output is None:
            output = ssh_exec(vm_name, command, timeout=30)
        if output:
            # Strip ANSI escape codes for cleaner output
            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            clean_output = ansi_escape.sub('', output)
            with open(f"{output_dir}/{filename}", "w") as f:
                f.write(clean_output)
        else:
            with open(f"{output_dir}/{filename}", "w") as f:
                f.write("Log not found")

if __name__ == "__main__":
    main()
