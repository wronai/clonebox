#!/bin/bash
# CloneBox Comprehensive Health Check - Fixed version

set -e

# Configuration
VM_NAME="${1:-clone-clonebox}"
USER_SESSION="${2:-true}"
OUTPUT_DIR="${HOME}/.local/share/clonebox/reports"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$OUTPUT_DIR/${VM_NAME}-health-${TIMESTAMP}"

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Helper functions
log() { echo -e "${CYAN}[INFO]${NC} $1"; }
ok() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[⚠]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; }
section() { echo -e "\n${BOLD}=== $1 ===${NC}"; }

# Initialize report directory
mkdir -p "$REPORT_DIR"
SUMMARY_FILE="$REPORT_DIR/summary.txt"
ISSUES_FILE="$REPORT_DIR/issues.txt"

# Initialize summary
cat > "$SUMMARY_FILE" << EOF
CloneBox VM Health Check Report
===============================
VM: $VM_NAME
Timestamp: $(date)
User Session: $USER_SESSION
================================

EOF

# Initialize issues tracker
echo "Identified Issues:" > "$ISSUES_FILE"
echo "==================" >> "$ISSUES_FILE"
echo "" >> "$ISSUES_FILE"

clear
echo -e "${BOLD}CloneBox Comprehensive Health Check${NC}"
echo "======================================"
echo "VM: $VM_NAME"
echo "Report Directory: $REPORT_DIR"
echo ""

# Track issues count
ISSUES_COUNT=0
WARNINGS_COUNT=0

# Function to add issue
add_issue() {
    local severity=$1
    local component=$2
    local description=$3
    local suggestion=$4
    
    echo "[$severity] $component: $description" >> "$ISSUES_FILE"
    echo "  Suggestion: $suggestion" >> "$ISSUES_FILE"
    echo "" >> "$ISSUES_FILE"
    
    if [ "$severity" = "CRITICAL" ]; then
        ISSUES_COUNT=$((ISSUES_COUNT + 1))
        fail "$component: $description"
    elif [ "$severity" = "WARNING" ]; then
        WARNINGS_COUNT=$((WARNINGS_COUNT + 1))
        warn "$component: $description"
    fi
}

# Function to add success
add_success() {
    local component=$1
    local description=$2
    
    ok "$component: $description"
    echo "[OK] $component: $description" >> "$SUMMARY_FILE"
}

section "1. Basic VM Status Check"
log "Checking VM basic status..."

# Get VM info
if virsh --connect "qemu:///session" dominfo "$VM_NAME" &>/dev/null; then
    VM_STATE=$(virsh --connect "qemu:///session" domstate "$VM_NAME" 2>/dev/null)
    if [ "$VM_STATE" = "running" ]; then
        add_success "VM State" "VM is running"
    else
        add_issue "CRITICAL" "VM State" "VM is not running (state: $VM_STATE)" "Run: clonebox start $VM_NAME --user"
    fi
    
    # Get VM resources
    VM_INFO=$(virsh --connect "qemu:///session" dominfo "$VM_NAME" 2>/dev/null)
    echo "$VM_INFO" | grep -E "(CPU|Memory)" | tee -a "$SUMMARY_FILE" | sed 's/^/  /'
else
    add_issue "CRITICAL" "VM Existence" "VM not found" "Run: clonebox clone . --user --run"
fi

section "2. Network Connectivity Analysis"
log "Analyzing network configuration..."

# Check SSH port
VM_DIR="${HOME}/.local/share/libvirt/images/${VM_NAME}"
if [ -f "$VM_DIR/ssh_port" ]; then
    SSH_PORT=$(cat "$VM_DIR/ssh_port")
    if ss -tlnp 2>/dev/null | grep -q ":$SSH_PORT"; then
        add_success "SSH Port" "Port $SSH_PORT is listening"
        
        # Test SSH connectivity
        if nc -zw2 127.0.0.1 "$SSH_PORT" 2>/dev/null; then
            add_success "SSH Connectivity" "SSH connection test passed"
        else
            add_issue "CRITICAL" "SSH Connectivity" "Cannot connect to SSH port" "Check VM network and SSH service"
        fi
    else
        add_issue "CRITICAL" "SSH Port" "Port $SSH_PORT not listening" "Check VM network configuration"
    fi
