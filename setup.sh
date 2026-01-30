#!/bin/bash

# Clonebox Setup Script
# This script helps prepare the environment for clonebox

set -e

echo "🔧 Clonebox Setup Script"
echo "========================"
echo

# Function to check if running as root
check_root() {
    if [[ $EUID -eq 0 ]]; then
        echo "❌ This script should not be run as root for user session setup"
        echo "   Run without sudo for user session, or with sudo for system session"
        exit 1
    fi
}

# Function to install dependencies
install_dependencies() {
    echo "📦 Installing required packages..."
    
    # Check if we can use apt
    if command -v apt &> /dev/null; then
        echo "   Using apt to install packages..."
        
        # Update package list
        sudo apt update
        
        # Install core packages
        sudo apt install -y \
            qemu-kvm \
            libvirt-daemon-system \
            libvirt-clients \
            bridge-utils \
            virtinst \
            virt-manager \
            qemu-utils \
            python3 \
            python3-pip \
            python3-venv \
            git
        
        # Install optional but recommended packages
        sudo apt install -y \
            virt-viewer \
            spice-client-gtk
        
        # Add user to required groups
        echo "👥 Adding user to libvirt and kvm groups..."
        sudo usermod -aG libvirt $USER
        sudo usermod -aG kvm $USER
        
        echo "✅ Packages installed successfully"
        echo "⚠️  You may need to log out and log back in for group changes to take effect"
        
    else
        echo "❌ apt not found. Please install the following packages manually:"
        echo "   - qemu-kvm"
        echo "   - libvirt"
        echo "   - python3"
        echo "   - python3-pip"
        echo "   - virt-viewer (optional, for GUI access)"
        exit 1
    fi
}

# Function to setup libvirt networks
setup_networks() {
    echo "🌐 Setting up libvirt networks..."
    
    # Check if libvirt is running
    if ! systemctl --user is-active --quiet libvirtd 2>/dev/null; then
        echo "   Starting libvirtd service..."
        systemctl --user start libvirtd
        systemctl --user enable libvirtd
    fi
    
    # Create default network for user session
    echo "   Creating default network for user session..."
    
    cat > /tmp/default-network.xml <<EOF
<network>
  <name>default</name>
  <forward mode='nat'/>
  <bridge name='virbr0' stp='on' delay='0'/>
  <ip address='192.168.122.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='192.168.122.2' end='192.168.122.254'/>
    </dhcp>
  </ip>
</network>
EOF
    
    # Try to create the network
    if virsh --connect qemu:///session net-list --all | grep -q "default"; then
        echo "   Default network already exists"
    else
        virsh --connect qemu:///session net-define /tmp/default-network.xml
        virsh --connect qemu:///session net-autostart default
        virsh --connect qemu:///session net-start default
        echo "   ✅ Default network created and started"
    fi
    
    # Clean up
    rm -f /tmp/default-network.xml
}

# Function to install clonebox
install_clonebox() {
    echo "📥 Installing clonebox..."
    
    # Check if we're in the clonebox directory
    if [[ ! -f "pyproject.toml" ]]; then
        echo "❌ Please run this script from the clonebox repository directory"
        exit 1
    fi
    
    # Install in development mode
    pip install --break-system-packages -e .
    
    echo "✅ Clonebox installed successfully"
}

# Function to show next steps
show_next_steps() {
    echo
    echo "🎉 Setup complete!"
    echo "================="
    echo
    echo "Next steps:"
    echo "1. If you haven't already, log out and log back in for group changes to take effect"
    echo "2. Run clonebox to create your VM:"
    echo "   clonebox clone . --user"
    echo
    echo "To connect to your VM after creation:"
    echo "- With GUI: virt-viewer --connect qemu:///session <vm-name>"
    echo "- With console: virsh --connect qemu:///session console <vm-name>"
    echo
    echo "To list your VMs:"
    echo "   clonebox list"
    echo
    echo "To manage VMs:"
    echo "   clonebox start <vm-name>"
    echo "   clonebox stop <vm-name>"
    echo "   clonebox delete <vm-name>"
}

# Main execution
main() {
    echo "Checking system..."
    
    # Check if user session or system session
    if [[ "$1" == "--system" ]]; then
        echo "Using system session (requires sudo)"
        # For system session, we'd need different setup
        echo "⚠️  System session setup not implemented in this script"
        echo "   Please use user session with --user flag"
        exit 1
    else
        check_root
    fi
    
    # Install dependencies
    install_dependencies
    
    # Setup networks
    setup_networks
    
    # Install clonebox
    install_clonebox
    
    # Show next steps
    show_next_steps
}

# Run main function
main "$@"
