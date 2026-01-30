#!/usr/bin/env python3
"""Tests for Pydantic models."""

from pathlib import Path

import pytest
import yaml

from clonebox.models import CloneBoxConfig, VMSettings


class TestVMSettings:
    """Test VMSettings model."""

    def test_default_values(self):
        settings = VMSettings()
        assert settings.name == "clonebox-vm"
        assert settings.ram_mb == 4096
        assert settings.vcpus == 4
        assert settings.gui is True

    @pytest.mark.parametrize("name,valid", [
        ("my-vm", True),
        ("test-vm-123", True),
        ("", False),
        ("   ", False),
        ("a" * 65, False),
    ])
    def test_name_validation(self, name, valid):
        if valid:
            settings = VMSettings(name=name)
            assert settings.name == name.strip()
        else:
            with pytest.raises(ValueError):
                VMSettings(name=name)

    @pytest.mark.parametrize("network_mode,valid", [
        ("auto", True),
        ("default", True),
        ("user", True),
        ("invalid", False),
        ("bridge", False),
    ])
    def test_network_mode_validation(self, network_mode, valid):
        if valid:
            settings = VMSettings(network_mode=network_mode)
            assert settings.network_mode == network_mode
        else:
            with pytest.raises(ValueError):
                VMSettings(network_mode=network_mode)

    @pytest.mark.parametrize("ram_mb,valid", [
        (512, True),
        (4096, True),
        (131072, True),
        (256, False),
        (200000, False),
    ])
    def test_ram_validation(self, ram_mb, valid):
        if valid:
            settings = VMSettings(ram_mb=ram_mb)
            assert settings.ram_mb == ram_mb
        else:
            with pytest.raises(ValueError):
                VMSettings(ram_mb=ram_mb)


class TestCloneBoxConfig:
    """Test CloneBoxConfig model."""

    def test_default_config(self):
        config = CloneBoxConfig()
        assert config.version == "1"
        assert config.vm.name == "clonebox-vm"
        assert config.paths == {}
        assert config.packages == []

    def test_full_config(self):
        config = CloneBoxConfig(
            vm=VMSettings(name="my-vm", ram_mb=8192),
            paths={"/home/user/project": "/mnt/project"},
            packages=["docker.io", "git"],
            services=["docker"],
        )
        assert config.vm.name == "my-vm"
        assert config.vm.ram_mb == 8192
        assert "/home/user/project" in config.paths
        assert "docker.io" in config.packages

    def test_path_validation_host_absolute(self):
        with pytest.raises(ValueError, match="Host path must be absolute"):
            CloneBoxConfig(paths={"relative/path": "/mnt/dest"})

    def test_path_validation_guest_absolute(self):
        with pytest.raises(ValueError, match="Guest path must be absolute"):
            CloneBoxConfig(paths={"/home/user": "relative/dest"})

    def test_handle_nested_vm_dict(self):
        data = {
            "version": "1",
            "vm": {"name": "nested-vm", "ram_mb": 2048},
            "packages": ["curl"],
        }
        config = CloneBoxConfig.model_validate(data)
        assert config.vm.name == "nested-vm"
        assert config.vm.ram_mb == 2048

    def test_handle_flat_vm_dict(self):
        data = {
            "version": "1",
            "name": "flat-vm",
            "ram_mb": 2048,
            "packages": ["curl"],
        }
        config = CloneBoxConfig.model_validate(data)
        assert config.vm.name == "flat-vm"

    def test_save_and_load(self, tmp_path):
        config = CloneBoxConfig(
            vm=VMSettings(name="test-vm"),
            packages=["git", "curl"],
            services=["docker"],
        )
        
        config_file = tmp_path / ".clonebox.yaml"
        config.save(config_file)
        
        assert config_file.exists()
        
        loaded = CloneBoxConfig.load(config_file)
        assert loaded.vm.name == "test-vm"
        assert loaded.packages == ["git", "curl"]

    def test_load_from_directory(self, tmp_path):
        config = CloneBoxConfig(vm=VMSettings(name="dir-vm"))
        config.save(tmp_path / ".clonebox.yaml")
        
        loaded = CloneBoxConfig.load(tmp_path)
        assert loaded.vm.name == "dir-vm"

    def test_load_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CloneBoxConfig.load(tmp_path / "nonexistent")

    def test_to_vm_config_dataclass(self):
        config = CloneBoxConfig(
            vm=VMSettings(name="convert-vm", ram_mb=2048, vcpus=2),
            paths={"/home/user/project": "/mnt/project"},
            packages=["git"],
        )
        
        vm_config = config.to_vm_config()
        
        assert vm_config.name == "convert-vm"
        assert vm_config.ram_mb == 2048
        assert vm_config.vcpus == 2
        assert vm_config.paths == {"/home/user/project": "/mnt/project"}
        assert vm_config.packages == ["git"]


class TestCloneBoxConfigYAML:
    """Test YAML serialization/deserialization."""

    def test_yaml_roundtrip(self, tmp_path):
        original = CloneBoxConfig(
            version="1",
            vm=VMSettings(name="yaml-vm", ram_mb=4096, network_mode="user"),
            paths={"/home/user/code": "/mnt/code"},
            app_data_paths={"/home/user/.config/app": "/home/ubuntu/.config/app"},
            packages=["python3", "nodejs"],
            services=["docker", "nginx"],
            post_commands=["echo hello"],
        )
        
        config_file = tmp_path / "config.yaml"
        original.save(config_file)
        
        loaded = CloneBoxConfig.load(config_file)
        
        assert loaded.vm.name == original.vm.name
        assert loaded.vm.ram_mb == original.vm.ram_mb
        assert loaded.paths == original.paths
        assert loaded.packages == original.packages
        assert loaded.services == original.services

    def test_parse_generated_yaml(self, tmp_path):
        yaml_content = """
version: "1"
generated: "2024-01-01T00:00:00"
vm:
  name: generated-vm
  ram_mb: 8192
  vcpus: 4
  gui: true
  network_mode: auto
  username: ubuntu
  password: ubuntu
paths:
  /home/user/projects: /mnt/projects
packages:
  - docker.io
  - git
services:
  - docker
"""
        config_file = tmp_path / ".clonebox.yaml"
        config_file.write_text(yaml_content)
        
        config = CloneBoxConfig.load(config_file)
        
        assert config.vm.name == "generated-vm"
        assert config.vm.ram_mb == 8192
        assert config.generated == "2024-01-01T00:00:00"
        assert "/home/user/projects" in config.paths
