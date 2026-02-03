#!/bin/bash

# Manual QGA Fix Script
# Run this inside the VM (via virt-viewer or console)

echo "=== Manual QGA Fix for CloneBox VM ==="
echo ""

echo "1. Updating package lists..."
sudo apt update

echo ""
echo "2. Installing QEMU Guest Agent..."
sudo apt install -y qemu-guest-agent cloud-guest-utils

echo ""
echo "3. Enabling and starting QGA service..."
sudo systemctl enable --now qemu-guest-agent

echo ""
echo "4. Checking QGA service status..."
sudo systemctl status qemu-guest-agent --no-pager

echo ""
echo "5. Checking if QGA is responding..."
sudo qemu-ga-client ping 2>/dev/null && echo "✅ QGA is responding!" || echo "❌ QGA not responding yet"

echo ""
echo "6. Restarting libvirt channel (if needed)..."
sudo systemctl restart qemu-guest-agent

echo ""
echo "=== Fix Complete! ==="
echo "Now run 'clonebox test . --user --quick' to verify QGA is working."
