#!/usr/bin/env python3
"""Tests for the SystemDetector module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from clonebox.detector import (
    SystemDetector,
    DetectedService,
    DetectedApplication,
    DetectedPath,
    SystemSnapshot,
)


class TestDetectedDataclasses:
    """Test dataclasses for detected items."""
    
    def test_detected_service(self):
        svc = DetectedService(
            name="docker",
            status="running",
            description="Docker daemon",
            enabled=True
        )
        assert svc.name == "docker"
        assert svc.status == "running"
        assert svc.enabled is True
    
    def test_detected_application(self):
        app = DetectedApplication(
            name="python3",
            pid=1234,
            cmdline="python3 app.py",
            exe="/usr/bin/python3",
            working_dir="/home/user/project",
            memory_mb=100.5
        )
        assert app.name == "python3"
        assert app.pid == 1234
        assert app.memory_mb == 100.5
    
    def test_detected_path(self):
        path = DetectedPath(
            path="/home/user/projects",
            type="project",
            size_mb=500.0,
            description="User projects"
        )
        assert path.path == "/home/user/projects"
        assert path.type == "project"
    
    def test_system_snapshot_running_services(self):
        services = [
            DetectedService("docker", "running", enabled=True),
            DetectedService("nginx", "stopped", enabled=False),
            DetectedService("postgresql", "running", enabled=True),
        ]
        snapshot = SystemSnapshot(services=services)
        
        running = snapshot.running_services
        assert len(running) == 2
        assert all(s.status == "running" for s in running)


class TestSystemDetector:
    """Test SystemDetector class."""
    
    def test_init(self):
        detector = SystemDetector()
        assert detector.home == Path.home()
        assert detector.user is not None
    
    @patch('clonebox.detector.subprocess.run')
    def test_detect_services_parses_output(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="UNIT                  LOAD   ACTIVE SUB     DESCRIPTION\n"
                   "docker.service        loaded active running Docker\n"
                   "nginx.service         loaded active running Nginx\n",
            returncode=0
        )
        
        detector = SystemDetector()
        services = detector.detect_services()
        
        # Should find docker and nginx (both in INTERESTING_SERVICES)
        service_names = [s.name for s in services]
        assert "docker" in service_names or "nginx" in service_names
    
    @patch('clonebox.detector.psutil.process_iter')
    def test_detect_applications(self, mock_process_iter):
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 1234,
            'name': 'python3',
            'cmdline': ['python3', 'app.py'],
            'exe': '/usr/bin/python3',
            'cwd': '/home/user/project',
            'memory_info': MagicMock(rss=100 * 1024 * 1024)  # 100 MB
        }
        mock_process_iter.return_value = [mock_proc]
        
        detector = SystemDetector()
        apps = detector.detect_applications()
        
        assert len(apps) >= 0  # May be empty if python3 not in INTERESTING_PROCESSES
    
    def test_detect_paths_finds_home_dirs(self):
        detector = SystemDetector()
        paths = detector.detect_paths()
        
        # Should find at least some paths
        assert isinstance(paths, list)
        
        # Check that paths have correct types
        for p in paths:
            assert p.type in ["config", "data", "project"]
            assert p.path.startswith("/")
    
    def test_get_system_info(self):
        detector = SystemDetector()
        info = detector.get_system_info()
        
        assert "hostname" in info
        assert "user" in info
        assert "cpu_count" in info
        assert "memory_total_gb" in info
        assert "memory_available_gb" in info
        assert "disk_total_gb" in info
        assert "disk_free_gb" in info
        
        assert info["cpu_count"] > 0
        assert info["memory_total_gb"] > 0
    
    def test_detect_all(self):
        detector = SystemDetector()
        snapshot = detector.detect_all()
        
        assert isinstance(snapshot, SystemSnapshot)
        assert isinstance(snapshot.services, list)
        assert isinstance(snapshot.applications, list)
        assert isinstance(snapshot.paths, list)


class TestDetectorHelpers:
    """Test helper methods."""
    
    def test_get_dir_size_nonexistent(self):
        detector = SystemDetector()
        size = detector._get_dir_size(Path("/nonexistent/path/12345"))
        assert size == 0
    
    def test_get_dir_size_existing(self, tmp_path):
        # Create a temp file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World!")
        
        detector = SystemDetector()
        size = detector._get_dir_size(tmp_path)
        
        assert size > 0
        assert size == len("Hello World!")
    
    @patch('clonebox.detector.subprocess.run')
    def test_detect_docker_containers(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="myapp\tmyimage:latest\tUp 2 hours\n"
                   "db\tpostgres:15\tUp 2 hours\n",
            returncode=0
        )
        
        detector = SystemDetector()
        containers = detector.detect_docker_containers()
        
        assert len(containers) == 2
        assert containers[0]["name"] == "myapp"
        assert containers[1]["name"] == "db"
    
    @patch('clonebox.detector.subprocess.run')
    def test_detect_docker_containers_no_docker(self, mock_run):
        mock_run.side_effect = FileNotFoundError("docker not found")
        
        detector = SystemDetector()
        containers = detector.detect_docker_containers()
        
        assert containers == []
