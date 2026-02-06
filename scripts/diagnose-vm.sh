#!/bin/bash
# CloneBox Unified VM Diagnostic Script
#
# Usage:
#   diagnose-vm.sh [VM_NAME] [OPTIONS]
#
# Options:
#   --verbose, -v   Show all checks (INFO, OK, WARN, FAIL)
#   --quiet, -q     Show only FAIL (critical errors)
#   --help, -h      Show this help
#
# Default mode: shows WARN and FAIL only.
# Exit code = number of FAILs.

set -euo pipefail

# ── parse arguments ──────────────────────────────────────────────────────────
VERBOSE=false
QUIET=false
VM_NAME="clone-clonebox"

for arg in "$@"; do
    case "$arg" in
        --verbose|-v) VERBOSE=true ;;
        --quiet|-q)   QUIET=true ;;
        --help|-h)
            sed -n '2,/^$/s/^# \?//p' "$0"
            exit 0 ;;
        -*) echo "Unknown flag: $arg (use --help)"; exit 1 ;;
        *)  VM_NAME="$arg" ;;
    esac
done

VM_DIR="${HOME}/.local/share/libvirt/images/${VM_NAME}"
CONN_URI="qemu:///session"
SSH_KEY="$VM_DIR/ssh_key"
SSH_PORT_FILE="$VM_DIR/ssh_port"
SERIAL_LOG="$VM_DIR/serial.log"

FAILS=0
WARNS=0

# resolved once for SSH helper and all subsequent sections
SSH_PORT=""

# ── colours ──────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi

# ── output helpers (respect verbosity) ───────────────────────────────────────
fail()    { echo -e "${RED}[FAIL]${NC} $1"; ((FAILS++)) || true; }
warn()    { ((WARNS++)) || true; $QUIET || echo -e "${YELLOW}[WARN]${NC} $1"; }
ok()      { $VERBOSE && echo -e "${GREEN}[OK]${NC}   $1" || true; }
log()     { $VERBOSE && echo -e "${CYAN}[INFO]${NC} $1" || true; }
section() { $VERBOSE && echo -e "\n${BOLD}=== $1 ===${NC}" || true; }

# ── resolve SSH port (file → QEMU hostfwd → skip) ───────────────────────────
_resolve_ssh_port() {
    # 1. Persisted port file
    if [ -f "$SSH_PORT_FILE" ]; then
        SSH_PORT=$(cat "$SSH_PORT_FILE")
        [ -n "$SSH_PORT" ] && return 0
    fi
    # 2. Extract from QEMU hostfwd rule
    local fwd
    fwd=$(ps aux 2>/dev/null | grep "[q]emu.*$VM_NAME" \
        | grep -oP 'hostfwd=tcp::\K\d+(?=-:22)' | head -1 || true)
    if [ -n "$fwd" ]; then
        SSH_PORT="$fwd"
        return 0
    fi
    return 1
}

# ── SSH helper (uses resolved $SSH_PORT) ─────────────────────────────────────
_ssh() {
    [ -n "$SSH_PORT" ] && [ -f "$SSH_KEY" ] || return 1
    ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null -o BatchMode=yes \
        -o LogLevel=ERROR \
        -i "$SSH_KEY" -p "$SSH_PORT" ubuntu@127.0.0.1 "$@" 2>/dev/null
}

# Track whether SSH is available for later sections
SSH_OK=false

# ═══════════════════════════════════════════════════════════════════════════════
#  1. VM existence & state
# ═══════════════════════════════════════════════════════════════════════════════
section "VM Status"

if ! virsh --connect "$CONN_URI" dominfo "$VM_NAME" &>/dev/null; then
    fail "VM '$VM_NAME' does not exist"
    echo -e "\n${BOLD}Summary:${NC} ${RED}Fails: $FAILS${NC}"
    exit $FAILS
fi

STATE=$(virsh --connect "$CONN_URI" domstate "$VM_NAME" 2>/dev/null)
if [ "$STATE" = "running" ]; then
    ok "VM '$VM_NAME' running"
