#!/usr/bin/env python3
"""
Cloud-init configuration generation for CloneBox VMs.
"""

import json
import yaml
from typing import Dict, List, Optional, Tuple

from clonebox.models import VMConfig


def generate_cloud_init_config(
    config: VMConfig,
    autostart_apps: List[Dict] = None,
    user_session: bool = False,
    bootcmd_extra: List = None,
) -> Tuple[str, str, str]:
    """Generate cloud-init configuration for VM.
    
    Returns:
        Tuple of (user_data, meta_data, network_config)
    """
    
    autostart_apps = autostart_apps or []
    bootcmd_extra = bootcmd_extra or []
    
    # Generate runcmd for setup with detailed progress logging
    runcmd_lines = [
        "echo '[clonebox] =========================================' > /dev/ttyS0",
        "echo '[clonebox] Starting VM setup (runcmd phase)...' > /dev/ttyS0",
        "echo '[clonebox] Step 1/10: Updating package lists...' > /dev/ttyS0",
        "apt-get update 2>&1 | tee -a /var/log/cloud-init-output.log || echo '[clonebox] WARNING: apt-get update failed' > /dev/ttyS0",
        "echo '[clonebox] Step 2/10: Installing qemu-guest-agent...' > /dev/ttyS0",
        "apt-get install -y qemu-guest-agent cloud-initramfs-growroot 2>&1 | tee -a /var/log/cloud-init-output.log || echo '[clonebox] WARNING: Package installation failed' > /dev/ttyS0",
        "echo '[clonebox] Step 3/10: Enabling qemu-guest-agent...' > /dev/ttyS0",
        "systemctl enable qemu-guest-agent 2>&1 | tee -a /var/log/cloud-init-output.log || echo '[clonebox] WARNING: Failed to enable qemu-guest-agent' > /dev/ttyS0 || true",
        "echo '[clonebox] Step 4/10: Starting qemu-guest-agent...' > /dev/ttyS0",
        "systemctl start qemu-guest-agent 2>&1 | tee -a /var/log/cloud-init-output.log || echo '[clonebox] WARNING: Failed to start qemu-guest-agent' > /dev/ttyS0",
        "echo '[clonebox] Core packages installed successfully' > /dev/ttyS0",
    ]
    
    # Install GNOME desktop if GUI mode is enabled
    if config.gui:
        runcmd_lines.extend([
            "echo '[clonebox] =========================================' > /dev/ttyS0",
            "echo '[clonebox] Installing GNOME Desktop Environment...' > /dev/ttyS0",
            "echo '[clonebox] This may take 10-15 minutes depending on connection speed' > /dev/ttyS0",
            # Update package lists first
            "apt-get update 2>&1 | tee -a /var/log/cloud-init-output.log | while read line; do echo \"[clonebox] [apt] $line\" > /dev/ttyS0; done",
            # Install ubuntu-desktop (minimal) or full ubuntu-desktop
            "echo '[clonebox] Installing ubuntu-desktop packages...' > /dev/ttyS0",
            "DEBIAN_FRONTEND=noninteractive apt-get install -y ubuntu-desktop-minimal gdm3 2>&1 | tee -a /var/log/cloud-init-output.log | while read line; do echo \"[clonebox] [apt-desktop] $line\" > /dev/ttyS0; done || echo '[clonebox] WARNING: Some desktop packages failed to install' > /dev/ttyS0",
            # Ensure GDM is enabled
            "systemctl enable gdm3 2>&1 | tee -a /var/log/cloud-init-output.log || echo '[clonebox] WARNING: Failed to enable gdm3' > /dev/ttyS0",
            # Set graphical target as default
            "systemctl set-default graphical.target 2>&1 | tee -a /var/log/cloud-init-output.log || echo '[clonebox] WARNING: Failed to set graphical target' > /dev/ttyS0",
            "echo '[clonebox] GNOME Desktop installation complete' > /dev/ttyS0",
        ])
    
    # Install packages with progress logging
    if config.packages:
        runcmd_lines.extend([
            f"echo '[clonebox] Installing {len(config.packages)} packages...' > /dev/ttyS0",
            f"echo '[clonebox] Packages: {' '.join(config.packages[:5])}{'...' if len(config.packages) > 5 else ''}' > /dev/ttyS0",
            f"apt-get install -y {' '.join(config.packages)} 2>&1 | tee -a /var/log/cloud-init-output.log | while read line; do echo \"[clonebox] [apt] $line\" > /dev/ttyS0; done || true",
        ])
    
    # Install snap packages with progress logging
    if config.snap_packages:
        runcmd_lines.extend([
            "echo '[clonebox] Installing snap packages...' > /dev/ttyS0",
            "echo '[clonebox] Installing snapd...' > /dev/ttyS0",
            "apt-get install -y snapd 2>&1 | tee -a /var/log/cloud-init-output.log | while read line; do echo \"[clonebox] [apt] $line\" > /dev/ttyS0; done || echo '[clonebox] WARNING: snapd installation failed' > /dev/ttyS0",
            "systemctl enable snapd 2>/dev/null || true",
            "systemctl start snapd 2>/dev/null || true",
            # Wait for snapd to be ready
            "echo '[clonebox] Waiting for snapd to be ready...' > /dev/ttyS0",
            "for i in 1 2 3 4 5; do snap wait system seed.loaded 2>/dev/null && break || sleep 5; done",
        ])
        
        for idx, snap in enumerate(config.snap_packages):
            runcmd_lines.append(f"echo '[clonebox] [{idx+1}/{len(config.snap_packages)}] Installing snap: {snap}...' > /dev/ttyS0")
            classic_snaps = ["code", "pycharm-community", "intellij-idea-community", "clion", "goland", "rubymine", "webstorm", "phpstorm", "datagrip"]
            is_classic = snap in classic_snaps
            classic_flag = "--classic" if is_classic else ""
            if snap in SNAP_INTERFACES:
                runcmd_lines.extend([
                    f"echo '[clonebox] Installing {snap} with interfaces...' > /dev/ttyS0",
                    f"snap install {snap} {classic_flag} 2>&1 | tee -a /var/log/cloud-init-output.log | while read line; do echo \"[clonebox] [snap-{snap}] $line\" > /dev/ttyS0; done || echo '[clonebox] WARNING: Failed to install {snap}' > /dev/ttyS0",
                ])
                # Classic snaps have full system access — snap connect is not needed/supported
                if not is_classic:
                    for iface in SNAP_INTERFACES[snap]:
                        runcmd_lines.append(
                            f"snap connections {snap} 2>/dev/null | grep -q ':{iface} ' "
                            f"&& snap connect {snap}:{iface} 2>&1 | tee -a /var/log/cloud-init-output.log "
                            f"|| echo '[clonebox] SKIP: {snap}:{iface} plug not available' > /dev/ttyS0"
                        )
            else:
                # Regular snap
                runcmd_lines.append(f"snap install {snap} 2>&1 | tee -a /var/log/cloud-init-output.log | while read line; do echo \"[clonebox] [snap-{snap}] $line\" > /dev/ttyS0; done || echo '[clonebox] WARNING: Failed to install {snap}' > /dev/ttyS0")
    
    # Create mount points with error handling
    if config.paths:
        runcmd_lines.append("echo '[clonebox] Setting up mount points...' > /dev/ttyS0")
        runcmd_lines.append(f"echo '[clonebox] Configuring {len(config.paths)} mount(s)...' > /dev/ttyS0")
        for idx, (host_path, guest_path) in enumerate(config.paths.items()):
            mount_name = f"mount{idx}"
            runcmd_lines.extend([
                f"echo '[clonebox] [{idx+1}/{len(config.paths)}] Mount: {host_path} -> {guest_path}' > /dev/ttyS0",
                f"mkdir -p {guest_path}",
                # Add nofail option to prevent boot failures if mount fails
                f"echo '{mount_name} {guest_path} 9p trans=virtio,version=9p2000.L,rw,nofail,x-systemd.device-timeout=5s 0 0' >> /etc/fstab",
                # Try to mount immediately and report status
                f"if mount {guest_path} 2>/dev/null; then echo '[clonebox] [OK] Mounted {guest_path}' > /dev/ttyS0; else echo '[clonebox] [WARN] Mount {guest_path} failed (will retry on boot)' > /dev/ttyS0; fi",
            ])
        runcmd_lines.append("echo '[clonebox] Mount configuration complete' > /dev/ttyS0")
        runcmd_lines.append("echo '[clonebox] Note: 9p mounts require virtio-9p in VM XML' > /dev/ttyS0")
    
    # Copy paths
    if config.copy_paths:
        runcmd_lines.append("echo '[clonebox] Copying files...' > /dev/ttyS0")
        for host_path, guest_path in config.copy_paths.items():
            runcmd_lines.append(f"mkdir -p {guest_path}")
            # Note: Actual copying happens via virt-customize
    
    # Setup services with verification
    if config.services:
        runcmd_lines.extend([
            "echo '[clonebox] Enabling services...' > /dev/ttyS0",
        ])
        for service in config.services:
            # Check if service file exists before enabling
            runcmd_lines.append(f"if systemctl list-unit-files {service}.service 2>/dev/null | grep -q {service}; then systemctl enable {service} 2>&1 | tee -a /var/log/cloud-init-output.log && echo '[clonebox] [OK] Enabled {service}' > /dev/ttyS0 || echo '[clonebox] [WARN] Failed to enable {service}' > /dev/ttyS0; else echo '[clonebox] [SKIP] {service} not found' > /dev/ttyS0; fi")
    
    # Setup autostart applications
    if autostart_apps and config.autostart_apps:
        runcmd_lines.append("echo '[clonebox] Setting up autostart applications...' > /dev/ttyS0")
        for app in autostart_apps:
            if app["type"] == "snap":
                # Create systemd user service for snap
                service_content = f"""[Unit]
Description={app['name']}
After=snapd.service

[Service]
Type=simple
ExecStart=/usr/bin/snap run {app['name']}
Restart=on-failure
User={config.username}

[Install]
WantedBy=default.target
"""
                runcmd_lines.extend([
                    f"mkdir -p /home/{config.username}/.config/systemd/user",
                    f"echo '{service_content}' > /home/{config.username}/.config/systemd/user/{app['name']}.service",
                    f"chown -R {config.username}:{config.username} /home/{config.username}/.config",
                    f"sudo -u {config.username} systemctl --user enable {app['name']}.service",
                ])
    
    # Setup web services
    if config.web_services:
        runcmd_lines.append("echo '[clonebox] Setting up web services...' > /dev/ttyS0")
        for service in config.web_services:
            if service["type"] == "uvicorn":
                runcmd_lines.extend([
                    f"echo '[Unit]' > /etc/systemd/system/{service['name']}.service",
                    "echo 'Description=UVicorn service' >> /etc/systemd/system/{service['name']}.service",
                    "echo 'After=network.target' >> /etc/systemd/system/{service['name']}.service",
                    "echo '' >> /etc/systemd/system/{service['name']}.service",
                    "echo '[Service]' >> /etc/systemd/system/{service['name']}.service",
                    f"echo 'User={config.username}' >> /etc/systemd/system/{service['name']}.service",
                    f"echo 'WorkingDirectory={service.get('working_dir', f'/home/{config.username}')}' >> /etc/systemd/system/{service['name']}.service",
                    f"echo 'ExecStart=/usr/bin/uvicorn {service['module']} --host {service.get('host', '0.0.0.0')} --port {service.get('port', 8000)}' >> /etc/systemd/system/{service['name']}.service",
                    "echo 'Restart=always' >> /etc/systemd/system/{service['name']}.service",
                    "echo '' >> /etc/systemd/system/{service['name']}.service",
                    "echo '[Install]' >> /etc/systemd/system/{service['name']}.service",
                    "echo 'WantedBy=multi-user.target' >> /etc/systemd/system/{service['name']}.service",
                    f"systemctl enable {service['name']}.service",
                ])
    
    # Post commands
    if config.post_commands:
        runcmd_lines.append("echo '[clonebox] Running post-commands...' > /dev/ttyS0")
        for cmd in config.post_commands:
            runcmd_lines.append(cmd)
        # Add marker to indicate post-commands completed
        runcmd_lines.extend([
            "touch /tmp/clonebox-post-commands-done",
            "echo '[clonebox] Post-commands completed' > /dev/ttyS0",
        ])
    
    # Setup monitor script
    monitor_script = f'''#!/bin/bash
# CloneBox Monitor Script
LOG_FILE="/var/log/clonebox-monitor.log"
STATUS_FILE="/var/run/clonebox-monitor-status.json"

log() {{
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}}

check_mounts() {{
    for mount in $(grep "^mount" /etc/fstab | awk '{{print $2}}'); do
        if ! mountpoint -q "$mount" 2>/dev/null; then
            log "Mount $mount not active, attempting remount..."
            mount "$mount" 2>/dev/null || log "Failed to mount $mount"
        fi
    done
}}

check_services() {{
    for service in {' '.join(config.services) if config.services else ''}; do
        if systemctl is-active --quiet "$service"; then
            log "Service $service is running"
        else
            log "Service $service is not running, attempting restart..."
            systemctl restart "$service" 2>/dev/null || log "Failed to restart $service"
        fi
    done
}}

write_status() {{
    echo '{{"timestamp": "'$(date -Iseconds)'", "mounts_ok": true}}' > "$STATUS_FILE"
}}

# Main loop
while true; do
    check_mounts
    check_services
    write_status
    sleep 60
done
'''
    
    runcmd_lines.extend([
        "echo '#!/bin/bash' > /usr/local/bin/clonebox-monitor",
        f"echo '{monitor_script}' >> /usr/local/bin/clonebox-monitor",
        "chmod +x /usr/local/bin/clonebox-monitor",
        "echo '[Unit]' > /etc/systemd/system/clonebox-monitor.service",
        "echo 'Description=CloneBox Monitor' >> /etc/systemd/system/clonebox-monitor.service",
        "echo 'After=network.target' >> /etc/systemd/system/clonebox-monitor.service",
        "echo '' >> /etc/systemd/system/clonebox-monitor.service",
        "echo '[Service]' >> /etc/systemd/system/clonebox-monitor.service",
        "echo 'Type=simple' >> /etc/systemd/system/clonebox-monitor.service",
        "echo 'ExecStart=/usr/local/bin/clonebox-monitor' >> /etc/systemd/system/clonebox-monitor.service",
        "echo 'Restart=always' >> /etc/systemd/system/clonebox-monitor.service",
        "echo '' >> /etc/systemd/system/clonebox-monitor.service",
        "echo '[Install]' >> /etc/systemd/system/clonebox-monitor.service",
        "echo 'WantedBy=multi-user.target' >> /etc/systemd/system/clonebox-monitor.service",
        "systemctl enable clonebox-monitor.service",
    ])
    
    # Setup logs disk
    runcmd_lines.extend([
        "mkdir -p /var/lib/clonebox /mnt/logs",
        "truncate -s 1G /var/lib/clonebox/logs.img",
        "mkfs.ext4 -F /var/lib/clonebox/logs.img >/dev/null 2>&1",
        "echo '/var/lib/clonebox/logs.img /mnt/logs ext4 loop,defaults 0 0' >> /etc/fstab",
        "mount /mnt/logs || echo 'Failed to mount logs disk'",
        "mkdir -p /mnt/logs/var/log /mnt/logs/tmp",
    ])
    
    # Reboot if GUI is enabled
    if config.gui:
        runcmd_lines.extend([
            "echo '[clonebox] Rebooting in 10 seconds to start GUI...' > /dev/ttyS0",
            "sleep 10 && reboot",
        ])
    
    # Build cloud-config
    cloud_config = {
        "hostname": config.name,
        "manage_etc_hosts": True,
        "users": [
            {
                "name": config.username,
                "groups": "sudo,adm,video,render",
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
                "ssh_authorized_keys": [config.ssh_public_key] if config.ssh_public_key else [],
                "lock_passwd": False,
            }
        ],
        "ssh_pwauth": True if config.gui else config.auth_method in ["password", "one_time_password"],
        "runcmd": runcmd_lines,
        "bootcmd": [
            ["sh", "-c", "echo '[clonebox] bootcmd - starting configuration' > /dev/ttyS0 || true"],
            ["systemctl", "enable", "serial-getty@ttyS0.service"],
        ],
        "output": {"all": "| tee -a /var/log/cloud-init-output.log"},
    }

    if config.gui or config.auth_method in ["password", "one_time_password"]:
        cloud_config["chpasswd"] = {
            "expire": False,
            "list": f"{config.username}:{config.password}",
        }
    
    # Generate network-config for user session (passt networking)
    network_config = None
    if user_session:
        network_config = generate_network_config()
    
    # Add user session network setup if needed
    if user_session:
        net_setup_cmd = (
            "NIC=$(ip -o link show | grep -E 'enp|ens|eth' | grep -v 'lo' | head -1 | awk -F': ' '{print $2}' | tr -d ' '); "
            "if [ -n \"$NIC\" ]; then "
            "  echo '[clonebox] Found NIC: $NIC' > /dev/ttyS0; "
            "  ip addr show $NIC | grep -q 'inet ' || ( "
            "    echo '[clonebox] Manual network config for $NIC' > /dev/ttyS0; "
            "    ip addr add 10.0.2.15/24 dev $NIC 2>/dev/null; "
            "    ip link set $NIC up; "
            "    ip route add default via 10.0.2.2 2>/dev/null; "
            "    echo nameserver 10.0.2.3 > /etc/resolv.conf "
            "  ); "
            "else "
            "  echo '[clonebox] No NIC found for network setup' > /dev/ttyS0; "
            "fi"
        )
        cloud_config["bootcmd"].extend([
            ["sh", "-c", "echo '[clonebox] Running network fallback...' > /dev/ttyS0"],
            ["sh", "-c", net_setup_cmd],
        ])
    
    # Add extra bootcmd if provided
    if bootcmd_extra:
        cloud_config["bootcmd"].extend(bootcmd_extra)
    
    # Convert to YAML
    cloud_config_yaml = yaml.dump(cloud_config, default_flow_style=False)
    
    # Add cloud-init header
    user_data = "#cloud-config\n" + cloud_config_yaml
    
    # Meta-data
    meta_data = f"instance-id: {config.name}\nlocal-hostname: {config.name}\n"
    
    return user_data, meta_data, network_config


