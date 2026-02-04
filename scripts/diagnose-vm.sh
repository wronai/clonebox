#!/bin/bash
# CloneBox VM Diagnostic Script
# Helps identify connectivity and configuration issues

set -e

VM_NAME="${1:-clone-clonebox}"
VM_DIR="${HOME}/.local/share/libvirt/images/${VM_NAME}"
CONN_URI="qemu:///session"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

log() { echo -e "${CYAN}[INFO]${NC} $1"; }
ok() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
section() { echo -e "\n${BOLD}=== $1 ===${NC}"; }

section "VM Detailed Status"

# VM info
virsh --connect "$CONN_URI" dominfo "$VM_NAME" 2>/dev/null | grep -E "(CPU|Memory|State|Autostart)" | sed 's/^/  /'

# QEMU command line
log "QEMU network config:"
ps aux | grep qemu | grep "$VM_NAME" | grep -o "netdev[^ ]*" | head -1 | sed 's/^/  /'

section "Network Deep Check"

# All network info
log "All listening ports:"
ss -tlnp 2>/dev/null | grep -E "(5900|22)" | sed 's/^/  /'

log "SSH forwarding rules:"
ps aux | grep qemu | grep "$VM_NAME" | grep -o "hostfwd[^ ]*" | sed 's/,/\n    /g' | sed 's/^/  /'

# Check if VM exists
if virsh --connect "$CONN_URI" dominfo "$VM_NAME" &>/dev/null; then
    STATE=$(virsh --connect "$CONN_URI" domstate "$VM_NAME" 2>/dev/null)
    ok "VM '$VM_NAME' exists (state: $STATE)"
else
    fail "VM '$VM_NAME' not found"
    exit 1
fi

section "Network Configuration"

# Check passt process
PASST_PROCS=$(pgrep -a passt | grep "$VM_NAME" || true)
if [ -n "$PASST_PROCS" ]; then
    ok "passt process found for VM"
    echo "$PASST_PROCS" | head -2
else
    warn "No passt process found for VM"
fi

# Check SSH port
if [ -f "$VM_DIR/ssh_port" ]; then
    SSH_PORT=$(cat "$VM_DIR/ssh_port")
    ok "SSH port: $SSH_PORT"
    
    # Check if port is listening
    if ss -tlnp 2>/dev/null | grep -q ":${SSH_PORT}"; then
        ok "Port $SSH_PORT is listening (passt forwarding active)"
    else
        warn "Port $SSH_PORT not listening"
    fi
    
    # Test TCP connection
    if nc -zw2 127.0.0.1 "$SSH_PORT" 2>/dev/null; then
        ok "TCP connection to port $SSH_PORT successful"
    else
        fail "TCP connection to port $SSH_PORT failed"
    fi
else
    warn "SSH port file not found at $VM_DIR/ssh_port"
fi

section "Cloud-Init Deep Analysis"

# Check cloud-init status in serial log
if [ -f "$SERIAL_LOG" ]; then
    log "Cloud-init phases detected:"
    grep -E "Cloud-init.*running" "$SERIAL_LOG" | tail -10 | sed 's/^/  /'
    
    log "Cloud-init progress:"
    grep -E "(Step [0-9]+|Starting VM setup|runcmd phase)" "$SERIAL_LOG" | tail -20 | sed 's/^/  /'
    
    log "Package installation status:"
    grep -E "(apt-get|Installing|packages installed)" "$SERIAL_LOG" | tail -5 | sed 's/^/  /'
    
    log "Services status from cloud-init:"
    grep -E "(systemctl.*enable|Service.*Started)" "$SERIAL_LOG" | tail -10 | sed 's/^/  /'
    
    log "Cloud-init errors:"
    grep -E "(ERROR|Failed|error:)" "$SERIAL_LOG" | tail -10 | sed 's/^/  /' || warn "No errors found"
else
    warn "No serial log available"
fi

section "QEMU Guest Agent Deep Check"

if virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-ping"}' &>/dev/null; then
    ok "QEMU guest agent responding"
    
    log "Guest OS info:"
    virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-get-osinfo"}' 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  Name: {d.get('return',{}).get('name','unknown')}\")" 2>/dev/null
    
    log "Guest network interfaces:"
    virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-network-get-interfaces"}' 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); 
