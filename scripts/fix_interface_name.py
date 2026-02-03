#!/usr/bin/env python3
"""
Fix Network Interface Name Mismatch
===================================
Updates cloud-init to use the correct interface name detected in VM.
"""

import sys
import re
from pathlib import Path


def fix_interface_name(vm_name: str):
    """Fix the interface name in cloud-init configuration."""
    vm_dir = Path.home() / ".local/share/libvirt/images" / vm_name
    cloudinit_dir = vm_dir / "cloud-init"
    user_data_path = cloudinit_dir / "user-data"
    
    if not user_data_path.exists():
        print(f"❌ user-data not found for VM {vm_name}")
        return False
    
    # Read current user-data
    content = user_data_path.read_text()
    
    # The VM has enp91s0, not enp17s0
    print("🔍 Fixing interface name mismatch...")
    print("   Detected interface: enp91s0")
    print("   Configured interface: enp17s0")
    
    # Replace all occurrences of enp17s0 with enp91s0
    new_content = content.replace('enp17s0', 'enp91s0')
    
    # Also fix the pattern matching to be more specific
    # Replace the generic pattern with explicit interface name
    old_pattern = 'NIC=$(ip -o link show | grep -E \'enp|eth\' | head -1 | cut -d: -f2 | tr -d \' \')'
    new_pattern = 'NIC="enp91s0"'
    new_content = new_content.replace(old_pattern, new_pattern)
    
    # Also fix in runcmd section
    old_runcmd = 'NIC=$(ip -o link show | grep -E \'enp|eth\' | grep -v \'lo:\' | head -1 | awk -F\': \' \'{print $2}\')'
    new_content = new_content.replace(old_runcmd, new_pattern)
    
    if new_content != content:
        print("✅ Fixed interface name to enp91s0")
        
        # Backup original
        backup_path = user_data_path.with_suffix('.interface.backup')
        user_data_path.rename(backup_path)
        print(f"💾 Backed up original to: {backup_path}")
        
        # Write fixed version
        user_data_path.write_text(new_content)
        print("✅ Fixed user-data written")
        
        # Show what changed
        print("\n📋 Changes made:")
        print("   - Replaced 'enp17s0' with 'enp91s0'")
        print("   - Set explicit interface name instead of pattern matching")
        
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
        print("✅ No interface name issues found")
        return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: fix_interface_name.py <vm_name>")
        sys.exit(1)
    
    vm_name = sys.argv[1]
    success = fix_interface_name(vm_name)
    sys.exit(0 if success else 1)
