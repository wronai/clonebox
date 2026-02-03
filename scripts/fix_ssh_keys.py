#!/usr/bin/env python3
"""
Fix SSH Key Injection Issues
============================
Detects and fixes SSH key injection problems in cloud-init.
"""

import sys
import os
import re
from pathlib import Path


def fix_ssh_keys(vm_name: str):
    """Fix SSH key configuration for specific VM."""
    vm_dir = Path.home() / ".local/share/libvirt/images" / vm_name
    cloudinit_dir = vm_dir / "cloud-init"
    user_data_path = cloudinit_dir / "user-data"
    
    if not user_data_path.exists():
        print(f"❌ user-data not found for VM {vm_name}")
        return False
    
    # Read current user-data
    content = user_data_path.read_text()
    
    # Check for SSH configuration
    ssh_config = {
        "ssh_pwauth": None,
        "ssh_authorized_keys": None,
        "disable_root": None,
        "ssh_keys": None
    }
    
    for key in ssh_config:
        pattern = f"{key}:"
        if pattern in content:
            # Extract the value
            start = content.find(pattern)
            end = start
            indent = len(content[start:content.find('\n', start)]) - len(pattern)
            
            # Find end of this YAML block
            lines = content[start:].split('\n')
            value_lines = []
            for line in lines[1:]:
                if line and (not line.startswith(' ' * (indent + 2)) or line.strip() == ''):
                    break
                value_lines.append(line)
            
            ssh_config[key] = '\n'.join(value_lines)
    
    print("\n🔍 Current SSH Configuration:")
    for key, value in ssh_config.items():
        if value:
            print(f"   {key}: {value[:100]}...")
        else:
            print(f"   {key}: Not found")
    
    # Check if SSH key file exists
    ssh_key_path = vm_dir / "ssh_key"
    if ssh_key_path.exists():
        public_key = ssh_key_path.with_suffix('.pub')
        if public_key.exists():
            key_content = public_key.read_text().strip()
            print(f"\n🔑 Found SSH public key: {key_content[:50]}...")
        else:
            # Generate public key from private
            print(f"\n🔑 Generating public key from private key...")
            rc, out, err = run_command(["ssh-keygen", "-y", "-f", str(ssh_key_path)])
            if rc == 0:
                key_content = out.strip()
                print(f"   Generated: {key_content[:50]}...")
                # Save it for future use
                public_key.write_text(key_content + '\n')
            else:
                print(f"   ❌ Failed to generate public key: {err}")
                key_content = None
    else:
        print(f"\n❌ SSH private key not found at {ssh_key_path}")
        key_content = None
    
    # Fix configuration
    fixes_needed = []
    
    # Check if ssh_authorized_keys is missing or empty
    if not ssh_config["ssh_authorized_keys"] and key_content:
        fixes_needed.append(("Add ssh_authorized_keys", key_content))
    
    # Ensure SSH is enabled
    if not ssh_config["ssh_pwauth"]:
        fixes_needed.append(("Enable SSH password auth (temporarily)", "ssh_pwauth: true"))
    
    if not fixes_needed:
        print("\n✅ SSH configuration looks correct")
        return True
    
    print(f"\n🔧 Applying {len(fixes_needed)} fixes...")
    
    # Apply fixes to user-data
    new_content = content
    
    for fix_name, fix_value in fixes_needed:
        print(f"\n   Fix: {fix_name}")
        
        if "ssh_authorized_keys" in fix_name:
            # Add ssh_authorized_keys section
            if "ssh_authorized_keys:" in new_content:
                # Replace existing empty section
                pattern = r'ssh_authorized_keys:\s*\n(?:\s+-.*\n?)*'
                replacement = f"ssh_authorized_keys:\n  - {fix_value}\n"
                new_content = re.sub(pattern, replacement, new_content)
            else:
                # Add new section
                # Find a good place to insert it (after ssh_pwauth or at end)
                if "ssh_pwauth:" in new_content:
                    insert_pos = new_content.find("ssh_pwauth:")
                    insert_pos = new_content.find('\n', insert_pos) + 1
                    new_content = new_content[:insert_pos] + f"ssh_authorized_keys:\n  - {fix_value}\n" + new_content[insert_pos:]
                else:
                    # Add at end of user-data (before runcmd)
                    runcmd_pos = new_content.find("runcmd:")
                    if runcmd_pos > 0:
                        new_content = new_content[:runcmd_pos] + f"ssh_authorized_keys:\n  - {fix_value}\n\n" + new_content[runcmd_pos:]
        
        elif "ssh_pwauth" in fix_name:
            if "ssh_pwauth:" not in new_content:
                # Add ssh_pwauth
                ssh_keys_pos = new_content.find("ssh_keys:")
                if ssh_keys_pos > 0:
                    new_content = new_content[:ssh_keys_pos] + "ssh_pwauth: true\n" + new_content[ssh_keys_pos:]
    
    # Backup original
    backup_path = user_data_path.with_suffix('.ssh.backup')
    user_data_path.rename(backup_path)
    print(f"\n💾 Backed up user-data to: {backup_path}")
    
    # Write fixed version
    user_data_path.write_text(new_content)
    print("✅ Fixed user-data written")
    
    # Show the SSH section
    print("\n📋 Updated SSH configuration:")
    ssh_section = re.search(r'(ssh_.*?:\s*\n(?:\s+- .+\n?)*)', new_content)
    if ssh_section:
        print(ssh_section.group(0))
    
    # Instructions
    print("\n📋 Next steps:")
    print("1. Rebuild cloud-init ISO:")
    print(f"   cd {cloudinit_dir}")
    print("   mkisofs -output cloud-init.iso -volid cidata -joliet -rock user-data meta-data")
    print("\n2. Restart VM:")
    print(f"   virsh --connect qemu:///session shutdown {vm_name}")
    print(f"   virsh --connect qemu:///session start {vm_name}")
    print("\n3. After boot, try SSH:")
    port_file = vm_dir / "ssh_port"
    if port_file.exists():
        port = port_file.read_text().strip()
        print(f"   ssh -i {ssh_key_path} -p {port} ubuntu@127.0.0.1")
    
    return True


def run_command(cmd):
    """Run command and return (rc, stdout, stderr)."""
    import subprocess
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: fix_ssh_keys.py <vm_name>")
        sys.exit(1)
    
    vm_name = sys.argv[1]
    success = fix_ssh_keys(vm_name)
    sys.exit(0 if success else 1)
