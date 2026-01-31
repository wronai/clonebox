# tests/test_validator_mocked.py
from clonebox.validator import VMValidator
import pytest
from unittest.mock import Mock


def make_validator(cfg=None):
    cfg = cfg or {}
    # Ensure we have a valid VM config
    if "vm" not in cfg:
        cfg["vm"] = {
            "name": "test-vm",
            "ram_mb": 2048,
            "vcpus": 2,
            "disk_size_gb": 20,
            "username": "ubuntu"
        }
    return VMValidator(config=cfg, vm_name="vm1", conn_uri="qemu:///system", console=None)


class CmdResponder:
    """Simple responder to emulate _exec_in_vm outputs based on command substrings."""
    
    def __init__(self, extra=None):
        self.extra = extra or {}

    def __call__(self, cmd, timeout=10):
        # mount detection
        if "mount | grep 9p" in cmd:
            # emulate a 9p mount at /mnt/guest
            return "/dev/host on /mnt/guest type 9p (rw)\n"
        # test -d
        if "test -d /mnt/guest" in cmd:
            return "yes"
        # list files
        if "ls -A /mnt/guest" in cmd:
            return "file1 file2"
        # dpkg checks
        if "dpkg -l" in cmd:
            if "pkg_present" in cmd:
                return "ii  pkg_present 1.2.3 all"
            return ""
        # snap checks in validate_snap_packages
        if "snap list | grep '^firefox'" in cmd:
            return "1234"
        if "snap list | grep '^pycharm-community'" in cmd:
            return "5678"
        if "snap list | grep '^chromium'" in cmd:
            return "9012"
        # systemctl checks
        if cmd.startswith("systemctl is-enabled"):
            svc = cmd.split()[-1]
            return "enabled" if svc == "goodservice" else "disabled"
        if cmd.startswith("systemctl is-active"):
            svc = cmd.split()[-1]
            return "active" if svc == "goodservice" else "inactive"
        if "systemctl show -p MainPID" in cmd:
            return "1234"
        # pgrep checks (apps)
        if "pgrep -f" in cmd and "firefox" in cmd:
            return "1234"
        if "pgrep -f" in cmd and "google-chrome" in cmd:
            return "5678"
        if "pgrep -f" in cmd and "chrome" in cmd:
            return "5678"
        # find pid
        if "pgrep -u" in cmd and "firefox" in cmd and "head -n 1" in cmd:
            return "4321"
        # snap connections used for interface detection (_snap_missing_interfaces)
        if "snap connections pycharm-community" in cmd:
            # "iface slot" per line (awk prints $1, $3), put '-' to mean not connected
            return "desktop -\nhome :\nnetwork -\n"
        # snap logs / journal checks: return short dummy text
        if cmd.startswith("snap logs"):
            return "some snap logs"
        if cmd.startswith("journalctl"):
            return ""
        # smoke tests: headless launches
        if "chromium --headless" in cmd or "firefox --headless" in cmd or "google-chrome --headless" in cmd:
            return ""
        if cmd.startswith("command -v docker"):
            return "/usr/bin/docker"
        if "docker info" in cmd:
            return "Containers: 0\nImages: 0"
        # snap list for smoke tests
        if "snap list firefox" in cmd:
            return "name  version  rev  tracking  notes  publisher\nfirefox  123.0  456  stable  -  publisher"
        if "snap list chromium" in cmd:
            return "name  version  rev  tracking  notes  publisher\nchromium  124.0  789  stable  -  publisher"
        # command -v for google-chrome
        if "command -v google-chrome" in cmd:
            return "/usr/bin/google-chrome"
        # default: return empty string for commands that would be harmless
        return ""


def test_validate_mounts_mounted_and_accessible(monkeypatch):
    v = make_validator({"paths": {"/host/path": "/mnt/guest"}, "app_data_paths": {}})
    monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
    res = v.validate_mounts()
    assert res["total"] == 1
    assert res["passed"] == 1
    d = res["details"][0]
    assert d["mounted"] is True and d["accessible"] is True and d["files"] == "file1 file2"


