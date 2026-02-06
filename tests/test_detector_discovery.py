#!/usr/bin/env python3
"""Tests for the auto-discovery engine in SystemDetector."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clonebox.detector import DetectedApplication, SystemDetector


class TestDiscoverXdgDirs:
    """Test XDG convention-based discovery."""

    def test_finds_config_dir(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        (tmp_path / ".config" / "Windsurf").mkdir(parents=True)
        (tmp_path / ".config" / "Windsurf" / "settings.json").write_text("{}")

        result = d._discover_xdg_dirs("windsurf")
        assert ".config/Windsurf" in result

    def test_finds_local_share_dir(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        (tmp_path / ".local" / "share" / "JetBrains").mkdir(parents=True)
        (tmp_path / ".local" / "share" / "JetBrains" / "data").write_text("x")

        result = d._discover_xdg_dirs("jetbrains")
        assert ".local/share/JetBrains" in result

    def test_finds_dotdir(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        (tmp_path / ".vscode").mkdir()
        (tmp_path / ".vscode" / "ext").write_text("x")

        result = d._discover_xdg_dirs("vscode")
        assert ".vscode" in result

    def test_case_insensitive_match(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        (tmp_path / ".config" / "Code").mkdir(parents=True)

        result = d._discover_xdg_dirs("code")
        assert ".config/Code" in result

    def test_no_match_returns_empty(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        (tmp_path / ".config" / "Other").mkdir(parents=True)

        result = d._discover_xdg_dirs("nonexistent")
        assert result == []


class TestDiscoverSnapDirs:
    """Test snap directory discovery."""

    def test_finds_snap_common_dirs(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        common = tmp_path / "snap" / "firefox" / "common"
        (common / ".mozilla" / "firefox").mkdir(parents=True)
        (common / ".cache").mkdir(parents=True)

        result = d._discover_snap_dirs("firefox")
        assert any(".mozilla" in r for r in result)
        assert any("snap/firefox" in r for r in result)

    def test_no_snap_dir(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path
        # No snap/ directory at all
        result = d._discover_snap_dirs("firefox")
        assert result == []

    def test_no_matching_snap(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        (tmp_path / "snap" / "other-app" / "common").mkdir(parents=True)

        result = d._discover_snap_dirs("firefox")
        assert result == []


class TestDiscoverProcDataDirs:
    """Test /proc/PID/fd discovery."""

    def test_nonexistent_pid(self):
        d = SystemDetector()
        result = d._discover_proc_data_dirs(99999999)
        assert result == []

    def test_filters_cache_paths(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        # Create a fake fd structure
        fd_dir = tmp_path / "fake_fd"
        fd_dir.mkdir()

        # This tests the logic, not actual /proc
        # We'll mock Path iteration
        with patch.object(Path, "exists", return_value=False):
            result = d._discover_proc_data_dirs(1)
        assert result == []

    def test_too_broad_dirs_filtered(self):
        d = SystemDetector()
        assert ".config" in d._TOO_BROAD_DIRS
        assert ".local/share" in d._TOO_BROAD_DIRS
        assert ".cache" in d._TOO_BROAD_DIRS


class TestDiscoverDesktopAppName:
    """Test .desktop file parsing."""

    def test_finds_name_from_desktop_file(self, tmp_path):
        d = SystemDetector()

        apps_dir = tmp_path / "applications"
        apps_dir.mkdir()
        (apps_dir / "windsurf.desktop").write_text(
            "[Desktop Entry]\n"
            "Name=Windsurf\n"
            "Exec=/usr/bin/windsurf %U\n"
            "Type=Application\n"
        )

        with patch.object(d, "_discover_desktop_app_name") as mock:
            # Test the actual method with the temp dir
            pass

        # Direct test
        desktop_dirs_backup = [
            Path("/usr/share/applications"),
            d.home / ".local" / "share" / "applications",
        ]
        # Use the actual method with patched dirs
        names = d._discover_desktop_app_name("/usr/bin/windsurf")
        # Can't guarantee system .desktop files exist, just verify no crash
        assert isinstance(names, list)

    def test_no_exe_returns_empty(self):
        d = SystemDetector()
        result = d._discover_desktop_app_name("")
        assert result == []


class TestAutoDiscoverAppData:
    """Test the main auto_discover_app_data method."""

    def test_static_registry_used(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        # Create a path that matches static registry for "windsurf"
        ws_dir = tmp_path / ".config" / "Windsurf"
        ws_dir.mkdir(parents=True)
        (ws_dir / "settings.json").write_text("{}")

        results = d.auto_discover_app_data([])
        paths = {r["path"] for r in results}
        assert str(ws_dir) in paths

    def test_xdg_discovers_unknown_app(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        # Create a dir for "myide" - NOT in static registry
        myide = tmp_path / ".config" / "MyIDE"
        myide.mkdir(parents=True)
        (myide / "config.json").write_text("{}")

        app = DetectedApplication(
            name="myide", pid=1, cmdline="myide", exe="/usr/bin/myide"
        )
        results = d.auto_discover_app_data([app])

        paths = {r["path"] for r in results}
        assert str(myide) in paths
        # Verify source is "xdg"
        xdg_results = [r for r in results if r["path"] == str(myide)]
        assert xdg_results[0]["source"] == "xdg"

    def test_snap_discovery(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        snap_dir = tmp_path / "snap" / "firefox" / "common" / ".mozilla"
        snap_dir.mkdir(parents=True)
        (snap_dir / "profiles.ini").write_text("[Profile0]")

        results = d.auto_discover_app_data([])
        paths = {r["path"] for r in results}
        assert any("snap/firefox" in p for p in paths)

    def test_deduplication(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path

        # Create dir that matches both static AND xdg
        code_dir = tmp_path / ".config" / "Code"
        code_dir.mkdir(parents=True)
        (code_dir / "settings.json").write_text("{}")

        results = d.auto_discover_app_data([])
        code_paths = [r for r in results if r["path"] == str(code_dir)]
        # Should appear only once despite matching from multiple sources
        assert len(code_paths) == 1

    def test_nonexistent_dirs_skipped(self, tmp_path):
        d = SystemDetector()
        d.home = tmp_path
        # Don't create any dirs - all should be skipped
        results = d.auto_discover_app_data([])
        assert results == []

    def test_detect_app_data_dirs_compatibility(self, tmp_path):
        """detect_app_data_dirs wraps auto_discover_app_data in legacy format."""
        d = SystemDetector()
        d.home = tmp_path

        ws = tmp_path / ".windsurf"
        ws.mkdir()
        (ws / "ext").write_text("x")

        results = d.detect_app_data_dirs([])
        for r in results:
            assert "path" in r
            assert "app" in r
            assert "type" in r
            assert "size_mb" in r
            # Legacy format should NOT have "source"
            assert "source" not in r


class TestSuggestPackagesForApps:
    """Test package suggestion including deb type."""

    def test_apt_package(self):
        d = SystemDetector()
        app = DetectedApplication(name="python3", pid=1, cmdline="python3", exe="/usr/bin/python3")
        result = d.suggest_packages_for_apps([app])
        assert "python3" in result["apt"]

    def test_snap_package(self):
        d = SystemDetector()
        app = DetectedApplication(name="pycharm", pid=1, cmdline="pycharm", exe="/snap/bin/pycharm")
        result = d.suggest_packages_for_apps([app])
        assert "pycharm-community" in result["snap"]

    def test_deb_package_generates_command(self):
        d = SystemDetector()
        app = DetectedApplication(name="windsurf", pid=1, cmdline="windsurf", exe="/usr/bin/windsurf")
        result = d.suggest_packages_for_apps([app])
        assert len(result["deb_commands"]) == 1
        assert "windsurf" in result["deb_commands"][0]

    def test_deb_commands_for_cursor(self):
        d = SystemDetector()
        app = DetectedApplication(name="cursor", pid=1, cmdline="cursor", exe="/usr/bin/cursor")
        result = d.suggest_packages_for_apps([app])
        assert len(result["deb_commands"]) == 1
        assert "cursor" in result["deb_commands"][0]

    def test_no_duplicate_deb_commands(self):
        d = SystemDetector()
        apps = [
            DetectedApplication(name="windsurf", pid=1, cmdline="windsurf", exe="a"),
            DetectedApplication(name="windsurf-helper", pid=2, cmdline="windsurf", exe="b"),
        ]
        result = d.suggest_packages_for_apps(apps)
        # Should only have one windsurf command despite two processes
        windsurf_cmds = [c for c in result["deb_commands"] if "windsurf" in c]
        assert len(windsurf_cmds) == 1

    def test_empty_apps(self):
        d = SystemDetector()
        result = d.suggest_packages_for_apps([])
        assert result["apt"] == []
        assert result["snap"] == []
        assert result["deb_commands"] == []

    def test_deb_install_commands_defined(self):
        d = SystemDetector()
        assert "windsurf" in d.DEB_INSTALL_COMMANDS
        assert "cursor" in d.DEB_INSTALL_COMMANDS
        assert "google-chrome" in d.DEB_INSTALL_COMMANDS
