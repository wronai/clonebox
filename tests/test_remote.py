"""Tests for remote VM management module."""
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from clonebox.remote import (
    RemoteCloner,
    RemoteConnection,
    RemoteCommandResult,
    connect,
)


class TestRemoteConnection:
    """Test RemoteConnection dataclass."""

    def test_from_simple_host(self):
        """Test parsing simple user@host connection."""
        conn = RemoteConnection.from_string("user@server")

        assert conn.ssh_user == "user"
        assert conn.ssh_host == "server"
        assert conn.ssh_port == 22
        assert "qemu+ssh://user@server/system" in conn.uri

    def test_from_host_with_port(self):
        """Test parsing user@host:port connection."""
        conn = RemoteConnection.from_string("admin@server:2222")

        assert conn.ssh_user == "admin"
        assert conn.ssh_host == "server"
        assert conn.ssh_port == 2222

    def test_from_qemu_uri(self):
        """Test parsing qemu+ssh URI."""
        conn = RemoteConnection.from_string("qemu+ssh://user@remote.host/system")

        assert conn.uri == "qemu+ssh://user@remote.host/system"
        assert conn.ssh_user == "user"
        assert conn.ssh_host == "remote.host"

    def test_from_host_only(self):
        """Test parsing host-only connection."""
        conn = RemoteConnection.from_string("myserver")

        assert conn.ssh_host == "myserver"
        assert conn.ssh_user is None
        assert conn.ssh_port == 22

    def test_get_ssh_target(self):
        """Test getting SSH target string."""
        conn = RemoteConnection.from_string("user@server")
        assert conn.get_ssh_target() == "user@server"

        conn = RemoteConnection.from_string("server")
        assert conn.get_ssh_target() == "server"

    def test_get_libvirt_uri(self):
        """Test getting libvirt URI."""
        conn = RemoteConnection.from_string("user@server")
        uri = conn.get_libvirt_uri()

        assert "qemu+ssh" in uri
        assert "user@server" in uri


class TestRemoteCommandResult:
    """Test RemoteCommandResult dataclass."""

    def test_successful_result(self):
        """Test successful command result."""
        result = RemoteCommandResult(
            success=True,
            stdout="output",
            stderr="",
            returncode=0,
        )

        assert result.success is True
        assert result.returncode == 0

    def test_failed_result(self):
        """Test failed command result."""
        result = RemoteCommandResult(
            success=False,
            stdout="",
            stderr="error message",
            returncode=1,
        )

        assert result.success is False
        assert result.stderr == "error message"


