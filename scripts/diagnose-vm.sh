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

section "VM Status Check"

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

section "Cloud-Init Configuration"

# Check cloud-init files
CLOUDINIT_DIR="$VM_DIR/cloud-init"
if [ -d "$CLOUDINIT_DIR" ]; then
    log "Cloud-init directory: $CLOUDINIT_DIR"
    ls -la "$CLOUDINIT_DIR/" 2>/dev/null || true
    
    if [ -f "$CLOUDINIT_DIR/network-config" ]; then
        log "Network config:"
        cat "$CLOUDINIT_DIR/network-config"
    else
        warn "No network-config file (using defaults)"
    fi
else
    warn "Cloud-init directory not found"
fi

section "QEMU Guest Agent"

# Try guest agent
if virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-ping"}' &>/dev/null; then
    ok "QEMU guest agent responding"
    
    # Get network info
    log "Guest network interfaces:"
    virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" '{"execute":"guest-network-get-interfaces"}' 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); [print(f\"  {i['name']}: {[a.get('ip-address','') for a in i.get('ip-addresses',[])]}\" ) for i in d.get('return',[])]" 2>/dev/null || true
else
    warn "QEMU guest agent not responding (VM may still be booting)"
fi

section "SSH Connectivity Test"

SSH_KEY="$VM_DIR/ssh_key"
if [ -f "$SSH_KEY" ] && [ -f "$VM_DIR/ssh_port" ]; then
    SSH_PORT=$(cat "$VM_DIR/ssh_port")
    log "Testing SSH connection..."
    
    # Try SSH with verbose output
    SSH_OUTPUT=$(ssh -v -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes \
        -i "$SSH_KEY" -p "$SSH_PORT" ubuntu@127.0.0.1 "echo connected" 2>&1 || true)
    
    if echo "$SSH_OUTPUT" | grep -q "connected"; then
        ok "SSH connection successful!"
    else
        fail "SSH connection failed"
        echo "$SSH_OUTPUT" | grep -E "(Connection|kex_exchange|debug1: Connecting)" | head -5
    fi
else
    warn "SSH key or port file not found"
fi

section "Console Output (last 30 lines)"

# Try to get serial log
SERIAL_LOG="$VM_DIR/serial.log"
if [ -f "$SERIAL_LOG" ] && [ -s "$SERIAL_LOG" ]; then
    log "Serial log (last 30 lines):"
    tail -30 "$SERIAL_LOG"
else
    warn "Serial log empty or not found"
    log "Try: virsh --connect $CONN_URI console $VM_NAME"
fi

section "Recommendations"

if [ "$STATE" = "running" ]; then
    echo -e "
${BOLD}If SSH is failing:${NC}
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
