#!/usr/bin/env python3
"""
Script to fix QGA by creating a new cloud-init ISO with updated configuration
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

def create_fixed_cloudinit():
    """Create a new cloud-init ISO with fixed runcmd"""
    
    vm_dir = Path.home() / ".local/share/libvirt/images/clone-clonebox"
    cloudinit_dir = vm_dir / "cloud-init"
    
    # Read the current user-data
    user_data_file = cloudinit_dir / "user-data"
    if not user_data_file.exists():
        print(f"ERROR: {user_data_file} not found")
        return False
    
    with open(user_data_file, 'r') as f:
        content = f.read()
    
    # Fix the runcmd section - ensure proper YAML formatting
    # The issue might be with special characters or indentation
    fixed_content = content.replace(
        'runcmd:\n  - echo \'═══════════════════════════════════════════════════════════\'',
        '''runcmd:
  - sh -c "echo '======================== CloneBox VM Installation ==========================='"
  - sh -c "echo ''"'''
    )
    
    # Write the fixed user-data
    fixed_user_data = cloudinit_dir / "user-data-fixed"
    with open(fixed_user_data, 'w') as f:
        f.write(fixed_content)
    
    # Create new ISO
    print("Creating new cloud-init ISO with fixed configuration...")
    os.chdir(cloudinit_dir)
    
    # Backup original ISO
    iso_path = vm_dir / "cloud-init.iso"
    if iso_path.exists():
        shutil.copy2(iso_path, iso_path.with_suffix('.iso.backup'))
    
    # Generate new ISO
    cmd = [
        "genisoimage",
        "-output", str(iso_path),
        "-volid", "cidata",
        "-joliet",
        "-rock",
        "user-data-fixed",
        "meta-data"
    ]
    
    result = os.system(" ".join(cmd))
    if result != 0:
        print("ERROR: Failed to create ISO")
        return False
    
    # Rename user-data-fixed back to user-data
    if fixed_user_data.exists():
        shutil.move(fixed_user_data, user_data_file)
    
    print("Fixed cloud-init ISO created!")
    print("Please restart the VM to apply the changes:")
    print("  virsh --connect qemu:///session shutdown clone-clonebox")
    print("  virsh --connect qemu:///session start clone-clonebox")
    
    return True

if __name__ == "__main__":
    create_fixed_cloudinit()
