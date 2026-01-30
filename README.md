# CloneBox 📦

```commandline
╔═══════════════════════════════════════════════════════╗
║     ____  _                    ____                   ║
║    / ___|| |  ___   _ __   ___|  _ \  ___ __  __      ║
║   | |    | | / _ \ | '_ \ / _ \ |_) |/ _ \\ \/ /      ║
║   | |___ | || (_) || | | |  __/  _ <| (_) |>  <       ║
║    \____||_| \___/ |_| |_|\___|_| \_\\___//_/\_\      ║
║                                                       ║
║      Clone your workstation to an isolated VM         ║
╚═══════════════════════════════════════════════════════╝
```
**Clone your workstation environment to an isolated VM with selective apps, paths and services.**

CloneBox lets you create isolated virtual machines with only the applications, directories and services you need - using bind mounts instead of full disk cloning. Perfect for development, testing, or creating reproducible environments.

## Features

- 🎯 **Selective cloning** - Choose exactly which paths, services and apps to include
- 🔍 **Auto-detection** - Automatically detects running services, applications, and project directories
- 🔗 **Bind mounts** - Share directories with the VM without copying data
- ☁️ **Cloud-init** - Automatic package installation and service setup
- 🖥️ **GUI support** - SPICE graphics with virt-viewer integration
- ⚡ **Fast creation** - No full disk cloning, VMs are ready in seconds

## Installation

### Prerequisites

```bash
# Install libvirt and QEMU/KVM
sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virt-manager virt-viewer

# Enable and start libvirtd
sudo systemctl enable --now libvirtd

# Add user to libvirt group
sudo usermod -aG libvirt $USER
newgrp libvirt

# Install genisoimage for cloud-init
sudo apt install genisoimage
```

### Install CloneBox

```bash
# From source
git clone https://github.com/wronai/clonebox.git
cd clonebox
pip install -e .

# Or directly
pip install clonebox
```
lub
```bash
# Aktywuj venv
source .venv/bin/activate

# Interaktywny tryb (wizard)
clonebox

# Lub poszczególne komendy
clonebox detect              # Pokaż wykryte usługi/apps/ścieżki
clonebox list                # Lista VM
clonebox create --config ... # Utwórz VM z JSON config
clonebox start <name>        # Uruchom VM
clonebox stop <name>         # Zatrzymaj VM
clonebox delete <name>       # Usuń VM
```

## Quick Start

### Interactive Mode (Recommended)

Simply run `clonebox` to start the interactive wizard:

```bash
clonebox
```

The wizard will:
1. Detect running services (Docker, PostgreSQL, nginx, etc.)
2. Detect running applications and their working directories
3. Detect project directories and config files
4. Let you select what to include in the VM
5. Create and optionally start the VM

### Command Line

```bash
# Create VM with specific config
clonebox create --name my-dev-vm --config '{
  "paths": {
    "/home/user/projects": "/mnt/projects",
    "/home/user/.config": "/mnt/config"
  },
  "packages": ["python3", "nodejs", "docker.io"],
  "services": ["docker"]
}' --ram 4096 --vcpus 4 --start

# List VMs
clonebox list

# Start/Stop VM
clonebox start my-dev-vm
clonebox stop my-dev-vm

# Delete VM
clonebox delete my-dev-vm

# Detect system state (useful for scripting)
clonebox detect --json
```

## Usage Examples

### Python Development Environment

```bash
clonebox create --name python-dev --config '{
  "paths": {
    "/home/user/my-python-project": "/workspace",
    "/home/user/.pyenv": "/root/.pyenv"
  },
  "packages": ["python3", "python3-pip", "python3-venv", "build-essential"],
  "services": []
}' --ram 2048 --start
```

### Docker Development

```bash
clonebox create --name docker-dev --config '{
  "paths": {
    "/home/user/docker-projects": "/projects",
    "/var/run/docker.sock": "/var/run/docker.sock"
  },
  "packages": ["docker.io", "docker-compose"],
  "services": ["docker"]
}' --ram 4096 --start
```

### Full Stack (Node.js + PostgreSQL)

```bash
clonebox create --name fullstack --config '{
  "paths": {
    "/home/user/my-app": "/app",
    "/home/user/pgdata": "/var/lib/postgresql/data"
  },
  "packages": ["nodejs", "npm", "postgresql"],
  "services": ["postgresql"]
}' --ram 4096 --vcpus 4 --start
```

## Inside the VM

After the VM boots, mount shared directories:

```bash
# Mount shared paths (9p filesystem)
sudo mkdir -p /mnt/projects
sudo mount -t 9p -o trans=virtio,version=9p2000.L mount0 /mnt/projects

# Or add to /etc/fstab for permanent mount
echo "mount0 /mnt/projects 9p trans=virtio,version=9p2000.L 0 0" | sudo tee -a /etc/fstab
```

## Architecture

```
┌────────────────────────────────────────────────────────┐
│                     HOST SYSTEM                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ /home/user/  │  │  /var/www/   │  │   Docker     │  │
│  │  projects/   │  │    html/     │  │   Socket     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │          │
│         │    9p/virtio    │                 │          │
│         │   bind mounts   │                 │          │
│  ┌──────▼─────────────────▼─────────────────▼───────┐  │
│  │               CloneBox VM                        │  │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐    │  │
│  │  │ /mnt/proj  │ │ /mnt/www   │ │ /var/run/  │    │  │
│  │  │            │ │            │ │ docker.sock│    │  │
│  │  └────────────┘ └────────────┘ └────────────┘    │  │
│  │                                                  │  │
│  │  cloud-init installed packages & services        │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

## Quick Clone (Recommended)

The fastest way to clone your current working directory:

```bash
# Clone current directory - generates .clonebox.yaml and asks to create VM
clonebox clone .

# Clone specific path
clonebox clone ~/projects/my-app

# Clone with custom name and auto-start
clonebox clone ~/projects/my-app --name my-dev-vm --run

# Clone and edit config before creating
clonebox clone . --edit
```

Later, start the VM from any directory with `.clonebox.yaml`:

```bash
# Start VM from config in current directory
clonebox start .

# Start VM from specific path
clonebox start ~/projects/my-app
```

### Export YAML Config

```bash
# Export detected state as YAML (with deduplication)
clonebox detect --yaml --dedupe

# Save to file
clonebox detect --yaml --dedupe -o my-config.yaml
```

## Commands Reference

| Command | Description |
|---------|-------------|
| `clonebox` | Interactive VM creation wizard |
| `clonebox clone <path>` | Generate `.clonebox.yaml` from path + running processes |
| `clonebox clone . --run` | Clone and immediately start VM |
| `clonebox clone . --edit` | Clone, edit config, then create |
| `clonebox start .` | Start VM from `.clonebox.yaml` in current dir |
| `clonebox start <name>` | Start existing VM by name |
| `clonebox stop <name>` | Stop a VM (graceful shutdown) |
| `clonebox stop -f <name>` | Force stop a VM |
| `clonebox delete <name>` | Delete VM and storage |
| `clonebox list` | List all VMs |
| `clonebox detect` | Show detected services/apps/paths |
| `clonebox detect --yaml` | Output as YAML config |
| `clonebox detect --yaml --dedupe` | YAML with duplicates removed |
| `clonebox detect --json` | Output as JSON |

## Requirements

- Linux with KVM support (`/dev/kvm`)
- libvirt daemon running
- Python 3.8+
- User in `libvirt` group

## License

MIT License - see [LICENSE](LICENSE) file.