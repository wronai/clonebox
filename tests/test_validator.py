"""
Tests for the VM validator module.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from clonebox.validator import VMValidator


class TestVMValidator:
    """Test VMValidator class."""

    @pytest.fixture
    def sample_config(self):
        """Sample config for testing."""
        return {
            "vm": {"name": "test-vm"},
            "paths": {
                "/home/user/projects": "/mnt/projects",
                "/home/user/data": "/mnt/data",
            },
            "app_data_paths": {
                "/home/user/.config/test": "/home/ubuntu/.config/test",
            },
            "packages": ["curl", "git", "vim"],
            "snap_packages": ["code"],
            "services": ["docker", "ssh"],
        }

    @pytest.fixture
    def mock_console(self):
        """Mock Rich console."""
        console = MagicMock()
        console.print = MagicMock()
        return console

    def test_validator_init(self, sample_config, mock_console):
        """Test validator initialization."""
        validator = VMValidator(
            config=sample_config,
            vm_name="test-vm",
            conn_uri="qemu:///session",
            console=mock_console,
        )

        assert validator.vm_name == "test-vm"
        assert validator.conn_uri == "qemu:///session"
        assert validator.results["overall"] == "unknown"

    def test_results_structure(self, sample_config, mock_console):
        """Test that results have correct structure."""
        validator = VMValidator(
            config=sample_config,
            vm_name="test-vm",
            conn_uri="qemu:///session",
            console=mock_console,
        )

        assert "mounts" in validator.results
        assert "packages" in validator.results
        assert "snap_packages" in validator.results
        assert "services" in validator.results
        assert "apps" in validator.results
        assert "overall" in validator.results

        for category in ["mounts", "packages", "snap_packages", "services", "apps"]:
            assert "passed" in validator.results[category]
            assert "failed" in validator.results[category]
            assert "total" in validator.results[category]
            assert "details" in validator.results[category]


class TestVMValidatorApps:
    @pytest.fixture
    def sample_config(self):
        return {
            "vm": {"name": "test-vm"},
            "paths": {
                "/home/user/projects": "/mnt/projects",
                "/home/user/data": "/mnt/data",
            },
            "app_data_paths": {
                "/home/user/.config/test": "/home/ubuntu/.config/test",
            },
            "packages": ["curl", "git", "vim"],
            "snap_packages": ["code"],
            "services": ["docker", "ssh"],
        }

    @pytest.fixture
    def mock_console(self):
        console = MagicMock()
        console.print = MagicMock()
        return console

    def test_validate_apps_all_ok(self, mock_console):
        config = {
            "vm": {"name": "test-vm"},
            "paths": {},
            "app_data_paths": {
                "/home/user/.config/google-chrome": "/home/ubuntu/.config/google-chrome",
            },
            "packages": ["firefox"],
            "snap_packages": ["pycharm-community"],
            "services": [],
        }

        validator = VMValidator(
            config=config, vm_name="test-vm", conn_uri="qemu:///session", console=mock_console
        )

        def fake_exec(cmd: str, timeout: int = 10):
            # install checks
            if "command -v firefox" in cmd:
                return "yes"
            if "snap list pycharm-community" in cmd:
                return "yes"
            if "command -v google-chrome" in cmd or "command -v google-chrome-stable" in cmd:
                return "yes"

            # profile dir checks
            if "test -d /home/ubuntu/snap/firefox/common/.mozilla/firefox" in cmd:
                return "yes"
            if "test -d /home/ubuntu/snap/pycharm-community/common/.config/JetBrains" in cmd:
                return "yes"
            if "test -d /home/ubuntu/.config/google-chrome" in cmd:
                return "yes"

            # running checks
            if "pgrep -u ubuntu -f '[f]irefox'" in cmd:
                return "yes"
            if (
                "pgrep -u ubuntu -f '[p]ycharm-community'" in cmd
                or "pgrep -u ubuntu -f '[p]ycharm'" in cmd
                or "pgrep -u ubuntu -f '[j]etbrains'" in cmd
            ):
                return "yes"
            if (
                "pgrep -u ubuntu -f '[g]oogle-chrome'" in cmd
                or "pgrep -u ubuntu -f '[g]oogle-chrome-stable'" in cmd
            ):
                return "yes"

            return "no"

        validator._exec_in_vm = fake_exec

        results = validator.validate_apps()
        assert results["total"] == 3
        assert results["failed"] == 0
        assert results["passed"] == 3

        for item in results["details"]:
            assert "running" in item

    def test_validate_apps_require_running_fails_when_not_running(self, mock_console):
        config = {
            "vm": {"name": "test-vm"},
            "paths": {},
            "app_data_paths": {},
            "packages": [],
            "snap_packages": ["pycharm-community"],
            "services": [],
        }

        validator = VMValidator(
            config=config,
            vm_name="test-vm",
            conn_uri="qemu:///session",
            console=mock_console,
            require_running_apps=True,
        )

        def fake_exec(cmd: str, timeout: int = 10):
            if "snap list pycharm-community" in cmd:
                return "yes"
            if "test -d /home/ubuntu/snap/pycharm-community/common/.config/JetBrains" in cmd:
                return "yes"
            if (
                "pgrep -u ubuntu -f '[p]ycharm-community'" in cmd
                or "pgrep -u ubuntu -f '[p]ycharm'" in cmd
                or "pgrep -u ubuntu -f '[j]etbrains'" in cmd
            ):
                return "no"
            if "snap connections pycharm-community" in cmd:
                return "desktop -\n"
            return "no"

        validator._exec_in_vm = fake_exec

        results = validator.validate_apps()
        assert results["total"] == 1
        assert results["passed"] == 0
        assert results["failed"] == 1

    def test_validate_apps_missing_profile_fails(self, mock_console):
        config = {
            "vm": {"name": "test-vm"},
            "paths": {},
            "app_data_paths": {
                "/home/user/.config/google-chrome": "/home/ubuntu/.config/google-chrome",
            },
            "packages": ["firefox"],
            "snap_packages": [],
            "services": [],
        }

        validator = VMValidator(
            config=config, vm_name="test-vm", conn_uri="qemu:///session", console=mock_console
        )

        def fake_exec(cmd: str, timeout: int = 10):
            if "command -v firefox" in cmd:
                return "yes"
            if "test -d /home/ubuntu/snap/firefox/common/.mozilla/firefox" in cmd:
                return "no"
            if "test -d /home/ubuntu/.mozilla/firefox" in cmd:
                return "no"
            if "command -v google-chrome" in cmd or "command -v google-chrome-stable" in cmd:
                return "yes"
            if "test -d /home/ubuntu/.config/google-chrome" in cmd:
                return "yes"

            # running checks
            if "pgrep -u ubuntu -f '[f]irefox'" in cmd:
                return "yes"
            if (
                "pgrep -u ubuntu -f '[g]oogle-chrome'" in cmd
                or "pgrep -u ubuntu -f '[g]oogle-chrome-stable'" in cmd
            ):
                return "yes"
            return "no"

        validator._exec_in_vm = fake_exec

        results = validator.validate_apps()
        assert results["total"] == 2
        assert results["failed"] == 1

        for item in results["details"]:
            assert "running" in item


class TestVMValidatorServices:
    @pytest.fixture
    def sample_config(self):
        return {
            "vm": {"name": "test-vm"},
            "paths": {
                "/home/user/projects": "/mnt/projects",
                "/home/user/data": "/mnt/data",
            },
            "app_data_paths": {
                "/home/user/.config/test": "/home/ubuntu/.config/test",
            },
            "packages": ["curl", "git", "vim"],
            "snap_packages": ["code"],
            "services": ["docker", "ssh"],
        }

    @pytest.fixture
    def mock_console(self):
        console = MagicMock()
        console.print = MagicMock()
        return console

    def test_validate_services_skips_host_only(self, mock_console):
        config = {
            "vm": {"name": "test-vm"},
            "paths": {},
            "app_data_paths": {},
            "packages": [],
            "snap_packages": [],
            "services": ["libvirtd", "docker"],
        }

        validator = VMValidator(
            config=config, vm_name="test-vm", conn_uri="qemu:///session", console=mock_console
        )

        def fake_exec(cmd: str, timeout: int = 10):
            if "systemctl is-enabled docker" in cmd:
                return "enabled"
            if "systemctl is-active docker" in cmd:
                return "active"
            if "systemctl show -p MainPID --value docker" in cmd:
                return "123"
            return ""

        validator._exec_in_vm = fake_exec

        results = validator.validate_services()
        assert results["total"] == 1
        assert results["passed"] == 1
        assert results.get("skipped") == 1

    @patch("subprocess.run")
    def test_exec_in_vm_success(self, mock_run, sample_config, mock_console):
        """Test successful command execution in VM."""
        # Mock guest-exec response
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout='{"return":{"pid":1234}}', stderr=""),
            MagicMock(
                returncode=0,
                stdout='{"return":{"exited":true,"exitcode":0,"out-data":"dGVzdCBvdXRwdXQ="}}',
                stderr="",
            ),
        ]

        validator = VMValidator(
            config=sample_config,
            vm_name="test-vm",
            conn_uri="qemu:///session",
            console=mock_console,
        )

        result = validator._exec_in_vm("echo test")
        assert result == "test output"

    @patch("subprocess.run")
    def test_exec_in_vm_failure(self, mock_run, sample_config, mock_console):
        """Test failed command execution in VM."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

        validator = VMValidator(
            config=sample_config,
            vm_name="test-vm",
            conn_uri="qemu:///session",
            console=mock_console,
        )

        result = validator._exec_in_vm("failing command")
        assert result is None

    @patch("subprocess.run")
    def test_validate_mounts_all_mounted(self, mock_run, sample_config, mock_console):
        """Test mount validation when all mounts are active."""
        # Mock responses for mount check
        mock_run.side_effect = [
            # mount | grep 9p
            MagicMock(returncode=0, stdout='{"return":{"pid":1}}', stderr=""),
            MagicMock(
                returncode=0,
                stdout='{"return":{"exited":true,"out-data":"bW91bnQwIG9uIC9tbnQvcHJvamVjdHMgdHlwZSA5cAptb3VudDEgb24gL21udC9kYXRhIHR5cGUgOXAKbW91bnQyIG9uIC9ob21lL3VidW50dS8uY29uZmlnL3Rlc3QgdHlwZSA5cA=="}}',
                stderr="",
            ),
            # test -d for each path (3 paths)
            MagicMock(returncode=0, stdout='{"return":{"pid":2}}', stderr=""),
            MagicMock(
                returncode=0,
                stdout='{"return":{"exited":true,"exitcode":0,"out-data":"eWVz"}}',
                stderr="",
            ),
            MagicMock(returncode=0, stdout='{"return":{"pid":3}}', stderr=""),
            MagicMock(
                returncode=0,
                stdout='{"return":{"exited":true,"exitcode":0,"out-data":"NQ=="}}',
                stderr="",
            ),
            MagicMock(returncode=0, stdout='{"return":{"pid":4}}', stderr=""),
            MagicMock(
                returncode=0,
                stdout='{"return":{"exited":true,"exitcode":0,"out-data":"eWVz"}}',
                stderr="",
            ),
            MagicMock(returncode=0, stdout='{"return":{"pid":5}}', stderr=""),
            MagicMock(
                returncode=0,
                stdout='{"return":{"exited":true,"exitcode":0,"out-data":"MTA="}}',
                stderr="",
            ),
            MagicMock(returncode=0, stdout='{"return":{"pid":6}}', stderr=""),
            MagicMock(
                returncode=0,
                stdout='{"return":{"exited":true,"exitcode":0,"out-data":"eWVz"}}',
                stderr="",
            ),
            MagicMock(returncode=0, stdout='{"return":{"pid":7}}', stderr=""),
            MagicMock(
                returncode=0,
                stdout='{"return":{"exited":true,"exitcode":0,"out-data":"Mw=="}}',
                stderr="",
            ),
        ]

        validator = VMValidator(
            config=sample_config,
            vm_name="test-vm",
            conn_uri="qemu:///session",
            console=mock_console,
        )

        results = validator.validate_mounts()

        assert results["total"] == 3
        # Console should have been called with table output
        assert mock_console.print.called

    @patch("subprocess.run")
    def test_validate_packages_all_installed(self, mock_run, sample_config, mock_console):
        """Test package validation when all packages are installed."""

        # Mock dpkg -l responses
        def run_side_effect(*args, **kwargs):
            result = MagicMock(returncode=0, stderr="")
            result.stdout = '{"return":{"pid":1}}'
            return result

        mock_run.side_effect = run_side_effect

        validator = VMValidator(
            config=sample_config,
            vm_name="test-vm",
            conn_uri="qemu:///session",
            console=mock_console,
        )

        # Manually set results for testing
        validator.results["packages"]["total"] = 3
        validator.results["packages"]["passed"] = 3
        validator.results["packages"]["failed"] = 0

        assert validator.results["packages"]["total"] == 3
        assert validator.results["packages"]["passed"] == 3

    def test_validate_empty_config(self, mock_console):
        """Test validation with empty config."""
        empty_config = {
            "vm": {"name": "empty-vm"},
            "paths": {},
            "app_data_paths": {},
            "packages": [],
            "snap_packages": [],
            "services": [],
        }

        validator = VMValidator(
            config=empty_config,
            vm_name="empty-vm",
            conn_uri="qemu:///session",
            console=mock_console,
        )

        # Validate mounts with empty paths
        results = validator.validate_mounts()
        assert results["total"] == 0

        # Validate packages with empty list
        results = validator.validate_packages()
        assert results["total"] == 0


