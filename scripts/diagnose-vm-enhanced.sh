#!/bin/bash
# Enhanced CloneBox VM Diagnostic Script with comprehensive analysis

set -e

VM_NAME="${1:-clone-clonebox}"
VM_DIR="${HOME}/.local/share/libvirt/images/${VM_NAME}"
CONN_URI="qemu:///session"
OUTPUT_FILE="${VM_NAME}-diagnostic-$(date +%Y%m%d-%H%M%S).txt"

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# Helper functions
log() { echo -e "${CYAN}[INFO]${NC} $1" | tee -a "$OUTPUT_FILE"; }
ok() { echo -e "${GREEN}[OK]${NC} $1" | tee -a "$OUTPUT_FILE"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1" | tee -a "$OUTPUT_FILE"; }
fail() { echo -e "${RED}[FAIL]${NC} $1" | tee -a "$OUTPUT_FILE"; }
section() { echo -e "\n${BOLD}=== $1 ===${NC}" | tee -a "$OUTPUT_FILE"; }
highlight() { echo -e "${BLUE}$1${NC}" | tee -a "$OUTPUT_FILE"; }

# Initialize output file
echo "CloneBox Enhanced VM Diagnostic Report" > "$OUTPUT_FILE"
echo "Generated: $(date)" >> "$OUTPUT_FILE"
echo "VM: $VM_NAME" >> "$OUTPUT_FILE"
echo "======================================" >> "$OUTPUT_FILE"
echo ""

clear
echo -e "${BOLD}CloneBox Enhanced VM Diagnostics${NC}"
echo "===================================="
echo "VM: $VM_NAME"
echo "Report will be saved to: $OUTPUT_FILE"
echo ""

section "VM Detailed Status"

# VM info
log "Basic VM information:"
virsh --connect "$CONN_URI" dominfo "$VM_NAME" 2>/dev/null | grep -E "(State|CPU|Memory|Autostart)" | tee -a "$OUTPUT_FILE" | sed 's/^/  /'

# QEMU process details
log "QEMU process details:"
QEMU_PID=$(ps aux | grep qemu | grep "$VM_NAME" | awk '{print $2}' | head -1)
if [ -n "$QEMU_PID" ]; then
    echo "  PID: $QEMU_PID" | tee -a "$OUTPUT_FILE"
    echo "  Command: $(ps -p $QEMU_PID -o cmd=)" | tee -a "$OUTPUT_FILE"
    echo "  Memory: $(ps -p $QEMU_PID -o rss= | awk '{print int($1/1024)"MB"}')" | tee -a "$OUTPUT_FILE"
    echo "  CPU: $(ps -p $QEMU_PID -o %cpu=)%" | tee -a "$OUTPUT_FILE"
else
    warn "QEMU process not found"
fi

# Network configuration deep dive
section "Network Deep Analysis"

log "Network configuration from QEMU:"
ps aux | grep qemu | grep "$VM_NAME" | grep -o "netdev[^ ]*" | head -1 | sed 's/^/  /' | tee -a "$OUTPUT_FILE"

log "All forwarded ports:"
ps aux | grep qemu | grep "$VM_NAME" | grep -o "hostfwd[^ ]*" | sed 's/,/\n/g' | sed 's/^/  /' | tee -a "$OUTPUT_FILE"

log "Host listening ports (relevant):"
ss -tlnp 2>/dev/null | grep -E "(5900|5901|22|2219[0-9])" | sed 's/^/  /' | tee -a "$OUTPUT_FILE"

# Check passt process
PASST_PROCS=$(pgrep -a passt | grep "$VM_NAME" || true)
if [ -n "$PASST_PROCS" ]; then
    ok "passt process found for VM"
    echo "$PASST_PROCS" | tee -a "$OUTPUT_FILE"
else
    warn "No passt process found for VM"
fi

# SSH configuration check
section "SSH Configuration Analysis"

if [ -f "$VM_DIR/ssh_port" ]; then
    SSH_PORT=$(cat "$VM_DIR/ssh_port")
    ok "SSH port configured: $SSH_PORT"
    
    # Check if port is listening
    if ss -tlnp 2>/dev/null | grep -q ":$SSH_PORT"; then
        ok "Port $SSH_PORT is listening"
        
        # Check what process is using it
        log "Process using port $SSH_PORT:"
        ss -tlnp 2>/dev/null | grep ":$SSH_PORT" | sed 's/^/  /' | tee -a "$OUTPUT_FILE"
    else
        fail "Port $SSH_PORT is not listening"
    fi
    
    # Test connectivity
    if nc -zw2 127.0.0.1 "$SSH_PORT" 2>/dev/null; then
        ok "TCP connection to port $SSH_PORT successful"
    else
        fail "TCP connection to port $SSH_PORT failed"
    fi
    
    # SSH key check
    if [ -f "$VM_DIR/ssh_key" ]; then
        ok "SSH key found"
        key_perms=$(stat -c "%a" "$VM_DIR/ssh_key")
        log "SSH key permissions: $key_perms"
        if [ "$key_perms" != "600" ] && [ "$key_perms" != "400" ]; then
            warn "SSH key should have permissions 600 or 400"
        fi
    else
        warn "SSH key not found"
    fi
else
    fail "SSH port file not found"
fi

# QEMU Guest Agent check
section "QEMU Guest Agent Analysis"

if virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-ping"}' &>/dev/null; then
    ok "QEMU guest agent is responding"
    
    # Get detailed guest info
    log "Guest OS information:"
    GUEST_OSINFO=$(virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-get-osinfo"}' 2>/dev/null)
    if [ -n "$GUEST_OSINFO" ]; then
        echo "$GUEST_OSINFO" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ret=d.get('return',{})
print(f\"  OS: {ret.get('name','unknown')} {ret.get('version','unknown')}\")
print(f\"  Kernel: {ret.get('kernel-release','unknown')}\")
print(f\"  Architecture: {ret.get('architecture','unknown')}\")
print(f\"  Hostname: {ret.get('hostname','unknown')}\")
" 2>/dev/null | tee -a "$OUTPUT_FILE"
    fi
    
    # Network interfaces
    log "Network interfaces in VM:"
    virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-network-get-interfaces"}' 2>/dev/null | \
    python3 -c "
import sys,json
d=json.load(sys.stdin)
for i in d.get('return',[]):
    if i.get('name') != 'lo':
        print(f\"  {i['name']}: {'UP' if i.get('hardware-address') else 'DOWN'}\")
        for a in i.get('ip-addresses',[]):
            if a.get('ip-address'):
                print(f\"    {a['ip-address']}/{a.get('prefix',0)} ({a.get('type','unknown')})\")
" 2>/dev/null | tee -a "$OUTPUT_FILE"
    
    # Time sync
    log "Time synchronization:"
    TIME_INFO=$(virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-get-time"}' 2>/dev/null)
    if [ -n "$TIME_INFO" ]; then
        GUEST_TIME=$(echo "$TIME_INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('return',0)//1000000000)" 2>/dev/null)
        HOST_TIME=$(date +%s)
        TIME_DIFF=$((GUEST_TIME - HOST_TIME))
        if [ ${TIME_DIFF#-} -lt 60 ]; then
            ok "Time sync: Guest and host time differ by ${TIME_DIFF}s"
        else
            warn "Time sync: Guest and host time differ by ${TIME_DIFF}s"
        fi
    fi
    
    # Disk usage
    log "Disk usage in VM:"
    virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-get-fsinfo"}' 2>/dev/null | \
    python3 -c "
import sys,json
d=json.load(sys.stdin)
for fs in d.get('return',[]):
    if fs.get('mountpoint'):
        total = fs.get('bytes', {}).get('total', 0)
        used = fs.get('bytes', {}).get('used', 0)
        if total > 0:
            pct = int(used / total * 100)
            print(f\"  {fs['mountpoint']}: {used//1024//1024}MB / {total//1024//1024}MB ({pct}%)\")
" 2>/dev/null | tee -a "$OUTPUT_FILE"
    
else
    fail "QEMU guest agent not responding"
    log "Possible reasons:"
    log "  - VM still booting (cloud-init installing qemu-guest-agent)"
    log "  - qemu-guest-agent service not started"
    log "  - VM crashed or frozen"
fi

# Serial log analysis
section "Serial Log Deep Analysis"

SERIAL_LOG="$VM_DIR/serial.log"
if [ -f "$SERIAL_LOG" ] && [ -s "$SERIAL_LOG" ]; then
    LOG_LINES=$(wc -l < "$SERIAL_LOG")
    LOG_SIZE=$(du -h "$SERIAL_LOG" | cut -f1)
    log "Serial log: $LOG_LINES lines, $LOG_SIZE"
    
    # Boot timeline
    log "Boot timeline analysis:"
    echo "" | tee -a "$OUTPUT_FILE"
    grep -E "(Linux version|Welcome to|cloud-init.*running|Reached target)" "$SERIAL_LOG" | \
    sed 's/\[.*\]//' | tee -a "$OUTPUT_FILE" | sed 's/^/  /'
    
    # Cloud-init progress
    log "Cloud-init progress:"
    CLOUD_INIT_STEPS=$(grep -E "(Cloud-init.*running|modules:|Finished.*Cloud-init)" "$SERIAL_LOG" | tail -10)
    if [ -n "$CLOUD_INIT_STEPS" ]; then
        echo "$CLOUD_INIT_STEPS" | sed 's/^/  /' | tee -a "$OUTPUT_FILE"
    else
        warn "No cloud-init progress found"
    fi
    
    # Package installation
    log "Package installation status:"
    PKG_STATUS=$(grep -E "(Installing packages|apt-get|packages installed)" "$SERIAL_LOG" | tail -5)
    if [ -n "$PKG_STATUS" ]; then
        echo "$PKG_STATUS" | sed 's/^/  /' | tee -a "$OUTPUT_FILE"
    else
        log "No package installation logs found"
    fi
    
    # Error analysis
    log "Error analysis:"
    ERROR_COUNT=$(grep -icE "(error|fail|warn|timeout)" "$SERIAL_LOG" | head -1)
    if [ "$ERROR_COUNT" -gt 0 ]; then
        warn "Found $ERROR_COUNT potential errors/warnings"
        echo "Recent errors:" | tee -a "$OUTPUT_FILE"
        grep -iE "(error|fail|warn|timeout)" "$SERIAL_LOG" | tail -5 | sed 's/^/  /' | tee -a "$OUTPUT_FILE"
    else
        ok "No errors found in serial log"
    fi
    
    # Service startup analysis
    log "Service startup analysis:"
    echo "" | tee -a "$OUTPUT_FILE"
    grep -E "(Started|Finished).*service" "$SERIAL_LOG" | tail -10 | sed 's/^/  /' | tee -a "$OUTPUT_FILE"
    
else
    warn "Serial log not found or empty"
fi

# Performance analysis
section "Performance Analysis"

# Host resources
log "Host resource utilization:"
echo "  CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)% idle" | tee -a "$OUTPUT_FILE"
echo "  Memory: $(free -h | grep Mem | awk '{print $3"/"$2 " ("$5")"}')" | tee -a "$OUTPUT_FILE"
echo "  Load average: $(uptime | awk -F'load average:' '{print $2}')" | tee -a "$OUTPUT_FILE"

# VM resources
if [ -n "$QEMU_PID" ]; then
    log "VM resource usage:"
    echo "  Process CPU: $(ps -p $QEMU_PID -o %cpu=)%" | tee -a "$OUTPUT_FILE"
    echo "  Process Memory: $(ps -p $QEMU_PID -o rss= | awk '{print int($1/1024)"MB"}')" | tee -a "$OUTPUT_FILE"
    echo "  Process Time: $(ps -p $QEMU_PID -o etime= | tr -d ' ')" | tee -a "$OUTPUT_FILE"
fi

# I/O analysis
log "I/O statistics:"
if command -v iostat &>/dev/null; then
    iostat -x 1 1 | grep -E "(Device|$VM_DIR)" | head -5 | sed 's/^/  /' | tee -a "$OUTPUT_FILE"
else
    log "iostat not available for I/O analysis"
fi

# GUI/Desktop analysis
section "GUI/Desktop Environment Analysis"

# Check if we can query via SSH/QGA
if [ -f "$VM_DIR/ssh_key" ] && [ -f "$VM_DIR/ssh_port" ]; then
    SSH_PORT=$(cat "$VM_DIR/ssh_port")
    
    log "Desktop environment status:"
    DESKTOP_STATUS=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes \
        -i "$VM_DIR/ssh_key" -p "$SSH_PORT" ubuntu@127.0.0.1 \
        "echo 'Desktop: '\$XDG_CURRENT_DESKTOP; echo 'Session: '\$XDG_SESSION_TYPE; \
        systemctl is-active gdm3 gdm sddm lightdm 2>/dev/null | head -1" 2>/dev/null || echo "Query failed")
    
    echo "$DESKTOP_STATUS" | sed 's/^/  /' | tee -a "$OUTPUT_FILE"
    
    # Check display server
    log "Display server information:"
    DISPLAY_INFO=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes \
        -i "$VM_DIR/ssh_key" -p "$SSH_PORT" ubuntu@127.0.0.1 \
        "ps aux | grep -E '(Xorg|Wayland)' | grep -v grep | head -3" 2>/dev/null || echo "No display server found")
    
    if [ -n "$DISPLAY_INFO" ]; then
        echo "$DISPLAY_INFO" | sed 's/^/  /' | tee -a "$OUTPUT_FILE"
        ok "Display server is running"
    else
        warn "No display server detected"
    fi
    
    # Check SPICE/VNC ports
    log "Graphics display ports:"
    for port in 5900 5901; do
        if ss -tlnp 2>/dev/null | grep -q ":$port"; then
            ok "Port $port is listening ($(ss -tlnp | grep ":$port" | grep qemu | head -1 | awk '{print $7}'))"
        else
            warn "Port $port not listening"
        fi
    done
else
    warn "Cannot check GUI status - SSH not available"
fi

# Security analysis
section "Security Analysis"

log "SSH configuration security:"
if [ -f "$VM_DIR/ssh_key" ]; then
    KEY_TYPE=$(ssh-keygen -l -f "$VM_DIR/ssh_key.pub" 2>/dev/null | awk '{print $4}')
    echo "  Key type: $KEY_TYPE" | tee -a "$OUTPUT_FILE"
    
    # Check if key is encrypted
    if grep -q "ENCRYPTED" "$VM_DIR/ssh_key" 2>/dev/null; then
        ok "SSH private key is encrypted"
    else
        warn "SSH private key is not encrypted"
    fi
fi

log "VM isolation check:"
# Check if VM is using user session (more isolated)
if [ "$CONN_URI" = "qemu:///session" ]; then
    ok "VM running in user session (better isolation)"
else
    warn "VM running in system session (higher privileges)"
fi

# Check network isolation
if pgrep -q "passt.*$VM_NAME"; then
    ok "VM using passt (user-mode networking)"
else
    warn "VM may be using bridged networking (less isolated)"
fi

# Recommendations section
section "Analysis Summary & Recommendations"

# Generate summary
ISSUES_FOUND=0

echo "" | tee -a "$OUTPUT_FILE"
log "Summary of findings:" | tee -a "$OUTPUT_FILE"

# Check critical services
if ! pgrep -q "passt.*$VM_NAME" && [ "$CONN_URI" = "qemu:///session" ]; then
    warn "• passt networking not running - network may not work"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
fi

if ! virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-ping"}' &>/dev/null; then
    warn "• QEMU Guest Agent not responding - limited monitoring"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
fi

if [ -f "$VM_DIR/ssh_port" ] && ! ss -tlnp 2>/dev/null | grep -q ":$(cat $VM_DIR/ssh_port)"; then
    warn "• SSH port not accessible - connectivity issues"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
fi

# Check serial log for cloud-init completion
if [ -f "$SERIAL_LOG" ]; then
    if ! grep -q "Finished.*Cloud-init.*Final" "$SERIAL_LOG"; then
        warn "• Cloud-init may not have completed successfully"
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
    fi
fi

if [ "$ISSUES_FOUND" -eq 0 ]; then
    ok "• No critical issues detected"
else
    warn "• Found $ISSUES_FOUND issue(s) requiring attention"
fi

echo "" | tee -a "$OUTPUT_FILE"
log "Recommendations:" | tee -a "$OUTPUT_FILE"

cat << 'EOF' | tee -a "$OUTPUT_FILE"
1. If cloud-init is still running, wait for completion (2-5 minutes)
2. For network issues, check: clonebox logs . --user --all
3. For GUI issues, try: remote-viewer spice://localhost:5900
4. For SSH issues, verify key permissions: chmod 600 ~/.local/share/libvirt/images/<vm>/ssh_key
5. Monitor performance with: clonebox watch . --user
6. Full validation: clonebox test . --user --validate --smoke-test
EOF

# Quick commands reference
section "Quick Commands Reference"

echo "" | tee -a "$OUTPUT_FILE"
echo "Useful commands for this VM:" | tee -a "$OUTPUT_FILE"
echo "  Connect via SSH:     ssh -p ${SSH_PORT:-<port>} ubuntu@localhost" | tee -a "$OUTPUT_FILE"
echo "  View GUI:           remote-viewer spice://localhost:5900" | tee -a "$OUTPUT_FILE"
echo "  Console access:     virsh --connect $CONN_URI console $VM_NAME" | tee -a "$OUTPUT_FILE"
echo "  View logs:          clonebox logs . --user --all" | tee -a "$OUTPUT_FILE"
echo "  Monitor VM:         clonebox watch . --user" | tee -a "$OUTPUT_FILE"
echo "  Restart VM:         virsh --connect $CONN_URI reboot $VM_NAME" | tee -a "$OUTPUT_FILE"
echo "  Stop VM:            virsh --connect $CONN_URI shutdown $VM_NAME" | tee -a "$OUTPUT_FILE"

echo ""
echo -e "${BOLD}Diagnostic complete!${NC}"
echo "Full report saved to: $OUTPUT_FILE"
echo ""
echo "To view the report: less $OUTPUT_FILE"
echo "To search for issues: grep -E '(FAIL|WARN|error)' $OUTPUT_FILE"
