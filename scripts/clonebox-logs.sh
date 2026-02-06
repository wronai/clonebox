#!/bin/bash
# CloneBox Logs Helper - Access VM logs from host

VM_NAME="${1:-clone-clonebox}"
USER_SESSION="${2:-false}"
SHOW_ALL="${3:-false}"

VM_DIR="${HOME}/.local/share/libvirt/images/${VM_NAME}"
SSH_KEY="$VM_DIR/ssh_key"
SSH_PORT_FILE="$VM_DIR/ssh_port"

log() { echo "[INFO] $1"; }

# SSH helper (avoids repeating flags)
_ssh() {
    [ -f "$SSH_KEY" ] && [ -f "$SSH_PORT_FILE" ] || return 1
    ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null -o BatchMode=yes \
        -o LogLevel=ERROR \
        -i "$SSH_KEY" -p "$(cat "$SSH_PORT_FILE")" ubuntu@127.0.0.1 "$@" 2>/dev/null
}

if [ "$USER_SESSION" = "true" ]; then
    CONNECT="qemu:///session"
    USE_QGA=true
else
    CONNECT="qemu:///system"
    LOGS_DISK="/var/lib/libvirt/images/clonebox-logs.qcow2"
    USE_QGA=false
fi

echo "CloneBox Log Viewer"
echo "=================="
echo "VM: $VM_NAME"
echo "Connection: $CONNECT"
echo ""

# Check if VM is running
if ! virsh --connect "$CONNECT" domstate "$VM_NAME" | grep -q "running"; then
    echo "❌ VM is not running!"
    exit 1
fi

