#!/usr/bin/env python3
"""
VM Importer - Import VM with path reconfiguration and decryption.
"""

import shutil
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

try:
    import libvirt
except ImportError:
    libvirt = None


class VMImporter:
    """Import VM with disk path reconfiguration."""

    DEFAULT_DISK_DIR = Path("/var/lib/libvirt/images")

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

    def import_vm(
        self,
        archive_path: Path,
        import_user_data: bool = False,
        import_app_data: bool = False,
        new_name: Optional[str] = None,
        disk_dir: Optional[Path] = None,
    ) -> str:
        """Import VM from archive with full path reconfiguration."""
        disk_dir = disk_dir or self.DEFAULT_DISK_DIR

        with tempfile.TemporaryDirectory(prefix="clonebox-import-") as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Extract archive
            with tarfile.open(archive_path) as tar:
                tar.extractall(tmp_path)

            # Find XML file
            xml_files = list(tmp_path.glob("*.xml"))
            if not xml_files:
                raise FileNotFoundError("No XML configuration found in archive")
            xml_file = xml_files[0]
            vm_name = xml_file.stem

            # Move disks to libvirt images directory
            disks_dir = tmp_path / "disks"
            disk_mapping = {}
            if disks_dir.exists():
                for disk_file in disks_dir.iterdir():
                    dest = disk_dir / disk_file.name
                    shutil.copy2(disk_file, dest)
                    disk_mapping[disk_file.name] = dest
                    print(f"   💾 Copied disk: {dest}")

            # Reconfigure disk paths in XML
            vm_xml = self._reconfigure_paths(xml_file, disk_mapping, new_name)

            # Define and create VM
            vm = self.conn.defineXML(vm_xml)
            final_name = new_name or vm_name
            print(f"   ✅ VM defined: {final_name}")

            # Import user/app data
            if import_user_data:
                self._import_user_data(tmp_path / "user-data")
            if import_app_data:
                self._import_app_data(tmp_path / "app-data")

            # Start VM
            vm.create()
            print(f"   🚀 VM started: {final_name}")

            return final_name

    def _reconfigure_paths(
        self,
        xml_file: Path,
        disk_mapping: dict,
        new_name: Optional[str] = None,
    ) -> str:
        """Update disk paths and optionally rename VM."""
        tree = ET.parse(xml_file)
        root = tree.getroot()

        # Update name if requested
        if new_name:
            name_elem = root.find("name")
            if name_elem is not None:
                name_elem.text = new_name

        # Update disk paths
        for disk in root.findall(".//disk[@type='file']"):
            source = disk.find(".//source")
            if source is not None:
                old_path = source.get("file")
                if old_path:
                    disk_name = Path(old_path).name
                    if disk_name in disk_mapping:
                        source.set("file", str(disk_mapping[disk_name]))
                        print(f"   🔄 Remapped: {disk_name} → {disk_mapping[disk_name]}")

        return ET.tostring(root, encoding="unicode")

    def _import_user_data(self, user_data_dir: Path) -> None:
        """Restore user data."""
        if user_data_dir.exists():
            for item in user_data_dir.iterdir():
                dest = Path.home() / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
                print(f"   👤 Restored: {dest}")

    def _import_app_data(self, app_data_dir: Path) -> None:
        """Restore application data."""
        if app_data_dir.exists():
            for item in app_data_dir.iterdir():
                # Map back to original paths
                dest_map = {
                    "projects": Path.home() / "projects",
                    ".docker": Path.home() / ".docker",
                    "myapp": Path("/opt/myapp"),
                    "www": Path("/var/www"),
                    "docker": Path("/srv/docker"),
                }
                dest = dest_map.get(item.name, Path.home() / item.name)
                try:
                    if item.is_dir():
                        shutil.copytree(item, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest)
                    print(f"   📁 Restored: {dest}")
                except PermissionError:
                    print(f"   ⚠️ Permission denied: {dest}")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class SecureImporter:
    """AES-256 decrypting VM importer."""

    KEY_PATH = Path.home() / ".clonebox.key"

    def __init__(self, conn_uri: str = "qemu:///system"):
        self.importer = VMImporter(conn_uri)

    @classmethod
    def load_key(cls) -> Optional[bytes]:
        """Load decryption key from file."""
        if cls.KEY_PATH.exists():
            return cls.KEY_PATH.read_bytes()
        return None

    def import_decrypted(
        self,
        encrypted_path: Path,
        import_user_data: bool = False,
        import_app_data: bool = False,
        new_name: Optional[str] = None,
    ) -> str:
        """Import VM with AES-256 decryption."""
        key = self.load_key()
        if key is None:
            raise FileNotFoundError(
                f"No decryption key found at {self.KEY_PATH}. "
                "Copy the team key to this location."
            )

        fernet = Fernet(key)

        # Create temporary decrypted archive
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            # Decrypt
            encrypted_data = encrypted_path.read_bytes()
            decrypted = fernet.decrypt(encrypted_data)
            tmp_path.write_bytes(decrypted)

            # Import
            vm_name = self.importer.import_vm(
                archive_path=tmp_path,
                import_user_data=import_user_data,
                import_app_data=import_app_data,
                new_name=new_name,
            )

        finally:
            # Cleanup
            if tmp_path.exists():
                tmp_path.unlink()

        return vm_name

    def close(self) -> None:
        self.importer.close()