else
    add_issue "WARNING" "SSH Configuration" "SSH port file not found" "VM may still be booting"
fi

# Check passt process
if pgrep -a passt | grep -q "$VM_NAME"; then
    add_success "Network" "passt networking is running"
else
    add_issue "WARNING" "Network" "passt process not found" "Network may not work properly"
fi

# Check display ports
for port in 5900 5901; do
    if ss -tlnp 2>/dev/null | grep -q ":$port"; then
        add_success "Display Port" "Port $port (SPICE/VNC) is listening"
        break
    fi
done

section "3. QEMU Guest Agent Check"
log "Testing QEMU Guest Agent..."

if virsh --connect "qemu:///session" qemu-agent-command "$VM_NAME" '{"execute":"guest-ping"}' &>/dev/null; then
    add_success "QEMU Guest Agent" "Agent is responding"
else
    add_issue "WARNING" "QEMU Guest Agent" "Agent not responding" "VM may still be booting or qemu-guest-agent not installed"
fi

section "4. Cloud-init Status"
log "Analyzing cloud-init progress..."

SERIAL_LOG="$VM_DIR/serial.log"
if [ -f "$SERIAL_LOG" ]; then
    # Check cloud-init completion
    if grep -q "Finished.*Cloud-init.*Final" "$SERIAL_LOG"; then
        add_success "Cloud-init" "Completed successfully"
    else
        # Check if still running
        if grep -q "Cloud-init.*running" "$SERIAL_LOG" | tail -5; then
            add_issue "WARNING" "Cloud-init" "Still running" "Wait for completion (can take 2-5 minutes)"
        else
            add_issue "CRITICAL" "Cloud-init" "Status unknown or failed" "Check: clonebox logs . --user --all"
        fi
    fi
else
    add_issue "WARNING" "Serial Log" "Not found or empty" "VM may still be starting"
fi

section "5. Resource Usage Analysis"
log "Analyzing resource utilization..."

# Host resources
HOST_CPU=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
HOST_MEM=$(free | grep Mem | awk '{printf "%.1f%%", $3/$2 * 100.0}')

echo "  Host CPU idle: ${HOST_CPU}%" | tee -a "$SUMMARY_FILE"
echo "  Host Memory used: $HOST_MEM" | tee -a "$SUMMARY_FILE"

# VM resources
QEMU_PID=$(ps aux | grep qemu | grep "$VM_NAME" | awk '{print $2}' | head -1)
if [ -n "$QEMU_PID" ]; then
    VM_CPU=$(ps -p "$QEMU_PID" -o %cpu= | tr -d ' ')
    VM_MEM_KB=$(ps -p "$QEMU_PID" -o rss= | tr -d ' ')
    VM_MEM=$((VM_MEM_KB / 1024))MB
    
    echo "  VM CPU usage: ${VM_CPU}%" | tee -a "$SUMMARY_FILE"
    echo "  VM Memory: $VM_MEM" | tee -a "$SUMMARY_FILE"
fi

# Disk usage
if [ -d "$VM_DIR" ]; then
    VM_DISK_SIZE=$(du -sh "$VM_DIR" | cut -f1)
    echo "  VM disk usage: $VM_DISK_SIZE" | tee -a "$SUMMARY_FILE"
fi

section "6. Running Enhanced Diagnostics"
log "Running comprehensive diagnostic tools..."

# Run enhanced diagnostic script
log "Running VM diagnostic analysis..."
if [ -f "$(dirname "$0")/diagnose-vm-enhanced.sh" ]; then
    "$(dirname "$0")/diagnose-vm-enhanced.sh" "$VM_NAME" > "$REPORT_DIR/diagnostic-output.txt" 2>&1
    add_success "Diagnostics" "Enhanced diagnostic completed"
else
    warn "Enhanced diagnostic script not found"
fi

