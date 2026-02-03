#!/usr/bin/env python3
"""
Fix YAML Quote Escaping Issues
==============================
Fixes nested quotes in YAML bootcmd that cause parsing errors.
"""

import sys
from pathlib import Path


def fix_yaml_quotes(vm_name: str):
    """Fix YAML quote escaping in bootcmd."""
    vm_dir = Path.home() / ".local/share/libvirt/images" / vm_name
    cloudinit_dir = vm_dir / "cloud-init"
    user_data_path = cloudinit_dir / "user-data"
    
    if not user_data_path.exists():
        print(f"❌ user-data not found for VM {vm_name}")
        return False
    
    # Read current user-data
    content = user_data_path.read_text()
    
    print("🔍 Fixing YAML quote escaping issues...")
    
    # Fix the problematic bootcmd lines
    # The issue: ["sh", "-c", "echo "[clonebox] message" > /dev/ttyS0"]
    # Should be: ["sh", "-c", "echo '[clonebox] message' > /dev/ttyS0"]
    
    import re
    
    # Pattern to find bootcmd entries with nested quotes
    pattern = r'(\s*-\s*\["sh",\s*"-c",\s*)"([^"]*\[clonebox\][^"]*)"([^"]*\])'
    
    def replace_func(match):
        prefix = match.group(1)
        content = match.group(2)
        suffix = match.group(3)
        
        # Replace double quotes inside with single quotes
        content_fixed = content.replace('"', "'")
        
        return f'{prefix}"{content_fixed}"{suffix}'
    
    # Apply the fix
    new_content = re.sub(pattern, replace_func, content)
    
    # Also fix the long network configuration line
    net_pattern = r'(\s*-\s*\["sh",\s*"-c",\s*)"([^"]*\[clonebox\][^"]*echo[^"]*\$NIC[^"]*)(")'
    
    def replace_net_func(match):
        prefix = match.group(1)
        content = match.group(2)
        suffix = match.group(3)
        
        # This is more complex - need to escape properly
        # Replace the entire command with a properly escaped version
        if 'echo "[clonebox]' in content:
            content = content.replace('echo "[clonebox]', "echo '[clonebox]")
            content = content.replace('" > /dev/ttyS0', "' > /dev/ttyS0")
        
        return f'{prefix}"{content}"{suffix}'
    
    new_content = re.sub(net_pattern, replace_net_func, new_content)
    
    # Check if we made changes
    if new_content != content:
        print("✅ Fixed YAML quote escaping issues")
        
        # Backup original
        backup_path = user_data_path.with_suffix('.quotes.backup')
        user_data_path.rename(backup_path)
        print(f"💾 Backed up original to: {backup_path}")
        
        # Write fixed version
        user_data_path.write_text(new_content)
        print("✅ Fixed user-data written")
        
        # Show the fixed bootcmd section
        print("\n📋 Fixed bootcmd section:")
        lines = new_content.split('\n')
        in_bootcmd = False
        for line in lines:
            if line.startswith('bootcmd:'):
                in_bootcmd = True
            elif in_bootcmd and line and not line.startswith('  '):
                break
            if in_bootcmd:
                print(line)
        
        # Instructions
        print("\n📋 Next steps:")
        print("1. Rebuild cloud-init ISO:")
        print(f"   cd {cloudinit_dir}")
        print("   mkisofs -output cloud-init.iso -volid cidata -joliet -rock user-data meta-data network-config")
        print("\n2. Restart VM:")
        print(f"   virsh --connect qemu:///session shutdown {vm_name}")
        print(f"   virsh --connect qemu:///session start {vm_name}")
        
        return True
    else:
        print("✅ No YAML quote issues found")
        return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: fix_yaml_quotes.py <vm_name>")
        sys.exit(1)
    
    vm_name = sys.argv[1]
    success = fix_yaml_quotes(vm_name)
    sys.exit(0 if success else 1)
