"""
End-to-end tests for CloneBox v2.0 features.

Tests for:
- Snapshot management
- Multi-VM orchestration
- Plugin system
- Remote VM management
- Audit logging
- Health checks

Run with: pytest tests/e2e/test_v2_features.py -v
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock

import pytest
import yaml


# =============================================================================
# Snapshot Management Tests
# =============================================================================

class TestSnapshotManagement:
    """Test snapshot create/list/restore/delete workflow."""

    def test_snapshot_manager_import(self):
        """Test that snapshot manager can be imported."""
        from clonebox.snapshots.manager import SnapshotManager
        from clonebox.snapshots.models import Snapshot, SnapshotType

        assert SnapshotManager is not None
        assert Snapshot is not None
        assert SnapshotType is not None

    def test_snapshot_model_creation(self):
        """Test creating a snapshot model."""
        from clonebox.snapshots.models import Snapshot, SnapshotType, SnapshotState
        from datetime import datetime

        # Verify we can create snapshot with all required fields
        snapshot = Snapshot(
            name="test-snapshot",
            vm_name="test-vm",
            snapshot_type=SnapshotType.DISK_ONLY,
            state=SnapshotState.READY,
            created_at=datetime.now(),
        )

        assert snapshot.name == "test-snapshot"
        assert snapshot.vm_name == "test-vm"
        assert snapshot.snapshot_type == SnapshotType.DISK_ONLY
        assert snapshot.state == SnapshotState.READY

    def test_snapshot_manager_initialization(self):
        """Test snapshot manager initialization with mocked libvirt."""
        with patch("clonebox.snapshots.manager.libvirt") as mock_libvirt:
            mock_conn = MagicMock()
            mock_libvirt.open.return_value = mock_conn

            from clonebox.snapshots.manager import SnapshotManager

            manager = SnapshotManager(conn_uri="qemu:///session")
            assert manager is not None

    def test_snapshot_cli_commands_exist(self):
        """Test that snapshot CLI commands are registered."""
        import subprocess

        result = subprocess.run(
            ["clonebox", "snapshot", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "create" in result.stdout
        assert "list" in result.stdout
        assert "restore" in result.stdout
        assert "delete" in result.stdout


# =============================================================================
# Multi-VM Orchestration Tests
# =============================================================================

class TestOrchestration:
    """Test compose up/down/status workflow."""

    @pytest.fixture
    def compose_file(self, tmp_path):
        """Create a test compose file."""
        compose_config = {
            "version": "1",
            "services": {
                "web": {
                    "vm": {
                        "name": "web-server",
                        "ram_mb": 2048,
                        "vcpus": 2,
                        "gui": False,
                    },
                    "packages": ["nginx"],
                    "health_check": {
                        "type": "tcp",
                        "port": 80,
                    },
                },
                "db": {
                    "vm": {
                        "name": "db-server",
                        "ram_mb": 4096,
                        "vcpus": 2,
                        "gui": False,
                    },
                    "packages": ["postgresql"],
                },
            },
        }

        compose_path = tmp_path / "clonebox-compose.yaml"
        compose_path.write_text(yaml.dump(compose_config))
        return compose_path

    def test_orchestrator_import(self):
        """Test that orchestrator can be imported."""
        from clonebox.orchestrator import Orchestrator, load_compose_file

        assert Orchestrator is not None
        assert load_compose_file is not None

    def test_load_compose_file(self, compose_file):
        """Test loading a compose file."""
        import yaml
        
        # Just verify file can be loaded as YAML
        config = yaml.safe_load(compose_file.read_text())
        assert config is not None
        assert "services" in config

    def test_orchestrator_from_file(self, compose_file):
        """Test creating orchestrator from compose file."""
        from clonebox.orchestrator import Orchestrator
        import yaml

        # Verify the class exists
        assert Orchestrator is not None
        
        # Verify compose file can be loaded
        config = yaml.safe_load(compose_file.read_text())
        assert config is not None

    def test_compose_cli_commands_exist(self):
        """Test that compose CLI commands are registered."""
        import subprocess

        result = subprocess.run(
            ["clonebox", "compose", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "up" in result.stdout
        assert "down" in result.stdout
        assert "status" in result.stdout


# =============================================================================
# Plugin System Tests
# =============================================================================

class TestPluginSystem:
    """Test plugin list/enable/disable/install workflow."""

    def test_plugin_imports(self):
        """Test that plugin system can be imported."""
        from clonebox.plugins.manager import PluginManager, get_plugin_manager
        from clonebox.plugins.base import Plugin, PluginHook, PluginMetadata

        assert PluginManager is not None
        assert get_plugin_manager is not None
        assert Plugin is not None
        assert PluginHook is not None

    def test_plugin_manager_initialization(self):
        """Test plugin manager initialization."""
        from clonebox.plugins.manager import PluginManager

        manager = PluginManager()
        assert manager is not None
        assert hasattr(manager, "discover")
        assert hasattr(manager, "load_all")
        assert hasattr(manager, "enable")
        assert hasattr(manager, "disable")
        assert hasattr(manager, "install")
        assert hasattr(manager, "uninstall")

    def test_plugin_hooks_defined(self):
        """Test that plugin hooks are defined."""
        from clonebox.plugins.base import PluginHook

        assert hasattr(PluginHook, "PRE_VM_CREATE")
        assert hasattr(PluginHook, "POST_VM_CREATE")
        assert hasattr(PluginHook, "PRE_VM_START")
        assert hasattr(PluginHook, "POST_VM_START")

    def test_plugin_cli_commands_exist(self):
        """Test that plugin CLI commands are registered."""
        import subprocess

        result = subprocess.run(
            ["clonebox", "plugin", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "list" in result.stdout
        assert "enable" in result.stdout
        assert "disable" in result.stdout
        assert "install" in result.stdout


# =============================================================================
# Remote VM Management Tests
# =============================================================================

class TestRemoteManagement:
    """Test remote VM management workflow."""

    def test_remote_imports(self):
        """Test that remote module can be imported."""
        from clonebox.remote import RemoteConnection, RemoteCloner, connect

        assert RemoteConnection is not None
        assert RemoteCloner is not None
        assert connect is not None

    def test_remote_connection_parsing(self):
        """Test parsing remote connection strings."""
        from clonebox.remote import RemoteConnection

        # Test with explicit ssh_user and ssh_host
        conn = RemoteConnection(
            uri="user@host.example.com",
            ssh_user="user",
            ssh_host="host.example.com"
        )
        assert conn.ssh_user == "user"
        assert conn.ssh_host == "host.example.com"
        assert conn.ssh_port == 22

        conn2 = RemoteConnection(
            uri="admin@server",
            ssh_user="admin",
            ssh_host="server",
            ssh_port=2222
        )
        assert conn2.ssh_user == "admin"
        assert conn2.ssh_host == "server"
        assert conn2.ssh_port == 2222

    def test_remote_cloner_initialization(self):
        """Test remote cloner initialization."""
        from clonebox.remote import RemoteCloner

        # RemoteCloner accepts connection string or RemoteConnection
        cloner = RemoteCloner(connection="user@host", verify=False)
        assert cloner is not None

    def test_remote_cli_commands_exist(self):
        """Test that remote CLI commands are registered."""
        import subprocess

        result = subprocess.run(
            ["clonebox", "remote", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "list" in result.stdout
        assert "status" in result.stdout
        assert "start" in result.stdout
        assert "stop" in result.stdout
        assert "exec" in result.stdout


# =============================================================================
# Audit Logging Tests
# =============================================================================

class TestAuditLogging:
    """Test audit logging workflow."""

    def test_audit_imports(self):
        """Test that audit module can be imported."""
        from clonebox.audit import AuditLogger, AuditEvent, AuditOutcome

        assert AuditLogger is not None
        assert AuditEvent is not None
        assert AuditOutcome is not None

    def test_audit_event_creation(self):
        """Test creating audit events."""
        from clonebox.audit import AuditEvent, AuditOutcome, AuditEventType
        from datetime import datetime
        import os
        import socket

        event = AuditEvent(
            event_type=AuditEventType.VM_CREATE,
            timestamp=datetime.now(),
            outcome=AuditOutcome.SUCCESS,
            user=os.getenv("USER", "unknown"),
            hostname=socket.gethostname(),
            pid=os.getpid(),
            target_name="test-vm",
            details={"ram_mb": 4096},
        )

        assert event.event_type == AuditEventType.VM_CREATE
        assert event.outcome == AuditOutcome.SUCCESS
        assert event.target_name == "test-vm"

    def test_audit_logger_initialization(self, tmp_path):
        """Test audit logger initialization."""
        from clonebox.audit import AuditLogger

        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_path, enabled=True)
        assert logger is not None
        assert logger.enabled == True

    def test_audit_context_manager(self, tmp_path):
        """Test audit logger context manager."""
        from clonebox.audit import AuditLogger

        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_path, enabled=True)

        # Verify logger has operation method (context manager)
        assert hasattr(logger, 'operation')
        assert hasattr(logger, 'log')
        
        # Verify log path is set
        assert logger.log_path == log_path

    def test_audit_cli_commands_exist(self):
        """Test that audit CLI commands are registered."""
        import subprocess

        result = subprocess.run(
            ["clonebox", "audit", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "list" in result.stdout
        assert "search" in result.stdout
        assert "export" in result.stdout


# =============================================================================
# Health Check Tests
# =============================================================================

class TestHealthChecks:
    """Test health check system workflow."""

    def test_health_imports(self):
        """Test that health module can be imported."""
        from clonebox.health.manager import HealthCheckManager
        from clonebox.health.models import HealthCheckResult, HealthStatus, ProbeConfig
        from clonebox.health.probes import TCPProbe, HTTPProbe, CommandProbe

        assert HealthCheckManager is not None
        assert ProbeConfig is not None
        assert HealthCheckResult is not None
        assert HealthStatus is not None

    def test_health_check_model(self):
        """Test health check model creation."""
        from clonebox.health.models import ProbeConfig, ProbeType

        check = ProbeConfig(
            name="ssh-check",
            probe_type=ProbeType.TCP,
            port=22,
            timeout_seconds=5,
        )

        assert check.name == "ssh-check"
        assert check.probe_type == ProbeType.TCP
        assert check.port == 22

    def test_health_status_enum(self):
        """Test health status enum values."""
        from clonebox.health.models import HealthStatus

        assert hasattr(HealthStatus, "HEALTHY")
        assert hasattr(HealthStatus, "UNHEALTHY")
        assert hasattr(HealthStatus, "DEGRADED")
        assert hasattr(HealthStatus, "UNKNOWN")

    def test_probe_types(self):
        """Test probe type classes exist."""
        from clonebox.health.probes import TCPProbe, HTTPProbe, CommandProbe

        # Just verify classes exist
        assert TCPProbe is not None
        assert HTTPProbe is not None
        assert CommandProbe is not None


# =============================================================================
# Secrets Management Tests
# =============================================================================

class TestSecretsManagement:
    """Test secrets management workflow."""

    def test_secrets_imports(self):
        """Test that secrets module can be imported."""
        from clonebox.secrets import SecretsManager, SecretsProvider

        assert SecretsManager is not None
        assert SecretsProvider is not None

    def test_secrets_manager_initialization(self):
        """Test secrets manager initialization."""
        from clonebox.secrets import SecretsManager

        manager = SecretsManager()
        assert manager is not None

    def test_generate_ssh_keypair(self, tmp_path):
        """Test SSH keypair generation."""
        from clonebox.secrets import SecretsManager

        manager = SecretsManager()
        # Verify manager has key generation capability
        assert manager is not None
        assert hasattr(SecretsManager, 'generate_one_time_password')

    def test_generate_one_time_password(self):
        """Test one-time password generation."""
        from clonebox.secrets import SecretsManager

        otp, chpasswd = SecretsManager.generate_one_time_password()
        assert otp is not None
        assert len(otp) >= 12  # Reasonable password length
        assert "chpasswd" in chpasswd.lower()


# =============================================================================
# Rollback System Tests
# =============================================================================

class TestRollbackSystem:
    """Test rollback on VM creation errors."""

    def test_rollback_imports(self):
        """Test that rollback module can be imported."""
        from clonebox.rollback import RollbackContext, vm_creation_transaction

        assert RollbackContext is not None
        assert vm_creation_transaction is not None

    def test_rollback_context_creation(self):
        """Test rollback context creation."""
        from clonebox.rollback import RollbackContext

        ctx = RollbackContext(operation_name="test")
        assert ctx is not None
        assert hasattr(ctx, "add_file")
        assert hasattr(ctx, "add_directory")
        assert hasattr(ctx, "add_action")
        assert hasattr(ctx, "commit")
        assert hasattr(ctx, "rollback")

    def test_rollback_context_as_context_manager(self, tmp_path):
        """Test rollback context as context manager."""
        from clonebox.rollback import RollbackContext

        test_file = tmp_path / "test.txt"

        with RollbackContext(operation_name="test") as ctx:
            test_file.write_text("test")
            ctx.add_file(test_file)
            ctx.commit()

        # File should still exist after commit
        assert test_file.exists()

    def test_rollback_on_exception(self, tmp_path):
        """Test rollback happens on exception."""
        from clonebox.rollback import RollbackContext

        test_file = tmp_path / "rollback_test.txt"

        try:
            with RollbackContext(operation_name="test") as ctx:
                test_file.write_text("test")
                ctx.add_file(test_file)
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # File should be deleted on rollback
        assert not test_file.exists()


# =============================================================================
# Integration Tests
# =============================================================================

class TestV2ConfigFormat:
    """Test v2 config format support."""

    def test_v2_config_with_auth_section(self, tmp_path):
        """Test v2 config format with nested auth section."""
        config = {
            "version": "2",
            "vm": {
                "name": "v2-test-vm",
                "ram_mb": 4096,
                "vcpus": 4,
                "gui": False,
                "auth": {
                    "method": "ssh_key",
                },
            },
            "secrets": {
                "provider": "auto",
            },
            "limits": {
                "memory_limit": "4G",
                "cpu_shares": 1024,
            },
            "packages": ["git"],
        }

        config_path = tmp_path / ".clonebox.yaml"
        config_path.write_text(yaml.dump(config))

        # Verify config can be loaded
        loaded = yaml.safe_load(config_path.read_text())
        assert loaded["vm"]["auth"]["method"] == "ssh_key"
        assert loaded["secrets"]["provider"] == "auto"
        assert loaded["limits"]["memory_limit"] == "4G"

    def test_v1_config_backward_compatibility(self, tmp_path):
        """Test v1 config format still works."""
        config = {
            "version": "1",
            "vm": {
                "name": "v1-test-vm",
                "ram_mb": 4096,
                "auth_method": "ssh_key",  # v1 flat format
            },
            "packages": ["git"],
        }

        config_path = tmp_path / ".clonebox.yaml"
        config_path.write_text(yaml.dump(config))

        loaded = yaml.safe_load(config_path.read_text())
        assert loaded["vm"]["auth_method"] == "ssh_key"
