#!/usr/bin/env python3
"""Tests for the CLI module."""

import argparse
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from clonebox.cli import (
    CLONEBOX_CONFIG_FILE,
    deduplicate_list,
    generate_clonebox_yaml,
    load_clonebox_config,
    main,
)
from clonebox.detector import (
    DetectedApplication,
    DetectedPath,
    DetectedService,
    SystemDetector,
    SystemSnapshot,
)


class TestDeduplicateList:
    """Test deduplicate_list helper function."""

    def test_dedupe_simple_list(self):
        items = [1, 2, 2, 3, 3, 3, 4]
        result = deduplicate_list(items)
        assert result == [1, 2, 3, 4]

    def test_dedupe_strings(self):
        items = ["a", "b", "a", "c", "b"]
        result = deduplicate_list(items)
        assert result == ["a", "b", "c"]

    def test_dedupe_preserves_order(self):
        items = ["z", "a", "z", "m"]
        result = deduplicate_list(items)
        assert result == ["z", "a", "m"]

    def test_dedupe_with_key(self):
        items = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}, {"id": 1, "name": "c"}]
        result = deduplicate_list(items, key=lambda x: x["id"])
        assert len(result) == 2
        assert result[0]["name"] == "a"  # First occurrence kept

    def test_dedupe_empty_list(self):
        result = deduplicate_list([])
        assert result == []


class TestGenerateCloneboxYaml:
    """Test YAML config generation."""

    def create_mock_snapshot(self):
        """Create a mock SystemSnapshot for testing."""
        services = [
            DetectedService("docker", "running", enabled=True),
            DetectedService("nginx", "running", enabled=True),
        ]
        apps = [
            DetectedApplication(
                "python3", 1234, "python3 app.py", "/usr/bin/python3", "/home/user/project", 100.0
            ),
            DetectedApplication(
                "node", 5678, "node server.js", "/usr/bin/node", "/home/user/webapp", 200.0
            ),
        ]
        paths = [
            DetectedPath("/home/user/projects", "project", 500.0),
            DetectedPath("/home/user/.config", "config", 10.0),
            DetectedPath("/home/user/data", "data", 1000.0),
        ]
        return SystemSnapshot(services=services, applications=apps, paths=paths)

    def create_mock_detector(self):
        """Create a mock SystemDetector."""
        detector = MagicMock(spec=SystemDetector)
        detector.get_system_info.return_value = {
            "hostname": "test-host",
            "user": "testuser",
            "cpu_count": 8,
            "memory_total_gb": 16.0,
            "memory_available_gb": 8.0,
            "disk_total_gb": 500.0,
            "disk_free_gb": 200.0,
        }
        return detector

    def test_generate_yaml_basic(self):
        snapshot = self.create_mock_snapshot()
        detector = self.create_mock_detector()

        yaml_str = generate_clonebox_yaml(snapshot, detector)
        config = yaml.safe_load(yaml_str)

        assert config["version"] == "1"
        assert "generated" in config
        assert "vm" in config
        assert "services" in config
        assert "packages" in config
        assert "paths" in config

    def test_generate_yaml_vm_name_from_path(self):
        snapshot = self.create_mock_snapshot()
        detector = self.create_mock_detector()

        yaml_str = generate_clonebox_yaml(snapshot, detector, target_path="/home/user/myproject")
        config = yaml.safe_load(yaml_str)

        assert config["vm"]["name"] == "clone-myproject"

    def test_generate_yaml_custom_vm_name(self):
        snapshot = self.create_mock_snapshot()
        detector = self.create_mock_detector()

        yaml_str = generate_clonebox_yaml(snapshot, detector, vm_name="custom-vm")
        config = yaml.safe_load(yaml_str)

        assert config["vm"]["name"] == "custom-vm"

    def test_generate_yaml_deduplicate(self):
        snapshot = self.create_mock_snapshot()
        detector = self.create_mock_detector()

        yaml_str = generate_clonebox_yaml(snapshot, detector, deduplicate=True)
        config = yaml.safe_load(yaml_str)

        # Services should be unique
        assert len(config["services"]) == len(set(config["services"]))

    def test_generate_yaml_includes_services(self):
        snapshot = self.create_mock_snapshot()
        detector = self.create_mock_detector()

        yaml_str = generate_clonebox_yaml(snapshot, detector)
        config = yaml.safe_load(yaml_str)

        assert "docker" in config["services"]
        assert "nginx" in config["services"]

    def test_generate_yaml_detected_section(self):
        snapshot = self.create_mock_snapshot()
        detector = self.create_mock_detector()

        yaml_str = generate_clonebox_yaml(snapshot, detector)
        config = yaml.safe_load(yaml_str)

        assert "detected" in config
        assert "running_apps" in config["detected"]
        assert "all_paths" in config["detected"]

    def test_generate_yaml_base_image(self):
        snapshot = self.create_mock_snapshot()
        detector = self.create_mock_detector()

        yaml_str = generate_clonebox_yaml(
            snapshot,
            detector,
            base_image="/images/base.qcow2",
        )
        config = yaml.safe_load(yaml_str)

        assert config["vm"]["base_image"] == "/images/base.qcow2"

    def test_generate_yaml_includes_disk_size_default(self):
        snapshot = self.create_mock_snapshot()
        detector = self.create_mock_detector()

        yaml_str = generate_clonebox_yaml(snapshot, detector)
        config = yaml.safe_load(yaml_str)

        assert config["vm"]["disk_size_gb"] == 20

    def test_generate_yaml_disk_size_override(self):
        snapshot = self.create_mock_snapshot()
        detector = self.create_mock_detector()

        yaml_str = generate_clonebox_yaml(snapshot, detector, disk_size_gb=42)
        config = yaml.safe_load(yaml_str)

        assert config["vm"]["disk_size_gb"] == 42


