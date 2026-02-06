#!/bin/bash
# Enhanced CloneBox Logs Helper - Access VM logs from host with comprehensive diagnostics

VM_NAME="${1:-clone-clonebox}"
USER_SESSION="${2:-false}"
SHOW_ALL="${3:-false}"
FOLLOW="${4:-false}"

if [ "$USER_SESSION" = "true" ]; then
    CONNECT="qemu:///session"
    # For user sessions, we'll use QEMU Guest Agent to fetch logs
    USE_QGA=true
else
    CONNECT="qemu:///system"
    LOGS_DISK="/var/lib/libvirt/images/clonebox-logs.qcow2"
    USE_QGA=false
fi

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'
BOLD='\033[1m'

# Helper functions
log() { echo -e "${CYAN}[INFO]${NC} $1"; }
ok() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
section() { echo -e "\n${BOLD}=== $1 ===${NC}"; }
highlight() { echo -e "${BLUE}$1${NC}"; }

echo -e "${BOLD}CloneBox Enhanced Log Viewer${NC}"
echo "============================="
echo "VM: $VM_NAME"
echo "Connection: $CONNECT"
echo "Mode: $([ "$USER_SESSION" = "true" ] && echo "User Session" || echo "System Session")"
echo ""

# Check if VM is running
if ! virsh --connect "$CONNECT" domstate "$VM_NAME" | grep -q "running"; then
    fail "VM is not running!"
    echo ""
    echo "To start the VM:"
    echo "  virsh --connect $CONNECT start $VM_NAME"
    echo "  or: clonebox start $VM_NAME"
    exit 1
fi

# Get VM info
section "VM Quick Status"
VM_INFO=$(virsh --connect "$CONNECT" dominfo "$VM_NAME" 2>/dev/null)
echo "$VM_INFO" | grep -E "(State|CPU|Memory)" | sed 's/^/  /'

