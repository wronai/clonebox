#!/usr/bin/env python3
"""
Fix YAML Parsing Error in Cloud-init bootcmd
============================================
Detects and fixes YAML parsing errors in cloud-init bootcmd configuration.
"""

import sys
import re
from pathlib import Path


def fix_yaml_bootcmd(vm_name: str):
    """Fix YAML parsing errors in bootcmd for specific VM."""
    vm_dir = Path.home() / ".local/share/libvirt/images" / vm_name
    cloudinit_dir = vm_dir / "cloud-init"
    user_data_path = cloudinit_dir / "user-data"
    
    if not user_data_path.exists():
        print(f"❌ user-data not found for VM {vm_name}")
        return False
    
    # Read current user-data
    content = user_data_path.read_text()
    
    # Find bootcmd section
    bootcmd_match = re.search(r'bootcmd:\s*\n((?:\s+- .+\n?)*)', content)
    if not bootcmd_match:
        print("❌ No bootcmd section found in user-data")
        return False
    
    bootcmd_section = bootcmd_match.group(0)
    print("\n🔍 Found bootcmd section:")
    print(bootcmd_section[:500])
    
    # Check for problematic patterns
    issues = []
    lines = bootcmd_section.split('\n')
    for i, line in enumerate(lines):
        if line.strip().startswith('- ') and ':' in line and not line.strip().startswith('- ["'):
            # Found potential YAML issue
            issues.append((i, line))
    
    if not issues:
        print("✅ No YAML issues detected in bootcmd")
        return True
    
    print(f"\n🚨 Found {len(issues)} potential YAML issues:")
    for line_num, line in issues:
        print(f"   Line {line_num}: {line}")
    
    # Generate fixed bootcmd
    fixed_lines = []
    for line_num, line in lines:
        if line_num in [i for i, _ in issues]:
            # Fix this line
            if 'echo' in line:
                # Extract the echo command
                echo_match = re.search(r'- (.+)', line)
                if echo_match:
                    cmd = echo_match.group(1)
                    # Convert to proper format
                    fixed_cmd = f'  - ["sh", "-c", "{cmd}"]'
                    fixed_lines.append(fixed_cmd)
                    print(f"   Fixed: {fixed_cmd}")
            else:
                fixed_lines.append(line)
        else:
            fixed_lines.append(line)
    
    # Replace in content
    new_bootcmd = '\n'.join(fixed_lines)
    new_content = content.replace(bootcmd_section, new_bootcmd)
    
    # Backup original
    backup_path = user_data_path.with_suffix('.yaml.backup')
    user_data_path.rename(backup_path)
    print(f"\n💾 Backed up original to: {backup_path}")
    
    # Write fixed version
    user_data_path.write_text(new_content)
    print("✅ Fixed user-data written")
    
    # Instructions to rebuild
    print("\n📋 Next steps:")
    print("1. Rebuild cloud-init ISO:")
    print(f"   cd {cloudinit_dir}")
    print("   mkisofs -output cloud-init.iso -volid cidata -joliet -rock user-data meta-data")
    print("\n2. Restart VM:")
    print(f"   virsh --connect qemu:///session shutdown {vm_name}")
    print(f"   virsh --connect qemu:///session start {vm_name}")
    
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: fix_yaml_bootcmd.py <vm_name>")
        sys.exit(1)
    
    vm_name = sys.argv[1]
    success = fix_yaml_bootcmd(vm_name)
    sys.exit(0 if success else 1)
