"""Tests for new CLI commands (audit, compose, plugin, remote, logs, set-password)."""
import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock, ANY
import json

import pytest


class TestAuditCommands:
    """Test audit CLI commands."""

    @patch("clonebox.cli.policy_audit_commands.AuditQuery")
    def test_cmd_audit_list(self, mock_query_cls):
        """Test audit list command."""
        from clonebox.cli import cmd_audit_list

        mock_query = MagicMock()
        mock_query.query.return_value = []
        mock_query_cls.return_value = mock_query

        args = argparse.Namespace(
            limit=50,
            event_type=None,
            since=None,
        )

        cmd_audit_list(args)
        mock_query.query.assert_called_once()

    @patch("clonebox.cli.policy_audit_commands.AuditQuery")
    def test_cmd_audit_list_with_events(self, mock_query_cls):
        """Test audit list with events."""
        from clonebox.cli import cmd_audit_list
        from clonebox.audit import AuditEvent, AuditEventType, AuditOutcome
        from datetime import datetime

        mock_event = MagicMock()
        mock_event.timestamp = datetime.now()
        mock_event.event_type = AuditEventType.VM_CREATE
        mock_event.outcome = AuditOutcome.SUCCESS
        mock_event.target_name = "test-vm"
        mock_event.user = "testuser"

        mock_query = MagicMock()
        mock_query.query.return_value = [mock_event]
        mock_query_cls.return_value = mock_query

        args = argparse.Namespace(
            limit=50,
            event_type=None,
            since=None,
        )

        cmd_audit_list(args)

    @patch("clonebox.cli.policy_audit_commands.AuditQuery")
    def test_cmd_audit_failures(self, mock_query_cls):
        """Test audit failures command."""
        from clonebox.cli import cmd_audit_failures
        from clonebox.audit import AuditOutcome

        mock_query = MagicMock()
        mock_query.query.return_value = []
        mock_query_cls.return_value = mock_query

        args = argparse.Namespace(limit=20)

        cmd_audit_failures(args)
        mock_query.query.assert_called_once_with(outcome=AuditOutcome.FAILURE, limit=20)

    @patch("clonebox.cli.policy_audit_commands.AuditQuery")
    def test_cmd_audit_search(self, mock_query_cls):
        """Test audit search command."""
        from clonebox.cli import cmd_audit_search

        mock_query = MagicMock()
        mock_query.query.return_value = []
        mock_query_cls.return_value = mock_query

        args = argparse.Namespace(
            event=None,
            since=None,
            user_filter=None,
            target=None,
            limit=100,
        )

        cmd_audit_search(args)

    @patch("clonebox.cli.policy_audit_commands.AuditQuery")
    def test_cmd_audit_export_json(self, mock_query_cls):
        """Test audit export to JSON."""
        from clonebox.cli import cmd_audit_export

        mock_query = MagicMock()
        mock_query.query.return_value = []
        mock_query_cls.return_value = mock_query

        args = argparse.Namespace(
            format="json",
            output=None,
            limit=10000,
        )

        cmd_audit_export(args)


class TestComposeCommands:
    """Test compose/orchestration CLI commands."""

    def test_cmd_compose_up_no_file(self, tmp_path):
        """Test compose up with missing file."""
        from clonebox.cli import cmd_compose_up
        import os

        os.chdir(tmp_path)

        args = argparse.Namespace(
            file="nonexistent.yaml",
            user=False,
            services=[],
        )

        # Should not raise, just print error
        cmd_compose_up(args)

    def test_cmd_compose_down_no_file(self, tmp_path):
        """Test compose down with missing file."""
        from clonebox.cli import cmd_compose_down
        import os

        os.chdir(tmp_path)

        args = argparse.Namespace(
            file="nonexistent.yaml",
            user=False,
            force=False,
            services=[],
        )

        cmd_compose_down(args)

    def test_cmd_compose_status_no_file(self, tmp_path):
        """Test compose status with missing file."""
        from clonebox.cli import cmd_compose_status
        import os

        os.chdir(tmp_path)

        args = argparse.Namespace(
            file="nonexistent.yaml",
            user=False,
            json=False,
        )

        cmd_compose_status(args)

    def test_cmd_compose_logs_no_file(self, tmp_path):
        """Test compose logs with missing file."""
        from clonebox.cli import cmd_compose_logs
        import os

        os.chdir(tmp_path)

        args = argparse.Namespace(
            file="nonexistent.yaml",
            user=False,
            follow=False,
            lines=50,
            service=None,
        )

        cmd_compose_logs(args)

    @patch("clonebox.cli.compose_commands.Orchestrator")
    def test_cmd_compose_up_with_file(self, mock_orch_cls, tmp_path):
        """Test compose up with valid file."""
        from clonebox.cli import cmd_compose_up

        compose_file = tmp_path / "clonebox-compose.yaml"
        compose_file.write_text("version: '1'\nservices: {}")

        mock_orch = MagicMock()
        mock_orch.up.return_value = MagicMock(success=True, failed_vms=[])
        mock_orch_cls.from_file.return_value = mock_orch
        
        # Make up accept any kwargs
        mock_orch.up.configure_mock(**{'return_value': MagicMock(success=True, failed_vms=[])})

        args = argparse.Namespace(
            file=str(compose_file),
            user=False,
            services=[],
            detach=False,
        )

        cmd_compose_up(args)
        mock_orch.up.assert_called_once()


