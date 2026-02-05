#!/bin/bash

# Monitor VM clone progress
VM_NAME="clone-clonebox"
SSH_PORT=$(cat /home/tom/.local/share/libvirt/images/$VM_NAME/ssh_port 2>/dev/null || echo "22196")

echo "=================================================="
echo "Monitoring VM: $VM_NAME (SSH port: $SSH_PORT)"
echo "=================================================="
echo ""

while true; do
    clear
    echo "=================================================="
    echo "VM Clone Progress Monitor - $(date)"
    echo "=================================================="
    echo ""
    
    # Test SSH connection
    if ssh -o ConnectTimeout=5 -o BatchMode=yes -p $SSH_PORT ubuntu@localhost "echo SSH_OK" 2>/dev/null | grep -q SSH_OK; then
        echo "✅ SSH: Connected"
        
        # Check cloud-init status
        CLOUD_STATUS=$(ssh -p $SSH_PORT ubuntu@localhost "sudo cloud-init status 2>/dev/null" | grep -o "status: [a-z]*" | cut -d' ' -f2 || echo "unknown")
        echo "📊 Cloud-init: $CLOUD_STATUS"
        
        if [ "$CLOUD_STATUS" = "done" ]; then
            echo ""
            echo "✅ Cloud-init completed!"
            echo ""
            
            # Check GUI packages
            echo "🖥️  GUI Status:"
            ssh -p $SSH_PORT ubuntu@localhost << 'EOF' 2>/dev/null
# Check if GUI is installed
if dpkg -l | grep -q "ubuntu-desktop-minimal"; then
    echo "  ✅ ubuntu-desktop-minimal: installed"
else
    echo "  ❌ ubuntu-desktop-minimal: not installed"
fi

if dpkg -l | grep -q "gnome-shell"; then
    echo "  ✅ gnome-shell: installed"
else
    echo "  ❌ gnome-shell: not installed"
fi

if dpkg -l | grep -q "gdm3"; then
    echo "  ✅ gdm3: installed"
else
    echo "  ❌ gdm3: not installed"
fi

# Check if GDM is running
if systemctl is-active gdm3 >/dev/null 2>&1; then
    echo "  ✅ GDM service: running"
else
    echo "  ❌ GDM service: not running"
fi

# Check graphical target
if [ "$(systemctl get-default)" = "graphical.target" ]; then
    echo "  ✅ Graphical target: enabled"
else
    echo "  ❌ Graphical target: not enabled"
fi
EOF
            
            echo ""
            echo "📦 Package Status:"
            ssh -p $SSH_PORT ubuntu@localhost << 'EOF' 2>/dev/null
# Check if apt is still running
if pgrep -f "apt-get\|dpkg" >/dev/null; then
    echo "  🔄 Package installation in progress..."
    echo "  Active processes:"
    ps aux | grep -E "apt-get|dpkg" | grep -v grep | awk '{print "    " $11 " " $12 " " $13 " " $14}' | head -5
else
    echo "  ✅ All package installations completed"
fi

# Show disk usage
echo "  💾 Disk usage: $(df -h / | tail -1 | awk '{print $5}')"
EOF
            
            echo ""
            echo "🌐 Network Services:"
            ssh -p $SSH_PORT ubuntu@localhost << 'EOF' 2>/dev/null
# Check display server
if pgrep -f "Xorg\|Xwayland" >/dev/null; then
    echo "  ✅ Display server: running"
else
    echo "  ❌ Display server: not running"
fi

# Check SPICE/VNC
if ss -tlnp | grep -E ":(5900|5901)" >/dev/null; then
    echo "  ✅ Remote display: active"
else
    echo "  ❌ Remote display: not active"
fi
EOF
            
            echo ""
            echo "🎮 Access Methods:"
            echo "  SSH: ssh -p $SSH_PORT ubuntu@localhost"
            echo "  SPICE: remote-viewer spice://localhost:5900"
            echo "  VNC: vncviewer localhost:5901"
            
            # Check if fully ready
            GUI_READY=$(ssh -p $SSH_PORT ubuntu@localhost << 'EOF' 2>/dev/null
if dpkg -l | grep -q "ubuntu-desktop-minimal" && systemctl is-active gdm3 >/dev/null 2>&1; then
    echo "ready"
else
    echo "not_ready"
fi
EOF
)
            
            if [ "$GUI_READY" = "ready" ]; then
                echo ""
                echo "🎉 VM IS FULLY READY WITH GUI!"
                echo "   You can now connect via SPICE/VNC for graphical access"
                echo ""
                exit 0
            fi
            
        else
            echo ""
            echo "📋 Cloud-init Log (last 5 lines):"
            ssh -p $SSH_PORT ubuntu@localhost "sudo tail -5 /var/log/cloud-init-output.log 2>/dev/null | grep -E '\[clonebox\]|Installing|Setting up|Finished' || echo '  (no recent activity)'"
        fi
        
    else
        echo "❌ SSH: Not connected yet"
        echo "   VM might still be booting..."
    fi
    
    echo ""
    echo "Next check in 20 seconds... (Ctrl+C to stop)"
    sleep 20
done
