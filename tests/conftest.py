"""
Pytest fixtures and configuration for CloneBox tests.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


@pytest.fixture(scope="function")
def temp_dir(tmp_path):
    """Create a temporary directory for tests (per-test isolation)."""
    yield tmp_path


@pytest.fixture(scope="session")
def session_temp_dir(tmp_path_factory):
    """Session-scoped temporary directory for shared resources."""
    return tmp_path_factory.mktemp("session")


@pytest.fixture(scope="module")
def module_vm_config(tmp_path_factory):
    """Module-scoped VM config directory - shared across tests in a module."""
    tmp_path = tmp_path_factory.mktemp("vm_configs")
    config = {
        "version": "1",
        "vm": {
            "name": "module-test-vm",
            "ram_mb": 2048,
            "vcpus": 2,
            "gui": True,
            "network_mode": "user",
            "username": "ubuntu",
            "password": "ubuntu",
        },
        "paths": {
            str(tmp_path / "projects"): "/mnt/projects",
        },
        "app_data_paths": {},
        "packages": ["curl", "git"],
        "snap_packages": [],
        "services": ["docker"],
        "post_commands": [],
    }
    
    config_file = tmp_path / ".clonebox.yaml"
    config_file.write_text(yaml.dump(config))
    (tmp_path / "projects").mkdir(exist_ok=True)
    
    return tmp_path


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create a temporary directory with a basic .clonebox.yaml config (per-test)."""
    config = {
        "version": "1",
        "vm": {
            "name": "test-vm",
            "ram_mb": 2048,
            "vcpus": 2,
            "gui": True,
            "network_mode": "user",
            "username": "ubuntu",
            "password": "ubuntu",
        },
        "paths": {
            str(tmp_path / "projects"): "/mnt/projects",
            str(tmp_path / "data"): "/mnt/data",
        },
        "app_data_paths": {
            str(tmp_path / ".config/test"): "/home/ubuntu/.config/test",
        },
        "packages": ["curl", "git", "vim"],
        "snap_packages": [],
        "services": ["docker"],
        "post_commands": [],
    }
    
    config_file = tmp_path / ".clonebox.yaml"
    config_file.write_text(yaml.dump(config))
    
    (tmp_path / "projects").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / ".config/test").mkdir(parents=True, exist_ok=True)
    
    (tmp_path / "projects" / "test.py").write_text("print('hello')")
    (tmp_path / "data" / "data.txt").write_text("test data")
    
    yield tmp_path


@pytest.fixture(scope="module")
def module_mock_subprocess():
    """Module-scoped mock subprocess for shared tests."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )
        yield mock_run


@pytest.fixture
def mock_subprocess():
    """Per-test mock subprocess when isolation needed."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )
        yield mock_run


@pytest.fixture(scope="module")
def module_mock_virsh():
    """Module-scoped virsh mock for shared VM tests."""
    with patch('subprocess.run') as mock_run:
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            cmd_str = ' '.join(cmd) if isinstance(cmd, list) else cmd
            
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            
            if 'domstate' in cmd_str:
                result.stdout = "running"
            elif 'dominfo' in cmd_str:
                result.stdout = "Name: test-vm\nState: running\n"
            elif 'domifaddr' in cmd_str:
                result.stdout = "vnet0 52:54:00:xx:xx:xx ipv4 192.168.122.100/24"
            elif 'list' in cmd_str:
                result.stdout = " Id   Name         State\n 1    test-vm     running"
            elif 'qemu-agent-command' in cmd_str:
                result.stdout = '{"return":{"pid":1234}}'
            else:
                result.stdout = ""
            
            return result
        
        mock_run.side_effect = side_effect
        yield mock_run


@pytest.fixture
def mock_virsh():
    """Mock virsh commands for VM testing."""
    with patch('subprocess.run') as mock_run:
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            cmd_str = ' '.join(cmd) if isinstance(cmd, list) else cmd
            
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            
            if 'domstate' in cmd_str:
                result.stdout = "running"
            elif 'dominfo' in cmd_str:
                result.stdout = "Name: test-vm\nState: running\n"
            elif 'domifaddr' in cmd_str:
                result.stdout = "vnet0 52:54:00:xx:xx:xx ipv4 192.168.122.100/24"
            elif 'list' in cmd_str:
                result.stdout = " Id   Name         State\n 1    test-vm     running"
            elif 'qemu-agent-command' in cmd_str:
                result.stdout = '{"return":{"pid":1234}}'
            else:
                result.stdout = ""
            
            return result
        
        mock_run.side_effect = side_effect
        yield mock_run


@pytest.fixture(scope="session")
def session_libvirt_mock():
    """Session-scoped libvirt mock - shared across all tests."""
    with patch('clonebox.cloner.libvirt') as mock_libvirt:
        mock_conn = MagicMock()
        mock_conn.isAlive.return_value = True
        mock_conn.listDomainsID.return_value = []
        mock_conn.listDefinedDomains.return_value = []
        mock_libvirt.open.return_value = mock_conn
        yield mock_libvirt


