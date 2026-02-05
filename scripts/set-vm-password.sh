#!/bin/bash
# Set password for ubuntu user in VM

VM_NAME="${1:-clone-clonebox}"

ARG2="${2:-}"
ARG3="${3:-}"
ARG4="${4:-}"

PASSWORD=""
USER_SESSION="false"
USERNAME="ubuntu"

if [ "$ARG2" = "true" ] || [ "$ARG2" = "false" ]; then
    USER_SESSION="$ARG2"
    USERNAME="${ARG3:-ubuntu}"
else
    PASSWORD="$ARG2"
    USER_SESSION="${ARG3:-false}"
    USERNAME="${ARG4:-ubuntu}"
fi

if [ "$USER_SESSION" = "true" ]; then
    CONNECT="qemu:///session"
else
    CONNECT="qemu:///system"
fi

echo "Setting password for ${USERNAME} user in VM: $VM_NAME"
echo ""

if [ -z "$PASSWORD" ]; then
    echo -n "Enter new password for ${USERNAME} user: "
    read -s PASSWORD
    echo ""
    echo -n "Confirm password: "
    read -s PASSWORD2
    echo ""

    if [ "$PASSWORD" != "$PASSWORD2" ]; then
        echo "Passwords do not match!"
        exit 1
    fi
fi

echo "Setting password..."
CLONEBOX_VM_NAME="$VM_NAME" CLONEBOX_CONNECT="$CONNECT" CLONEBOX_USERNAME="$USERNAME" CLONEBOX_PASSWORD="$PASSWORD" python3 <<'EOF'
import base64
import json
import os
import subprocess
import sys
import time


def _qga_cmd(payload: dict) -> dict:
    cmd = [
        "virsh",
        "--connect",
        os.environ["CLONEBOX_CONNECT"],
        "qemu-agent-command",
        os.environ["CLONEBOX_VM_NAME"],
        json.dumps(payload),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "virsh failed")
    return json.loads(result.stdout)


def _wait_exec(pid: int, timeout_s: int = 30) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _qga_cmd({"execute": "guest-exec-status", "arguments": {"pid": pid}})
        ret = status.get("return", {})
        if ret.get("exited"):
            return ret
        time.sleep(0.5)
    raise TimeoutError("guest-exec-status timed out")


def _decode(data: str) -> str:
    if not data:
        return ""
    try:
        return base64.b64decode(data).decode("utf-8", errors="ignore")
    except Exception:
        return ""


username = os.environ.get("CLONEBOX_USERNAME", "ubuntu")
password = os.environ["CLONEBOX_PASSWORD"]

exec_payload = {
    "execute": "guest-exec",
    "arguments": {
        "path": "/bin/sh",
        "arg": ["-c", f"echo '{username}:{password}' | chpasswd"],
        "capture-output": True,
    },
}

resp = _qga_cmd(exec_payload)
pid = resp.get("return", {}).get("pid")
if not pid:
    print("Failed to start password set command")
    sys.exit(1)

ret = _wait_exec(pid)
exitcode = ret.get("exitcode")
stderr = _decode(ret.get("err-data", ""))
stdout = _decode(ret.get("out-data", ""))

if exitcode not in (0, None):
    print("Failed to set password")
    if stdout:
        print(stdout)
    if stderr:
        print(stderr)
    sys.exit(1)

print("Password set successfully")
EOF

# Enable password authentication in SSH
echo "Enabling password authentication in SSH..."
CLONEBOX_VM_NAME="$VM_NAME" CLONEBOX_CONNECT="$CONNECT" python3 <<'EOF'
import base64
import json
import os
import subprocess
import sys
import time


def _qga_cmd(payload: dict) -> dict:
    cmd = [
        "virsh",
        "--connect",
        os.environ["CLONEBOX_CONNECT"],
        "qemu-agent-command",
        os.environ["CLONEBOX_VM_NAME"],
        json.dumps(payload),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "virsh failed")
    return json.loads(result.stdout)


def _wait_exec(pid: int, timeout_s: int = 30) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _qga_cmd({"execute": "guest-exec-status", "arguments": {"pid": pid}})
        ret = status.get("return", {})
        if ret.get("exited"):
            return ret
        time.sleep(0.5)
    raise TimeoutError("guest-exec-status timed out")


def _decode(data: str) -> str:
    if not data:
        return ""
    try:
        return base64.b64decode(data).decode("utf-8", errors="ignore")
    except Exception:
        return ""


cmd = (
    "sed -i -E \"s/^[#[:space:]]*PasswordAuthentication[[:space:]].*/PasswordAuthentication yes/\" /etc/ssh/sshd_config "
    "&& systemctl restart ssh"
)

exec_payload = {
    "execute": "guest-exec",
    "arguments": {
        "path": "/bin/sh",
        "arg": ["-c", cmd],
        "capture-output": True,
    },
}

resp = _qga_cmd(exec_payload)
pid = resp.get("return", {}).get("pid")
if not pid:
    print("Failed to start SSH config command")
    sys.exit(1)

ret = _wait_exec(pid)
exitcode = ret.get("exitcode")
stderr = _decode(ret.get("err-data", ""))
stdout = _decode(ret.get("out-data", ""))

if exitcode not in (0, None):
    print("Failed to enable SSH password auth")
    if stdout:
        print(stdout)
    if stderr:
        print(stderr)
    sys.exit(1)

print("SSH password authentication enabled")
EOF

echo ""
echo "Password configuration complete!"
echo "You can now SSH to the VM using: ssh ubuntu@<vm-ip>"
