#!/bin/bash
# Set password for ubuntu user in VM

VM_NAME="${1:-clone-clonebox}"
USER_SESSION="${2:-false}"

if [ "$USER_SESSION" = "true" ]; then
    CONNECT="qemu:///session"
else
    CONNECT="qemu:///system"
fi

echo "Setting password for ubuntu user in VM: $VM_NAME"
echo ""

# Prompt for password
echo -n "Enter new password for ubuntu user: "
read -s PASSWORD
echo ""
echo -n "Confirm password: "
read -s PASSWORD2
echo ""

if [ "$PASSWORD" != "$PASSWORD2" ]; then
    echo "Passwords do not match!"
    exit 1
fi

# Use QEMU Guest Agent to set password
echo "Setting password..."
python3 <<EOF
import subprocess
import json
import sys

# Set password using chpasswd
password = "$PASSWORD"
cmd = ['virsh', '--connect', '$CONNECT', 'qemu-agent-command', '$VM_NAME',
       '{"execute":"guest-exec","arguments":{"path":"/bin/sh","arg":["-c","echo ubuntu:' + password + ' | sudo chpasswd"],"capture-output":true}}']

result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode == 0:
    data = json.loads(result.stdout)
    if 'return' in data:
        print('Password set successfully')
    else:
        print('Failed to set password')
        sys.exit(1)
else:
    print('Error executing command')
    sys.exit(1)
EOF

# Enable password authentication in SSH
echo "Enabling password authentication in SSH..."
python3 <<EOF
import subprocess
import json

cmd = ['virsh', '--connect', '$CONNECT', 'qemu-agent-command', '$VM_NAME',
       '{"execute":"guest-exec","arguments":{"path":"/bin/sh","arg":["-c","sudo sed -i \\\"s/#PasswordAuthentication yes/PasswordAuthentication yes/\\\" /etc/ssh/sshd_config && sudo systemctl restart ssh"],"capture-output":true}}']

result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode == 0:
    data = json.loads(result.stdout)
    if 'return' in data:
        print('SSH password authentication enabled')
    else:
        print('Failed to enable SSH password auth')
EOF

echo ""
echo "Password configuration complete!"
echo "You can now SSH to the VM using: ssh ubuntu@<vm-ip>"