@pytest.fixture(scope="module")
def module_system_detector():
    """Module-scoped SystemDetector mock for shared detection tests."""
    from clonebox.detector import (
        DetectedApplication,
        DetectedPath,
        DetectedService,
        SystemSnapshot,
    )
    
    services = [
        DetectedService("docker", "running", enabled=True),
        DetectedService("nginx", "running", enabled=True),
        DetectedService("postgresql", "running", enabled=True),
    ]
    
    apps = [
        DetectedApplication(
            name="python3",
            pid=1234,
            cmdline="python3 app.py",
            exe="/usr/bin/python3",
            cwd="/home/user/project",
            memory_mb=100.0
        ),
    ]
    
    paths = [
        DetectedPath("/home/user/projects", "project", 500.0),
        DetectedPath("/home/user/.config/JetBrains", "config", 100.0),
    ]
    
    snapshot = SystemSnapshot(services=services, applications=apps, paths=paths)
    
    with patch('clonebox.detector.SystemDetector') as MockDetector:
        detector = MagicMock()
        detector.detect_all.return_value = snapshot
        detector.get_system_info.return_value = {
            "hostname": "test-host",
            "user": "testuser",
            "cpu_count": 8,
            "memory_total_gb": 16.0,
            "memory_available_gb": 8.0,
            "disk_total_gb": 500.0,
            "disk_free_gb": 200.0,
        }
        MockDetector.return_value = detector
        yield detector


@pytest.fixture
def mock_system_detector():
    """Mock SystemDetector for testing."""
    from clonebox.detector import (
        DetectedApplication,
        DetectedPath,
        DetectedService,
        SystemSnapshot,
    )
    
    services = [
        DetectedService("docker", "running", enabled=True),
        DetectedService("nginx", "running", enabled=True),
        DetectedService("postgresql", "running", enabled=True),
    ]
    
    apps = [
        DetectedApplication(
            name="python3",
            pid=1234,
            cmdline="python3 app.py",
            exe="/usr/bin/python3",
            cwd="/home/user/project",
            memory_mb=100.0
        ),
        DetectedApplication(
            name="pycharm",
            pid=5678,
            cmdline="pycharm",
            exe="/opt/pycharm/bin/pycharm",
            cwd="/home/user/projects",
            memory_mb=2000.0
        ),
    ]
    
    paths = [
        DetectedPath("/home/user/projects", "project", 500.0),
        DetectedPath("/home/user/.config/JetBrains", "config", 100.0),
        DetectedPath("/home/user/Downloads", "data", 1000.0),
    ]
    
    snapshot = SystemSnapshot(services=services, applications=apps, paths=paths)
    
    with patch('clonebox.detector.SystemDetector') as MockDetector:
        detector = MagicMock()
        detector.detect_all.return_value = snapshot
        detector.get_system_info.return_value = {
            "hostname": "test-host",
            "user": "testuser",
            "cpu_count": 8,
            "memory_total_gb": 16.0,
            "memory_available_gb": 8.0,
            "disk_total_gb": 500.0,
            "disk_free_gb": 200.0,
        }
        MockDetector.return_value = detector
        yield detector


# Sample YAML for module fixtures
YAML_SAMPLE = """
version: "1"
vm:
  name: sample-vm
  ram_mb: 4096
  vcpus: 4
  gui: true
  network_mode: user
  username: ubuntu
  password: ubuntu
paths:
  /home/user/projects: /mnt/projects
app_data_paths:
  /home/user/.config/JetBrains: /home/ubuntu/.config/JetBrains
packages:
  - docker.io
  - git
  - curl
  - vim
snap_packages:
  - code
services:
  - docker
  - ssh
post_commands:
  - echo 'Setup complete'
"""


@pytest.fixture(scope="session")
def sample_vm_config_session():
    """Session-scoped sample config for read-only tests."""
    return {
        "version": "1",
        "vm": {
            "name": "sample-vm",
            "ram_mb": 4096,
            "vcpus": 4,
            "gui": True,
            "network_mode": "user",
            "username": "ubuntu",
            "password": "ubuntu",
        },
        "paths": {
            "/home/user/projects": "/mnt/projects",
        },
        "app_data_paths": {
            "/home/user/.config/JetBrains": "/home/ubuntu/.config/JetBrains",
        },
        "packages": ["docker.io", "git", "curl", "vim"],
        "snap_packages": ["code"],
        "services": ["docker", "ssh"],
        "post_commands": ["echo 'Setup complete'"],
    }


@pytest.fixture
def sample_vm_config(sample_vm_config_session):
    """Per-test sample VMConfig dictionary (copy of session-scoped)."""
    import copy
    return copy.deepcopy(sample_vm_config_session)


# CliRunner fixture for CLI integration tests
@pytest.fixture(scope="module")
def cli_runner():
    """Module-scoped CliRunner for CLI tests."""
    from click.testing import CliRunner
    return CliRunner()


@pytest.fixture
def isolated_cli_runner():
    """Per-test isolated CliRunner with temp directory."""
    from click.testing import CliRunner
    runner = CliRunner()
    with runner.isolated_filesystem():
        yield runner


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "e2e: End-to-end tests requiring libvirt/KVM")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow tests")


def pytest_collection_modifyitems(config, items):
    """Auto-skip e2e tests when libvirt/KVM not available."""
    import os
    
    # Check if libvirt is available
    try:
        import libvirt
        libvirt_available = True
    except ImportError:
        libvirt_available = False
    
    # Check if KVM is available
    kvm_available = os.path.exists("/dev/kvm")
    
    # Check if running in CI
    is_ci = os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"
    
    skip_e2e = pytest.mark.skip(reason="libvirt/KVM not available or running in CI")
    
    for item in items:
        # Auto-skip e2e tests if prerequisites not met
        if "e2e" in item.keywords:
            if not libvirt_available or not kvm_available or is_ci:
                item.add_marker(skip_e2e)
