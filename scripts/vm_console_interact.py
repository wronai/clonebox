#!/usr/bin/env python3
"""
VM Console Interaction Helper
=============================
Send commands to VM console and receive responses.
"""

import sys
import time
import pexpect
from pathlib import Path


def interact_with_console(vm_name: str, commands: list, timeout: int = 30):
    """Send commands to VM console and capture responses."""
    cmd = f"virsh --connect qemu:///session console {vm_name}"
    
    try:
        # Start virsh console
        child = pexpect.spawn(cmd, encoding='utf-8')
        
        # Wait for console to connect
        child.expect("Escape character is", timeout=10)
        time.sleep(1)
        
        responses = []
        
        for cmd_to_send in commands:
            print(f"\n>>> Sending: {cmd_to_send}")
            child.sendline(cmd_to_send)
            time.sleep(2)
            
            # Capture output
            output = child.before[-1000:] if hasattr(child, 'before') else ""
            responses.append(output)
            print(f"<<< Response:\n{output}")
        
        # Exit console
        child.sendcontrol(']')
        child.close()
        
        return responses
        
    except pexpect.exceptions.TIMEOUT:
        print("Timeout waiting for console")
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []


def check_vm_network(vm_name: str):
    """Check network configuration in VM."""
    commands = [
        "ip addr show | grep -E 'inet|state UP'",
        "ip route show",
        "cat /etc/resolv.conf",
        "systemctl status ssh | head -10",
        "ps aux | grep sshd"
    ]
    
    return interact_with_console(vm_name, commands)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: vm_console_interact.py <vm_name>")
        sys.exit(1)
    
    vm_name = sys.argv[1]
    check_vm_network(vm_name)