else
    fail "VM '$VM_NAME' not running (state: $STATE)"
    echo -e "\n${BOLD}Summary:${NC} ${RED}Fails: $FAILS${NC}"
    exit $FAILS
fi

if $VERBOSE; then
    virsh --connect "$CONN_URI" dominfo "$VM_NAME" 2>/dev/null \
        | grep -E "(CPU|Memory|State|Autostart)" | sed 's/^/  /'
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  2. Network / SSH
# ═══════════════════════════════════════════════════════════════════════════════
section "Network & SSH"

# passt
if pgrep -a passt 2>/dev/null | grep -q "$VM_NAME"; then
    ok "passt process found"
else
    warn "No passt process for VM (may use different networking)"
fi

if $VERBOSE; then
    log "QEMU network config:"
    ps aux | grep "[q]emu.*$VM_NAME" | grep -oP 'netdev\S+' | head -1 | sed 's/^/  /' || true
    log "SSH forwarding rules:"
    ps aux | grep "[q]emu.*$VM_NAME" | grep -oP 'hostfwd\S+' | sed 's/,/\n    /g' | sed 's/^/  /' || true
    log "Listening ports (5900/SSH):"
    ss -tlnp 2>/dev/null | grep -E ":(5900|22[0-9]{3})\b" | sed 's/^/  /' || true
fi

# Resolve SSH port once
if _resolve_ssh_port; then
    if ! ss -tlnp 2>/dev/null | grep -q ":${SSH_PORT}\b"; then
        fail "SSH port $SSH_PORT not listening"
    else
        ok "SSH port $SSH_PORT listening"
    fi

    if ! nc -zw2 127.0.0.1 "$SSH_PORT" 2>/dev/null; then
        fail "TCP connect to port $SSH_PORT failed"
    else
        ok "TCP connect to $SSH_PORT OK"
    fi
else
    fail "Cannot determine SSH port (no port file, no QEMU hostfwd)"
fi

# SSH auth test
if [ -n "$SSH_PORT" ] && [ -f "$SSH_KEY" ]; then
    if _ssh "echo OK" | grep -q OK; then
        ok "SSH authentication OK"
        SSH_OK=true
    else
        fail "SSH authentication failed"
    fi

    if $VERBOSE; then
        log "SSH banner:"
        timeout 3 bash -c "echo '' | nc -w2 127.0.0.1 $SSH_PORT 2>&1" | head -2 | sed 's/^/  /' || true
    fi
else
    [ ! -f "$SSH_KEY" ] && fail "SSH key missing: $SSH_KEY"
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  3. Cloud-init
# ═══════════════════════════════════════════════════════════════════════════════
section "Cloud-init"

if [ ! -f "$SERIAL_LOG" ] || [ ! -s "$SERIAL_LOG" ]; then
    warn "Serial log not found or empty"
else
    if grep --text -q "Finished.*Cloud-init.*Final" "$SERIAL_LOG"; then
        ok "Cloud-init completed"
    else
        warn "Cloud-init may still be running or failed"
    fi

    # Always show cloud-init errors (even without --verbose)
    CI_ERRORS=$(grep --text -iE "(ERROR|error:)" "$SERIAL_LOG" \
        | grep -v "aspell\|node-\|RAS:\|EXT4-fs\|remount-ro\|Correctable Errors\|ACPI Error\|has no plug\|error-pages\|GPT:.*error\|Enabling conf" \
        | tail -5 || true)
    if [ -n "$CI_ERRORS" ]; then
        warn "Cloud-init errors found:"
        echo "$CI_ERRORS" | sed 's/^/  /'
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  4. QEMU Guest Agent
# ═══════════════════════════════════════════════════════════════════════════════
section "QEMU Guest Agent"

if virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" \
    '{"execute":"guest-ping"}' &>/dev/null; then
    ok "QEMU Guest Agent responding"

    if $VERBOSE; then
        log "Guest OS:"
        virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" \
            '{"execute":"guest-get-osinfo"}' 2>/dev/null | \
            python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  {d.get('return',{}).get('name','?')} {d.get('return',{}).get('version-id','')}\")" 2>/dev/null || true

        log "Network interfaces:"
        virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" \
            '{"execute":"guest-network-get-interfaces"}' 2>/dev/null | \
            python3 -c "
import sys,json; d=json.load(sys.stdin)
for i in d.get('return',[]):
    ips=', '.join(a.get('ip-address','')+'/'+str(a.get('prefix',0)) for a in i.get('ip-addresses',[]) if a.get('ip-address'))
    if ips: print(f\"  {i['name']}: {ips}\")" 2>/dev/null || true

        log "Active users:"
        virsh --connect "$CONN_URI" qemu-agent-command "$VM_NAME" \
            '{"execute":"guest-get-users"}' 2>/dev/null | \
            python3 -c "import sys,json; [print(f\"  {u.get('user','?')}\") for u in json.load(sys.stdin).get('return',[])]" 2>/dev/null || true
    fi
else
    warn "QEMU Guest Agent not responding"
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  5. GUI / Display
# ═══════════════════════════════════════════════════════════════════════════════
section "GUI & Display"

# SPICE
if ss -tlnp 2>/dev/null | grep -q ":5900"; then
    ok "SPICE port 5900 listening"
else
    warn "SPICE port 5900 not listening"
fi

if $SSH_OK; then
    GDM_STATUS=$(_ssh "systemctl is-active gdm3 2>/dev/null" || echo "inactive")
    if [ "$GDM_STATUS" = "active" ]; then
        ok "Display Manager (gdm3) running"
    else
        warn "Display Manager status: $GDM_STATUS"
    fi

    if $VERBOSE; then
        log "Session type:"
        _ssh "loginctl show-session \$(loginctl 2>/dev/null | grep ubuntu | awk '{print \$1}' | head -1) 2>/dev/null | grep -E 'Type|Desktop'" | sed 's/^/  /' || true
        log "Available desktop sessions:"
        _ssh "ls /usr/share/xsessions/ /usr/share/wayland-sessions/ 2>/dev/null | sed 's/.desktop//'" | sed 's/^/  /' || true
        log "Active display:"
        _ssh "loginctl show-user ubuntu 2>/dev/null | grep -E 'Display|State'" | sed 's/^/  /' || true
        log "GDM recent logs:"
        _ssh "journalctl -u gdm -n 5 --no-pager 2>/dev/null | grep -E '(session opened|session closed|failing|error)'" | sed 's/^/  /' || true
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  6. Browser validation
# ═══════════════════════════════════════════════════════════════════════════════
section "Browsers"

if $SSH_OK; then

    # ── 6a. Detection (command -v, not which) ────────────────────────────────
    HAS_FIREFOX=$(_ssh  "command -v firefox >/dev/null 2>&1 && echo y || echo n")
    HAS_CHROME=$(_ssh   "(command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1) && echo y || echo n")
    HAS_CHROMIUM=$(_ssh "command -v chromium >/dev/null 2>&1 && echo y || echo n")

    N=0
    [ "$HAS_FIREFOX"  = "y" ] && ((N++)) || true
    [ "$HAS_CHROME"   = "y" ] && ((N++)) || true
    [ "$HAS_CHROMIUM" = "y" ] && ((N++)) || true

    if [ "$N" -gt 0 ]; then
        ok "$N browser(s) installed"
    else
        warn "No browsers found in VM"
    fi

    # ── 6b. Profile checks ───────────────────────────────────────────────────
    _dir_nonempty() {
        # Returns "y" if directory exists and has at least one entry
        _ssh "test -d '$1' && [ \$(ls -A '$1' 2>/dev/null | wc -l) -gt 0 ] && echo y || echo n"
    }

    # Firefox profile
    if [ "$HAS_FIREFOX" = "y" ]; then
        FF_SNAP_PROF=$(_dir_nonempty "/home/ubuntu/snap/firefox/common/.mozilla/firefox")
        FF_CLASSIC_PROF=$(_dir_nonempty "/home/ubuntu/.mozilla/firefox")
        if [ "$FF_SNAP_PROF" = "y" ] || [ "$FF_CLASSIC_PROF" = "y" ]; then
            ok "Firefox profile present"
        else
            warn "Firefox installed but profile is missing/empty"
        fi

        # profiles.ini check
        FF_INI=$(_ssh "cat /home/ubuntu/snap/firefox/common/.mozilla/firefox/profiles.ini 2>/dev/null || cat /home/ubuntu/.mozilla/firefox/profiles.ini 2>/dev/null || echo ''" || echo "")
        if [ -n "$FF_INI" ] && echo "$FF_INI" | grep -q "\[Profile"; then
            ok "Firefox profiles.ini valid"
        elif [ "$FF_SNAP_PROF" = "y" ] || [ "$FF_CLASSIC_PROF" = "y" ]; then
            warn "Firefox profiles.ini missing or invalid"
        fi
    fi

    # Chrome profile
    if [ "$HAS_CHROME" = "y" ]; then
        CHROME_PROF=$(_dir_nonempty "/home/ubuntu/.config/google-chrome")
        if [ "$CHROME_PROF" = "y" ]; then
            ok "Chrome profile present"
        else
            warn "Chrome installed but profile is missing/empty"
        fi
    fi

    # Chromium profile
    if [ "$HAS_CHROMIUM" = "y" ]; then
        CR_SNAP=$(_dir_nonempty "/home/ubuntu/snap/chromium/common/chromium")
        CR_CLASSIC=$(_dir_nonempty "/home/ubuntu/.config/chromium")
        if [ "$CR_SNAP" = "y" ] || [ "$CR_CLASSIC" = "y" ]; then
            ok "Chromium profile present"
        else
            warn "Chromium installed but profile is missing/empty"
        fi
    fi

    # ── 6c. Profile permissions ──────────────────────────────────────────────
    BAD_PERMS=$(_ssh "find /home/ubuntu/.mozilla /home/ubuntu/.config/google-chrome \
        /home/ubuntu/.config/chromium /home/ubuntu/snap/firefox \
        /home/ubuntu/snap/chromium -maxdepth 0 -not -user ubuntu 2>/dev/null" || echo "")
    if [ -n "$BAD_PERMS" ]; then
        warn "Browser profile ownership wrong (not ubuntu): $BAD_PERMS"
    else
        ok "Browser profile permissions OK"
    fi

    # ── 6d. Lock files (leftover from copied running profile) ────────────────
    LOCKS=$(_ssh "find /home/ubuntu/.mozilla /home/ubuntu/snap/firefox \
        /home/ubuntu/.config/google-chrome /home/ubuntu/.config/chromium \
        /home/ubuntu/snap/chromium \
        -maxdepth 4 -type f \( -name 'parent.lock' -o -name '.parentlock' \
        -o -name 'lock' -o -name 'lockfile' -o -name 'SingletonLock' \) \
        2>/dev/null | head -5" || echo "")
    if [ -n "$LOCKS" ]; then
        warn "Browser lock files found (stale profile copy?):"
        echo "$LOCKS" | sed 's/^/  /'
    else
        ok "No stale browser lock files"
    fi

    # ── 6e. Crash reports ────────────────────────────────────────────────────
    CRASHES=$(_ssh "find /home/ubuntu/.mozilla /home/ubuntu/snap/firefox \
        /home/ubuntu/.config/google-chrome /home/ubuntu/.config/chromium \
        /home/ubuntu/snap/chromium \
        -maxdepth 4 -type f \( -name '*.dmp' -o -name '*.extra' \) \
        -newer /proc/1/status 2>/dev/null | wc -l" || echo "0")
    if [ "${CRASHES:-0}" -gt 0 ]; then
        warn "$CRASHES recent crash dump(s) found in browser profiles"
    else
        ok "No recent browser crash dumps"
    fi

    # ── 6f. Snap interface validation ────────────────────────────────────────
    REQUIRED_IFACES="desktop desktop-legacy x11 wayland home network"
    for snap_browser in firefox chromium; do
        _ssh "snap list $snap_browser >/dev/null 2>&1" || continue
        MISSING=""
        CONNS=$(_ssh "snap connections $snap_browser 2>/dev/null | awk 'NR>1{print \$1, \$3}'" || echo "")
        for iface in $REQUIRED_IFACES; do
            if ! echo "$CONNS" | grep -q "$iface.*[^-]$"; then
                MISSING="${MISSING:+$MISSING, }$iface"
            fi
        done
        if [ -n "$MISSING" ]; then
            warn "snap $snap_browser missing interfaces: $MISSING"
        else
            ok "snap $snap_browser interfaces connected"
        fi
    done

    # ── 6g. Headless smoke tests ─────────────────────────────────────────────
    # Resolve UID and runtime dir for headless tests
    VM_UID=$(_ssh "id -u ubuntu 2>/dev/null" || echo "1000")
    RUNTIME_DIR="/run/user/${VM_UID}"
    _ssh "sudo mkdir -p $RUNTIME_DIR && sudo chown $VM_UID:$VM_UID $RUNTIME_DIR && sudo chmod 700 $RUNTIME_DIR" >/dev/null 2>&1 || true
    USER_ENV="sudo -u ubuntu env HOME=/home/ubuntu USER=ubuntu LOGNAME=ubuntu XDG_RUNTIME_DIR=$RUNTIME_DIR"

    if [ "$HAS_FIREFOX" = "y" ]; then
        FF_HL=$(_ssh "timeout 25 $USER_ENV firefox --headless --version >/dev/null 2>&1 && echo y || echo n" || echo "n")
        if [ "$FF_HL" = "y" ]; then
            ok "Firefox headless OK"
        else
            warn "Firefox headless test failed"
            if $VERBOSE; then
                log "Firefox headless stderr:"
                _ssh "timeout 10 $USER_ENV firefox --headless --version 2>&1 | tail -5" | sed 's/^/  /' || true
            fi
        fi
    fi

    if [ "$HAS_CHROME" = "y" ]; then
        CH_HL=$(_ssh "timeout 15 $USER_ENV google-chrome --headless=new --no-sandbox --disable-gpu --dump-dom about:blank 2>&1" || echo "")
        if echo "$CH_HL" | grep -qi "<html"; then
            ok "Chrome headless OK"
        else
            warn "Chrome headless test failed"
        fi
    fi

    if [ "$HAS_CHROMIUM" = "y" ]; then
        CR_HL=$(_ssh "timeout 15 $USER_ENV chromium --headless=new --no-sandbox --disable-gpu --dump-dom about:blank 2>&1" || echo "")
        if echo "$CR_HL" | grep -qi "<html"; then
            ok "Chromium headless OK"
        else
            warn "Chromium headless test failed"
        fi
    fi

    # ── 6h. Verbose browser details ──────────────────────────────────────────
    if $VERBOSE; then
        log "Browser binaries:"
        _ssh "command -v firefox chromium google-chrome google-chrome-stable 2>/dev/null" | sed 's/^/  /' || true
        log "Snap browser packages:"
        _ssh "snap list 2>/dev/null | grep -E '(firefox|chromium|chrome)'" | sed 's/^/  /' || true
        log "Chrome profile:"
        _ssh "ls -la ~/.config/google-chrome/ 2>/dev/null | head -5" | sed 's/^/  /' || true
        log "Chromium profile (snap):"
        _ssh "ls -la ~/snap/chromium/common/chromium/ 2>/dev/null | head -5" | sed 's/^/  /' || true
        log "Firefox profile (snap):"
        _ssh "ls -la ~/snap/firefox/common/.mozilla/firefox/ 2>/dev/null | head -5" | sed 's/^/  /' || true
        log "Firefox profile (classic):"
        _ssh "ls -la ~/.mozilla/firefox/ 2>/dev/null | head -5" | sed 's/^/  /' || true
        log "Browser processes:"
        _ssh "pgrep -a -f 'chrome|chromium|firefox' 2>/dev/null | head -5" | sed 's/^/  /' || log "  (none running)"
        log "Browser journal logs:"
        _ssh "journalctl -n 20 --no-pager 2>/dev/null | grep -iE 'chrome|chromium|firefox' | tail -5" | sed 's/^/  /' || true
    fi
else
    warn "SSH not available — cannot check browsers"
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  7. Resources & filesystem (verbose only)
# ═══════════════════════════════════════════════════════════════════════════════
if $VERBOSE; then
    section "VM XML"
    log "Network interface:"
    virsh --connect "$CONN_URI" dumpxml "$VM_NAME" 2>/dev/null | grep -A2 "interface type" | sed 's/^/  /' || true
    log "Forwarded ports:"
    virsh --connect "$CONN_URI" dumpxml "$VM_NAME" 2>/dev/null | grep -oP "hostfwd\S+" | sed 's/,/\n    /g' | sed 's/^/  /' || true
    log "Graphics:"
    virsh --connect "$CONN_URI" dumpxml "$VM_NAME" 2>/dev/null | grep -E "(spice|vnc|graphics)" | head -3 | sed 's/^/  /' || true

    section "Resources"
    log "VM resources:"
    virsh --connect "$CONN_URI" dominfo "$VM_NAME" 2>/dev/null | grep -E "(CPU time|Max memory|Used memory)" | sed 's/^/  /'
    log "Host resources:"
    echo "  CPU idle: $(top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d'%' -f1)%"
    echo "  Memory: $(free -h | grep Mem | awk '{print $3"/"$2}')"
    echo "  Disk: $(df -h "$VM_DIR" | tail -1 | awk '{print $3"/"$2 " ("$5")"}')"
    log "QEMU process:"
    ps aux | grep "[q]emu.*$VM_NAME" | awk '{print "  PID:" $2 " CPU:" $3 "% MEM:" $4 "%"}' || true

    section "Filesystem"
    log "VM directory:"
    ls -la "$VM_DIR/" 2>/dev/null | head -10 | sed 's/^/  /'
    log "Disk images:"
    for search_dir in "$VM_DIR" "${HOME}/.local/share/libvirt/images"; do
        for img in "$search_dir"/*.qcow2 "$search_dir"/${VM_NAME}*.qcow2; do
            [ -f "$img" ] || continue
            echo "  $(basename "$img"):"
            qemu-img info "$img" 2>/dev/null | grep -E "(virtual size|disk size|backing file)" | sed 's/^/    /'
        done
    done
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  8. Quick Actions (verbose only)
# ═══════════════════════════════════════════════════════════════════════════════
if $VERBOSE; then
    section "Quick Actions"
    echo ""
    echo -e "  ${BOLD}Connect:${NC}"
    [ -n "$SSH_PORT" ] && echo "    ssh -i $SSH_KEY -p $SSH_PORT ubuntu@127.0.0.1"
    echo "    remote-viewer spice://localhost:5900"
    echo "    virsh --connect $CONN_URI console $VM_NAME"
    echo ""
    echo -e "  ${BOLD}Manage:${NC}"
    echo "    virsh --connect $CONN_URI reboot $VM_NAME"
    echo "    virsh --connect $CONN_URI shutdown $VM_NAME"
    echo "    virsh --connect $CONN_URI destroy $VM_NAME"
    echo "    tail -f $VM_DIR/serial.log"
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  Summary
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
if [ $FAILS -eq 0 ] && [ $WARNS -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All checks passed.${NC}"
else
    echo -e "${BOLD}Summary:${NC}  ${RED}Fails: $FAILS${NC}  ${YELLOW}Warns: $WARNS${NC}"
fi

exit $FAILS
