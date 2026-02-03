#!/usr/bin/env bash
set -euo pipefail

PATH_ARG="${1:-.}"
shift || true

BASE_IMAGE=""
DISK_SIZE_GB=""
TAIL_SECONDS="30"
VALIDATE="true"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --base-image)
      BASE_IMAGE="$2"
      shift 2
      ;;
    --disk-size-gb)
      DISK_SIZE_GB="$2"
      shift 2
      ;;
    --tail-seconds)
      TAIL_SECONDS="$2"
      shift 2
      ;;
    --no-validate)
      VALIDATE="false"
      shift 1
      ;;
    -h|--help)
      cat <<EOF
Usage:
  scripts/test-user-vm.sh [PATH] [--base-image <qcow2>] [--disk-size-gb <N>] [--tail-seconds <N>] [--no-validate]

This script:
  1) runs: clonebox clone PATH --user --run --replace
  2) tails host serial.log for quick provisioning visibility
  3) waits for SSH on passt-forwarded port (reads ssh_key + ssh_port files)
  4) optionally runs: clonebox test PATH --user --validate
EOF
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

PATH_ABS="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$PATH_ARG")"
CONFIG_FILE="$PATH_ABS/.clonebox.yaml"

CLONE_ARGS=(clonebox clone "$PATH_ABS" --user --run --replace)
if [ -n "$BASE_IMAGE" ]; then
  CLONE_ARGS+=(--base-image "$BASE_IMAGE")
fi
if [ -n "$DISK_SIZE_GB" ]; then
  CLONE_ARGS+=(--disk-size-gb "$DISK_SIZE_GB")
fi

echo "[test-user-vm] Running: ${CLONE_ARGS[*]}"
"${CLONE_ARGS[@]}"

echo ""
if [ ! -f "$CONFIG_FILE" ]; then
  echo "[test-user-vm] ERROR: config not found: $CONFIG_FILE" >&2
  exit 1
fi

VM_NAME="$(python3 -c 'import sys,yaml; print((yaml.safe_load(open(sys.argv[1])) or {})["vm"]["name"])' "$CONFIG_FILE")"
VM_DIR="$HOME/.local/share/libvirt/images/$VM_NAME"
SERIAL_LOG="$VM_DIR/serial.log"
SSH_KEY="$VM_DIR/ssh_key"
SSH_PORT_FILE="$VM_DIR/ssh_port"

echo "[test-user-vm] VM: $VM_NAME"
echo "[test-user-vm] VM dir: $VM_DIR"
echo "[test-user-vm] serial.log: $SERIAL_LOG"

if [ -f "$SERIAL_LOG" ]; then
  echo "[test-user-vm] Showing serial.log (last 80 lines):"
  tail -n 80 "$SERIAL_LOG" || true
else
  echo "[test-user-vm] serial.log not created yet (this is OK right after start)."
fi

echo ""
echo "[test-user-vm] Follow live logs with: tail -f $SERIAL_LOG"

echo ""
echo "[test-user-vm] Tailing serial.log for ${TAIL_SECONDS}s (Ctrl+C to stop)..."
if command -v timeout >/dev/null 2>&1; then
  timeout "${TAIL_SECONDS}"s tail -n 200 -f "$SERIAL_LOG" 2>/dev/null || true
else
  tail -n 200 -f "$SERIAL_LOG" 2>/dev/null || true
fi

echo ""
if [ ! -f "$SSH_KEY" ]; then
  echo "[test-user-vm] ERROR: SSH key not found: $SSH_KEY" >&2
  exit 1
fi

if [ ! -f "$SSH_PORT_FILE" ]; then
  echo "[test-user-vm] ERROR: SSH port file not found: $SSH_PORT_FILE" >&2
  exit 1
fi

SSH_PORT="$(cat "$SSH_PORT_FILE" | tr -d '[:space:]')"
if [ -z "$SSH_PORT" ]; then
  echo "[test-user-vm] ERROR: empty ssh_port file" >&2
  exit 1
fi

echo "[test-user-vm] Waiting for SSH: ssh -i $SSH_KEY -p $SSH_PORT ubuntu@127.0.0.1"

DEADLINE=$(( $(date +%s) + 240 ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  if ssh \
      -i "$SSH_KEY" \
      -p "$SSH_PORT" \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o ConnectTimeout=3 \
      -o BatchMode=yes \
      ubuntu@127.0.0.1 \
      "echo ok" >/dev/null 2>&1; then
    echo "[test-user-vm] SSH is up."
    break
  fi
  sleep 2
done

if [ "$(date +%s)" -ge "$DEADLINE" ]; then
  echo "[test-user-vm] ERROR: SSH did not become ready within 240s" >&2
  exit 1
fi

echo ""
echo "[test-user-vm] Quick in-guest checks (SSH):"
ssh \
  -i "$SSH_KEY" \
  -p "$SSH_PORT" \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=5 \
  -o BatchMode=yes \
  ubuntu@127.0.0.1 \
  "cloud-init status 2>/dev/null || true; echo '---'; ip -br addr 2>/dev/null || true; echo '---'; systemctl is-active qemu-guest-agent 2>/dev/null || true" \
  || true

echo ""
if [ "$VALIDATE" = "true" ]; then
  echo "[test-user-vm] Running: clonebox test $PATH_ABS --user --validate"
  clonebox test "$PATH_ABS" --user --validate
else
  echo "[test-user-vm] Skipping clonebox test --validate (--no-validate)."
fi