def test_validate_mounts_multiple_paths(monkeypatch):
    v = make_validator({
        "paths": {"/host/path1": "/mnt/guest1", "/host/path2": "/mnt/guest2"},
        "app_data_paths": {"/host/app1": "/home/ubuntu/.app1"}
    })
    monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
    res = v.validate_mounts()
    assert res["total"] == 3
    assert res["passed"] == 3


def test_validate_mounts_not_mounted(monkeypatch):
    def responder(cmd, timeout=10):
        if "mount | grep 9p" in cmd:
            return ""  # No mounts
        return ""
    
    v = make_validator({"paths": {"/host/path": "/mnt/guest"}, "app_data_paths": {}})
    monkeypatch.setattr(v, "_exec_in_vm", responder)
    res = v.validate_mounts()
    assert res["total"] == 1
    assert res["passed"] == 0
    assert res["failed"] == 1


def test_validate_packages_installed_and_missing(monkeypatch):
    cfg = {"packages": ["pkg_present", "pkg_missing"]}
    v = make_validator(cfg)
    monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
    res = v.validate_packages()
    assert res["total"] == 2
    assert res["passed"] == 1
    assert any(d["package"] == "pkg_present" and d["installed"] for d in res["details"])
    assert any(d["package"] == "pkg_missing" and not d["installed"] for d in res["details"])


def test_validate_packages_no_packages(monkeypatch):
    v = make_validator({})
    monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
    res = v.validate_packages()
    assert res["total"] == 0
    assert res["passed"] == 0


def test_validate_services_skip_and_enabled_running(monkeypatch):
    cfg = {"services": ["libvirtd", "goodservice", "badservice"]}
    v = make_validator(cfg)
    monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
    res = v.validate_services()
    # libvirtd should be skipped (host-only)
    assert any(d.get("service") == "libvirtd" and d.get("skipped") for d in res["details"])
    # goodservice enabled & running counted as pass
    assert any(d["service"] == "goodservice" and d["enabled"] and d["running"] for d in res["details"])
    # badservice should be failed
    assert any(d["service"] == "badservice" and (not d["enabled"] or not d["running"]) for d in res["details"])


def test_validate_snap_packages_installed_and_missing(monkeypatch):
    cfg = {"snap_packages": ["firefox", "pycharm-community", "missing-snap"]}
    v = make_validator(cfg)
    monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
    res = v.validate_snap_packages()
    assert res["total"] == 3
    assert res["passed"] == 2
    assert res["failed"] == 1


def test_validate_snap_interfaces_and_apps(monkeypatch):
    cfg = {"snap_packages": ["pycharm-community", "firefox"], "packages": ["firefox"], "app_data_paths": {}}
    v = make_validator(cfg)
    monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
    snap_res = v.validate_snap_packages()
    app_res = v.validate_apps()
    # snap packages should be detected as installed
    assert snap_res["passed"] >= 1
    # firefox is installed, running (our responder returns pgrep yes)
    assert any(d["app"] == "firefox" for d in v.results["apps"]["details"])


def test_validate_apps_from_app_data_paths(monkeypatch):
    cfg = {"app_data_paths": {"/host/chrome": "/home/ubuntu/.config/google-chrome"}}
    v = make_validator(cfg)
    
    def responder(cmd, timeout=10):
        if "command -v google-chrome" in cmd:
            return "/usr/bin/google-chrome"
        elif "pgrep -f chrome" in cmd:
            return "5678"
        return ""
    
    monkeypatch.setattr(v, "_exec_in_vm", responder)
    res = v.validate_apps()
    assert res["total"] == 1
    assert res["passed"] == 1


def test_validate_apps_missing_interfaces(monkeypatch):
    cfg = {"snap_packages": ["pycharm-community"]}
    v = make_validator(cfg)
    monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
    res = v.validate_apps()
    # Should fail due to missing interfaces
    assert res["total"] == 1
    assert res["passed"] == 0