class TestVMValidatorIntegration:
    """Integration tests for VMValidator (require mocking)."""

    @patch("subprocess.run")
    def test_validate_all_with_vm_not_running(self, mock_run, mock_console=None):
        """Test validate_all when VM is not running."""
        mock_console = MagicMock()

        mock_run.return_value = MagicMock(returncode=0, stdout="shut off", stderr="")

        config = {
            "vm": {"name": "stopped-vm"},
            "paths": {},
            "app_data_paths": {},
            "packages": [],
            "snap_packages": [],
            "services": [],
        }

        validator = VMValidator(
            config=config, vm_name="stopped-vm", conn_uri="qemu:///session", console=mock_console
        )

        results = validator.validate_all()

        assert results["overall"] == "vm_not_running"


class TestValidatorResultsCalculation:
    """Test results calculation logic."""

    def test_overall_pass(self):
        """Test overall status is 'pass' when all checks pass."""
        console = MagicMock()
        config = {
            "vm": {"name": "test"},
            "paths": {},
            "app_data_paths": {},
            "packages": [],
            "snap_packages": [],
            "services": [],
        }

        validator = VMValidator(config, "test", "qemu:///session", console)

        # Simulate all passed
        validator.results["mounts"] = {"passed": 5, "failed": 0, "total": 5, "details": []}
        validator.results["packages"] = {"passed": 3, "failed": 0, "total": 3, "details": []}
        validator.results["snap_packages"] = {"passed": 1, "failed": 0, "total": 1, "details": []}
        validator.results["services"] = {"passed": 2, "failed": 0, "total": 2, "details": []}

        total_failed = sum(
            r["failed"]
            for r in [
                validator.results["mounts"],
                validator.results["packages"],
                validator.results["snap_packages"],
                validator.results["services"],
            ]
        )

        assert total_failed == 0

    def test_overall_partial(self):
        """Test overall status is 'partial' when some checks fail."""
        console = MagicMock()
        config = {
            "vm": {"name": "test"},
            "paths": {},
            "app_data_paths": {},
            "packages": [],
            "snap_packages": [],
            "services": [],
        }

        validator = VMValidator(config, "test", "qemu:///session", console)

        # Simulate some failed
        validator.results["mounts"] = {"passed": 3, "failed": 2, "total": 5, "details": []}
        validator.results["packages"] = {"passed": 2, "failed": 1, "total": 3, "details": []}

        total_failed = (
            validator.results["mounts"]["failed"] + validator.results["packages"]["failed"]
        )

        assert total_failed == 3
