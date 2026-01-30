#!/usr/bin/env python3
"""Tests for the CLI module."""

from unittest.mock import MagicMock

import pytest
import yaml

from clonebox.cli import (
    CLONEBOX_CONFIG_FILE,
    deduplicate_list,
    generate_clonebox_yaml,
    load_clonebox_config,
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
