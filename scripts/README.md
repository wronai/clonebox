# CloneBox Monitoring and Self-Healing

This directory contains scripts and configuration for continuous monitoring and self-healing of CloneBox VMs.

## Components

### 1. clonebox-monitor.sh
The main monitoring script that:
- Monitors GUI apps (PyCharm, Firefox, Chromium, Chrome)
- Monitors system services (docker, nginx, containerd, etc.)
- Monitors web services (uvicorn)
- Auto-restarts failed apps and services
- Logs all activities to `/var/log/clonebox-monitor.log`
- Updates status in `/var/run/clonebox-monitor-status`

### 2. clonebox-monitor.service
Systemd user service that runs the monitor:
- Starts after GUI login
- Restarts automatically if it crashes
- Runs as the ubuntu user
- Logs to systemd journal

### 3. clonebox-monitor.default
Configuration file for environment variables:
- `CLONEBOX_MONITOR_INTERVAL`: Check interval (default: 30s)
- `CLONEBOX_AUTO_REPAIR`: Enable auto-repair (default: true)
- `CLONEBOX_WATCH_APPS`: Monitor GUI apps (default: true)
- `CLONEBOX_WATCH_SERVICES`: Monitor services (default: true)

## Installation

The scripts are automatically installed during VM creation. For manual installation:

```bash
# Copy scripts to VM
sudo cp clonebox-monitor.sh /usr/local/bin/clonebox-monitor
sudo cp clonebox-monitor.service /etc/systemd/user/clonebox-monitor.service
sudo cp clonebox-monitor.default /etc/default/clonebox-monitor

# Set permissions
sudo chmod +x /usr/local/bin/clonebox-monitor

# Enable and start service (as ubuntu user)
systemctl --user enable clonebox-monitor
systemctl --user start clonebox-monitor
```

## Usage

### Check monitor status
```bash
# Check if service is running
systemctl --user status clonebox-monitor

# View logs
journalctl --user -u clonebox-monitor -f

# View monitor log file
tail -f /var/log/clonebox-monitor.log

# Check last status
cat /var/run/clonebox-monitor-status
```

### Manual control
```bash
# Stop monitoring
systemctl --user stop clonebox-monitor

# Start monitoring
systemctl --user start clonebox-monitor

# Restart monitoring
systemctl --user restart clonebox-monitor
```

## Monitoring Details

### GUI Apps Monitored
- **PyCharm Community**: `/snap/bin/pycharm-community`
- **Firefox**: `/snap/bin/firefox`
- **Chromium**: `/snap/bin/chromium`
- **Google Chrome**: `google-chrome-stable` (if installed)

### Services Monitored
- **System Services**: docker, nginx, containerd, qemu-guest-agent, snapd
- **Web Services**: uvicorn (and any others defined in web_services)

### Self-Healing Actions
1. **Service down**: `systemctl restart <service>`
2. **App not running**: Start app with `nohup` in background
3. **Display detection**: Automatically sets `DISPLAY=:1` for VM

## Troubleshooting

### Monitor not starting
```bash
# Check if login is enabled for lingering
loginctl enable-linger ubuntu

# Check user session
echo $XDG_RUNTIME_DIR
```

### Apps not starting
```bash
# Check display
echo $DISPLAY

# Check X11 socket
ls -la /tmp/.X11-unix/

# Manual test
sudo -u ubuntu DISPLAY=:1 /snap/bin/firefox &
```

### Logs location
- Monitor log: `/var/log/clonebox-monitor.log`
- Systemd journal: `journalctl --user -u clonebox-monitor`
- Status file: `/var/run/clonebox-monitor-status`
