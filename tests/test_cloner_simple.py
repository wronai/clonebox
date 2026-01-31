"""Simple tests to increase cloner coverage."""

import pytest
from unittest.mock import Mock, patch


def test_cloner_import():
    """Test that cloner can be imported."""
    from clonebox.cloner import SelectiveVMCloner, VMConfig

    assert SelectiveVMCloner is not None
    assert VMConfig is not None


def test_vm_config():
    """Test VMConfig dataclass."""
    from clonebox.cloner import VMConfig

    # Test default values
    config = VMConfig()
    assert config.name == "clonebox-vm"
    assert config.ram_mb == 8192
    assert config.vcpus == 4
    assert config.disk_size_gb == 20
    assert config.gui is True
    assert config.base_image is None
    assert config.paths == {}
    assert config.packages == []

    # Test to_dict (only returns specific fields: paths, packages, services)
    config_dict = config.to_dict()
    assert config_dict["paths"] == {}
    assert config_dict["packages"] == []
    assert config_dict["services"] == []
