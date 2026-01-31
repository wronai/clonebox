#!/usr/bin/env python3
"""
VM Exporter - Export VM with all data and optional AES-256 encryption.
"""

import os
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional

from cryptography.fernet import Fernet

try:
    import libvirt
except ImportError:
    libvirt = None


class VMExporter:
    """Export VM with disks, app data, and user data."""

    def __init__(self, conn_uri: str = "qemu:///system"):
        self.conn_uri = conn_uri
        self._conn = None

    @property
    def conn(self):
        if self._conn is None:
            if libvirt is None:
                raise RuntimeError("libvirt-python not installed")
            self._conn = libvirt.open(self.conn_uri)
        return self._conn

    def export_vm(
        self,
        vm_name: str,
        output_path: Path,
        include_user_data: bool = False,
        include_app_data: bool = False,
    ) -> Path:
        """Full export of VM with disks and optional data."""
        vm = self.conn.lookupByName(vm_name)
        vm_xml = vm.XMLDesc()
        root = ET.fromstring(vm_xml)

        # Find all disk files
        disks: List[Path] = []
        for disk in root.findall(".//disk[@type='file']"):
            source = disk.find(".//source")
            if source is not None and source.get("file"):
                disk_path = Path(source.get("file"))
                if disk_path.exists():
                    disks.append(disk_path)

        # Create archive
        with tarfile.open(output_path, "w:gz") as tar:
            # Add XML config
            xml_tmp = Path(tempfile.gettempdir()) / f"{vm_name}.xml"
            xml_tmp.write_text(vm_xml)
            tar.add(xml_tmp, arcname=f"{vm_name}.xml")
            xml_tmp.unlink()

            # Add disks
            for disk in disks:
                arcname = f"disks/{disk.name}"
                tar.add(disk, arcname=arcname)
                print(f"   💾 Added disk: {disk}")

            # Add app data
            if include_app_data:
                self._export_app_data(tar)

            # Add user data
            if include_user_data:
                self._export_user_data(tar)

        return output_path

    def _export_app_data(self, tar: tarfile.TarFile) -> None:
        """Export common application data paths."""
        common_paths = [
            Path.home() / "projects",
            Path.home() / ".docker",
            Path("/opt/myapp"),
            Path("/var/www"),
            Path("/srv/docker"),
        ]

        for path in common_paths:
            if path.exists():
                arcname = f"app-data/{path.name}"
                try:
                    tar.add(path, arcname=arcname, recursive=True)
                    print(f"   📁 App data: {path}")
                except PermissionError:
                    print(f"   ⚠️ Permission denied: {path}")

    def _export_user_data(self, tar: tarfile.TarFile) -> None:
        """Export user data (home, SSH keys)."""
        user_paths = [
            Path.home() / ".ssh",
            Path.home() / ".gitconfig",
            Path.home() / ".bashrc",
            Path.home() / ".zshrc",
        ]

        for path in user_paths:
            if path.exists():
                arcname = f"user-data/{path.name}"
                try:
                    tar.add(path, arcname=arcname, recursive=True)
                    print(f"   👤 User data: {path}")
                except PermissionError:
                    print(f"   ⚠️ Permission denied: {path}")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class SecureExporter:
    """AES-256 encrypted VM export."""

    KEY_PATH = Path.home() / ".clonebox.key"

    def __init__(self, conn_uri: str = "qemu:///system"):
        self.exporter = VMExporter(conn_uri)

    @classmethod
    def generate_key(cls) -> Path:
        """Generate and save team encryption key."""
        key = Fernet.generate_key()
        cls.KEY_PATH.write_bytes(key)
        os.chmod(str(cls.KEY_PATH), 0o600)
        return cls.KEY_PATH

    @classmethod
    def load_key(cls) -> Optional[bytes]:
        """Load encryption key from file."""
        if cls.KEY_PATH.exists():
            return cls.KEY_PATH.read_bytes()
        return None

    def export_encrypted(
        self,
        vm_name: str,
        output_path: Path,
        include_user_data: bool = False,
        include_app_data: bool = False,
    ) -> Path:
        """Export VM with AES-256 encryption."""
        key = self.load_key()
        if key is None:
            raise FileNotFoundError(
                f"No encryption key found at {self.KEY_PATH}. Run: clonebox keygen"
            )

        fernet = Fernet(key)

        # Create temporary unencrypted archive
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            # Export to temp file
            self.exporter.export_vm(
                vm_name=vm_name,
                output_path=tmp_path,
                include_user_data=include_user_data,
                include_app_data=include_app_data,
            )

            # Encrypt
            data = tmp_path.read_bytes()
            encrypted = fernet.encrypt(data)
            output_path.write_bytes(encrypted)

        finally:
            # Cleanup temp file
            if tmp_path.exists():
                tmp_path.unlink()

        return output_path

    def close(self) -> None:
        self.exporter.close()
