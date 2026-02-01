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
```

## 📋 View Logs

### Using the logs command (recommended)
```bash
# Interactive log viewer
clonebox logs . --user

# Show all logs at once
clonebox logs . --user --all

# For system session VMs
clonebox logs . --all
```

### Available logs
- **Boot diagnostic log** - Shows VM boot process and any issues
- **Monitor log** - CloneBox monitor service logs
- **Cloud-init logs** - System initialization logs

### Legacy log access
```bash
# Via SSH
ssh ubuntu@<IP_VM> "tail -f /var/log/clonebox-monitor.log"

# Via log disk (system session only)
sudo mount -o loop /var/lib/libvirt/images/clonebox-logs.qcow2 /mnt/clonebox-logs
less /mnt/clonebox-logs/var/log/clonebox-boot.log
```

## 🔐 Password Management

### Set VM Password
```bash
# Interactive password setting
clonebox set-password . --user

# For system session VMs
clonebox set-password .
```

### Password Authentication
The VM uses SSH key authentication by default. To enable password authentication:
1. Set password using `clonebox set-password` command
2. Or set `VM_PASSWORD` environment variable before creating VM
3. Or configure directly in `.clonebox.yaml`:
   ```yaml
   vm:
     auth_method: "ssh_key"  # or "one_time_password"
     password: "your-password"
   ```

### SSH Access
```bash
# Get VM IP first
clonebox status . --user

# SSH with password
ssh ubuntu@<IP_VM>

# SSH with key (default)
ssh -i ~/.local/share/libvirt/images/clone-clonebox/ssh_key ubuntu@<IP_VM>
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

# Access logs from host (new method)
clonebox logs . --user  # Interactive
clonebox logs . --user --all  # Show all at once

# Legacy method
./scripts/clonebox-logs.sh  # Interactive log viewer
# Or manually:
sudo mount -o loop /var/lib/libvirt/images/clonebox-logs.qcow2 /mnt/clonebox-logs
less /mnt/clonebox-logs/var/log/clonebox-boot.log
```

## 📋 Configuration Files

### Config Format v2 (Recommended)
```yaml
version: '2'
vm:
  name: my-dev-vm
  ram_mb: 8192
  vcpus: 8
  gui: true
  auth:
    method: ssh_key  # ssh_key | one_time_password | password

secrets:
  provider: auto  # auto | env | vault | sops

limits:
  memory_limit: 8G
  cpu_shares: 1024

health_checks:
  - name: ssh
    type: tcp
    port: 22

packages:
  - docker.io
  - git

services:
  - docker
```

### Config Format v1 (Legacy)
```yaml
vm:
  name: my-vm
  auth_method: ssh_key  # Flat structure
  password: ubuntu      # Deprecated - use auth.method: ssh_key
```

### Host Configuration
- `.clonebox.yaml` - VM configuration
- `.env` - Environment variables

### VM Configuration
- `/etc/environment` - System-wide env vars
- `/etc/default/clonebox-monitor` - Monitor settings
- `~/.config/autostart/` - GUI app autostart
- `/var/log/clonebox-*.log` - Various logs

## 📸 Snapshot Management

```bash
# Create a snapshot
clonebox snapshot create . --name "before-upgrade" --user

# List snapshots
clonebox snapshot list . --user

# Restore a snapshot
clonebox snapshot restore . --name "before-upgrade" --user

# Delete a snapshot
clonebox snapshot delete . --name "before-upgrade" --user
```

## 🎭 Multi-VM Orchestration

```bash
# Start all VMs from clonebox-compose.yaml
clonebox compose up

# Stop all VMs
clonebox compose down

# Check status
clonebox compose status

# View aggregated logs
clonebox compose logs
```

## 🔌 Plugin Management

```bash
# List plugins
clonebox plugin list

# Install a plugin
clonebox plugin install clonebox-plugin-kubernetes

# Enable/disable
clonebox plugin enable kubernetes
clonebox plugin disable kubernetes

# Discover available plugins
clonebox plugin discover
```

## 🌐 Remote VM Management

```bash
# List VMs on remote host
clonebox remote list user@server --user

# Get remote VM status
clonebox remote status user@server my-vm --user

# Start/stop remote VM
clonebox remote start user@server my-vm --user
clonebox remote stop user@server my-vm --user

# Execute command in remote VM
clonebox remote exec user@server my-vm -- ls -la

# Health check on remote
clonebox remote health user@server my-vm --user
```

## 📝 Audit Logging

```bash
# List recent audit events
clonebox audit list --since "1 week ago"

# Search for specific events
clonebox audit search --event vm.create

# Export audit log
clonebox audit export --format json > audit.json
```

## 🔄 Workflow Examples

### Daily Development
```bash
# Start VM and monitor
clonebox start . --user
clonebox watch . --user

# If something breaks
clonebox repair . --user

# Check logs (new method)
clonebox logs . --user  # Interactive
clonebox logs . --user --all  # Show all at once

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
# Or use log disk (new method):
clonebox logs . --user --all
```