# For user session, use QEMU Guest Agent to fetch logs
if [ "$USE_QGA" = "true" ]; then
    echo "📋 Fetching logs via QEMU Guest Agent (SSH fallback if needed)..."
    echo ""
    
    # Create temp directory for logs
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT
    
    # Fetch logs using QGA
    SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
    python3 "$SCRIPT_DIR/fetch-logs.py" "$VM_NAME" "$CONNECT" "$TEMP_DIR"
    
    # Fetch browser-specific logs via SSH helper
    log "Fetching browser logs..."
    _ssh "journalctl -n 50 --no-pager 2>/dev/null | grep -iE 'chrome|chromium|firefox|snap'" \
        > "$TEMP_DIR/browser-journal.log" 2>/dev/null || true
    _ssh "snap list 2>/dev/null | grep -E '(firefox|chromium)'" \
        > "$TEMP_DIR/snap-list.log" 2>/dev/null || true
    _ssh "ls -la ~/.config/google-chrome/ ~/snap/chromium/common/chromium/ ~/snap/firefox/common/.mozilla/firefox/ 2>&1" \
        > "$TEMP_DIR/browser-profiles.log" 2>/dev/null || true
    _ssh "pgrep -a -f 'chrome|chromium|firefox' 2>/dev/null" \
        > "$TEMP_DIR/browser-processes.log" 2>/dev/null || true
    
    echo ""
    echo "📋 Available logs:"
    echo "-------------------"
    ls -la "$TEMP_DIR/"
    echo ""
    
    # If SHOW_ALL is true, display all logs and exit
    if [ "$SHOW_ALL" = "true" ]; then
        echo "📄 All logs:"
        echo "============"
        echo ""
        echo "--- Boot diagnostic log ---"
        cat "$TEMP_DIR/clonebox-boot.log"
        echo ""
        echo "--- Monitor log ---"
        cat "$TEMP_DIR/clonebox-monitor.log"
        echo ""
        echo "--- Cloud-init output log (last 100 lines) ---"
        cat "$TEMP_DIR/cloud-init-output.log"
        echo ""
        echo "--- Cloud-init log (last 100 lines) ---"
        cat "$TEMP_DIR/cloud-init.log"
        echo ""
        echo "--- Browser logs ---"
        echo "Browser journal logs:"
        cat "$TEMP_DIR/browser-journal.log" 2>/dev/null || echo "No browser journal logs"
        echo ""
        echo "Snap packages:"
        cat "$TEMP_DIR/snap-list.log" 2>/dev/null || echo "No snap list"
        echo ""
        echo "Browser profiles:"
        cat "$TEMP_DIR/browser-profiles.log" 2>/dev/null || echo "No browser profiles"
        echo ""
        echo "Browser processes:"
        cat "$TEMP_DIR/browser-processes.log" 2>/dev/null || echo "No browser processes"
        exit 0
    fi
    
    # Menu
    echo "What would you like to view?"
    echo "1) Boot diagnostic log"
    echo "2) Monitor log"
    echo "3) Cloud-init output log"
    echo "4) Cloud-init log"
    echo "5) All logs summary"
    echo "6) Show all logs at once"
    echo "7) Browser logs (Chrome/Chromium/Firefox)"
    echo "8) Exit"
    echo ""
    
    read -p "Select option: " choice
    echo ""
    
    case "$choice" in
        1)
            echo "📄 Boot diagnostic log:"
            echo "======================"
            [ -f "$TEMP_DIR/clonebox-boot.log" ] && cat "$TEMP_DIR/clonebox-boot.log" || echo "Log not found"
            ;;
        2)
            echo "📄 Monitor log:"
            echo "==============="
            [ -f "$TEMP_DIR/clonebox-monitor.log" ] && cat "$TEMP_DIR/clonebox-monitor.log" || echo "Log not found"
            ;;
        3)
            echo "📄 Cloud-init output log:"
            echo "========================"
            [ -f "$TEMP_DIR/cloud-init-output.log" ] && cat "$TEMP_DIR/cloud-init-output.log" || echo "Log not found"
            ;;
        4)
            echo "📄 Cloud-init log:"
            echo "=================="
            [ -f "$TEMP_DIR/cloud-init.log" ] && cat "$TEMP_DIR/cloud-init.log" || echo "Log not found"
            ;;
        5)
            echo "📊 Logs summary:"
            echo "================"
            echo "Boot log ($(wc -l < "$TEMP_DIR/clonebox-boot.log" 2>/dev/null || echo 0) lines):"
            tail -20 "$TEMP_DIR/clonebox-boot.log" 2>/dev/null || echo "Not found"
            echo ""
            echo "Monitor log ($(wc -l < "$TEMP_DIR/clonebox-monitor.log" 2>/dev/null || echo 0) lines):"
            tail -10 "$TEMP_DIR/clonebox-monitor.log" 2>/dev/null || echo "Not found"
            echo ""
            echo "Cloud-init output log ($(wc -l < "$TEMP_DIR/cloud-init-output.log" 2>/dev/null || echo 0) lines):"
            tail -10 "$TEMP_DIR/cloud-init-output.log" 2>/dev/null || echo "Not found"
            ;;
        6)
            echo "📄 All logs:"
            echo "============"
            echo ""
            echo "--- Boot diagnostic log ---"
            cat "$TEMP_DIR/clonebox-boot.log"
            echo ""
            echo "--- Monitor log ---"
            cat "$TEMP_DIR/clonebox-monitor.log"
            echo ""
            echo "--- Cloud-init output log (last 100 lines) ---"
            cat "$TEMP_DIR/cloud-init-output.log"
            echo ""
            echo "--- Cloud-init log (last 100 lines) ---"
            cat "$TEMP_DIR/cloud-init.log"
            echo ""
            echo "--- Browser logs ---"
            echo "Browser journal logs:"
            cat "$TEMP_DIR/browser-journal.log" 2>/dev/null || echo "No browser journal logs"
            echo ""
            echo "Snap packages:"
            cat "$TEMP_DIR/snap-list.log" 2>/dev/null || echo "No snap list"
            echo ""
            echo "Browser profiles:"
            cat "$TEMP_DIR/browser-profiles.log" 2>/dev/null || echo "No browser profiles"
            echo ""
            echo "Browser processes:"
            cat "$TEMP_DIR/browser-processes.log" 2>/dev/null || echo "No browser processes"
            ;;
        7)
            echo "🌐 Browser logs:"
            echo "================"
            echo ""
            echo "Browser journal logs ($(wc -l < "$TEMP_DIR/browser-journal.log" 2>/dev/null || echo 0) lines):"
            cat "$TEMP_DIR/browser-journal.log" 2>/dev/null || echo "No browser journal logs"
            echo ""
            echo "Snap browser packages:"
            cat "$TEMP_DIR/snap-list.log" 2>/dev/null || echo "No snap list"
            echo ""
            echo "Browser profile paths:"
            cat "$TEMP_DIR/browser-profiles.log" 2>/dev/null || echo "No browser profiles"
            echo ""
            echo "Running browser processes:"
            cat "$TEMP_DIR/browser-processes.log" 2>/dev/null || echo "No browser processes running"
            ;;
        8)
            echo "👋 Exiting..."
            exit 0
            ;;
        *)
            echo "Invalid option"
            ;;
    esac
    
    exit 0