def test_validate_smoke_tests(monkeypatch):
    cfg = {
        "packages": ["firefox"],
        "snap_packages": ["chromium"],
        "app_data_paths": {"/host/x": "/home/ubuntu/.config/google-chrome"},
        "services": ["docker"],
    }
    v = make_validator(cfg)
    v.smoke_test = True
    # re-use responder that returns 'yes' for headless launches and docker present
    monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
    res = v.validate_smoke_tests()
    # smoke test items exist and some should pass per responder
    assert res["total"] >= 1
    # at least one passed (chromium/firefox/docker as our responder returns yes)
    assert res["passed"] >= 1


def test_validate_smoke_tests_failures(monkeypatch):
    cfg = {"snap_packages": ["firefox"]}
    v = make_validator(cfg)
    v.smoke_test = True
    
    def responder(cmd, timeout=10):
        if "snap list | grep '^firefox'" in cmd:
            return "1234"
        elif "pgrep -f firefox" in cmd:
            return ""  # Not running
        elif "firefox --headless" in cmd:
            return ""  # Command fails
        return ""
    
    monkeypatch.setattr(v, "_exec_in_vm", responder)
    res = v.validate_smoke_tests()
    assert res["total"] == 1
    assert res["passed"] == 0
    assert res["failed"] == 1


def test_validate_all_with_vm_running(monkeypatch):
    from unittest.mock import patch
    
    cfg = {
        "paths": {"/host/path": "/mnt/guest"},
        "packages": ["pkg_present"],
        "services": ["goodservice"],
        "snap_packages": ["firefox"]
    }
    v = make_validator(cfg)
    v.smoke_test = True
    
    # Mock virsh domstate
    with patch('subprocess.run') as mock_subprocess:
        mock_subprocess.return_value = Mock(stdout="running", returncode=0)
        monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
        
        res = v.validate_all()
        assert res["overall"] in ["pass", "partial"]
        assert res["mounts"]["total"] > 0
        assert res["packages"]["total"] > 0
        assert res["services"]["total"] > 0


def test_validate_all_with_vm_not_running(monkeypatch):
    from unittest.mock import patch
    
    cfg = {"paths": {"/host/path": "/mnt/guest"}}
    v = make_validator(cfg)
    
    # Mock virsh domstate
    with patch('subprocess.run') as mock_subprocess:
        mock_subprocess.return_value = Mock(stdout="shutdown", returncode=0)
        
        res = v.validate_all()
        assert res["overall"] == "vm_not_running"


def test_validate_all_error_checking_vm_state(monkeypatch):
    from unittest.mock import patch
    
    v = make_validator({})
    
    # Mock virsh domstate error
    with patch('subprocess.run') as mock_subprocess:
        mock_subprocess.side_effect = Exception("Connection error")
        
        res = v.validate_all()
        assert res["overall"] == "error"


def test_validate_all_no_checks(monkeypatch):
    from unittest.mock import patch
    
    v = make_validator({})
    
    # Mock virsh domstate
    with patch('subprocess.run') as mock_subprocess:
        mock_subprocess.return_value = Mock(stdout="running", returncode=0)
        monkeypatch.setattr(v, "_exec_in_vm", CmdResponder())
        
        res = v.validate_all()
        assert res["overall"] == "no_checks"


def test_validate_all_with_journal_errors(monkeypatch):
    from unittest.mock import patch
    
    cfg = {"packages": ["pkg_present"]}
    v = make_validator(cfg)
    
    def responder(cmd, timeout=10):
        if "dpkg -l" in cmd:
            return "ii  pkg_present 1.2.3 all"
        elif "journalctl" in cmd:
            return "Error 1\nError 2\nError 3"
        return ""
    
    # Mock virsh domstate
    with patch('subprocess.run') as mock_subprocess:
        mock_subprocess.return_value = Mock(stdout="running", returncode=0)
        monkeypatch.setattr(v, "_exec_in_vm", responder)
        
        # Mock console to capture panel output
        mock_console = Mock()
        v.console = mock_console
        
        res = v.validate_all()
        assert res["overall"] == "pass"
        # Verify that errors were logged
        mock_console.print.assert_called()
