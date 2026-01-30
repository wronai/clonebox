# CloneBox 📦
![img.png](img.png)

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
- 📥 **Auto-download** - Automatically downloads and caches Ubuntu cloud images (stored in ~/Downloads)
- 📊 **Health monitoring** - Built-in health checks for packages, services, and mounts
- 🔄 **VM migration** - Export/import VMs with data between workstations
- 🧪 **Configuration testing** - Validate VM settings and functionality
- 📁 **App data sync** - Include browser profiles, IDE settings, and app configs




CloneBox to narzędzie CLI do **szybkiego klonowania aktualnego środowiska workstation do izolowanej maszyny wirtualnej (VM)**. 
Zamiast pełnego kopiowania dysku, używa **bind mounts** (udostępnianie katalogów na żywo) i **cloud-init** do selektywnego przeniesienia tylko potrzebnych elementów: uruchomionych usług (Docker, PostgreSQL, nginx), aplikacji, ścieżek projektów i konfiguracji. Automatycznie pobiera obrazy Ubuntu, instaluje pakiety i uruchamia VM z SPICE GUI. Idealne dla deweloperów na Linuxie – VM powstaje w minuty, bez duplikowania danych.

Kluczowe komendy:
- `clonebox` – interaktywny wizard (detect + create + start)
- `clonebox detect` – skanuje usługi/apps/ścieżki
- `clonebox clone . --user --run` – szybki klon bieżącego katalogu z użytkownikiem i autostartem

### Dlaczego wirtualne klony workstation mają sens?

**Problem**: Developerzy/Vibecoderzy nie izolują środowisk dev/test (np. dla AI agentów), bo ręczne odtwarzanie setupu to ból – godziny na instalację apps, usług, configów, dotfiles. Przechodzenie z fizycznego PC na VM wymagałoby pełnego rebuilda, co blokuje workflow.

**Rozwiązanie CloneBox**: Automatycznie **skanuje i klonuje stan "tu i teraz"** (usługi z `ps`, dockery z `docker ps`, projekty z git/.env). VM dziedziczy środowisko bez kopiowania całego śmietnika – tylko wybrane bind mounty. 

**Korzyści w twoim kontekście (embedded/distributed systems, AI automation)**:
- **Sandbox dla eksperymentów**: Testuj AI agenty, edge computing (RPi/ESP32 symulacje) czy Camel/ERP integracje w izolacji, bez psucia hosta.
- **Reprodukcja workstation**: Na firmowym PC masz setup z domu (Python/Rust/Go envs, Docker compose, Postgres dev DB) – klonujesz i pracujesz identycznie.
- **Szybkość > dotfiles**: Dotfiles odtwarzają configi, ale nie łapią runtime stanu (uruchomione serwery, otwarte projekty). CloneBox to "snapshot na sterydach".
- **Bezpieczeństwo/cost-optymalizacja**: Izolacja od plików hosta (tylko mounts), zero downtime, tanie w zasobach (libvirt/QEMU). Dla SME: szybki onboarding dev env bez migracji fizycznej.
- **AI-friendly**: Agenci LLMs (jak te z twoich hobby) mogą działać w VM z pełnym kontekstem, bez ryzyka "zasmiecania" main PC.

Przykład: Masz uruchomiony Kubernetes Podman z twoim home labem + projekt automotive leasing. `clonebox clone ~/projects --run` → VM gotowa w 30s, z tymi samymi serwisami, ale izolowana. Lepsze niż Docker (brak GUI/full OS) czy pełna migracja.

**Dlaczego ludzie tego nie robią?** Brak automatyzacji – nikt nie chce ręcznie rebuildować. 
- CloneBox rozwiązuje to jednym poleceniem. Super match dla twoich interesów (distributed infra, AI tools, business automation).



## Installation

### Quick Setup (Recommended)

Run the setup script to automatically install dependencies and configure the environment:

```bash
# Clone the repository
git clone https://github.com/wronai/clonebox.git
cd clonebox

# Run the setup script
./setup.sh
```

The setup script will:
- Install all required packages (QEMU, libvirt, Python, etc.)
- Add your user to the necessary groups
- Configure libvirt networks
- Install clonebox in development mode

### Manual Installation

#### Prerequisites

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

#### Install CloneBox

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
clonebox clone . --user --run --replace --base-image ~/ubuntu-22.04-cloud.qcow2

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

After the VM boots, shared directories are automatically mounted via fstab entries. You can check their status:

