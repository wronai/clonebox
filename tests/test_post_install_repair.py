#!/usr/bin/env python3
"""Tests for the post_install_repair module."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from clonebox.post_install_repair import (
    RepairResult,
    RepairReport,
    _RepairCtx,
    _repair_snap_dir_ownership,
    _repair_copied_data_ownership,
    _repair_app_lock_files,
    _repair_crash_reports,
    _repair_snap_interfaces,
    _repair_xdg_runtime_dir,
    _repair_fontconfig_cache,
    _repair_machine_id,
    _repair_dbus_session,
    _repair_home_dir_permissions,
    _repair_gdm_running,
    _repair_dns_resolution,
    _repair_apt_lock,
    _repair_firefox_profiles_ini,
    _repair_ide_config_paths,
    _verify_headless_browsers,
    _verify_ide_launch,
    run_post_install_repairs,
)


# ── Data model tests ─────────────────────────────────────────────────────────


class TestRepairResult:
    def test_create_ok_result(self):
        r = RepairResult(name="test", detected=False, repaired=False, detail="OK")
        assert r.name == "test"
        assert not r.detected
        assert not r.repaired
        assert r.detail == "OK"

    def test_create_fixed_result(self):
        r = RepairResult(name="fix", detected=True, repaired=True, detail="Fixed")
        assert r.detected
        assert r.repaired

    def test_create_failed_result(self):
        r = RepairResult(name="fail", detected=True, repaired=False, error="err")
        assert r.detected
        assert not r.repaired
        assert r.error == "err"


class TestRepairReport:
    def test_empty_report(self):
        report = RepairReport()
        assert report.detected_count == 0
        assert report.repaired_count == 0
        assert report.failed_count == 0

    def test_report_with_results(self):
        report = RepairReport(results=[
            RepairResult("a", detected=True, repaired=True),
            RepairResult("b", detected=True, repaired=False),
            RepairResult("c", detected=False, repaired=False),
            RepairResult("d", detected=True, repaired=True),
        ])
        assert report.detected_count == 3
        assert report.repaired_count == 2
        assert report.failed_count == 1

    def test_log_summary(self, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            report = RepairReport(results=[
                RepairResult("ok", detected=False, repaired=False, detail="fine"),
                RepairResult("fix", detected=True, repaired=True, detail="fixed it"),
            ])
            report.log_summary()
        assert "POST-INSTALL REPAIR REPORT" in caplog.text
        assert "2 checks" in caplog.text


# ── RepairCtx tests ──────────────────────────────────────────────────────────


class TestRepairCtx:
    def test_init(self):
        ctx = _RepairCtx(ssh_port=22196, ssh_key=Path("/tmp/key"), vm_username="ubuntu")
        assert ctx.port == 22196
        assert ctx.user == "ubuntu"

    @patch("clonebox.post_install_repair._ssh_exec", return_value="hello")
    def test_run_delegates_to_ssh_exec(self, mock_ssh):
        ctx = _RepairCtx(ssh_port=22196, ssh_key=Path("/tmp/key"))
        result = ctx.run("echo hello")
        assert result == "hello"
        mock_ssh.assert_called_once()


# ── Individual repair tests (mocked SSH) ─────────────────────────────────────


def _make_ctx(responses):
    """Create a mock RepairCtx that returns sequential responses."""
    ctx = _RepairCtx(ssh_port=22000, ssh_key=None)
    ctx.run = MagicMock(side_effect=list(responses))
    return ctx


class TestRepairSnapDirOwnership:
    def test_no_snap_dirs(self):
        ctx = _make_ctx([""])  # ls -1 returns empty
        results = _repair_snap_dir_ownership(ctx)
        assert results == []

    def test_all_ok(self):
        ctx = _make_ctx([
            "firefox\nchromium",  # ls -1
            "ubuntu",             # stat firefox
            "ubuntu",             # stat chromium
        ])
        results = _repair_snap_dir_ownership(ctx)
        assert len(results) == 2
        assert all(not r.detected for r in results)

    def test_detects_and_fixes_root_ownership(self):
        ctx = _make_ctx([
            "firefox",   # ls -1
            "root",      # stat → root (detected)
            None,        # chown
            "ubuntu",    # stat verify → fixed
        ])
        results = _repair_snap_dir_ownership(ctx)
        assert len(results) == 1
        assert results[0].detected
        assert results[0].repaired


class TestRepairCopiedDataOwnership:
    def test_all_dirs_ok(self):
        ctx = _make_ctx(["MISSING"] * 14 + ["MISSING"] * 0)  # all MISSING
        results = _repair_copied_data_ownership(ctx, {})
        assert len(results) == 1
        assert not results[0].detected

    def test_detects_root_owned_dir(self):
        responses = []
        # 14 known dirs: first one "root", rest "MISSING"
        responses.append("root")
        responses.extend(["MISSING"] * 13)
        # chown
        responses.append(None)
        # verify
        responses.append("ubuntu")
        ctx = _make_ctx(responses)
        results = _repair_copied_data_ownership(ctx, {})
        assert results[0].detected
        assert results[0].repaired


class TestRepairAppLockFiles:
    def test_no_locks(self):
        ctx = _make_ctx(["", ""])  # lock_cmd empty, socket_cmd empty
        results = _repair_app_lock_files(ctx)
        assert len(results) == 1
        assert not results[0].detected

    def test_detects_and_removes_locks(self):
        ctx = _make_ctx([
            "/home/ubuntu/.mozilla/firefox/parent.lock",  # lock_cmd finds 1
            "",                                            # socket_cmd
            None,                                          # rm
            "",                                            # verify
        ])
        results = _repair_app_lock_files(ctx)
        assert results[0].detected
        assert results[0].repaired


class TestRepairCrashReports:
    def test_no_crash_dumps(self):
        ctx = _make_ctx(["0"] * 8)  # 8 crash dirs, all 0
        results = _repair_crash_reports(ctx)
        assert not results[0].detected

    def test_detects_and_removes_crash_dumps(self):
        responses = ["5"]  # first dir has 5 dumps
        responses.extend(["0"] * 7)  # rest empty
        responses.extend([None] * 8)  # delete calls
        ctx = _make_ctx(responses)
        results = _repair_crash_reports(ctx)
        assert results[0].detected
        assert results[0].repaired
        assert "5" in results[0].detail


class TestRepairSnapInterfaces:
    def test_no_snap_packages(self):
        ctx = _make_ctx([""])  # snap list returns nothing
        results = _repair_snap_interfaces(ctx)
        assert results == []

    def test_classic_snap_skipped(self):
        ctx = _make_ctx([
            "y",        # snap list pycharm-community → installed
            "classic",  # Notes column
        ])
        results = _repair_snap_interfaces(ctx, snap_packages=["pycharm-community"])
        assert len(results) == 1
        assert not results[0].detected
        assert "Classic" in results[0].detail

    def test_all_interfaces_connected(self):
        conns = (
            "Interface  Plug           Slot\n"
            "desktop    firefox:desktop  :desktop\n"
            "home       firefox:home     :home\n"
            "network    firefox:network  :network\n"
            "x11        firefox:x11      :x11\n"
            "wayland    firefox:wayland  :wayland\n"
            "desktop-legacy firefox:desktop-legacy :desktop-legacy\n"
        )
        ctx = _make_ctx([
            "y",       # installed
            "strict",  # not classic
            conns,     # connections
        ])
        results = _repair_snap_interfaces(ctx, snap_packages=["firefox"])
        assert len(results) == 1
        assert not results[0].detected


class TestRepairXdgRuntimeDir:
    def test_already_exists(self):
        ctx = _make_ctx(["1000", "y"])  # uid, exists
        results = _repair_xdg_runtime_dir(ctx)
        assert not results[0].detected

    def test_creates_dir(self):
        ctx = _make_ctx(["1000", "n", None, "y"])  # uid, missing, mkdir, verify
        results = _repair_xdg_runtime_dir(ctx)
        assert results[0].detected
        assert results[0].repaired


class TestRepairMachineId:
    def test_valid_machine_id(self):
        ctx = _make_ctx(["a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"])  # 32 hex chars
        results = _repair_machine_id(ctx)
        assert not results[0].detected

    def test_empty_machine_id_fixed(self):
        ctx = _make_ctx([
            "",                                           # empty
            None,                                         # regenerate
            "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",         # new valid
        ])
        results = _repair_machine_id(ctx)
        assert results[0].detected
        assert results[0].repaired

    def test_all_zeros_detected(self):
        ctx = _make_ctx([
            "0" * 32,                                     # all zeros
            None,                                         # regenerate
            "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",         # new valid
        ])
        results = _repair_machine_id(ctx)
        assert results[0].detected


class TestRepairDbusSession:
    def test_already_installed(self):
        ctx = _make_ctx(["y"])
        results = _repair_dbus_session(ctx)
        assert not results[0].detected

    def test_installs_dbus(self):
        ctx = _make_ctx(["n", None, "y"])  # missing, install, verify
        results = _repair_dbus_session(ctx)
        assert results[0].detected
        assert results[0].repaired


class TestRepairHomeDirPermissions:
    def test_all_ok(self):
        ctx = _make_ctx(["MISSING"] * 7)
        results = _repair_home_dir_permissions(ctx)
        assert not results[0].detected

    def test_fixes_root_owned(self):
        responses = ["root"]  # first dir (.config) owned by root
        responses.extend(["MISSING"] * 6)  # rest missing
        responses.append(None)  # chown
        responses.append("ubuntu")  # verify
        ctx = _make_ctx(responses)
        results = _repair_home_dir_permissions(ctx)
        assert results[0].detected
        assert results[0].repaired


class TestRepairGdmRunning:
    def test_not_gui_mode(self):
        ctx = _make_ctx([])
        results = _repair_gdm_running(ctx, gui_mode=False)
        assert results == []

    @patch("time.sleep")
    def test_gdm_already_active(self, _):
        ctx = _make_ctx(["active"])
        results = _repair_gdm_running(ctx, gui_mode=True)
        assert not results[0].detected

    @patch("time.sleep")
    def test_gdm_started(self, _):
        ctx = _make_ctx(["inactive", None, "active"])
        results = _repair_gdm_running(ctx, gui_mode=True)
        assert results[0].detected
        assert results[0].repaired


class TestRepairDnsResolution:
    def test_dns_ok(self):
        ctx = _make_ctx(["y"])
        results = _repair_dns_resolution(ctx)
        assert not results[0].detected

    @patch("time.sleep")
    def test_dns_fixed(self, _):
        ctx = _make_ctx(["n", None, "y"])
        results = _repair_dns_resolution(ctx)
        assert results[0].detected
        assert results[0].repaired


class TestRepairAptLock:
    def test_no_lock(self):
        ctx = _make_ctx(["idle"])
        results = _repair_apt_lock(ctx)
        assert not results[0].detected

    @patch("time.sleep")
    def test_lock_released(self, _):
        ctx = _make_ctx(["busy", "idle"])
        results = _repair_apt_lock(ctx)
        assert results[0].detected
        assert results[0].repaired


class TestRepairFontconfigCache:
    def test_cache_exists(self):
        ctx = _make_ctx(["y"])
        results = _repair_fontconfig_cache(ctx)
        assert not results[0].detected

    def test_rebuilds_cache(self):
        ctx = _make_ctx(["n", None, "y"])
        results = _repair_fontconfig_cache(ctx)
        assert results[0].detected
        assert results[0].repaired


class TestRepairFirefoxProfilesIni:
    def test_no_profiles_ini(self):
        ctx = _make_ctx(["", ""])  # both paths return empty
        results = _repair_firefox_profiles_ini(ctx)
        assert not results[0].detected

    def test_correct_paths_ok(self):
        ini = "[Profile0]\nPath=abc.default\nIsRelative=1\n"
        ctx = _make_ctx([ini, ""])  # snap path has content, classic path empty
        results = _repair_firefox_profiles_ini(ctx)
        assert not results[0].detected

    def test_fixes_wrong_host_paths(self):
        ini = "[Profile0]\nPath=/home/tom/.mozilla/firefox/abc.default\nIsRelative=0\n"
        ctx = _make_ctx([
            ini,   # cat profiles.ini
            None,  # tee
            None,  # chown
        ])
        results = _repair_firefox_profiles_ini(ctx)
        assert results[0].detected
        assert results[0].repaired


class TestRepairIdeConfigPaths:
    def test_no_host_username(self):
        ctx = _make_ctx([])
        results = _repair_ide_config_paths(ctx, host_username=None)
        assert not results[0].detected
        assert "skipped" in results[0].detail

    def test_same_user_skipped(self):
        ctx = _make_ctx([])
        results = _repair_ide_config_paths(ctx, host_username="ubuntu")
        assert not results[0].detected

    def test_fixes_host_paths_in_settings(self):
        content = '{"terminal.cwd": "/home/tom/projects"}'
        ctx = _make_ctx([
            content,  # cat settings.json (Code)
            None,     # sed
            None,     # chown
            "",       # rest return empty
            "", "", "", "",
        ])
        results = _repair_ide_config_paths(ctx, host_username="tom")
        assert results[0].detected
        assert results[0].repaired


class TestVerifyHeadlessBrowsers:
    def test_no_browsers(self):
        ctx = _make_ctx(["1000"])  # uid is always read first
        results = _verify_headless_browsers(ctx, [])
        assert results == []

    def test_browser_not_installed(self):
        ctx = _make_ctx(["1000", "n"])  # uid, firefox not found
        results = _verify_headless_browsers(ctx, ["firefox"])
        assert results == []

    def test_browser_headless_ok(self):
        ctx = _make_ctx(["1000", "y", "y"])  # uid, installed, headless ok
        results = _verify_headless_browsers(ctx, ["firefox"])
        assert len(results) == 1
        assert not results[0].detected
        assert "OK" in results[0].detail


class TestVerifyIdeLaunch:
    def test_no_ides_installed(self):
        # windsurf: command -v → n
        # code: command -v → n
        # cursor: command -v → n
        # pycharm: command -v → n, snap list → n
        ctx = _make_ctx(["n", "n", "n", "n", "n"])
        results = _verify_ide_launch(ctx)
        assert results == []

    def test_ide_version_ok(self):
        ctx = _make_ctx([
            "n",       # windsurf: command -v → n
            "y",       # code: command -v → y
            "1.86.0",  # code: version output
            "n",       # cursor: command -v → n
            "n",       # pycharm: command -v → n
            "n",       # pycharm: snap list → n
        ])
        results = _verify_ide_launch(ctx)
        assert len(results) == 1
        assert not results[0].detected
        assert "1.86.0" in results[0].detail


# ── Integration test: run_post_install_repairs ────────────────────────────────


class TestRunPostInstallRepairs:
    @patch("clonebox.post_install_repair._ssh_exec")
    def test_runs_all_phases(self, mock_ssh):
        # Return sensible defaults for all SSH calls
        mock_ssh.return_value = "y"

        report = run_post_install_repairs(
            ssh_port=22000,
            ssh_key=None,
            vm_username="ubuntu",
            browsers=[],
            gui_mode=False,
            copy_paths={},
            snap_packages=[],
            host_username=None,
        )

        assert isinstance(report, RepairReport)
        assert len(report.results) > 0
        # Should have run all phase checks
        names = {r.name for r in report.results}
        assert "dns-resolution" in names
        assert "machine-id" in names
        assert "home-dir-permissions" in names
        assert "app-lock-files" in names
        assert "fontconfig-cache" in names
