# CloneBox Quick Reference

## 🚀 Quick Start

```bash
# Clone current directory and start VM
clonebox clone . --user --run

# Open VM GUI
clonebox open . --user
```

## 📊 Monitoring Commands

### Watch Live Status
```bash
# Real-time monitoring dashboard
clonebox watch . --user

# Detailed status with logs
clonebox status . --user --verbose
```

### Check VM Status
```bash
# Basic status
clonebox status . --user

# With health check
clonebox status . --user --health

# View monitor logs (via SSH)
ssh ubuntu@<IP_VM> "tail -f /var/log/clonebox-monitor.log"
# Or via log disk
./scripts/clonebox-logs.sh
```

## 🔧 Repair Commands

### Automatic Repair
```bash
# Run full automatic repair
clonebox repair . --user

# Interactive repair menu (via SSH)
ssh ubuntu@<IP_VM> "clonebox-repair"
```

### Specific Repairs
```bash
# Fix permissions only
clonebox repair . --user --perms

# Fix audio (PulseAudio)
clonebox repair . --user --audio

# Reconnect snap interfaces
clonebox repair . --user --snaps

# Remount filesystems
clonebox repair . --user --mounts

# Reset GNOME keyring
clonebox repair . --user --keyring
```

## 🖥️ GUI App Management

### Check Running Apps
```bash
# Inside VM - check what's running
ps aux | grep -E "(firefox|pycharm|chromium|chrome)"

# Restart specific app
clonebox-repair --all  # Restarts all GUI apps
```

### Autostart Configuration
```bash
# Edit autostart entries
ls ~/.config/autostart/
rm ~/.config/autostart/pycharm-community.desktop  # Disable autostart
```

## 🔍 Service Management

### Check Services
```bash
# Inside VM - check service status
systemctl status docker nginx uvicorn

# User services (monitor)
systemctl --user status clonebox-monitor
```

### Service Logs
```bash
# System service logs
journalctl -u docker -f
journalctl -u nginx -f

# Monitor logs
journalctl --user -u clonebox-monitor -f
tail -f /var/log/clonebox-monitor.log
```

## 📁 Mount Management

### Check Mounts
```bash
# List all mounts
mount | grep 9p

# Check specific mount
mountpoint /mnt/project0
```

### Fix Mounts
```bash
# Remount all
sudo mount -a

# Remount specific
sudo mount /mnt/project0
```

## 🛠️ Troubleshooting

### Common Issues
```bash
# VM not responding
clonebox stop . --user
clonebox start . --user

# GUI not working
clonebox open . --user

# Apps not starting
clonebox repair . --user --all

# Permission errors
clonebox repair . --user --perms

# Audio not working
clonebox repair . --user --audio
```

### VM Access
```bash
# SSH into VM (get IP from clonebox status first)
clonebox status . --user  # Shows IP
ssh ubuntu@192.168.122.xxx

# Execute commands via QEMU Guest Agent
virsh --connect qemu:///session qemu-agent-command clone-clonebox -- '{"execute":"guest-exec","arguments":{"path":"/bin/bash","arg":["-c","ps aux"],"capture-output":true}}'

# Virsh console (emergency)
virsh --connect qemu:///session console clone-clonebox

# Access logs from host
./scripts/clonebox-logs.sh  # Interactive log viewer
# Or manually:
sudo mount -o loop /var/lib/libvirt/images/clonebox-logs.qcow2 /mnt/clonebox-logs
less /mnt/clonebox-logs/var/log/clonebox-boot.log
```

## 📋 Configuration Files

### Host Configuration
- `.clonebox.yaml` - VM configuration
- `.env` - Environment variables

### VM Configuration
- `/etc/environment` - System-wide env vars
- `/etc/default/clonebox-monitor` - Monitor settings
- `~/.config/autostart/` - GUI app autostart
- `/var/log/clonebox-*.log` - Various logs

## 🔄 Workflow Examples

### Daily Development
```bash
# Start VM and monitor
clonebox start . --user
clonebox watch . --user

# If something breaks
clonebox repair . --user

# Check logs
./scripts/clonebox-logs.sh  # Interactive viewer
# Or via SSH:
ssh ubuntu@<IP_VM> "tail -f /var/log/clonebox-monitor.log"
```

### After System Update
```bash
# Update VM packages
ssh ubuntu@<IP_VM> "sudo apt update && sudo apt upgrade"

# Fix any issues
clonebox repair . --user --all

# Restart VM
clonebox restart . --user  # Easiest - stop and start
clonebox restart . --user --open  # Restart and open GUI
clonebox restart . --user --force  # Force stop if stuck
virsh --connect qemu:///session reboot clone-clonebox  # Direct reboot
virsh --connect qemu:///session reset clone-clonebox  # Hard reset if frozen
```

### Debugging
```bash
# Full status report
clonebox status . --user --verbose > vm-status.txt

# Collect logs
ssh ubuntu@<IP_VM> "journalctl > vm-journal.log"
ssh ubuntu@<IP_VM> "tar -czf /tmp/logs.tar.gz /var/log/clonebox-*.log"

# Download logs
scp ubuntu@<IP_VM>:/tmp/logs.tar.gz .
# Or use log disk:
./scripts/clonebox-logs.sh
```