```bash
# Check mount status
mount | grep 9p

# View health check report
cat /var/log/clonebox-health.log

# Re-run health check manually
clonebox-health

# Check cloud-init status
sudo cloud-init status

# Manual mount (if needed)
sudo mkdir -p /mnt/projects
sudo mount -t 9p -o trans=virtio,version=9p2000.L,nofail mount0 /mnt/projects
```

### Health Check System

CloneBox includes automated health checks that verify:
- Package installation (apt/snap)
- Service status
- Mount points accessibility
- GUI readiness

Health check logs are saved to `/var/log/clonebox-health.log` with a summary in `/var/log/clonebox-health-status`.

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
# Base OS image is automatically downloaded to ~/Downloads on first run
clonebox clone .

# Clone specific path
clonebox clone ~/projects/my-app

# Clone with custom name and auto-start
clonebox clone ~/projects/my-app --name my-dev-vm --run

# Clone and edit config before creating
clonebox clone . --edit

# Replace existing VM (stops, deletes, and recreates)
clonebox clone . --replace

# Use custom base image instead of auto-download
clonebox clone . --base-image ~/ubuntu-22.04-cloud.qcow2

# User session mode (no root required)
clonebox clone . --user
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

### Base Images

CloneBox automatically downloads a bootable Ubuntu cloud image on first run:

```bash
# Auto-download (default) - downloads Ubuntu 22.04 to ~/Downloads on first run
clonebox clone .

# Use custom base image
clonebox clone . --base-image ~/my-custom-image.qcow2

# Manual download (optional - clonebox does this automatically)
wget -O ~/Downloads/clonebox-ubuntu-jammy-amd64.qcow2 \
  https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img
```

**Base image behavior:**
- If no `--base-image` is specified, Ubuntu 22.04 cloud image is auto-downloaded
- Downloaded images are cached in `~/Downloads/clonebox-ubuntu-jammy-amd64.qcow2`
- Subsequent VMs reuse the cached image (no re-download)
- Each VM gets its own disk using the base image as a backing file (copy-on-write)

### VM Login Credentials

VM credentials are managed through `.env` file for security:

**Setup:**
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set your password:
   ```bash
   # .env file
   VM_PASSWORD=your_secure_password
   VM_USERNAME=ubuntu
   ```

3. The `.clonebox.yaml` file references the password from `.env`:
   ```yaml
   vm:
     username: ubuntu
     password: ${VM_PASSWORD}  # Loaded from .env
   ```

**Default credentials (if .env not configured):**
- **Username:** `ubuntu`
- **Password:** `ubuntu`

**Security notes:**
- `.env` is automatically gitignored (never committed)
- Username is stored in YAML (not sensitive)
- Password is stored in `.env` (sensitive, not committed)
- Change password after first login: `passwd`
- User has passwordless sudo access

### User Session & Networking

CloneBox supports creating VMs in user session (no root required) with automatic network fallback:

```bash
# Create VM in user session (uses ~/.local/share/libvirt/images)
clonebox clone . --user

# Explicitly use user-mode networking (slirp) - works without libvirt network
clonebox clone . --user --network user

# Force libvirt default network (may fail in user session)
clonebox clone . --network default

# Auto mode (default): tries libvirt network, falls back to user-mode if unavailable
clonebox clone . --network auto
```

**Network modes:**
- `auto` (default): Uses libvirt default network if available, otherwise falls back to user-mode (slirp)
- `default`: Forces use of libvirt default network
- `user`: Uses user-mode networking (slirp) - no bridge setup required

## Commands Reference

| Command | Description |
|---------|-------------|
| `clonebox` | Interactive VM creation wizard |
| `clonebox clone <path>` | Generate `.clonebox.yaml` from path + running processes |
| `clonebox clone . --run` | Clone and immediately start VM |
| `clonebox clone . --edit` | Clone, edit config, then create |
| `clonebox clone . --replace` | Replace existing VM (stop, delete, recreate) |
| `clonebox clone . --user` | Clone in user session (no root) |
| `clonebox clone . --base-image <path>` | Use custom base image |
| `clonebox clone . --network user` | Use user-mode networking (slirp) |
| `clonebox clone . --network auto` | Auto-detect network mode (default) |
| `clonebox start .` | Start VM from `.clonebox.yaml` in current dir |
| `clonebox start . --viewer` | Start VM and open GUI window |
| `clonebox start <name>` | Start existing VM by name |
| `clonebox stop <name>` | Stop a VM (graceful shutdown) |
| `clonebox stop -f <name>` | Force stop a VM |
| `clonebox delete <name>` | Delete VM and storage |
| `clonebox list` | List all VMs |
| `clonebox detect` | Show detected services/apps/paths |
| `clonebox detect --yaml` | Output as YAML config |
| `clonebox detect --yaml --dedupe` | YAML with duplicates removed |
| `clonebox detect --json` | Output as JSON |
| `clonebox status . --user` | Check VM health, cloud-init status, and IP address |
| `clonebox test . --user` | Test VM configuration and validate all settings |
| `clonebox export . --user` | Export VM for migration to another workstation |
| `clonebox export . --user --include-data` | Export VM with browser profiles and configs |
| `clonebox import archive.tar.gz --user` | Import VM from export archive |
| `clonebox open . --user` | Open GUI viewer for VM (same as virt-viewer) |
| `virt-viewer --connect qemu:///session <vm>` | Open GUI for running VM |
| `virsh --connect qemu:///session console <vm>` | Open text console (Ctrl+] to exit) |