fi

# For system session, use the original disk mounting approach
MOUNT_POINT="/mnt/clonebox-logs"

# Check if logs disk exists
if [ ! -f "$LOGS_DISK" ]; then
    echo "❌ Logs disk not found: $LOGS_DISK"
    echo "   The VM might not have the logs feature enabled."
    exit 1
fi

# Create mount point
sudo mkdir -p "$MOUNT_POINT"

# Mount logs disk
echo "📂 Mounting logs disk..."
if ! sudo mount -o loop "$LOGS_DISK" "$MOUNT_POINT" 2>/dev/null; then
    echo "❌ Failed to mount logs disk"
    exit 1
fi

echo "✅ Logs mounted at $MOUNT_POINT"
echo ""

# Show available logs
echo "📋 Available logs:"
echo "-------------------"
if [ -d "$MOUNT_POINT/var/log" ]; then
    ls -la "$MOUNT_POINT/var/log/" | grep clonebox
fi
if [ -d "$MOUNT_POINT/tmp" ]; then
    ls -la "$MOUNT_POINT/tmp/" | grep error
fi
echo ""

# Menu
echo "What would you like to view?"
echo "1) Boot diagnostic log"
echo "2) Monitor log"
echo "3) Error logs"
echo "4) All logs summary"
echo "5) Open shell in logs directory"
echo "6) Unmount and exit"
echo ""

read -p "Select option: " choice

case "$choice" in
    1)
        echo "📄 Boot diagnostic log:"
        echo "======================"
        if [ -f "$MOUNT_POINT/var/log/clonebox-boot.log" ]; then
            less "$MOUNT_POINT/var/log/clonebox-boot.log"
        else
            echo "Log not found"
        fi
        ;;
    2)
        echo "📄 Monitor log:"
        echo "==============="
        if [ -f "$MOUNT_POINT/var/log/clonebox-monitor.log" ]; then
            less "$MOUNT_POINT/var/log/clonebox-monitor.log"
        else
            echo "Log not found"
        fi
        ;;
    3)
        echo "📄 Error logs:"
        echo "=============="
        for log in "$MOUNT_POINT/tmp"/*-error.log; do
            if [ -f "$log" ]; then
                echo "--- $(basename "$log") ---"
                cat "$log"
                echo ""
            fi
        done
        ;;
    4)
        echo "📊 Logs summary:"
        echo "================"
        echo "Boot log ($(wc -l < "$MOUNT_POINT/var/log/clonebox-boot.log" 2>/dev/null || echo 0) lines):"
        tail -20 "$MOUNT_POINT/var/log/clonebox-boot.log" 2>/dev/null || echo "Not found"
        echo ""
        echo "Monitor log ($(wc -l < "$MOUNT_POINT/var/log/clonebox-monitor.log" 2>/dev/null || echo 0) lines):"
        tail -10 "$MOUNT_POINT/var/log/clonebox-monitor.log" 2>/dev/null || echo "Not found"
        ;;
    5)
        echo "📂 Opening shell in logs directory..."
        sudo bash -c "cd '$MOUNT_POINT' && exec bash"
        ;;
    6)
        echo "👋 Unmounting..."
        sudo umount "$MOUNT_POINT"
        exit 0
        ;;
    *)
        echo "Invalid option"
        ;;
esac

# Unmount on exit
echo ""
echo "👋 Unmounting logs disk..."
sudo umount "$MOUNT_POINT"
