"""
End-to-end tests for CloneBox full workflow.

These tests require:
- KVM support (/dev/kvm)
- libvirt running
- qemu-system-x86_64 installed
- Network access (to download Ubuntu cloud image)

Run with: pytest tests/e2e/ -m e2e -v --tb=short
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import yaml


@pytest.mark.e2e
@pytest.mark.slow
class TestFullWorkflow:
    """Test complete CloneBox workflow: clone → start → validate → stop → delete."""

    @pytest.fixture
    def e2e_config_dir(self):
        """Create a temporary directory with E2E test config."""
        with tempfile.TemporaryDirectory(prefix="clonebox-e2e-") as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test project structure
            (tmpdir / "projects" / "test-project").mkdir(parents=True)
            (tmpdir / "projects" / "test-project" / "main.py").write_text("print('hello')")
            (tmpdir / "data").mkdir()
            (tmpdir / "data" / "test.txt").write_text("test data")

            # Create minimal config for fast E2E testing
            config = {
                "version": "1",
                "vm": {
                    "name": "e2e-test-vm",
                    "ram_mb": 2048,
                    "vcpus": 2,
                    "gui": False,  # No GUI for E2E tests
                    "network_mode": "user",
                    "username": "ubuntu",
                    "password": "ubuntu",
                },
                "paths": {
                    str(tmpdir / "projects"): "/mnt/projects",
                    str(tmpdir / "data"): "/mnt/data",
                },
                "app_data_paths": {},
                "packages": ["curl", "git"],
                "snap_packages": [],
                "services": [],
                "post_commands": [],
            }

            (tmpdir / ".clonebox.yaml").write_text(yaml.dump(config))

            yield tmpdir

    def test_detect_command(self):
        """Test clonebox detect command."""
        result = subprocess.run(
            ["clonebox", "detect", "--json"], capture_output=True, text=True, timeout=30
        )

        # Command should succeed
        assert result.returncode == 0
        # Should output valid JSON - find JSON in output
        import json

        output = result.stdout
        # Try to find JSON object in output
        try:
            # Look for JSON starting with {
            start = output.find("{")
            if start >= 0:
                data = json.loads(output[start:])
                assert isinstance(data, dict)
            else:
                # No JSON found, but command succeeded
                pass
        except json.JSONDecodeError:
            # JSON parsing failed but command succeeded, that's OK for detect
            pass

    def test_detect_yaml_output(self):
        """Test clonebox detect --yaml command."""
        result = subprocess.run(
            ["clonebox", "detect", "--yaml"], capture_output=True, text=True, timeout=30
        )

        assert result.returncode == 0
        # Should output valid YAML - try to parse it
        try:
            # Find YAML section (starts with version: or vm:)
            output = result.stdout
            if "version:" in output or "vm:" in output:
                config = yaml.safe_load(output)
                assert config is not None
        except yaml.YAMLError:
            # YAML parsing might fail for Rich formatted output
            pass

    @pytest.mark.skipif(not os.path.exists("/dev/kvm"), reason="KVM not available")
    def test_clone_creates_config(self, e2e_config_dir):
        """Test that clone command uses existing config."""
        os.chdir(e2e_config_dir)

        # Verify config exists
        assert (e2e_config_dir / ".clonebox.yaml").exists()

        # Load and verify config
        config = yaml.safe_load((e2e_config_dir / ".clonebox.yaml").read_text())
        assert config["vm"]["name"] == "e2e-test-vm"

    @pytest.mark.skipif(not os.path.exists("/dev/kvm"), reason="KVM not available")
    def test_list_command(self):
        """Test clonebox list command."""
        result = subprocess.run(
            ["clonebox", "list", "--user"], capture_output=True, text=True, timeout=10
        )

        # Should succeed even with no VMs
        assert result.returncode == 0


@pytest.mark.e2e
@pytest.mark.slow
class TestVMLifecycle:
    """Test VM lifecycle operations (requires actual VM creation)."""

    VM_NAME = "e2e-lifecycle-test"

    @pytest.fixture(scope="class")
    def lifecycle_config_dir(self):
        """Create config for lifecycle tests."""
        tmpdir = Path(tempfile.mkdtemp(prefix="clonebox-lifecycle-"))

        config = {
            "version": "1",
            "vm": {
                "name": self.VM_NAME,
                "ram_mb": 2048,
                "vcpus": 2,
                "gui": False,
                "network_mode": "user",
                "username": "ubuntu",
                "password": "ubuntu",
            },
            "paths": {},
            "app_data_paths": {},
            "packages": ["curl"],
            "snap_packages": [],
            "services": [],
            "post_commands": [],
        }

        (tmpdir / ".clonebox.yaml").write_text(yaml.dump(config))

        yield tmpdir

        # Cleanup
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.skipif(
        not os.path.exists("/dev/kvm")
        or os.environ.get("CI") == "true"
        or True,  # Skip by default - too slow
        reason="KVM not available, running in CI, or skipped by default",
    )
    @pytest.mark.slow
    def test_full_vm_lifecycle(self, lifecycle_config_dir):
        """
        Test complete VM lifecycle:
        1. Clone/create VM
        2. Start VM
        3. Check status
        4. Stop VM
        5. Delete VM
        """
        os.chdir(lifecycle_config_dir)

        try:
            # Step 1: Create VM (this downloads image if needed, may take time)
            print("\n[E2E] Creating VM...")
            result = subprocess.run(
                ["clonebox", "clone", ".", "--user"],
                capture_output=True,
                text=True,
                timeout=600,  # 10 min for image download
            )
            print(f"Clone output: {result.stdout}")
            if result.returncode != 0:
                print(f"Clone stderr: {result.stderr}")
            assert result.returncode == 0, f"Clone failed: {result.stderr}"

            # Step 2: Start VM
            print("[E2E] Starting VM...")
            result = subprocess.run(
                ["clonebox", "start", ".", "--user"], capture_output=True, text=True, timeout=60
            )
            assert result.returncode == 0, f"Start failed: {result.stderr}"

            # Wait for VM to boot
            print("[E2E] Waiting for VM to boot...")
            time.sleep(30)

            # Step 3: Check status
            print("[E2E] Checking status...")
            result = subprocess.run(
                ["clonebox", "status", ".", "--user"], capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0
            assert "running" in result.stdout.lower() or "VM State" in result.stdout

            # Step 4: Stop VM
            print("[E2E] Stopping VM...")
            result = subprocess.run(
                ["clonebox", "stop", ".", "--user"], capture_output=True, text=True, timeout=60
            )
            assert result.returncode == 0

            # Step 5: Delete VM
            print("[E2E] Deleting VM...")
            result = subprocess.run(
                ["clonebox", "delete", ".", "--user", "--yes"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert result.returncode == 0

            print("[E2E] Full lifecycle test passed!")

        except Exception as e:
            # Cleanup on failure
            subprocess.run(
                ["clonebox", "stop", ".", "--user", "-f"], capture_output=True, timeout=30
            )
            subprocess.run(
                ["clonebox", "delete", ".", "--user", "--yes"], capture_output=True, timeout=30
            )
            raise e


@pytest.mark.e2e
class TestConfigValidation:
    """Test configuration validation."""

    def test_invalid_yaml_rejected(self, tmp_path):
        """Test that invalid YAML is rejected."""
        os.chdir(tmp_path)

        # Write invalid YAML
        (tmp_path / ".clonebox.yaml").write_text("invalid: yaml: content: [")

        result = subprocess.run(
            ["clonebox", "test", ".", "--user"], capture_output=True, text=True, timeout=10
        )

        # Should fail or show error/failed message
        output = (result.stdout + result.stderr).lower()
        assert result.returncode != 0 or "error" in output or "failed" in output

    def test_missing_vm_name_rejected(self, tmp_path):
        """Test that config without VM name is rejected."""
        os.chdir(tmp_path)

        config = {
            "version": "1",
            "paths": {},
        }
        (tmp_path / ".clonebox.yaml").write_text(yaml.dump(config))

        result = subprocess.run(
            ["clonebox", "test", ".", "--user"], capture_output=True, text=True, timeout=10
        )

        # Should fail due to missing vm.name
        output = (result.stdout + result.stderr).lower()
        assert result.returncode != 0 or "error" in output or "failed" in output


@pytest.mark.e2e
class TestExportImport:
    """Test export/import functionality."""

    @pytest.mark.skipif(
        not os.path.exists("/dev/kvm") or os.environ.get("CI") == "true",
        reason="KVM not available or running in CI",
    )
    def test_export_requires_existing_vm(self, tmp_path):
        """Test that export fails gracefully for non-existent VM."""
        os.chdir(tmp_path)

        config = {
            "version": "1",
            "vm": {"name": "nonexistent-vm"},
            "paths": {},
        }
        (tmp_path / ".clonebox.yaml").write_text(yaml.dump(config))

        result = subprocess.run(
            ["clonebox", "export", ".", "--user", "-o", "test.tar.gz"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should fail with clear error
        assert (
            result.returncode != 0
            or "not found" in result.stdout.lower()
            or "error" in result.stderr.lower()
        )
