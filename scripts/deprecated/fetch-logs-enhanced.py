#!/usr/bin/env python3
"""Enhanced Fetch logs from VM using QEMU Guest Agent with comprehensive diagnostics"""

import subprocess
import json
import sys
import base64
import time
import os
import zlib
import re
from datetime import datetime

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


def exec_command(vm_name, conn_uri, command, timeout=30):
    """Try QGA first, fallback to SSH"""
    output = qga_exec(vm_name, conn_uri, command, timeout)
    if output is None:
        output = ssh_exec(vm_name, command, timeout)
    return output


def strip_ansi_codes(text):
    """Remove ANSI escape codes for cleaner output"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def main():
    if len(sys.argv) < 4:
        print("Usage: fetch-logs-enhanced.py <vm_name> <conn_uri> <output_dir>")
        sys.exit(1)
    
    vm_name = sys.argv[1]
    conn_uri = sys.argv[2]
    output_dir = sys.argv[3]
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Fetching logs from VM '{vm_name}'...")
    
    # Basic logs
    logs = {
        "clonebox-boot.log": "cat /var/log/clonebox-boot.log 2>/dev/null || echo 'Log not found'",
        "clonebox-monitor.log": "cat /var/log/clonebox-monitor.log 2>/dev/null || echo 'Log not found'",
        "cloud-init-output.log": "tail -200 /var/log/cloud-init-output.log 2>/dev/null || echo 'Log not found'",
        "cloud-init.log": "tail -200 /var/log/cloud-init.log 2>/dev/null || echo 'Log not found'",
        "syslog": "tail -200 /var/log/syslog 2>/dev/null || echo 'Log not found'",
    }
    
    # Diagnostic information
    diagnostics = {
        "cloud-init-status": "cloud-init status --format=json 2>/dev/null || echo 'Cloud-init not available'",
        "services-status": """
            systemctl is-active sshd docker gdm3 qemu-guest-agent 2>/dev/null | \
            awk '{print $1 ": " $2}' || echo 'Service check failed'
        """,
        "recent-errors": """
            journalctl -p err -n 10 --no-pager 2>/dev/null | \
            grep -v ' -- begin ' | grep -v ' -- end ' || echo 'No recent errors'
        """,
        "disk-usage": """
            echo '=== Disk Usage ===' && df -h | head -5 && echo && \
            echo '=== Large Directories ===' && du -sh /var/log /tmp /home 2>/dev/null || echo 'Disk info unavailable'
        """,
        "network-info": """
            echo '=== Interfaces ===' && ip addr show | grep -E 'inet|UP' | head -10 && echo && \
            echo '=== Routes ===' && ip route | head -5 && echo && \
            echo '=== DNS ===' && cat /etc/resolv.conf 2>/dev/null || echo 'Network info unavailable'
        """,
        "performance": """
            echo '=== Load Average ===' && uptime && echo && \
            echo '=== Memory Usage ===' && free -h && echo && \
            echo '=== Top Processes ===' && ps aux --sort=-%cpu | head -6 || echo 'Performance info unavailable'
        """,
    }
    
    # Fetch all logs
    all_logs = {**logs, **diagnostics}
    
    for filename, command in all_logs.items():
        print(f"Fetching {filename}...")
        output = exec_command(vm_name, conn_uri, command, timeout=30)
        
        if output:
            # Clean up the output
            clean_output = strip_ansi_codes(output)
            
            # Add timestamp for diagnostic files
            if filename in diagnostics:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                clean_output = f"Generated at: {timestamp}\n{'='*50}\n{clean_output}"
            
            with open(f"{output_dir}/{filename}", "w") as f:
                f.write(clean_output)
        else:
            error_msg = f"Failed to fetch {filename}"
            print(f"  {error_msg}")
            with open(f"{output_dir}/{filename}", "w") as f:
                f.write(error_msg)
    
    # Additional specific checks
    print("\nPerforming additional checks...")
    
    # Check for specific error patterns
    error_patterns = {
        "sssd-errors": "grep -i 'sssd.*failed\\|dependency failed' /var/log/cloud-init-output.log 2>/dev/null | tail -10 || echo 'No SSSD errors'",
        "package-errors": "grep -E '(ERROR|Failed|error:)' /var/log/cloud-init-output.log 2>/dev/null | grep -E '(apt|dpkg|package)' | tail -10 || echo 'No package errors'",
        "network-errors": "grep -i 'network.*failed\\|connection.*failed' /var/log/cloud-init-output.log 2>/dev/null | tail -10 || echo 'No network errors'",
    }
    
    for filename, command in error_patterns.items():
        output = exec_command(vm_name, conn_uri, command, timeout=10)
        if output and output != "No SSSD errors" and output != "No package errors" and output != "No network errors":
            with open(f"{output_dir}/{filename}", "w") as f:
                f.write(f"Found at: {datetime.now()}\n\n{output}")
    
    # Create a summary report
    print("\nGenerating summary report...")
    summary = []
    summary.append(f"VM Log Summary Report")
    summary.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    summary.append(f"VM Name: {vm_name}")
    summary.append("="*50)
    
    # Check cloud-init status
    if os.path.exists(f"{output_dir}/cloud-init-status"):
        with open(f"{output_dir}/cloud-init-status", "r") as f:
            status = f.read()
            if "status: done" in status.lower():
                summary.append("✅ Cloud-init: Completed successfully")
            elif "running" in status.lower():
                summary.append("⏳ Cloud-init: Still running")
            else:
                summary.append("❌ Cloud-init: Status unknown or failed")
    
    # Check for errors
    error_count = 0
    for error_file in ["sssd-errors", "package-errors", "network-errors"]:
        if os.path.exists(f"{output_dir}/{error_file}"):
            error_count += 1
    
    if error_count > 0:
        summary.append(f"⚠️  Found {error_count} categories of errors")
    else:
        summary.append("✅ No specific errors detected")
    
    # Check services
    if os.path.exists(f"{output_dir}/services-status"):
        with open(f"{output_dir}/services-status", "r") as f:
            services = f.read()
            active_services = services.count("active")
            total_services = services.count("\n")
            summary.append(f"📊 Services: {active_services} active out of {total_services} checked")
    
    summary.append("\nLog files available:")
    for log_file in sorted(os.listdir(output_dir)):
        if log_file.endswith('.log') or log_file.endswith('-status'):
            size = os.path.getsize(f"{output_dir}/{log_file}")
            summary.append(f"  - {log_file} ({size} bytes)")
    
    with open(f"{output_dir}/summary-report.txt", "w") as f:
        f.write("\n".join(summary))
    
    print("Log fetching complete!")


if __name__ == "__main__":
    main()