class TestPluginCommands:
    """Test plugin CLI commands."""

    @patch("clonebox.cli.plugin_commands.get_plugin_manager")
    def test_cmd_plugin_list_empty(self, mock_get_manager):
        """Test plugin list with no plugins."""
        from clonebox.cli import cmd_plugin_list

        mock_manager = MagicMock()
        mock_manager.list_plugins.return_value = []
        mock_get_manager.return_value = mock_manager

        args = argparse.Namespace(verbose=False)

        cmd_plugin_list(args)

    @patch("clonebox.cli.plugin_commands.get_plugin_manager")
    def test_cmd_plugin_list_with_plugins(self, mock_get_manager):
        """Test plugin list with plugins."""
        from clonebox.cli import cmd_plugin_list

        mock_manager = MagicMock()
        mock_manager.list_plugins.return_value = [
            {"name": "test-plugin", "version": "1.0.0", "enabled": True}
        ]
        mock_get_manager.return_value = mock_manager

        args = argparse.Namespace(verbose=False)

        cmd_plugin_list(args)

    @patch("clonebox.cli.plugin_commands.get_plugin_manager")
    def test_cmd_plugin_enable(self, mock_get_manager):
        """Test plugin enable command."""
        from clonebox.cli import cmd_plugin_enable

        mock_manager = MagicMock()
        mock_get_manager.return_value = mock_manager

        args = argparse.Namespace(name="test-plugin")

        cmd_plugin_enable(args)
        mock_manager.enable.assert_called_once_with("test-plugin")

    @patch("clonebox.cli.plugin_commands.get_plugin_manager")
    def test_cmd_plugin_disable(self, mock_get_manager):
        """Test plugin disable command."""
        from clonebox.cli import cmd_plugin_disable

        mock_manager = MagicMock()
        mock_get_manager.return_value = mock_manager

        args = argparse.Namespace(name="test-plugin")

        cmd_plugin_disable(args)
        mock_manager.disable.assert_called_once_with("test-plugin")

    @patch("clonebox.cli.plugin_commands.get_plugin_manager")
    @patch("pathlib.Path.exists", return_value=True)
    def test_cmd_plugin_discover(self, mock_exists, mock_get_manager):
        """Test plugin discover command."""
        from clonebox.cli import cmd_plugin_discover

        mock_manager = MagicMock()
        mock_manager.discover_plugins.return_value = ["plugin1", "plugin2"]
        mock_manager.plugin_dirs = [Path("/test")]
        mock_get_manager.return_value = mock_manager

        args = argparse.Namespace(paths=None, verbose=False)

        cmd_plugin_discover(args)
        mock_manager.discover_plugins.assert_called()


