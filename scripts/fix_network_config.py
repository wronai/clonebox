#!/usr/bin/env python3
"""
Fix Network Configuration Issues
================================
Detects and fixes network configuration problems in cloud-init.
"""

import sys
import re
from pathlib import Path


def detect_interface_name(vm_name: str) -> str:
    """Try to detect the actual network interface name from logs."""
    vm_dir = Path.home() / ".local/share/libvirt/images" / vm_name
    serial_log = vm_dir / "serial.log"
    
    if not serial_log.exists():
        return None
    
    content = serial_log.read_text()
    
    # Look for various interface patterns
    patterns = [
        r'\b(enp\d+s\d)\b',  # enp17s0, enp3s0, etc.
        r'\b(eth\d)\b',      # eth0, eth1, etc.
        r'\b(ens\d)\b',      # ens3, ens4, etc.
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, content)
        if matches:
            # Return the most frequently mentioned interface
            from collections import Counter
            counter = Counter(matches)
            return counter.most_common(1)[0][0]
    
    return None


def fix_network_config(vm_name: str):
    """Fix network configuration for specific VM."""
    vm_dir = Path.home() / ".local/share/libvirt/images" / vm_name
    cloudinit_dir = vm_dir / "cloud-init"
    
    # Detect interface name
    interface = detect_interface_name(vm_name)
    print(f"\n🔍 Detected network interface: {interface or 'Not found'}")
    
    # Check current network-config
    net_config_path = cloudinit_dir / "network-config"
    if net_config_path.exists():
        current_config = net_config_path.read_text()
        print("\n📋 Current network-config:")
        print(current_config)
    else:
        print("\n⚠️  No network-config file found")
        current_config = ""
    
    # Generate improved network config
    if interface:
        # Use explicit interface name
        new_config = f"""version: 2
renderer: networkd
ethernets:
  {interface}:
    dhcp4: true
    dhcp6: false
    optional: true
"""
    else:
        # Use driver matching as fallback
        new_config = """version: 2
renderer: networkd
ethernets:
  nics:
    match:
      driver: virtio*
    dhcp4: true
    dhcp6: false
    optional: true
"""
    
    print("\n🔧 Proposed new network-config:")
    print(new_config)
    
    # Also check user-data for network configuration
    user_data_path = cloudinit_dir / "user-data"
    if user_data_path.exists():
        user_data = user_data_path.read_text()
        
        # Check for network block in user-data
        if "network:" in user_data:
            print("\n⚠️  Found network configuration in user-data")
            print("   This may conflict with network-config file")
            
            # Find and show the network block
            network_match = re.search(r'network:\s*\n((?:\s+.+\n?)*)', user_data)
            if network_match:
                print("\nCurrent network block in user-data:")
                print(network_match.group(0))
    
    # Write the new config
    if net_config_path.exists():
        backup_path = net_config_path.with_suffix('.yaml.backup')
        net_config_path.rename(backup_path)
        print(f"\n💾 Backed up network-config to: {backup_path}")
    
    net_config_path.write_text(new_config)
    print("✅ New network-config written")
    
    # Also update bootcmd fallback if needed
    user_data_path = cloudinit_dir / "user-data"
    if user_data_path.exists():
        user_data = user_data_path.read_text()
        
        # Find net_fallback in bootcmd
        if "net_fallback" in user_data and interface:
            print(f"\n🔧 Updating bootcmd to use interface: {interface}")
            
            # Replace the pattern matching with explicit interface
            old_pattern = r'NIC=\$\(ip -o link show \| grep -E .enp\|eth. \| head-1 \| cut -d: -f2 \| tr -d . \)'
            new_pattern = f'NIC="{interface}"'
            
            new_user_data = re.sub(old_pattern, new_pattern, user_data)
            
            if new_user_data != user_data:
                backup_path = user_data_path.with_suffix('.backup')
                user_data_path.rename(backup_path)
                print(f"💾 Backed up user-data to: {backup_path}")
                
                user_data_path.write_text(new_user_data)
                print("✅ Updated user-data with explicit interface name")
    
    # Instructions
    print("\n📋 Next steps:")
    print("1. Rebuild cloud-init ISO:")
    print(f"   cd {cloudinit_dir}")
    print("   mkisofs -output cloud-init.iso -volid cidata -joliet -rock user-data meta-data network-config")
    print("\n2. Restart VM:")
    print(f"   virsh --connect qemu:///session shutdown {vm_name}")
    print(f"   virsh --connect qemu:///session start {vm_name}")
    print("\n3. Monitor boot:")
    print(f"   tail -f {vm_dir}/serial.log")
    
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: fix_network_config.py <vm_name>")
        sys.exit(1)
    
    vm_name = sys.argv[1]
    success = fix_network_config(vm_name)
    sys.exit(0 if success else 1)