# For user session, use QEMU Guest Agent to fetch logs
if [ "$USE_QGA" = "true" ]; then
    highlight "📋 Fetching logs via QEMU Guest Agent (SSH fallback if needed)..."
    echo ""
    
    # Create temp directory for logs
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT
    
    # Fetch logs using QGA
    SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
    python3 "$SCRIPT_DIR/fetch-logs-enhanced.py" "$VM_NAME" "$CONNECT" "$TEMP_DIR"
    
    echo ""
    section "Available Logs"
    ls -la "$TEMP_DIR/" | grep -v "^total" | awk '{print "  " $9 " (" $5 " bytes)"}'
    
    # Get additional diagnostic info
    section "System Status Summary"
    
    # Check cloud-init status
    if [ -f "$TEMP_DIR/cloud-init-status" ]; then
        log "Cloud-init status:"
        cat "$TEMP_DIR/cloud-init-status" | sed 's/^/  /'
    fi
    
    # Check service status
    if [ -f "$TEMP_DIR/services-status" ]; then
        log "Key services status:"
        cat "$TEMP_DIR/services-status" | sed 's/^/  /'
    fi
    
    # Check recent errors
    if [ -f "$TEMP_DIR/recent-errors" ]; then
        log "Recent errors (last 10):"
        cat "$TEMP_DIR/recent-errors" | sed 's/^/  /'
    fi
    
    # If FOLLOW is true, tail the logs
    if [ "$FOLLOW" = "true" ]; then
        section "Live Log Monitoring"
        echo "Press Ctrl+C to stop monitoring..."
        echo ""
        
        # Monitor cloud-init output if it's still running
        if grep -q "running" "$TEMP_DIR/cloud-init-status" 2>/dev/null; then
            highlight "Monitoring cloud-init output..."
            ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes \
                -i "$HOME/.local/share/libvirt/images/$VM_NAME/ssh_key" \
                -p "$(cat "$HOME/.local/share/libvirt/images/$VM_NAME/ssh_port" 2>/dev/null || echo 22)" \
                ubuntu@127.0.0.1 "sudo tail -f /var/log/cloud-init-output.log" 2>/dev/null || \
                warn "Cannot monitor cloud-init logs"
        else
            highlight "Monitoring system logs..."
            ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes \
                -i "$HOME/.local/share/libvirt/images/$VM_NAME/ssh_key" \
                -p "$(cat "$HOME/.local/share/libvirt/images/$VM_NAME/ssh_port" 2>/dev/null || echo 22)" \
                ubuntu@127.0.0.1 "sudo tail -f /var/log/syslog" 2>/dev/null || \
                warn "Cannot monitor system logs"
        fi
        exit 0
    fi
    
    # If SHOW_ALL is true, display all logs and exit
    if [ "$SHOW_ALL" = "true" ]; then
        section "Complete Log Dump"
        echo ""
        
        for log_file in "$TEMP_DIR"/*.log; do
            if [ -f "$log_file" ]; then
                basename=$(basename "$log_file" .log)
                echo -e "${MAGENTA}--- $basename ---${NC}"
                cat "$log_file"
                echo ""
            fi
        done
        
        # Show additional diagnostics
        if [ -f "$TEMP_DIR/disk-usage" ]; then
            echo -e "${MAGENTA}--- Disk Usage ---${NC}"
            cat "$TEMP_DIR/disk-usage"
            echo ""
        fi
        
        if [ -f "$TEMP_DIR/network-info" ]; then
            echo -e "${MAGENTA}--- Network Info ---${NC}"
            cat "$TEMP_DIR/network-info"
            echo ""
        fi
        
        exit 0
    fi
    
    # Interactive menu
    echo ""
    section "Log Selection Menu"
    echo "What would you like to view?"
    echo "1) Boot diagnostic log"
    echo "2) Monitor log"
    echo "3) Cloud-init output log"
    echo "4) Cloud-init log"
    echo "5) System log (last 100 lines)"
    echo "6) Service status"
    echo "7) Recent errors only"
    echo "8) Performance metrics"
    echo "9) Network configuration"
    echo "10) All logs summary"
    echo "11) Show all logs at once"
    echo "12) Export logs to file"
    echo "13) Follow live logs"
    echo "14) Exit"
    echo ""
    
    read -p "Select option: " choice
    echo ""
    
    case "$choice" in
        1)
            echo -e "${MAGENTA}📄 Boot diagnostic log:${NC}"
            echo "======================"
            [ -f "$TEMP_DIR/clonebox-boot.log" ] && cat "$TEMP_DIR/clonebox-boot.log" || echo "Log not found"
            ;;
        2)
            echo -e "${MAGENTA}📄 Monitor log:${NC}"
            echo "==============="
            [ -f "$TEMP_DIR/clonebox-monitor.log" ] && cat "$TEMP_DIR/clonebox-monitor.log" || echo "Log not found"
            ;;
        3)
            echo -e "${MAGENTA}📄 Cloud-init output log:${NC}"
            echo "========================"
            [ -f "$TEMP_DIR/cloud-init-output.log" ] && cat "$TEMP_DIR/cloud-init-output.log" || echo "Log not found"
            ;;
        4)
            echo -e "${MAGENTA}📄 Cloud-init log:${NC}"
            echo "=================="
            [ -f "$TEMP_DIR/cloud-init.log" ] && cat "$TEMP_DIR/cloud-init.log" || echo "Log not found"
            ;;
        5)
            echo -e "${MAGENTA}📄 System log:${NC}"
            echo "============="
            [ -f "$TEMP_DIR/syslog" ] && cat "$TEMP_DIR/syslog" || echo "Log not found"
            ;;
        6)
            echo -e "${MAGENTA}📊 Service status:${NC}"
            echo "=================="
            [ -f "$TEMP_DIR/services-status" ] && cat "$TEMP_DIR/services-status" || echo "Status not found"
            ;;
        7)
            echo -e "${MAGENTA}❌ Recent errors:${NC}"
            echo "=================="
            [ -f "$TEMP_DIR/recent-errors" ] && cat "$TEMP_DIR/recent-errors" || echo "No errors found"
            ;;
        8)
            echo -e "${MAGENTA}📈 Performance metrics:${NC}"
            echo "======================"
            [ -f "$TEMP_DIR/performance" ] && cat "$TEMP_DIR/performance" || echo "Metrics not found"
            ;;
        9)
            echo -e "${MAGENTA}🌐 Network configuration:${NC}"
            echo "========================"
            [ -f "$TEMP_DIR/network-info" ] && cat "$TEMP_DIR/network-info" || echo "Network info not found"
            ;;
        10)
            echo -e "${MAGENTA}📊 Logs summary:${NC}"
            echo "================"
            for log_file in "$TEMP_DIR"/*.log; do
                if [ -f "$log_file" ]; then
                    basename=$(basename "$log_file" .log)
                    lines=$(wc -l < "$log_file" 2>/dev/null || echo 0)
                    echo "$basename log ($lines lines):"
                    tail -5 "$log_file" 2>/dev/null | sed 's/^/  /' || echo "  Not readable"
                    echo ""
                fi
            done
            ;;
        11)
            echo -e "${MAGENTA}📄 All logs:${NC}"
            echo "============"
            echo ""
            for log_file in "$TEMP_DIR"/*.log; do
                if [ -f "$log_file" ]; then
                    basename=$(basename "$log_file" .log)
                    echo -e "${MAGENTA}--- $basename ---${NC}"
                    cat "$log_file"
                    echo ""
                fi
            done
            ;;
        12)
            echo -e "${MAGENTA}💾 Exporting logs...${NC}"
            EXPORT_FILE="${VM_NAME}-logs-$(date +%Y%m%d-%H%M%S).tar.gz"
            tar -czf "$EXPORT_FILE" -C "$TEMP_DIR" .
            ok "Logs exported to: $EXPORT_FILE"
            echo "File size: $(du -h "$EXPORT_FILE" | cut -f1)"
            ;;
        13)
            log "Starting live log monitoring..."
            log "Use Ctrl+C to stop"
            exec "$0" "$VM_NAME" "$USER_SESSION" "false" "true"
            ;;
        14)
            echo "👋 Exiting..."
            exit 0
            ;;
        *)
            fail "Invalid option"
            ;;
    esac
    
    exit 0
fi

# For system session, use the original disk mounting approach
MOUNT_POINT="/mnt/clonebox-logs"

# Check if logs disk exists
if [ ! -f "$LOGS_DISK" ]; then
    fail "Logs disk not found: $LOGS_DISK"
    echo "   The VM might not have the logs feature enabled."
    exit 1
fi

# Create mount point
sudo mkdir -p "$MOUNT_POINT"

# Mount logs disk
log "📂 Mounting logs disk..."
if ! sudo mount -o loop "$LOGS_DISK" "$MOUNT_POINT" 2>/dev/null; then
    fail "Failed to mount logs disk"
    exit 1
fi

ok "Logs mounted at $MOUNT_POINT"
echo ""

# Show available logs
section "Available Logs"
if [ -d "$MOUNT_POINT/var/log" ]; then
    ls -la "$MOUNT_POINT/var/log/" | grep -E "(clonebox|cloud-init|syslog)" | awk '{print "  " $9 " (" $5 " bytes)"}'
fi
if [ -d "$MOUNT_POINT/tmp" ]; then
    ls -la "$MOUNT_POINT/tmp/" | grep error | awk '{print "  " $9 " (" $5 " bytes)"}'
fi

# Enhanced menu for system session
echo ""
section "Log Selection Menu"
echo "What would you like to view?"
echo "1) Boot diagnostic log"
echo "2) Monitor log"
echo "3) Cloud-init logs"
echo "4) System logs"
echo "5) Error logs"
echo "6) All logs summary"
echo "7) Open shell in logs directory"
echo "8) Export logs"
echo "9) Unmount and exit"
echo ""

read -p "Select option: " choice

case "$choice" in
    1)
        echo -e "${MAGENTA}📄 Boot diagnostic log:${NC}"
        echo "======================"
        if [ -f "$MOUNT_POINT/var/log/clonebox-boot.log" ]; then
            less "$MOUNT_POINT/var/log/clonebox-boot.log"
        else
            echo "Log not found"
        fi
        ;;
    2)
        echo -e "${MAGENTA}📄 Monitor log:${NC}"
        echo "==============="
        if [ -f "$MOUNT_POINT/var/log/clonebox-monitor.log" ]; then
            less "$MOUNT_POINT/var/log/clonebox-monitor.log"
        else
            echo "Log not found"
        fi
        ;;
    3)
        echo -e "${MAGENTA}📄 Cloud-init logs:${NC}"
        echo "=================="
        for log in "$MOUNT_POINT/var/log"/cloud-init*.log; do
            if [ -f "$log" ]; then
                echo "--- $(basename "$log") ---"
                less "$log"
            fi
        done
        ;;
    4)
        echo -e "${MAGENTA}📄 System logs:${NC}"
        echo "=============="
        for log in "$MOUNT_POINT/var/log"/{syslog,kern.log,auth.log}; do
            if [ -f "$log" ]; then
                echo "--- $(basename "$log") (last 100 lines) ---"
                tail -100 "$log"
                echo ""
            fi
        done
        ;;
    5)
        echo -e "${MAGENTA}❌ Error logs:${NC}"
        echo "=============="
        for log in "$MOUNT_POINT/tmp"/*-error.log; do
            if [ -f "$log" ]; then
                echo "--- $(basename "$log") ---"
                cat "$log"
                echo ""
            fi
        done
        ;;
    6)
        echo -e "${MAGENTA}📊 Logs summary:${NC}"
        echo "================"
        for log in "$MOUNT_POINT/var/log"/clonebox*.log; do
            if [ -f "$log" ]; then
                basename=$(basename "$log" .log)
                lines=$(wc -l < "$log" 2>/dev/null || echo 0)
                echo "$basename log ($lines lines):"
                tail -20 "$log" 2>/dev/null | sed 's/^/  /' || echo "  Not readable"
                echo ""
            fi
        done
        ;;
    7)
        echo -e "${MAGENTA}📂 Opening shell in logs directory...${NC}"
        sudo bash -c "cd '$MOUNT_POINT' && exec bash"
        ;;
    8)
        echo -e "${MAGENTA}💾 Exporting logs...${NC}"
        EXPORT_FILE="${VM_NAME}-logs-$(date +%Y%m%d-%H%M%S).tar.gz"
        sudo tar -czf "$EXPORT_FILE" -C "$MOUNT_POINT" var/log/ tmp/
        sudo chown "$USER:$USER" "$EXPORT_FILE"
        ok "Logs exported to: $EXPORT_FILE"
        echo "File size: $(du -h "$EXPORT_FILE" | cut -f1)"
        ;;
    9)
        echo -e "${MAGENTA}👋 Unmounting...${NC}"
        sudo umount "$MOUNT_POINT"
        exit 0
        ;;
    *)
        fail "Invalid option"
        ;;
esac

# Unmount on exit
echo ""
echo -e "${MAGENTA}👋 Unmounting logs disk...${NC}"
sudo umount "$MOUNT_POINT"
