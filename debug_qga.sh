#!/bin/bash

# Script to debug QGA issues in the VM

VM_NAME="clone-clonebox"

echo "=== Checking VM status ==="
virsh --connect qemu:///session dominfo $VM_NAME

echo -e "\n=== Checking QGA channel in XML ==="
virsh --connect qemu:///session dumpxml $VM_NAME | grep -A 5 -B 5 "org.qemu.guest_agent"

echo -e "\n=== Checking if QGA socket exists ==="
VM_ID=$(virsh --connect qemu:///session dominfo $VM_NAME | grep "Id:" | awk '{print $2}')
SOCKET_PATH="/run/user/1000/libvirt/qemu/run/channel/${VM_ID}-${VM_NAME}/org.qemu.guest_agent.0"
if [ -e "$SOCKET_PATH" ]; then
    echo "Socket exists: $SOCKET_PATH"
    ls -la "$SOCKET_PATH"
else
    echo "Socket NOT found at: $SOCKET_PATH"
fi

echo -e "\n=== Recent serial log output ==="
tail -20 /home/tom/.local/share/libvirt/images/${VM_NAME}/serial.log

echo -e "\n=== To connect to VM console ==="
echo "virsh --connect qemu:///session console $VM_NAME"
echo ""
echo "Once in console, run:"
echo "sudo systemctl status qemu-guest-agent"
echo "sudo apt install qemu-guest-agent -y"
echo "sudo systemctl enable --now qemu-guest-agent"