[print(f\"  {i['name']}: {', '.join([a.get('ip-address','') + '/' + str(a.get('prefix',0)) for a in i.get('ip-addresses',[]) if a.get('ip-address')])}\") for i in d.get('return',[])]" 2>/dev/null || true
    
    log "Active users:"
    virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-get-users"}' 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); [print(f\"  {u.get('user','unknown')}\") for u in d.get('return',[])]" 2>/dev/null || true
    
    log "Running processes (top 10):"
    virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-get-processes"}' 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); [print(f\"  {p.get('name',p.get('cmd',p.get('pid','?')))}\") for p in d.get('return',[])[:10]]" 2>/dev/null || true
else
    warn "QEMU guest agent not responding"
    log "Possible reasons:"
    log "  - VM still booting (cloud-init installing qemu-guest-agent)"
    log "  - qemu-guest-agent not installed yet"
    log "  - VM crashed or frozen"
fi

section "SSH Full Diagnostics"

SSH_KEY="$VM_DIR/ssh_key"
SSH_PORT_FILE="$VM_DIR/ssh_port"

if [ -f "$SSH_PORT_FILE" ]; then
    SSH_PORT=$(cat "$SSH_PORT_FILE")
    log "SSH port configured: $SSH_PORT"
    
    # Detailed port check
    log "Port listening status:"
    ss -tlnp | grep ":$SSH_PORT" | sed 's/^/  /'
    
    # SSH banner grab
    log "SSH banner:"
    timeout 3 bash -c "echo '' | nc -w2 127.0.0.1 $SSH_PORT 2>&1" | head -2 | sed 's/^/  /' || warn "Cannot get SSH banner"
    
    # Test SSH with full verbose
    if [ -f "$SSH_KEY" ]; then
        log "Testing SSH connection with key $SSH_KEY..."
        SSH_OUTPUT=$(ssh -vvv -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o BatchMode=yes \
            -i "$SSH_KEY" -p "$SSH_PORT" ubuntu@127.0.0.1 "echo '===SSH_OK==='; whoami; uptime" 2>&1 || true)
        
        if echo "$SSH_OUTPUT" | grep -q "===SSH_OK==="; then
            ok "SSH connection successful!"
            log "SSH output:"
            echo "$SSH_OUTPUT" | grep -E "(===SSH_OK===|whoami|uptime)" | sed 's/^/  /'
        else
            fail "SSH connection failed"
            log "SSH debug output (last 20 lines):"
            echo "$SSH_OUTPUT" | tail -20 | sed 's/^/  /'
        fi
    else
        warn "SSH key not found at $SSH_KEY"
        log "Attempting password auth..."
        SSH_OUTPUT=$(sshpass -p "ubuntu" ssh -v -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
            -p "$SSH_PORT" ubuntu@127.0.0.1 "echo connected" 2>&1 || true)
        if echo "$SSH_OUTPUT" | grep -q "connected"; then
            ok "SSH with password works!"
        else
            fail "Both key and password auth failed"
        fi
    fi
else
    warn "SSH port file not found"
fi

section "Serial Log Deep Analysis"

SERIAL_LOG="$VM_DIR/serial.log"
if [ -f "$SERIAL_LOG" ] && [ -s "$SERIAL_LOG" ]; then
    LOG_LINES=$(wc -l < "$SERIAL_LOG")
    LOG_SIZE=$(du -h "$SERIAL_LOG" | cut -f1)
    log "Serial log: $LOG_LINES lines, $LOG_SIZE"
    
    log "=== Last 50 lines ==="
    tail -50 "$SERIAL_LOG" | sed 's/^/  /'
    
    log "=== Boot timeline ==="
    grep -E "(Linux version|Welcome to|cloud-init.*running|Reached target)" "$SERIAL_LOG" | tail -15 | sed 's/^/  /'
    
    log "=== Network status ==="
    grep -E "(ens|eth|enp).*True.*10\.0\.2" "$SERIAL_LOG" | tail -5 | sed 's/^/  /'
    
    log "=== Service status ==="
    grep -E "(Started|Finished).*ssh|openssh" "$SERIAL_LOG" | tail -5 | sed 's/^/  /' || warn "No SSH service messages"
    
    log "=== Errors/Warnings ==="
    grep -iE "(error|fail|warn|timeout)" "$SERIAL_LOG" | tail -10 | sed 's/^/  /' || ok "No errors found"
    
    # Check if cloud-init completed
    if grep -q "Finished.*Cloud-init.*Final" "$SERIAL_LOG"; then
        ok "Cloud-init final stage completed"
    else
        warn "Cloud-init may still be running or failed"
    fi
else
    warn "Serial log empty or not found"
    log "Try: virsh --connect $CONN_URI console $VM_NAME"
fi

section "VM XML Configuration"

log "Network interface type:"
virsh --connect "$CONN_URI" dumpxml "$VM_NAME" 2>/dev/null | grep -A2 "interface type" | sed 's/^/  /'

log "Forwarded ports:"
virsh --connect "$CONN_URI" dumpxml "$VM_NAME" 2>/dev/null | grep -o "hostfwd[^ ]*" | sed 's/,/\n    /g' | sed 's/^/  /'

log "Graphics (SPICE/VNC):"
virsh --connect "$CONN_URI" dumpxml "$VM_NAME" 2>/dev/null | grep -E "(spice|vnc|graphics)" | head -3 | sed 's/^/  /'

section "System Resources"

log "VM resource usage:"
virsh --connect "$CONN_URI" dominfo "$VM_NAME" 2>/dev/null | grep -E "(CPU time|Max memory|Used memory)" | sed 's/^/  /'

log "Host resource usage:"
echo "  CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)% idle"
echo "  Memory: $(free -h | grep Mem | awk '{print $3"/"$2}')"
echo "  Disk: $(df -h $VM_DIR | tail -1 | awk '{print $3"/"$2 " ("$5")"}')"

log "QEMU process info:"
ps aux | grep qemu | grep "$VM_NAME" | awk '{print "  PID: " $2 ", CPU: " $3 "%, MEM: " $4 "%, Time: " $10}'

section "File System & Mounts"

log "VM directory structure:"
ls -la "$VM_DIR/" 2>/dev/null | head -10 | sed 's/^/  /'

log "Disk image info:"
for img in "$VM_DIR"/*.qcow2; do
    if [ -f "$img" ]; then
        echo "  $img:"
        qemu-img info "$img" 2>/dev/null | grep -E "(virtual size|disk size|backing file)" | sed 's/^/    /'
    fi
done

section "Quick Actions Summary"

echo ""
echo "  ${BOLD}Connect to VM:${NC}"
if [ -f "$VM_DIR/ssh_port" ]; then
    echo "    SSH:     ssh -p $(cat "$VM_DIR/ssh_port") ubuntu@localhost"
else
    echo "    SSH:     (port not configured)"
fi
echo "    SPICE:   remote-viewer spice://localhost:5900"
echo "    Console: virsh --connect $CONN_URI console $VM_NAME"
echo ""
echo "  ${BOLD}Useful commands:${NC}"
echo "    Reboot:  virsh --connect $CONN_URI reboot $VM_NAME"
echo "    Stop:    virsh --connect $CONN_URI shutdown $VM_NAME"
echo "    Destroy: virsh --connect $CONN_URI destroy $VM_NAME"
echo "    Logs:    tail -f $VM_DIR/serial.log"
echo ""

section "Recommendations"
  1. Wait for cloud-init to complete (can take 2-3 minutes)
  2. Check VM console: virsh --connect $CONN_URI console $VM_NAME
  3. Look for network issues in console output
  4. Check if VM has IPv4 address (should be 10.0.2.x with passt)

${BOLD}If network is not configured:${NC}
  1. passt provides DHCP on 10.0.2.0/24 network
  2. Default gateway: 10.0.2.2
  3. DNS: 10.0.2.3
  4. VM should get 10.0.2.15 via DHCP

${BOLD}Manual network fix (via console):${NC}
  sudo ip addr add 10.0.2.15/24 dev enp*s0
  sudo ip route add default via 10.0.2.2
  echo 'nameserver 10.0.2.3' | sudo tee /etc/resolv.conf
"
fi

echo -e "\n${BOLD}Diagnostic complete${NC}"