## Requirements

- Linux with KVM support (`/dev/kvm`)
- libvirt daemon running
- Python 3.8+
- User in `libvirt` group

## Troubleshooting

### Network Issues

If you encounter "Network not found" or "network 'default' is not active" errors:

```bash
# Option 1: Use user-mode networking (no setup required)
clonebox clone . --user --network user

# Option 2: Run the network fix script
./fix-network.sh

# Or manually fix:
virsh --connect qemu:///session net-destroy default 2>/dev/null
virsh --connect qemu:///session net-undefine default 2>/dev/null
virsh --connect qemu:///session net-define /tmp/default-network.xml
virsh --connect qemu:///session net-start default
```

### Permission Issues

If you get permission errors:

```bash
# Ensure user is in libvirt and kvm groups
sudo usermod -aG libvirt $USER
sudo usermod -aG kvm $USER

# Log out and log back in for groups to take effect
```

### VM Already Exists

If you get "VM already exists" error:

```bash
# Option 1: Use --replace flag to automatically replace it
clonebox clone . --replace

# Option 2: Delete manually first
clonebox delete <vm-name>

# Option 3: Use virsh directly
virsh --connect qemu:///session destroy <vm-name>
virsh --connect qemu:///session undefine <vm-name>

# Option 4: Start the existing VM instead
clonebox start <vm-name>
```

### virt-viewer not found

If GUI doesn't open:

```bash
# Install virt-viewer
sudo apt install virt-viewer

# Then connect manually
virt-viewer --connect qemu:///session <vm-name>
```

### Browser Profiles Not Syncing

If browser profiles or app data aren't available:

1. **Regenerate config with app data:**
   ```bash
   rm .clonebox.yaml
   clonebox clone . --user --run --replace
   ```

2. **Check mount permissions in VM:**
   ```bash
   # Verify mounts are accessible
   ls -la ~/.config/google-chrome
   ls -la ~/.mozilla/firefox
   ```

### Mount Points Empty After Reboot

If shared directories appear empty after VM restart:

1. **Check fstab entries:**
   ```bash
   cat /etc/fstab | grep 9p
   ```

2. **Mount manually:**
   ```bash
   sudo mount -a
   ```

3. **Verify access mode:**
   - VMs created with `accessmode="mapped"` allow any user to access mounts
   - Older VMs used `accessmode="passthrough"` which preserves host UIDs

## Advanced Usage

### VM Migration Between Workstations

Export your complete VM environment:

```bash
# Export VM with all data
clonebox export . --user --include-data -o my-dev-env.tar.gz

# Transfer to new workstation, then import
clonebox import my-dev-env.tar.gz --user
clonebox start . --user
```

### Testing VM Configuration

Validate your VM setup:

```bash
# Quick test (basic checks)
clonebox test . --user --quick

# Full test (includes health checks)
clonebox test . --user --verbose
```

### Monitoring VM Health

Check VM status from workstation:

```bash
# Check VM state, IP, cloud-init, and health
clonebox status . --user

# Trigger health check in VM
clonebox status . --user --health
```

### Reopening VM Window

If you close the VM window, you can reopen it:

```bash
# Open GUI viewer (easiest)
clonebox open . --user

# Start VM and open GUI (if VM is stopped)
clonebox start . --user --viewer

# Open GUI for running VM
virt-viewer --connect qemu:///session clone-clonebox

# List VMs to get the correct name
clonebox list

# Text console (no GUI)
virsh --connect qemu:///session console clone-clonebox
# Press Ctrl + ] to exit console
```

## License

MIT License - see [LICENSE](LICENSE) file.