class TestRemoteCloner:
    """Test RemoteCloner class."""

    @pytest.fixture
    def mock_subprocess(self):
        """Mock subprocess.run for SSH commands."""
        with patch("clonebox.remote.subprocess.run") as mock:
            # Default successful response
            mock.return_value = MagicMock(
                returncode=0,
                stdout="ok",
                stderr="",
            )
            yield mock

    def test_init_with_string(self, mock_subprocess):
        """Test initializing with connection string."""
        remote = RemoteCloner("user@server", verify=False)

        assert remote.connection.ssh_user == "user"
        assert remote.connection.ssh_host == "server"

    def test_init_with_connection(self, mock_subprocess):
        """Test initializing with RemoteConnection."""
        conn = RemoteConnection.from_string("admin@host")
        remote = RemoteCloner(conn, verify=False)

        assert remote.connection == conn

    def test_verify_connection_success(self, mock_subprocess):
        """Test successful connection verification."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "ok"

        # Should not raise
        remote = RemoteCloner("user@server", verify=True)
        assert remote is not None

    def test_verify_connection_failure(self, mock_subprocess):
        """Test failed connection verification."""
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stderr = "Connection refused"

        with pytest.raises(ConnectionError):
            RemoteCloner("user@server", verify=True)

    def test_build_ssh_command(self, mock_subprocess):
        """Test building SSH command."""
        remote = RemoteCloner("user@server", verify=False)
        cmd = remote._build_ssh_command()

        assert "ssh" in cmd
        assert "user@server" in cmd
        assert "-o" in cmd

    def test_build_ssh_command_with_key(self, mock_subprocess):
        """Test building SSH command with key."""
        remote = RemoteCloner("user@server", ssh_key=Path("/path/to/key"), verify=False)
        cmd = remote._build_ssh_command()

        assert "-i" in cmd
        assert "/path/to/key" in cmd

    def test_build_ssh_command_with_port(self, mock_subprocess):
        """Test building SSH command with custom port."""
        remote = RemoteCloner("user@server:2222", verify=False)
        cmd = remote._build_ssh_command()

        assert "-p" in cmd
        assert "2222" in cmd

    def test_run_remote(self, mock_subprocess):
        """Test running remote command."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "output"
        mock_subprocess.return_value.stderr = ""

        remote = RemoteCloner("user@server", verify=False)
        result = remote._run_remote(["echo", "test"])

        assert result.success is True
        assert result.stdout == "output"

    def test_run_remote_timeout(self, mock_subprocess):
        """Test remote command timeout."""
        import subprocess
        mock_subprocess.side_effect = subprocess.TimeoutExpired("ssh", 30)

        remote = RemoteCloner("user@server", verify=False)
        result = remote._run_remote(["slow", "command"], timeout=30)

        assert result.success is False
        assert "timed out" in result.stderr.lower()

    def test_is_clonebox_installed(self, mock_subprocess):
        """Test checking if CloneBox is installed."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "/usr/bin/clonebox"

        remote = RemoteCloner("user@server", verify=False)
        assert remote.is_clonebox_installed() is True

        mock_subprocess.return_value.returncode = 1
        assert remote.is_clonebox_installed() is False

    def test_get_clonebox_version(self, mock_subprocess):
        """Test getting CloneBox version."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "clonebox 1.2.3\n"

        remote = RemoteCloner("user@server", verify=False)
        version = remote.get_clonebox_version()

        assert version == "clonebox 1.2.3"

    def test_list_vms(self, mock_subprocess):
        """Test listing VMs."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = '[{"name": "vm1"}, {"name": "vm2"}]'

        remote = RemoteCloner("user@server", verify=False)
        vms = remote.list_vms()

        assert len(vms) == 2
        assert vms[0]["name"] == "vm1"

    def test_list_vms_non_json(self, mock_subprocess):
        """Test listing VMs with non-JSON output."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "vm1\nvm2\nvm3"

        remote = RemoteCloner("user@server", verify=False)
        vms = remote.list_vms()

        assert len(vms) == 3

    def test_start_vm(self, mock_subprocess):
        """Test starting VM."""
        mock_subprocess.return_value.returncode = 0

        remote = RemoteCloner("user@server", verify=False)
        remote.start_vm("test-vm")  # Should not raise

        # Verify command was called
        call_args = mock_subprocess.call_args[0][0]
        assert "clonebox" in call_args
        assert "start" in call_args
        assert "test-vm" in call_args

    def test_stop_vm(self, mock_subprocess):
        """Test stopping VM."""
        mock_subprocess.return_value.returncode = 0

        remote = RemoteCloner("user@server", verify=False)
        remote.stop_vm("test-vm")

        call_args = mock_subprocess.call_args[0][0]
        assert "stop" in call_args

    def test_stop_vm_force(self, mock_subprocess):
        """Test force stopping VM."""
        mock_subprocess.return_value.returncode = 0

        remote = RemoteCloner("user@server", verify=False)
        remote.stop_vm("test-vm", force=True)

        call_args = mock_subprocess.call_args[0][0]
        assert "--force" in call_args

    def test_delete_vm(self, mock_subprocess):
        """Test deleting VM."""
        mock_subprocess.return_value.returncode = 0

        remote = RemoteCloner("user@server", verify=False)
        remote.delete_vm("test-vm")

        call_args = mock_subprocess.call_args[0][0]
        assert "delete" in call_args
        assert "--yes" in call_args

    def test_restart_vm(self, mock_subprocess):
        """Test restarting VM."""
        mock_subprocess.return_value.returncode = 0

        remote = RemoteCloner("user@server", verify=False)
        remote.restart_vm("test-vm")

        call_args = mock_subprocess.call_args[0][0]
        assert "restart" in call_args

    def test_get_status(self, mock_subprocess):
        """Test getting VM status."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = '{"state": "running"}'

        remote = RemoteCloner("user@server", verify=False)
        status = remote.get_status("test-vm")

        assert status["state"] == "running"

    def test_exec_in_vm(self, mock_subprocess):
        """Test executing command in VM."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "command output"

        remote = RemoteCloner("user@server", verify=False)
        output = remote.exec_in_vm("test-vm", "echo hello")

        assert output == "command output"

    def test_health_check(self, mock_subprocess):
        """Test running health check."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "Health check passed"

        remote = RemoteCloner("user@server", verify=False)
        result = remote.health_check("test-vm")

        assert result["success"] is True
        assert "Health check passed" in result["output"]

    def test_snapshot_create(self, mock_subprocess):
        """Test creating snapshot."""
        mock_subprocess.return_value.returncode = 0

        remote = RemoteCloner("user@server", verify=False)
        remote.snapshot_create("test-vm", "snap1", description="Test snapshot")

        call_args = mock_subprocess.call_args[0][0]
        assert "snapshot" in call_args
        assert "create" in call_args
        assert "--name" in call_args
        assert "snap1" in call_args

    def test_snapshot_restore(self, mock_subprocess):
        """Test restoring snapshot."""
        mock_subprocess.return_value.returncode = 0

        remote = RemoteCloner("user@server", verify=False)
        remote.snapshot_restore("test-vm", "snap1")

        call_args = mock_subprocess.call_args[0][0]
        assert "restore" in call_args

    def test_snapshot_list(self, mock_subprocess):
        """Test listing snapshots."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "snap1\nsnap2"

        remote = RemoteCloner("user@server", verify=False)
        snaps = remote.snapshot_list("test-vm")

        assert len(snaps) == 2

    def test_user_session_flag(self, mock_subprocess):
        """Test user session flag propagation."""
        mock_subprocess.return_value.returncode = 0

        remote = RemoteCloner("user@server", verify=False)
        remote.list_vms(user_session=True)

        call_args = mock_subprocess.call_args[0][0]
        assert "--user" in call_args

    def test_error_handling(self, mock_subprocess):
        """Test error handling for failed commands."""
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stderr = "VM not found"

        remote = RemoteCloner("user@server", verify=False)

        with pytest.raises(RuntimeError, match="Failed"):
            remote.start_vm("nonexistent-vm")


class TestConnectFunction:
    """Test the connect() convenience function."""

    def test_connect(self):
        """Test connect function creates RemoteCloner."""
        with patch("clonebox.remote.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

            remote = connect("user@server")
            assert isinstance(remote, RemoteCloner)

    def test_connect_with_kwargs(self):
        """Test connect function with extra kwargs."""
        with patch("clonebox.remote.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

            remote = connect("user@server", ssh_key=Path("/key"), verify=False)
            assert remote.connection.ssh_key == Path("/key")