class TestRemoteCommands:
    """Test remote management CLI commands."""

    @patch("clonebox.cli.remote_commands.RemoteCloner")
    def test_cmd_remote_list(self, mock_remote_cls):
        """Test remote list command."""
        from clonebox.cli import cmd_remote_list

        mock_remote = MagicMock()
        mock_remote.is_clonebox_installed.return_value = True
        mock_remote.list_vms.return_value = [{"name": "vm1", "state": "running"}]
        mock_remote_cls.return_value = mock_remote

        args = argparse.Namespace(host="user@server", user=False, json=False)

        cmd_remote_list(args)
        mock_remote.list_vms.assert_called_once()

    @patch("clonebox.cli.remote_commands.RemoteCloner")
    def test_cmd_remote_list_not_installed(self, mock_remote_cls):
        """Test remote list when clonebox not installed."""
        from clonebox.cli import cmd_remote_list

        mock_remote = MagicMock()
        mock_remote.is_clonebox_installed.return_value = False
        mock_remote_cls.return_value = mock_remote

        args = argparse.Namespace(host="user@server", user=False, json=False)

        cmd_remote_list(args)

    @patch("clonebox.cli.remote_commands.RemoteCloner")
    def test_cmd_remote_status(self, mock_remote_cls):
        """Test remote status command."""
        from clonebox.cli import cmd_remote_status

        mock_remote = MagicMock()
        mock_remote.get_vm_status.return_value = {
            "name": "test-vm",
            "state": "running",
            "uuid": "1234",
            "memory": 2048,
            "vcpus": 2,
            "disk_size": 20,
            "ip": "192.168.1.100",
            "uptime": "2h 30m"
        }
        mock_remote_cls.return_value = mock_remote

        args = argparse.Namespace(
            host="user@server",
            vm_name="test-vm",
            user=False,
            json=False,
            logs=False,
        )

        cmd_remote_status(args)
        mock_remote.get_vm_status.assert_called_once()

    @patch("clonebox.cli.remote_commands.RemoteCloner")
    def test_cmd_remote_start(self, mock_remote_cls):
        """Test remote start command."""
        from clonebox.cli import cmd_remote_start

        mock_remote = MagicMock()
        mock_remote_cls.return_value = mock_remote

        args = argparse.Namespace(
            host="user@server",
            vm_name="test-vm",
            user=False,
            viewer=False,
        )

        cmd_remote_start(args)
        mock_remote.start_vm.assert_called_once_with("test-vm", open_viewer=False, console=ANY)

    @patch("clonebox.cli.remote_commands.RemoteCloner")
    def test_cmd_remote_stop(self, mock_remote_cls):
        """Test remote stop command."""
        from clonebox.cli import cmd_remote_stop

        mock_remote = MagicMock()
        mock_remote_cls.return_value = mock_remote

        args = argparse.Namespace(
            host="user@server",
            vm_name="test-vm",
            user=False,
            force=False,
        )

        cmd_remote_stop(args)
        mock_remote.stop_vm.assert_called_once_with("test-vm", force=False, console=ANY)

    @patch("clonebox.cli.remote_commands.RemoteCloner")
    def test_cmd_remote_exec(self, mock_remote_cls):
        """Test remote exec command."""
        from clonebox.cli import cmd_remote_exec

        mock_remote = MagicMock()
        mock_remote.exec_in_vm.return_value = "output"
        mock_remote_cls.return_value = mock_remote

        args = argparse.Namespace(
            host="user@server",
            vm_name="test-vm",
            command=["echo", "hello"],
            user=False,
            timeout=30,
        )

        cmd_remote_exec(args)
        mock_remote.exec_in_vm.assert_called_once_with("test-vm", ["echo", "hello"], timeout=30)

    @patch("clonebox.cli.remote_commands.RemoteCloner")
    def test_cmd_remote_health(self, mock_remote_cls):
        """Test remote health command."""
        from clonebox.cli import cmd_remote_health

        mock_remote = MagicMock()
        mock_remote.health_check.return_value = {"passed": True, "output": "OK"}
        mock_remote_cls.return_value = mock_remote

        args = argparse.Namespace(
            host="user@server",
            vm_name="test-vm",
            user=False,
        )

        cmd_remote_health(args)
        mock_remote.health_check.assert_called_once()

    @patch("clonebox.cli.remote_commands.RemoteCloner")
    def test_cmd_remote_connection_error(self, mock_remote_cls):
        """Test remote command with connection error."""
        from clonebox.cli import cmd_remote_list

        mock_remote_cls.side_effect = ConnectionError("Cannot connect")

        args = argparse.Namespace(host="user@server", user=False, json=False)

        # Should not raise, just print error
        cmd_remote_list(args)


class TestLogsCommands:
    """Test logs CLI commands."""

    @patch("subprocess.run")
    def test_cmd_logs(self, mock_run):
        """Test logs command."""
        from clonebox.cli import cmd_logs

        mock_run.return_value = MagicMock(returncode=0)

        args = argparse.Namespace(
            name="test-vm",
            user=False,
            all=False,
        )

        cmd_logs(args)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "scripts/clonebox-logs.sh" in " ".join(call_args)

    @patch("subprocess.run")
    def test_cmd_logs_with_all_flag(self, mock_run):
        """Test logs command with --all flag."""
        from clonebox.cli import cmd_logs

        mock_run.return_value = MagicMock(returncode=0)

        args = argparse.Namespace(
            name="test-vm",
            user=True,
            all=True,
        )

        cmd_logs(args)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "scripts/clonebox-logs.sh" in " ".join(call_args)
        assert "true" in call_args  # user session flag
        assert "true" in call_args  # all flag


class TestSetPasswordCommands:
    """Test set-password CLI commands."""

    @patch("subprocess.run")
    def test_cmd_set_password(self, mock_run):
        """Test set-password command."""
        from clonebox.cli import cmd_set_password

        mock_run.return_value = MagicMock(returncode=0)

        args = argparse.Namespace(
            name="test-vm",
            user=False,
        )

        cmd_set_password(args)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "scripts/set-vm-password.sh" in " ".join(call_args)

    @patch("subprocess.run")
    def test_cmd_set_password_user_session(self, mock_run):
        """Test set-password command with user session."""
        from clonebox.cli import cmd_set_password

        mock_run.return_value = MagicMock(returncode=0)

        args = argparse.Namespace(
            name="test-vm",
            user=True,
        )

        cmd_set_password(args)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "scripts/set-vm-password.sh" in " ".join(call_args)
        assert "true" in call_args  # user session flag