def generate_network_config() -> str:
    """Generate network-config for cloud-init NoCloud datasource.
    
    Uses static IP configuration for passt user-mode networking.
    """
    network_config = {
        "version": 2,
        "ethernets": {
            "eth0": {
                "match": {"name": "en*"},
                "addresses": ["10.0.2.15/24"],
                "routes": [{"to": "default", "via": "10.0.2.2"}],
                "nameservers": {"addresses": ["10.0.2.3"]},
            }
        }
    }
    return yaml.dump(network_config, default_flow_style=False)


# Snap interfaces configuration
SNAP_INTERFACES = {
    "pycharm-community": [
        "desktop",
        "desktop-legacy",
        "x11",
        "wayland",
        "home",
        "network",
        "network-bind",
        "cups-control",
    ],
    "chromium": [
        "desktop",
        "desktop-legacy",
        "x11",
        "wayland",
        "home",
        "network",
        "audio-playback",
        "camera",
    ],
    "firefox": [
        "desktop",
        "desktop-legacy",
        "x11",
        "wayland",
        "home",
        "network",
        "audio-playback",
        "removable-media",
    ],
    "code": ["desktop", "desktop-legacy", "x11", "wayland", "home", "network", "ssh-keys"],
    "slack": ["desktop", "desktop-legacy", "x11", "wayland", "home", "network", "audio-playback"],
    "spotify": ["desktop", "x11", "wayland", "home", "network", "audio-playback"],
}
DEFAULT_SNAP_INTERFACES = ["desktop", "desktop-legacy", "x11", "home", "network"]
