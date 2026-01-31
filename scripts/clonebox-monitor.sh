#!/bin/bash
# CloneBox Monitor Service - Continuous monitoring and self-healing
# This script monitors apps and services, auto-restarts them if needed

set -euo pipefail

# Configuration from environment
MONITOR_INTERVAL="${CLONEBOX_MONITOR_INTERVAL:-30}"
AUTO_REPAIR="${CLONEBOX_AUTO_REPAIR:-true}"
WATCH_APPS="${CLONEBOX_WATCH_APPS:-true}"
WATCH_SERVICES="${CLONEBOX_WATCH_SERVICES:-true}"
LOG_FILE="/var/log/clonebox-monitor.log"
STATUS_FILE="/var/run/clonebox-monitor-status"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_info() {
    log "${BLUE}[INFO]${NC} $1"
}

log_warn() {
    log "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    log "${RED}[ERROR]${NC} $1"
}

log_success() {
    log "${GREEN}[SUCCESS]${NC} $1"
}

# Check if a process is running
is_process_running() {
    local pattern="$1"
    local user="${2:-ubuntu}"
    
    if pgrep -u "$user" -f "$pattern" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Check if a systemd service is active
is_service_active() {
    local service="$1"
    if systemctl is-active --quiet "$service" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Restart a systemd service
restart_service() {
    local service="$1"
    log_warn "Restarting service: $service"
    
    if systemctl restart "$service" 2>/dev/null; then
        sleep 2
        if is_service_active "$service"; then
            log_success "Service $service restarted successfully"
            return 0
        else
            log_error "Failed to restart service $service"
            return 1
        fi
    else
        log_error "Failed to restart service $service (command failed)"
        return 1
    fi
}

# Start a GUI app for a user
start_gui_app() {
    local app="$1"
    local user="${2:-ubuntu}"
    local exec_cmd="$3"
    
    log_warn "Starting GUI app: $app for user $user"
    
    # Check if X11/Wayland display is available
    if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
        export DISPLAY=:1  # Default for VM
    fi
    
    # Start app as user in background
    if sudo -u "$user" bash -c "nohup $exec_cmd >/dev/null 2>&1 &"; then
        sleep 3
        if is_process_running "$app" "$user"; then
            log_success "App $app started successfully"
            return 0
        else
            log_error "Failed to start app $app"
            return 1
        fi
    else
        log_error "Failed to start app $app (command failed)"
        return 1
    fi
}

# Monitor GUI apps
monitor_apps() {
    if [ "$WATCH_APPS" != "true" ]; then
        return 0
    fi
    
    log_info "Checking GUI apps..."
    local apps_restarted=0
    
    # PyCharm Community
    if ! is_process_running "pycharm-community"; then
        if [ "$AUTO_REPAIR" = "true" ]; then
            start_gui_app "pycharm-community" "ubuntu" "/snap/bin/pycharm-community"
            ((apps_restarted++))
        else
            log_warn "PyCharm Community is not running"
        fi
    fi
    
    # Firefox
    if ! is_process_running "firefox"; then
        if [ "$AUTO_REPAIR" = "true" ]; then
            start_gui_app "firefox" "ubuntu" "/snap/bin/firefox"
            ((apps_restarted++))
        else
            log_warn "Firefox is not running"
        fi
    fi
    
    # Chromium
    if ! is_process_running "chromium"; then
        if [ "$AUTO_REPAIR" = "true" ]; then
            start_gui_app "chromium" "ubuntu" "/snap/bin/chromium"
            ((apps_restarted++))
        else
            log_warn "Chromium is not running"
        fi
    fi
    
    # Google Chrome
    if command -v google-chrome-stable >/dev/null 2>&1 && ! is_process_running "google-chrome"; then
        if [ "$AUTO_REPAIR" = "true" ]; then
            start_gui_app "google-chrome" "ubuntu" "google-chrome-stable"
            ((apps_restarted++))
        else
            log_warn "Google Chrome is not running"
        fi
    fi
    
    if [ "$apps_restarted" -gt 0 ]; then
        log_info "Restarted $apps_restarted GUI apps"
    else
        log_success "All GUI apps are running"
    fi
}

# Monitor system services
monitor_services() {
    if [ "$WATCH_SERVICES" != "true" ]; then
        return 0
    fi
    
    log_info "Checking system services..."
    local services_restarted=0
    
    # Core services to monitor
    local services=(
        "docker"
        "nginx"
        "containerd"
        "qemu-guest-agent"
        "snapd"
    )
    
    # Web services from configuration
    local web_services=(
        "uvicorn"
    )
    
    # Check system services
    for service in "${services[@]}"; do
        if ! is_service_active "$service"; then
            if [ "$AUTO_REPAIR" = "true" ]; then
                restart_service "$service"
                ((services_restarted++))
            else
                log_warn "Service $service is not active"
            fi
        fi
    done
    
    # Check web services
    for service in "${web_services[@]}"; do
        if ! is_service_active "$service"; then
            if [ "$AUTO_REPAIR" = "true" ]; then
                restart_service "$service"
                ((services_restarted++))
            else
                log_warn "Web service $service is not active"
            fi
        fi
    done
    
    if [ "$services_restarted" -gt 0 ]; then
        log_info "Restarted $services_restarted services"
    else
        log_success "All services are active"
    fi
}

# Update status file
update_status() {
    local timestamp=$(date -Iseconds)
    cat > "$STATUS_FILE" <<EOF
last_check="$timestamp"
monitor_interval=$MONITOR_INTERVAL
auto_repair=$AUTO_REPAIR
watch_apps=$WATCH_APPS
watch_services=$WATCH_SERVICES
EOF
}

# Main monitoring loop
main() {
    log_info "CloneBox Monitor started (interval: ${MONITOR_INTERVAL}s)"
    log_info "Auto-repair: $AUTO_REPAIR | Watch apps: $WATCH_APPS | Watch services: $WATCH_SERVICES"
    
    # Ensure log directory exists
    mkdir -p "$(dirname "$LOG_FILE")"
    mkdir -p "$(dirname "$STATUS_FILE")"
    
    while true; do
        monitor_apps
        echo ""
        monitor_services
        echo ""
        update_status
        log_info "Next check in ${MONITOR_INTERVAL} seconds..."
        echo "----------------------------------------"
        sleep "$MONITOR_INTERVAL"
    done
}

# Handle signals gracefully
trap 'log_info "CloneBox Monitor stopping..."; exit 0' SIGTERM SIGINT

# Start monitoring
main "$@"
