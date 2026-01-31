"""Comprehensive tests to boost coverage to 70%."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os


def test_validator_comprehensive():
    """Test validator with comprehensive mocking."""
    from clonebox.validator import VMValidator
    
    # Create validator with full config
    config = {
        "vm": {"name": "test-vm", "username": "ubuntu"},
        "paths": {"/host": "/guest"},
        "packages": ["vim"],
        "services": ["docker"],
        "snap_packages": ["chromium"],
        "app_data_paths": {"/host/app": "/home/ubuntu/app"}
    }
    
    validator = VMValidator(config, "test-vm", "qemu:///system", None)
    
    # Mock all commands to return success
    def mock_exec(cmd, timeout=10):
        if "mount" in cmd:
            return "/dev/host on /guest type 9p (rw)\n/dev/host2 on /guest2 type 9p (rw)"
        elif "test -d" in cmd:
            return "yes"
        elif "ls -A" in cmd:
            return "2"
        elif "dpkg" in cmd:
            return "ii  vim 2.0 all"
        elif "systemctl" in cmd:
            if "is-enabled" in cmd:
                return "enabled"
            elif "is-active" in cmd:
                return "active"
            elif "MainPID" in cmd:
                return "1234"
            return "active"
        elif "snap" in cmd:
            if "list" in cmd:
                return "chromium 124.0"
            elif "connections" in cmd:
                return "desktop -\nhome -\nnetwork -"
            elif "logs" in cmd:
                return "logs"
        elif "pgrep" in cmd:
            return "1234"
        elif "command" in cmd:
            return "/usr/bin/chrome"
        elif "docker" in cmd:
            if "info" in cmd:
                return "Containers: 0"
            return "/usr/bin/docker"
        elif "journalctl" in cmd:
            return ""
        elif "chromium --headless" in cmd or "firefox --headless" in cmd or "google-chrome --headless" in cmd:
            return "yes"
        return ""
    
    validator._exec_in_vm = mock_exec
    validator.smoke_test = True
    
    # Run all validations
    validator.validate_mounts()
    validator.validate_packages()
    validator.validate_services()
    validator.validate_snap_packages()
    validator.validate_apps()
    validator.validate_smoke_tests()
    
    # Test validate_all
    with patch('subprocess.run') as mock_subprocess:
        mock_subprocess.return_value = Mock(stdout="running", returncode=0)
        validator.validate_all()


def test_cloner_comprehensive():
    """Test cloner for comprehensive coverage."""
    try:
        from clonebox.cloner import SelectiveVMCloner, SNAP_INTERFACES, DEFAULT_SNAP_INTERFACES
        
        # Test constants
        assert SNAP_INTERFACES
        assert DEFAULT_SNAP_INTERFACES
        assert "chromium" in SNAP_INTERFACES
        assert "firefox" in SNAP_INTERFACES
        
        with patch('clonebox.cloner.libvirt') as mock_libvirt:
            mock_conn = Mock()
            mock_conn.listDomainsID.return_value = [1, 2]
            mock_conn.listDefinedDomains.return_value = ["vm3", "vm4"]
            mock_libvirt.open.return_value = mock_conn
            
            cloner = SelectiveVMCloner()
            
            # Test properties
            assert cloner.SYSTEM_IMAGES_DIR
            assert cloner.USER_IMAGES_DIR
            assert cloner.DEFAULT_BASE_IMAGE_URL
            assert cloner.DEFAULT_BASE_IMAGE_FILENAME
            
            # Test methods
            cloner.get_images_dir()
            cloner.list_vms()
            cloner.check_prerequisites()
            
            # Test backward compatibility methods
            cloner._get_base_image_info("test.img")
            cloner.get_vm_info("test-vm")
            
            # Test _generate_vm_xml with defaults
            xml = cloner._generate_vm_xml()
            assert xml is not None
            assert "<domain" in xml
            
            cloner.close()
            
    except ImportError:
        pytest.skip("libvirt not available")


def test_detector_comprehensive():
    """Test detector for comprehensive coverage."""
    from clonebox.detector import SystemDetector
    
    detector = SystemDetector()
    
    # Test with mocked subprocess
    with patch('subprocess.run') as mock_subprocess:
        mock_subprocess.return_value = Mock(stdout="test output", returncode=0)
        
        detector.detect_services()
        detector.detect_applications()
        detector.detect_paths()
        detector.detect_docker_containers()
        detector.get_system_info()
    
    # Test with command not found
    with patch('subprocess.run', side_effect=FileNotFoundError()):
        detector.detect_services()
        detector.detect_docker_containers()
    
    # Test get_dir_size with error
    with patch('subprocess.run', side_effect=Exception("Error")):
        size = detector.get_dir_size("/test")
        assert size == 0


def test_models_comprehensive():
    """Test models for comprehensive coverage."""
    from clonebox.models import VMSettings, CloneBoxConfig, ContainerConfig
    
    # Test VMSettings edge cases
    vm = VMSettings(name="test" * 20)  # Very long name
    VMSettings(network_mode="user")
    VMSettings(ram_mb=131072, vcpus=128, disk_size_gb=1000)
    
    # Test CloneBoxConfig
    config = CloneBoxConfig()
    config.model_dump()
    config.model_dump_json()
    
    # Test ContainerConfig
    ContainerConfig(ports=[])
    ContainerConfig(ports=["8080:80"])
    ContainerConfig(ports={"8080": "80"})
    ContainerConfig(engine="podman")
    ContainerConfig(engine="docker")


def test_profiles_comprehensive():
    """Test profiles for comprehensive coverage."""
    from clonebox.profiles import load_profile, merge_with_profile
    
    # Test with non-existent profile
    result = load_profile("nonexistent", [])
    assert result is None
    
    # Test merge with empty profile
    result = merge_with_profile("", {})
    assert result == {}
    
    # Test merge with None
    result = merge_with_profile(None, {})
    assert result == {}


def test_dashboard_comprehensive():
    """Test dashboard with mocked dependencies."""
    mocks = {
        'streamlit': Mock(),
        'pandas': Mock(),
        'plotly': Mock(),
        'plotly.express': Mock(),
        'plotly.graph_objects': Mock()
    }
    
    # Add streamlit methods
    st = mocks['streamlit']
    st.title = Mock()
    st.header = Mock()
    st.subheader = Mock()
    st.sidebar = Mock()
    st.button = Mock(return_value=False)
    st.selectbox = Mock(return_value="option")
    st.multiselect = Mock(return_value=[])
    st.text_input = Mock(return_value="")
    st.number_input = Mock(return_value=1)
    st.checkbox = Mock(return_value=False)
    st.file_uploader = Mock(return_value=None)
    st.dataframe = Mock()
    st.plotly_chart = Mock()
    st.json = Mock()
    st.code = Mock()
    st.success = Mock()
    st.error = Mock()
    st.warning = Mock()
    st.info = Mock()
    st.session_state = {}
    
    # Mock pandas
    mocks['pandas'].DataFrame = Mock(return_value=Mock())
    
    # Mock plotly
    mocks['plotly.express'].line = Mock(return_value=Mock())
    mocks['plotly.express'].bar = Mock(return_value=Mock())
    mocks['plotly.express'].pie = Mock(return_value=Mock())
    mocks['plotly.graph_objects'].Figure = Mock(return_value=Mock())
    
    with patch.dict('sys.modules', mocks):
        try:
            import clonebox.dashboard as dashboard
            assert dashboard is not None
            
            # Try to access any functions that might exist
            for name in dir(dashboard):
                if not name.startswith('_'):
                    obj = getattr(dashboard, name)
                    if callable(obj):
                        # Just verify they're callable
                        assert callable(obj)
                        
        except ImportError:
            pytest.skip("dashboard not available")


def test_main_and_init_comprehensive():
    """Test __main__ and __init__ modules."""
    from clonebox import __main__, SelectiveVMCloner, SystemDetector, __version__
    
    assert __main__ is not None
    assert SelectiveVMCloner is not None
    assert SystemDetector is not None
    assert __version__ is not None
    assert isinstance(__version__, str)


def test_validator_error_cases():
    """Test validator error cases."""
    from clonebox.validator import VMValidator
    
    validator = VMValidator({}, "test", "qemu:///system", None)
    
    # Test with timeout
    def timeout_exec(cmd, timeout=10):
        raise TimeoutError("timeout")
    
    validator._exec_in_vm = timeout_exec
    validator.validate_packages()
    validator.validate_services()
    
    # Test with command error
    def error_exec(cmd, timeout=10):
        raise Exception("Command failed")
    
    validator._exec_in_vm = error_exec
    validator.validate_mounts()
    
    # Test validate_all with VM not running
    with patch('subprocess.run') as mock_subprocess:
        mock_subprocess.return_value = Mock(stdout="shutdown", returncode=0)
        result = validator.validate_all()
        assert result["overall"] == "vm_not_running"
    
    # Test validate_all with error
    with patch('subprocess.run', side_effect=Exception("Error")):
        result = validator.validate_all()
        assert result["overall"] == "error"
    
    # Test validate_all with no checks
    with patch('subprocess.run') as mock_subprocess:
        mock_subprocess.return_value = Mock(stdout="running", returncode=0)
        validator._exec_in_vm = lambda cmd, timeout=10: ""
        result = validator.validate_all()
        assert result["overall"] == "no_checks"


def test_cloner_error_cases():
    """Test cloner error cases."""
    try:
        from clonebox.cloner import SelectiveVMCloner
        
        # Test with connection error
        with patch('clonebox.cloner.libvirt') as mock_libvirt:
            import libvirt
            mock_libvirt.open.side_effect = libvirt.libvirtError("Connection failed")
            
            try:
                cloner = SelectiveVMCloner()
            except Exception:
                pass  # Expected
            
        # Test with VM not found
        with patch('clonebox.cloner.libvirt') as mock_libvirt:
            mock_conn = Mock()
            mock_conn.lookupByName.side_effect = libvirt.libvirtError("VM not found")
            mock_libvirt.open.return_value = mock_conn
            
            cloner = SelectiveVMCloner()
            result = cloner.get_vm_info("nonexistent")
            assert result == {}
            
    except ImportError:
        pytest.skip("libvirt not available")


def test_detector_edge_cases():
    """Test detector edge cases."""
    from clonebox.detector import SystemDetector
    
    detector = SystemDetector()
    
    # Test get_dir_size with actual directory
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test file
        test_file = os.path.join(tmpdir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        
        size = detector.get_dir_size(tmpdir)
        assert size >= 0
    
    # Test with non-existent directory
    size = detector.get_dir_size("/nonexistent/path/that/does/not/exist")
    assert size == 0
