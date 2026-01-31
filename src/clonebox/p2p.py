#!/usr/bin/env python3
"""
P2P Manager - Transfer VMs between workstations via SSH/SCP.
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class P2PManager:
    """Manage P2P VM transfers between workstations."""

    def __init__(self, ssh_options: Optional[list] = None):
        self.ssh_options = ssh_options or [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]

    def _run_ssh(self, host: str, command: str) -> subprocess.CompletedProcess:
        """Execute command on remote host via SSH."""
        cmd = ["ssh"] + self.ssh_options + [host, command]
        return subprocess.run(cmd, capture_output=True, text=True)

    def _run_scp(
        self,
        source: str,
        destination: str,
        recursive: bool = False,
    ) -> subprocess.CompletedProcess:
        """Copy files via SCP."""
        cmd = ["scp"] + self.ssh_options
        if recursive:
            cmd.append("-r")
        cmd.extend([source, destination])
        return subprocess.run(cmd, capture_output=True, text=True)

    def export_remote(
        self,
        host: str,
        vm_name: str,
        output: Path,
        encrypted: bool = False,
        include_user_data: bool = False,
        include_app_data: bool = False,
    ) -> Path:
        """Export VM from remote host to local file.

        Args:
            host: Remote host in format user@hostname
            vm_name: Name of VM to export
            output: Local output path
            encrypted: Use encrypted export
            include_user_data: Include user data
            include_app_data: Include app data
        """
        remote_tmp = f"/tmp/clonebox-{vm_name}.tar.gz"
        if encrypted:
            remote_tmp = f"/tmp/clonebox-{vm_name}.enc"

        # Build export command
        export_cmd = f"clonebox export {vm_name} -o {remote_tmp}"
        if encrypted:
            export_cmd = f"clonebox export-encrypted {vm_name} -o {remote_tmp}"
        if include_user_data:
            export_cmd += " --user"
        if include_app_data:
            export_cmd += " --include-data"

        print(f"📤 Exporting {vm_name} from {host}...")

        # Execute remote export
        result = self._run_ssh(host, export_cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Remote export failed: {result.stderr}")

        # Download file
        print(f"⬇️  Downloading to {output}...")
        result = self._run_scp(f"{host}:{remote_tmp}", str(output))
        if result.returncode != 0:
            raise RuntimeError(f"SCP download failed: {result.stderr}")

        # Cleanup remote temp file
        self._run_ssh(host, f"rm -f {remote_tmp}")

        print(f"✅ Downloaded: {output}")
        return output

    def import_remote(
        self,
        host: str,
        archive_path: Path,
        encrypted: bool = False,
        import_user_data: bool = False,
        new_name: Optional[str] = None,
    ) -> str:
        """Upload and import VM on remote host.

        Args:
            host: Remote host in format user@hostname
            archive_path: Local archive to upload
            encrypted: Use decrypted import
            import_user_data: Import user data
            new_name: New name for VM on remote
        """
        remote_tmp = f"/tmp/{archive_path.name}"

        print(f"⬆️  Uploading {archive_path} to {host}...")

        # Upload file
        result = self._run_scp(str(archive_path), f"{host}:{remote_tmp}")
        if result.returncode != 0:
            raise RuntimeError(f"SCP upload failed: {result.stderr}")

        # Build import command
        if encrypted:
            import_cmd = f"clonebox import-encrypted {remote_tmp}"
        else:
            import_cmd = f"clonebox import {remote_tmp}"

        if import_user_data:
            import_cmd += " --user"
        if new_name:
            import_cmd += f" --name {new_name}"

        print(f"📥 Importing on {host}...")

        # Execute remote import
        result = self._run_ssh(host, import_cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Remote import failed: {result.stderr}")

        # Cleanup remote temp file
        self._run_ssh(host, f"rm -f {remote_tmp}")

        print(f"✅ Import complete on {host}")
        return new_name or archive_path.stem

    def sync_key(self, host: str) -> bool:
        """Sync encryption key to remote host.

        Args:
            host: Remote host in format user@hostname

        Returns:
            True if key was synced successfully
        """
        key_path = Path.home() / ".clonebox.key"
        if not key_path.exists():
            raise FileNotFoundError(f"No local key found at {key_path}")

        print(f"🔑 Syncing encryption key to {host}...")

        result = self._run_scp(str(key_path), f"{host}:~/.clonebox.key")
        if result.returncode != 0:
            raise RuntimeError(f"Key sync failed: {result.stderr}")

        # Set proper permissions on remote
        self._run_ssh(host, "chmod 600 ~/.clonebox.key")

        print(f"✅ Key synced to {host}")
        return True

    def list_remote_vms(self, host: str) -> list:
        """List VMs on remote host.

        Args:
            host: Remote host in format user@hostname

        Returns:
            List of VM names
        """
        result = self._run_ssh(host, "virsh list --all --name")
        if result.returncode != 0:
            return []

        vms = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return vms

    def check_clonebox_installed(self, host: str) -> bool:
        """Check if clonebox is installed on remote host."""
        result = self._run_ssh(host, "which clonebox || command -v clonebox")
        return result.returncode == 0
