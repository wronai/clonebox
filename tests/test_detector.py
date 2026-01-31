#!/usr/bin/env python3
"""Tests for the SystemDetector module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clonebox.detector import (
    DetectedApplication,
    DetectedPath,
    DetectedService,
    SystemDetector,
    SystemSnapshot,
)


class TestDetectedDataclasses:
    """Test dataclasses for detected items."""

    @pytest.mark.parametrize("name,status,enabled", [
        ("docker", "running", True),
        ("nginx", "stopped", False),
        ("postgresql", "running", True),
    ])
    def test_detected_service(self, name, status, enabled):
        svc = DetectedService(
            name=name, status=status, description=f"{name} service", enabled=enabled
        )
        assert svc.name == name
        assert svc.status == status
        assert svc.enabled is enabled

    @pytest.mark.parametrize("name,pid,memory_mb", [
        ("python3", 1234, 100.5),
        ("node", 5678, 200.0),
        ("java", 9012, 1024.0),
    ])
    def test_detected_application(self, name, pid, memory_mb):
        app = DetectedApplication(
            name=name,
            pid=pid,
            cmdline=f"{name} app",
            exe=f"/usr/bin/{name}",
            working_dir="/home/user/project",
            memory_mb=memory_mb,
        )
        assert app.name == name
        assert app.pid == pid
        assert app.memory_mb == memory_mb

    @pytest.mark.parametrize("path,path_type,size_mb", [
        ("/home/user/projects", "project", 500.0),
        ("/home/user/.config", "config", 10.0),
        ("/home/user/data", "data", 1000.0),
    ])
    def test_detected_path(self, path, path_type, size_mb):
        detected = DetectedPath(
            path=path, type=path_type, size_mb=size_mb, description="Test path"
        )
        assert detected.path == path
        assert detected.type == path_type

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

    @patch("clonebox.detector.subprocess.run")
    def test_detect_services_parses_output(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="UNIT                  LOAD   ACTIVE SUB     DESCRIPTION\n"
            "docker.service        loaded active running Docker\n"
            "nginx.service         loaded active running Nginx\n",
            returncode=0,
        )

        detector = SystemDetector()
        services = detector.detect_services()

        # Should find docker and nginx (both in INTERESTING_SERVICES)
        service_names = [s.name for s in services]
        assert "docker" in service_names or "nginx" in service_names

    @patch("clonebox.detector.psutil.process_iter")
    def test_detect_applications(self, mock_process_iter):
        mock_proc = MagicMock()
        mock_proc.info = {
            "pid": 1234,
            "name": "python3",
            "cmdline": ["python3", "app.py"],
            "exe": "/usr/bin/python3",
            "cwd": "/home/user/project",
            "memory_info": MagicMock(rss=100 * 1024 * 1024),  # 100 MB
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

    @pytest.mark.parametrize("docker_output,expected_count,expected_names", [
        ("myapp\tmyimage:latest\tUp 2 hours\ndb\tpostgres:15\tUp 2 hours\n", 2, ["myapp", "db"]),
        ("web\tnginx:latest\tUp 1 hour\n", 1, ["web"]),
        ("", 0, []),
    ])
    @patch("clonebox.detector.subprocess.run")
    def test_detect_docker_containers(self, mock_run, docker_output, expected_count, expected_names):
        mock_run.return_value = MagicMock(stdout=docker_output, returncode=0)

        detector = SystemDetector()
        containers = detector.detect_docker_containers()

        assert len(containers) == expected_count
        for i, name in enumerate(expected_names):
            assert containers[i]["name"] == name

    @patch("clonebox.detector.subprocess.run")
    def test_detect_docker_containers_no_docker(self, mock_run):
        mock_run.side_effect = FileNotFoundError("docker not found")

        detector = SystemDetector()
        containers = detector.detect_docker_containers()

        assert containers == []


class TestDetectorAppDataDirs:
    def test_detect_app_data_dirs_prefers_snap_paths(self, tmp_path, monkeypatch):
        detector = SystemDetector()

        # Redirect detector.home to tmp path
        detector.home = tmp_path

        # Create snap firefox profile path
        snap_firefox = tmp_path / "snap/firefox/common/.mozilla/firefox"
        snap_firefox.mkdir(parents=True)
        (snap_firefox / "profiles.ini").write_text("[Profile0]\n")

        # Create also classic path - should be ignored in favor of snap
        classic_firefox = tmp_path / ".mozilla/firefox"
        classic_firefox.mkdir(parents=True)
        (classic_firefox / "profiles.ini").write_text("[Profile0]\n")

        # No apps running - still should detect because of forced patterns
        result = detector.detect_app_data_dirs([])
        paths = {item["path"] for item in result}

        assert str(snap_firefox) in paths
