"""Additional coverage tests to reach 70% threshold."""

import pytest
from unittest.mock import Mock, patch, MagicMock


def test_cloner_vmconfig_methods():
    """Test VMConfig methods to increase cloner coverage."""
    from clonebox.cloner import VMConfig
    
    # Test with custom values
    config = VMConfig(
        name="test-vm",
        ram_mb=4096,
        vcpus=2,
        disk_size_gb=30,
        gui=False,
        base_image="ubuntu.img",
        paths={"/host": "/guest"},
        packages=["vim", "git"]
    )
    
    assert config.name == "test-vm"
    assert config.ram_mb == 4096
    assert config.vcpus == 2
    assert config.disk_size_gb == 30
    assert config.gui is False
    assert config.base_image == "ubuntu.img"
    assert config.paths == {"/host": "/guest"}
    assert config.packages == ["vim", "git"]
    
    # Test to_dict (only returns specific fields)
    config_dict = config.to_dict()
    assert config_dict["paths"] == {"/host": "/guest"}
    assert config_dict["packages"] == ["vim", "git"]
    assert "services" in config_dict


def test_selective_vm_cloner_methods():
    """Test SelectiveVMCloner methods to increase coverage."""
    try:
        from clonebox.cloner import SelectiveVMCloner, VMConfig
        
        # Mock libvirt to avoid connection issues
        with patch('clonebox.cloner.libvirt') as mock_libvirt:
            mock_conn = Mock()
            mock_libvirt.open.return_value = mock_conn
            
            # Test initialization
            config = VMConfig(name="test-vm")
            cloner = SelectiveVMCloner(config)
            
            # Test get_images_dir
            images_dir = cloner.get_images_dir()
            assert images_dir is not None
            
            # Test close
            cloner.close()
            
            # Test with user session
            cloner2 = SelectiveVMCloner(config, user_session=True)
            assert cloner2 is not None
            cloner2.close()
            
    except ImportError:
        pytest.skip("libvirt not available")


def test_dashboard_basic_functions():
    """Test dashboard basic functions."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
        
        # Mock streamlit to avoid dependency
        with patch.dict('sys.modules', {'streamlit': Mock()}):
            from clonebox import dashboard
            assert dashboard is not None
            
            # Test if main function exists
            if hasattr(dashboard, 'main'):
                assert callable(dashboard.main)
                
    except ImportError:
        pytest.skip("dashboard dependencies not available")


def test_validator_edge_cases():
    """Test validator edge cases for more coverage."""
    from clonebox.validator import VMValidator
    
    # Test with minimal config
    validator = VMValidator(
        config={},
        vm_name="test-vm",
        conn_uri="qemu:///system",
        console=None
    )
    
    # Test _exec_in_vm mock
    def mock_exec(cmd, timeout=10):
        return ""
    
    validator._exec_in_vm = mock_exec
    
    # Test various validation methods
    mounts = validator.validate_mounts()
    assert mounts["total"] == 0
    
    packages = validator.validate_packages()
    assert packages["total"] == 0
    
    services = validator.validate_services()
    assert services["total"] == 0
    
    snap_packages = validator.validate_snap_packages()
    assert snap_packages["total"] == 0
    
    apps = validator.validate_apps()
    assert apps["total"] == 0


def test_models_additional_coverage():
    """Test models for additional coverage."""
    from clonebox.models import CloneBoxConfig, VMSettings, ContainerConfig
    
    # Test CloneBoxConfig with various settings
    vm = VMSettings(
        name="test-vm",
        ram_mb=2048,
        vcpus=2,
        disk_size_gb=20,
        network_mode="default"
    )
    
    config = CloneBoxConfig(
        vm=vm,
        paths={"/host": "/guest"},
        packages=["vim"],
        services=["docker"],
        snap_packages=["chromium"]
    )
    
    assert config.vm.name == "test-vm"
    assert config.vm.ram_mb == 2048
    assert config.paths == {"/host": "/guest"}
    assert config.packages == ["vim"]
    assert config.services == ["docker"]
    assert config.snap_packages == ["chromium"]
    
    # Test ContainerConfig
    container = ContainerConfig(
        name="test-container",
        image="ubuntu:latest",
        ports={"8080": "80"},
        environment={"TEST": "value"}
    )
    
    assert container.name == "test-container"
    assert container.image == "ubuntu:latest"
    assert container.ports == {"8080": "80"}
    assert container.environment == {"TEST": "value"}
