#!/bin/bash

# Quick fix for network issues
echo "🔧 Fixing clonebox network issues..."

# Stop any running VMs
echo "Stopping any running clonebox VMs..."
virsh --connect qemu:///session list --name | xargs -r -I {} virsh --connect qemu:///session destroy {}

# Clean up network interfaces
echo "Cleaning up network interfaces..."
sudo ip link set virbr0 down 2>/dev/null || true
sudo brctl delbr virbr0 2>/dev/null || true

# Restart libvirtd
echo "Restarting libvirtd..."
systemctl --user restart libvirtd

# Wait a moment
sleep 2

# Create and start network
echo "Creating default network..."
virsh --connect qemu:///session net-define /tmp/default-network.xml
virsh --connect qemu:///session net-autostart default
virsh --connect qemu:///session net-start default

echo "✅ Network fixed! You can now run:"
echo "   clonebox clone . --user"