class TestLoadCloneboxConfig:
    """Test loading .clonebox.yaml configs."""

    def test_load_config_from_file(self, tmp_path):
        config_content = {
            "version": "1",
            "vm": {"name": "test-vm", "ram_mb": 2048},
            "services": ["docker"],
            "packages": ["python3"],
            "paths": {"/home/user/project": "/mnt/project"},
        }

        config_file = tmp_path / CLONEBOX_CONFIG_FILE
        config_file.write_text(yaml.dump(config_content))

        loaded = load_clonebox_config(config_file)

        assert loaded["vm"]["name"] == "test-vm"
        assert loaded["services"] == ["docker"]

    def test_load_config_from_directory(self, tmp_path):
        config_content = {"version": "1", "vm": {"name": "dir-vm"}}

        config_file = tmp_path / CLONEBOX_CONFIG_FILE
        config_file.write_text(yaml.dump(config_content))

        loaded = load_clonebox_config(tmp_path)  # Pass directory, not file

        assert loaded["vm"]["name"] == "dir-vm"

    def test_load_config_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_clonebox_config(tmp_path / "nonexistent")


class TestCLIConstants:
    """Test CLI constants."""

    def test_config_file_name(self):
        assert CLONEBOX_CONFIG_FILE == ".clonebox.yaml"