# Run enhanced log fetcher
log "Fetching detailed logs..."
if [ -f "$(dirname "$0")/fetch-logs-enhanced.py" ]; then
    mkdir -p "$REPORT_DIR/logs"
    python3 "$(dirname "$0")/fetch-logs-enhanced.py" "$VM_NAME" "qemu:///session" "$REPORT_DIR/logs" 2>/dev/null
    add_success "Log Collection" "Enhanced logs fetched"
fi

section "7. Generating Health Summary"
log "Creating comprehensive summary..."

# Add summary statistics
cat >> "$SUMMARY_FILE" << EOF

Health Check Summary
===================
Critical Issues: $ISSUES_COUNT
Warnings: $WARNINGS_COUNT

EOF

# Add recommendations
if [ "$ISSUES_COUNT" -gt 0 ]; then
    cat >> "$SUMMARY_FILE" << EOF
RECOMMENDATIONS:
================
1. Address critical issues before proceeding
2. Run: clonebox repair . --user --auto
3. Check detailed logs: clonebox logs . --user --all
4. Monitor with: clonebox watch . --user

EOF
elif [ "$WARNINGS_COUNT" -gt 0 ]; then
    cat >> "$SUMMARY_FILE" << EOF
RECOMMENDATIONS:
================
1. VM is operational but has warnings
2. Review warnings for potential improvements
3. Consider running: clonebox repair . --user

EOF
else
    cat >> "$SUMMARY_FILE" << EOF
STATUS: HEALTHY
================
All checks passed successfully!
VM is ready for use.

EOF
fi

# Add quick commands
cat >> "$SUMMARY_FILE" << EOF
Quick Commands:
===============
- Connect: ssh -p ${SSH_PORT:-<port>} ubuntu@localhost
- GUI: remote-viewer spice://localhost:5900
- Logs: clonebox logs . --user --all
- Monitor: clonebox watch . --user
EOF

# Display final summary
echo ""
section "HEALTH CHECK COMPLETE"
echo ""

if [ "$ISSUES_COUNT" -eq 0 ] && [ "$WARNINGS_COUNT" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}✓ VM is HEALTHY - No issues detected!${NC}"
elif [ "$ISSUES_COUNT" -eq 0 ]; then
    echo -e "${YELLOW}${BOLD}⚠ VM is operational with $WARNINGS_COUNT warning(s)${NC}"
else
    echo -e "${RED}${BOLD}✗ VM has $ISSUES_COUNT critical issue(s) and $WARNINGS_COUNT warning(s)${NC}"
fi

echo ""
echo "Report saved to: $REPORT_DIR"
echo "Summary: $SUMMARY_FILE"
echo "Issues: $ISSUES_FILE"
echo ""

# Show top issues if any
if [ "$ISSUES_COUNT" -gt 0 ] || [ "$WARNINGS_COUNT" -gt 0 ]; then
    echo "Top Issues:"
    grep "^\[CRITICAL\]" "$ISSUES_FILE" | head -3 | sed 's/^\[CRITICAL\]/  /'
    grep "^\[WARNING\]" "$ISSUES_FILE" | head -2 | sed 's/^\[WARNING\]/  /'
    echo ""
    echo "For detailed analysis: less $ISSUES_FILE"
fi

# Suggest next steps
echo "Next Steps:"
if [ "$ISSUES_COUNT" -gt 0 ]; then
    echo "  1. Review critical issues: cat $ISSUES_FILE"
    echo "  2. Run repair: clonebox repair . --user --auto"
    echo "  3. Re-run health check: $0 $VM_NAME"
elif [ "$WARNINGS_COUNT" -gt 0 ]; then
    echo "  1. Review warnings: cat $ISSUES_FILE"
    echo "  2. Optional repair: clonebox repair . --user"
    echo "  3. Start using VM: clonebox open . --user"
else
    echo "  1. Start using VM: clonebox open . --user"
    echo "  2. Monitor with: clonebox watch . --user"
fi

echo ""
echo "Full diagnostic output: $REPORT_DIR/diagnostic-output.txt"
echo "Detailed logs: $REPORT_DIR/logs/"
