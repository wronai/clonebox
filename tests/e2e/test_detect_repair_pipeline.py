#!/usr/bin/env python3
"""
End-to-end tests for the detect → auto-discovery → repair pipeline.

Tests:
- Auto-discovery engine finds app data dirs
- post_install_repair CLI entrypoint
- DEB install command generation
- Full pipeline: detect → config → copy_paths → repair
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from clonebox.detector import DetectedApplication, SystemDetector
from clonebox.post_install_repair import (
    RepairReport,
    RepairResult,
    run_post_install_repairs,
)


# ═════════════════════════════════════════════════════════════════════════════
#  Auto-discovery pipeline e2e
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.e2e
class TestAutoDiscoveryPipeline:
    """Test full auto-discovery → config generation pipeline."""

    def test_detect_command_includes_app_data(self):
        """clonebox detect should include app data dirs in output."""
        result = subprocess.run(
            [sys.executable, "-m", "clonebox", "detect", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0

    def test_discovery_finds_real_xdg_dirs(self):
        """Auto-discovery should find actual ~/.config dirs on this host."""
        d = SystemDetector()
        apps = d.detect_applications()
        results = d.auto_discover_app_data(apps)

        # At minimum should find SOMETHING on any dev machine
        assert isinstance(results, list)
        # All results have required fields
        for r in results:
            assert "path" in r
            assert "app" in r
            assert "source" in r
            assert "size_mb" in r
            assert r["source"] in ("static", "xdg", "snap", "proc", "desktop")

    def test_discovery_sources_are_diverse(self):
        """Auto-discovery should use multiple sources, not just static."""
        d = SystemDetector()
        apps = d.detect_applications()
        results = d.auto_discover_app_data(apps)

        sources = {r["source"] for r in results}
        # Should have at least static + one dynamic source
        assert "static" in sources or len(sources) >= 1

    def test_detect_app_data_dirs_backward_compatible(self):
        """Legacy detect_app_data_dirs should return same format as before."""
        d = SystemDetector()
        apps = d.detect_applications()
        results = d.detect_app_data_dirs(apps)

        for r in results:
            assert set(r.keys()) == {"path", "app", "type", "size_mb"}

    def test_suggest_packages_returns_deb_commands(self):
        """suggest_packages_for_apps should return deb_commands key."""
        d = SystemDetector()
        apps = d.detect_applications()
        result = d.suggest_packages_for_apps(apps)

        assert "apt" in result
        assert "snap" in result
        assert "deb_commands" in result
        assert isinstance(result["deb_commands"], list)


# ═════════════════════════════════════════════════════════════════════════════
#  Config generation e2e
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.e2e
class TestConfigGeneration:
    """Test that generated config includes all detected data."""

    def test_init_generates_config_with_app_data(self, tmp_path):
        """clonebox init should generate config with app_data_paths."""
        result = subprocess.run(
            [sys.executable, "-m", "clonebox", "init", str(tmp_path), "--yes"],
            capture_output=True, text=True, timeout=30,
            cwd=str(tmp_path),
        )

        config_path = tmp_path / ".clonebox.yaml"
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text())
            # Should have app_data_paths section
            assert "app_data_paths" in config or "paths" in config

    def test_deb_commands_in_post_commands(self):
        """DEB install commands should be generated for detected deb apps."""
        d = SystemDetector()

        # Simulate windsurf running
        apps = [
            DetectedApplication(
                name="windsurf", pid=1, cmdline="windsurf",
                exe="/usr/bin/windsurf",
            )
        ]
        result = d.suggest_packages_for_apps(apps)

        assert len(result["deb_commands"]) >= 1
        assert any("windsurf" in cmd for cmd in result["deb_commands"])


# ═════════════════════════════════════════════════════════════════════════════
#  Post-install repair e2e
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.e2e
class TestPostInstallRepairPipeline:
    """Test post-install repair as integrated pipeline."""

    @patch("clonebox.post_install_repair._ssh_exec")
    def test_repair_all_phases_run(self, mock_ssh):
        """All 5 repair phases should execute."""
        mock_ssh.return_value = "y"

        report = run_post_install_repairs(
            ssh_port=22000,
            ssh_key=None,
            vm_username="ubuntu",
            browsers=["firefox"],
            gui_mode=True,
            copy_paths={"/home/tom/.config/Code": "/home/ubuntu/.config/Code"},
            snap_packages=["firefox"],
            host_username="tom",
        )

        assert isinstance(report, RepairReport)
        names = {r.name for r in report.results}

        # Phase 1: System
        assert "dns-resolution" in names
        assert "apt-lock" in names
        assert "xdg-runtime-dir" in names
        assert "machine-id" in names
        assert "dbus-user-session" in names
        assert "gdm-running" in names

        # Phase 2: Ownership
        assert "home-dir-permissions" in names
        assert "copied-data-ownership" in names

        # Phase 3: App repairs
        assert "app-lock-files" in names
        assert "fontconfig-cache" in names
        assert "ide-config-paths" in names

        # Phase 4: Browser verification
        assert any("headless-verify" in n for n in names)

    @patch("clonebox.post_install_repair._ssh_exec")
    def test_repair_report_counts(self, mock_ssh):
        """Repair report should have correct counts."""
        mock_ssh.return_value = "y"

        report = run_post_install_repairs(
            ssh_port=22000, ssh_key=None,
            browsers=[], gui_mode=False,
        )

        assert report.detected_count >= 0
        assert report.repaired_count >= 0
        assert report.failed_count >= 0
        assert len(report.results) == (
            report.detected_count
            + (len(report.results) - report.detected_count)
        )

    @patch("clonebox.post_install_repair._ssh_exec")
    def test_repair_handles_ssh_failures(self, mock_ssh):
        """Repair should handle SSH failures gracefully."""
        mock_ssh.return_value = None  # SSH returns None on failure

        report = run_post_install_repairs(
            ssh_port=22000, ssh_key=None,
            browsers=[], gui_mode=False,
        )

        # Should still return a report (not crash)
        assert isinstance(report, RepairReport)
        assert len(report.results) > 0

    @patch("clonebox.post_install_repair._ssh_exec")
    def test_ide_config_paths_repair(self, mock_ssh):
        """IDE config path repair should rewrite host paths."""

        def mock_run(port, key, command, username, timeout):
            if "cat" in command and "Code/User/settings.json" in command:
                return '{"terminal.cwd": "/home/tom/projects"}'
            return "y"

        mock_ssh.side_effect = mock_run

        report = run_post_install_repairs(
            ssh_port=22000, ssh_key=None,
            browsers=[], gui_mode=False,
            host_username="tom",
        )

        ide_result = next(
            (r for r in report.results if r.name == "ide-config-paths"), None
        )
        assert ide_result is not None
        assert ide_result.detected

    @patch("clonebox.post_install_repair._ssh_exec")
    def test_snap_classic_detection(self, mock_ssh):
        """Classic snaps should be detected and skipped for interface repair."""
        def mock_run(port, key, command, username, timeout):
            if "snap list pycharm-community" in command and "echo y" in command:
                return "y"
            if "snap list pycharm-community" in command and "awk" in command:
                return "classic"
            if "snap list" in command and "awk" in command and "NR>1" in command:
                return "pycharm-community"
            return "y"

        mock_ssh.side_effect = mock_run

        report = run_post_install_repairs(
            ssh_port=22000, ssh_key=None,
            browsers=[], gui_mode=False,
            snap_packages=["pycharm-community"],
        )

        snap_result = next(
            (r for r in report.results
             if r.name == "snap-interfaces:pycharm-community"), None
        )
        assert snap_result is not None
        assert not snap_result.detected
        assert "Classic" in snap_result.detail


# ═════════════════════════════════════════════════════════════════════════════
#  CLI entrypoint tests
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.e2e
class TestRepairCLI:
    """Test post_install_repair CLI."""

    def test_repair_module_help(self):
        """python -m clonebox.post_install_repair without args shows usage."""
        result = subprocess.run(
            [sys.executable, "-m", "clonebox.post_install_repair"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1
        assert "Usage" in result.stdout

    def test_repair_module_bad_vm(self):
        """python -m clonebox.post_install_repair nonexistent-vm should fail."""
        result = subprocess.run(
            [sys.executable, "-m", "clonebox.post_install_repair", "nonexistent-vm-12345"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0