class TestCLIIntegration:
    """Integration tests for CLI commands."""

    @pytest.mark.parametrize(
        "command,expected_exit",
        [
            (["--version"], 0),
            (["--help"], 0),
            (["detect", "--help"], 0),
            (["clone", "--help"], 0),
            (["list", "--help"], 0),
            (["container", "--help"], 0),
            (["container", "ps", "--help"], 0),
            (["container", "up", "--help"], 0),
        ],
    )
    def test_cli_help_commands(self, command, expected_exit):
        """Test CLI help and version commands."""
        result = subprocess.run(
            [sys.executable, "-m", "clonebox"] + command,
            capture_output=True,
            text=True,
        )
        assert result.returncode == expected_exit

    @patch("clonebox.cli.vm_commands.SystemDetector")
    @patch("clonebox.cli.vm_commands.console")
    def test_detect_json_output(self, mock_console, mock_detector_class, tmp_path):
        """Test detect command with JSON output."""
        from clonebox.cli import cmd_detect

        mock_detector = MagicMock()
        mock_detector.detect_all.return_value = SystemSnapshot(
            services=[DetectedService("docker", "running", enabled=True)], applications=[], paths=[]
        )
        mock_detector.get_system_info.return_value = {
            "hostname": "test",
            "user": "testuser",
            "cpu_count": 4,
            "memory_total_gb": 16.0,
            "memory_available_gb": 8.0,
            "disk_total_gb": 500.0,
            "disk_free_gb": 200.0,
        }
        mock_detector.detect_docker_containers.return_value = []
        mock_detector_class.return_value = mock_detector

        args = argparse.Namespace(json=True, yaml=False, dedupe=False, output=None)
        cmd_detect(args)

        mock_console.print.assert_called()

    @patch("clonebox.cli.vm_commands.SystemDetector")
    @patch("clonebox.cli.vm_commands.console")
    def test_detect_yaml_output(self, mock_console, mock_detector_class):
        """Test detect command with YAML output."""
        from clonebox.cli import cmd_detect

        mock_detector = MagicMock()
        mock_detector.detect_all.return_value = SystemSnapshot(
            services=[DetectedService("nginx", "running", enabled=True)],
            applications=[],
            paths=[DetectedPath("/home/user/project", "project", 100.0)],
        )
        mock_detector.get_system_info.return_value = {
            "hostname": "test",
            "user": "testuser",
            "cpu_count": 4,
            "memory_total_gb": 16.0,
            "memory_available_gb": 8.0,
            "disk_total_gb": 500.0,
            "disk_free_gb": 200.0,
        }
        mock_detector.detect_docker_containers.return_value = []
        mock_detector_class.return_value = mock_detector

        args = argparse.Namespace(json=False, yaml=True, dedupe=True, output=None)
        cmd_detect(args)

        mock_console.print.assert_called()

    @patch("clonebox.cli.SelectiveVMCloner")
    @patch("clonebox.cli.questionary")
    @patch("clonebox.cli.Progress")
    @patch("clonebox.cli.console")
    @patch("clonebox.cli.SystemDetector")
    def test_clone_creates_config_file(
        self,
        mock_detector_class,
        mock_console,
        mock_progress,
        mock_questionary,
        mock_cloner,
        tmp_path,
    ):
        """Test clone command creates .clonebox.yaml config file."""
        config_file = tmp_path / CLONEBOX_CONFIG_FILE

        mock_detector = MagicMock()
        mock_detector.detect_all.return_value = SystemSnapshot(
            services=[DetectedService("docker", "running", enabled=True)], applications=[], paths=[]
        )
        mock_detector.get_system_info.return_value = {
            "hostname": "test",
            "user": "testuser",
            "cpu_count": 4,
            "memory_total_gb": 16.0,
            "memory_available_gb": 8.0,
            "disk_total_gb": 500.0,
            "disk_free_gb": 200.0,
        }
        mock_detector.detect_docker_containers.return_value = []
        mock_detector_class.return_value = mock_detector
        mock_questionary.confirm.return_value.ask.return_value = False

        from clonebox.cli import cmd_clone

        args = argparse.Namespace(
            path=str(tmp_path),
            name=None,
            run=False,
            edit=False,
            dedupe=True,
            user=True,
            network="auto",
            base_image=None,
            disk_size_gb=None,
            replace=False,
        )
        cmd_clone(args)

        assert config_file.exists()
        config = yaml.safe_load(config_file.read_text())
        assert "vm" in config
        assert "version" in config

    @patch("clonebox.cli.SelectiveVMCloner")
    @patch("clonebox.cli.utils.SelectiveVMCloner")
    def test_create_vm_from_config_propagates_disk_size(self, mock_cloner_class, mock_cloner_utils_class, tmp_path):
        from clonebox.cli import create_vm_from_config

        mock_cloner = MagicMock()
        mock_cloner.create_vm.return_value = "uuid-123"
        mock_cloner.check_prerequisites.return_value = {
            "images_dir_writable": True,
            "images_dir": "/tmp",
            "session_type": "user",
        }
        mock_cloner_class.return_value = mock_cloner
        mock_cloner_utils_class.return_value = mock_cloner

        cfg = {
            "version": "1",
            "vm": {"name": "test-vm", "disk_size_gb": 50},
            "paths": {},
            "packages": [],
            "snap_packages": [],
            "services": [],
            "post_commands": [],
        }

        create_vm_from_config(cfg, start=False, user_session=True, replace=False)

        assert mock_cloner.create_vm.called
        passed_vm_config = mock_cloner.create_vm.call_args[0][0]
        assert getattr(passed_vm_config, "disk_size_gb") == 50


class TestCLIParametrized:
    """Parametrized CLI tests."""

    @pytest.mark.parametrize(
        "vm_name,expected",
        [
            ("my-vm", "my-vm"),
            ("test-project", "test-project"),
            ("clone-app", "clone-app"),
        ],
    )
    def test_generate_yaml_custom_vm_names(self, vm_name, expected):
        """Test YAML generation with various VM names."""
        snapshot = SystemSnapshot(
            services=[DetectedService("docker", "running", enabled=True)], applications=[], paths=[]
        )
        detector = MagicMock(spec=SystemDetector)
        detector.get_system_info.return_value = {
            "hostname": "test-host",
            "user": "testuser",
            "cpu_count": 8,
            "memory_total_gb": 16.0,
            "memory_available_gb": 8.0,
            "disk_total_gb": 500.0,
            "disk_free_gb": 200.0,
        }

        yaml_str = generate_clonebox_yaml(snapshot, detector, vm_name=vm_name)
        config = yaml.safe_load(yaml_str)

        assert config["vm"]["name"] == expected

    @pytest.mark.parametrize(
        "services,expected_count",
        [
            (["docker"], 1),
            (["docker", "nginx"], 2),
            (["docker", "nginx", "postgresql"], 3),
            ([], 0),
        ],
    )
    def test_generate_yaml_services_count(self, services, expected_count):
        """Test YAML generation with various service configurations."""
        detected_services = [DetectedService(name, "running", enabled=True) for name in services]
        snapshot = SystemSnapshot(services=detected_services, applications=[], paths=[])
        detector = MagicMock(spec=SystemDetector)
        detector.get_system_info.return_value = {
            "hostname": "test-host",
            "user": "testuser",
            "cpu_count": 8,
            "memory_total_gb": 16.0,
            "memory_available_gb": 8.0,
            "disk_total_gb": 500.0,
            "disk_free_gb": 200.0,
        }

        yaml_str = generate_clonebox_yaml(snapshot, detector)
        config = yaml.safe_load(yaml_str)

        assert len(config["services"]) == expected_count
