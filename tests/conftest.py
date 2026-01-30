"""
Pytest fixtures and configuration for CloneBox tests.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_config_dir(temp_dir):
    """Create a temporary directory with a basic .clonebox.yaml config."""
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
            str(temp_dir / "projects"): "/mnt/projects",
            str(temp_dir / "data"): "/mnt/data",
        },
        "app_data_paths": {
            str(temp_dir / ".config/test"): "/home/ubuntu/.config/test",
        },
        "packages": ["curl", "git", "vim"],
        "snap_packages": [],
        "services": ["docker"],
        "post_commands": [],
    }
    
    config_file = temp_dir / ".clonebox.yaml"
    config_file.write_text(yaml.dump(config))
    
    # Create directories
    (temp_dir / "projects").mkdir(exist_ok=True)
    (temp_dir / "data").mkdir(exist_ok=True)
    (temp_dir / ".config/test").mkdir(parents=True, exist_ok=True)
    
    # Create some test files
    (temp_dir / "projects" / "test.py").write_text("print('hello')")
    (temp_dir / "data" / "data.txt").write_text("test data")
    
    yield temp_dir


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for testing without actual command execution."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )
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


@pytest.fixture
def sample_vm_config():
    """Return a sample VMConfig dictionary."""
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


# Markers for test categories
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "e2e: End-to-end tests (require running VM)")
    config.addinivalue_line("markers", "slow: Slow tests")
    config.addinivalue_line("markers", "integration: Integration tests")
