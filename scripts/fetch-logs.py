#!/usr/bin/env python3
"""Fetch logs from VM using QEMU Guest Agent"""

import subprocess
import json
import sys
import base64
import time
import os
import zlib

def qga_exec(vm_name, conn_uri, command, timeout=10):
    """Execute command via QEMU Guest Agent"""
    try:
        # Execute command
        payload = {
            "execute": "guest-exec",
            "arguments": {
                "path": "/bin/sh",
                "arg": ["-c", command],
                "capture-output": True,
            },
        }
        exec_result = subprocess.run(
            ["virsh", "--connect", conn_uri, "qemu-agent-command", vm_name, json.dumps(payload)],
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

        # Wait for completion
        deadline = time.time() + timeout
        while time.time() < deadline:
            status_payload = {"execute": "guest-exec-status", "arguments": {"pid": pid}}
            status_result = subprocess.run(
                ["virsh", "--connect", conn_uri, "qemu-agent-command", vm_name, json.dumps(status_payload)],
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
    except Exception as e:
        return f"Error: {e}"


def ssh_exec(vm_name, command, timeout=20):
    """Execute command via SSH (requires passt port-forward + ssh_key)."""
    try:
        key_path = os.path.expanduser(f"~/.local/share/libvirt/images/{vm_name}/ssh_key")
        if not os.path.exists(key_path):
            return None

        port_path = os.path.expanduser(f"~/.local/share/libvirt/images/{vm_name}/ssh_port")
        if os.path.exists(port_path):
            try:
                ssh_port = int(open(port_path, "r").read().strip())
            except Exception:
                ssh_port = 22000 + (zlib.crc32(vm_name.encode("utf-8")) % 1000)
        else:
            ssh_port = 22000 + (zlib.crc32(vm_name.encode("utf-8")) % 1000)
        user = "ubuntu"
        result = subprocess.run(
            [
                "ssh",
                "-i",
                key_path,
                "-p",
                str(ssh_port),
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "BatchMode=yes",
                f"{user}@127.0.0.1",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        return (result.stdout or "").strip()
    except Exception:
        return None

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
