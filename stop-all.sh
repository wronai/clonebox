#!/bin/bash
# Stop all CloneBox VMs (both user and system sessions)

echo "Stopping all CloneBox VMs..."

# Stop user session VMs
echo "Stopping user session VMs..."
python3 -m clonebox list --json 2>/dev/null | jq -r '.[] | select(.session == "user") | .name' | while read vm; do
    if [ -n "$vm" ]; then
        echo "Stopping $vm (user session)..."
        python3 -m clonebox stop "$vm" --user 2>/dev/null || echo "Failed to stop $vm"
    fi
done

# Stop system session VMs
echo "Stopping system session VMs..."
python3 -m clonebox list --json 2>/dev/null | jq -r '.[] | select(.session == "system") | .name' | while read vm; do
    if [ -n "$vm" ]; then
        echo "Stopping $vm (system session)..."
        python3 -m clonebox stop "$vm" 2>/dev/null || echo "Failed to stop $vm"
    fi
done

echo "All VMs stopped!"
