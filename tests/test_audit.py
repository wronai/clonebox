"""Tests for audit logging module."""
import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from clonebox.audit import (
    AuditEvent,
    AuditEventType,
    AuditLogger,
    AuditOutcome,
    AuditQuery,
    AuditContext,
    get_audit_logger,
    set_audit_logger,
)


class TestAuditEvent:
    """Test AuditEvent dataclass."""

    def test_create_event(self):
        """Test creating an audit event."""
        event = AuditEvent(
            event_type=AuditEventType.VM_CREATE,
            timestamp=datetime.now(),
            outcome=AuditOutcome.SUCCESS,
            user="testuser",
            hostname="testhost",
            pid=1234,
            target_type="vm",
            target_name="test-vm",
        )

        assert event.event_type == AuditEventType.VM_CREATE
        assert event.outcome == AuditOutcome.SUCCESS
        assert event.user == "testuser"
        assert event.target_name == "test-vm"
        assert event.event_id  # Should be auto-generated

    def test_event_to_dict(self):
        """Test converting event to dictionary."""
        event = AuditEvent(
            event_type=AuditEventType.VM_START,
            timestamp=datetime(2026, 1, 15, 10, 30, 0),
            outcome=AuditOutcome.SUCCESS,
            user="testuser",
            hostname="testhost",
            pid=1234,
        )

        d = event.to_dict()
        assert d["event_type"] == "vm.start"
        assert d["outcome"] == "success"
        assert d["actor"]["user"] == "testuser"
        assert d["actor"]["hostname"] == "testhost"

    def test_event_to_json(self):
        """Test converting event to JSON."""
        event = AuditEvent(
            event_type=AuditEventType.VM_STOP,
            timestamp=datetime.now(),
            outcome=AuditOutcome.FAILURE,
            user="testuser",
            hostname="testhost",
            pid=1234,
            error_message="Test error",
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)
        assert parsed["event_type"] == "vm.stop"
        assert parsed["outcome"] == "failure"
        assert parsed["error_message"] == "Test error"

    def test_event_from_dict(self):
        """Test creating event from dictionary."""
        data = {
            "event_id": "abc123",
            "event_type": "vm.create",
            "timestamp": "2026-01-15T10:30:00",
            "outcome": "success",
            "actor": {"user": "testuser", "hostname": "testhost", "pid": 1234},
            "target": {"type": "vm", "name": "test-vm"},
            "details": {"ram_mb": 4096},
        }

        event = AuditEvent.from_dict(data)
        assert event.event_type == AuditEventType.VM_CREATE
        assert event.outcome == AuditOutcome.SUCCESS
        assert event.target_name == "test-vm"
        assert event.details["ram_mb"] == 4096


class TestAuditLogger:
    """Test AuditLogger class."""

    def test_logger_init(self, tmp_path):
        """Test logger initialization."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_path, enabled=True)

        assert logger.log_path == log_path
        assert logger.enabled is True

    def test_log_event(self, tmp_path):
        """Test logging an event."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_path, enabled=True)

        event = logger.log(
            event_type=AuditEventType.VM_CREATE,
            outcome=AuditOutcome.SUCCESS,
            target_type="vm",
            target_name="test-vm",
            details={"ram_mb": 4096},
        )

        assert event.event_type == AuditEventType.VM_CREATE
        assert log_path.exists()

        # Verify log content
        with open(log_path) as f:
            line = f.readline()
            parsed = json.loads(line)
            assert parsed["event_type"] == "vm.create"
            assert parsed["target"]["name"] == "test-vm"

    def test_log_disabled(self, tmp_path):
        """Test that disabled logger doesn't write."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_path, enabled=False)

        logger.log(
            event_type=AuditEventType.VM_CREATE,
            outcome=AuditOutcome.SUCCESS,
        )

        assert not log_path.exists()

    def test_operation_context_success(self, tmp_path):
        """Test operation context manager on success."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_path, enabled=True)

        with logger.operation(
            AuditEventType.VM_CREATE,
            target_type="vm",
            target_name="test-vm",
        ) as ctx:
            ctx.add_detail("ram_mb", 4096)
            # Operation succeeds

        with open(log_path) as f:
            parsed = json.loads(f.readline())
            assert parsed["outcome"] == "success"
            assert parsed["details"]["ram_mb"] == 4096

    def test_operation_context_failure(self, tmp_path):
        """Test operation context manager on failure."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_path, enabled=True)

        with pytest.raises(ValueError):
            with logger.operation(
                AuditEventType.VM_CREATE,
                target_type="vm",
                target_name="test-vm",
            ) as ctx:
                raise ValueError("Test error")

        with open(log_path) as f:
            parsed = json.loads(f.readline())
            assert parsed["outcome"] == "failure"
            assert "Test error" in parsed["error_message"]

    def test_correlation_id(self, tmp_path):
        """Test correlation ID propagation."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_path, enabled=True)

        logger.set_correlation_id("corr-123")
        logger.log(AuditEventType.VM_CREATE, AuditOutcome.SUCCESS)

        with open(log_path) as f:
            parsed = json.loads(f.readline())
            assert parsed["correlation_id"] == "corr-123"

        logger.clear_correlation_id()
        logger.log(AuditEventType.VM_START, AuditOutcome.SUCCESS)

        with open(log_path) as f:
            f.readline()  # Skip first
            parsed = json.loads(f.readline())
            assert parsed["correlation_id"] is None


class TestAuditQuery:
    """Test AuditQuery class."""

    @pytest.fixture
    def populated_log(self, tmp_path):
        """Create a populated audit log."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=log_path, enabled=True)

        # Log various events
        logger.log(AuditEventType.VM_CREATE, AuditOutcome.SUCCESS, target_type="vm", target_name="vm1")
        logger.log(AuditEventType.VM_START, AuditOutcome.SUCCESS, target_type="vm", target_name="vm1")
        logger.log(AuditEventType.VM_CREATE, AuditOutcome.FAILURE, target_type="vm", target_name="vm2", error_message="Error")
        logger.log(AuditEventType.VM_STOP, AuditOutcome.SUCCESS, target_type="vm", target_name="vm1")

        return log_path

    def test_query_all(self, populated_log):
        """Test querying all events."""
        query = AuditQuery(log_path=populated_log)
        events = query.query()

        assert len(events) == 4

    def test_query_by_type(self, populated_log):
        """Test querying by event type."""
        query = AuditQuery(log_path=populated_log)
        events = query.query(event_type=AuditEventType.VM_CREATE)

        assert len(events) == 2
        assert all(e.event_type == AuditEventType.VM_CREATE for e in events)

    def test_query_by_target(self, populated_log):
        """Test querying by target name."""
        query = AuditQuery(log_path=populated_log)
        events = query.query(target_name="vm1")

        assert len(events) == 3

    def test_query_by_outcome(self, populated_log):
        """Test querying by outcome."""
        query = AuditQuery(log_path=populated_log)
        events = query.query(outcome=AuditOutcome.FAILURE)

        assert len(events) == 1
        assert events[0].target_name == "vm2"

    def test_get_failures(self, populated_log):
        """Test getting failures."""
        query = AuditQuery(log_path=populated_log)
        failures = query.get_failures()

        assert len(failures) == 1
        assert failures[0].error_message == "Error"

    def test_query_limit(self, populated_log):
        """Test query limit."""
        query = AuditQuery(log_path=populated_log)
        events = query.query(limit=2)

        assert len(events) == 2


class TestAuditContext:
    """Test AuditContext class."""

    def test_add_detail(self):
        """Test adding details to context."""
        ctx = AuditContext(
            _logger=None,
            _event_type=AuditEventType.VM_CREATE,
            _target_type="vm",
            _target_name="test-vm",
        )

        ctx.add_detail("ram_mb", 4096)
        ctx.add_detail("vcpus", 4)

        assert ctx._details["ram_mb"] == 4096
        assert ctx._details["vcpus"] == 4

    def test_set_error(self):
        """Test setting error."""
        ctx = AuditContext(
            _logger=None,
            _event_type=AuditEventType.VM_CREATE,
            _target_type="vm",
            _target_name="test-vm",
        )

        ctx.set_error("Something went wrong")

        assert ctx._error == "Something went wrong"
        assert ctx._outcome == AuditOutcome.FAILURE


class TestGlobalLogger:
    """Test global logger functions."""

    def test_get_audit_logger(self):
        """Test getting global logger."""
        logger = get_audit_logger()
        assert isinstance(logger, AuditLogger)

    def test_set_audit_logger(self, tmp_path):
        """Test setting global logger."""
        log_path = tmp_path / "custom.log"
        custom_logger = AuditLogger(log_path=log_path)

        set_audit_logger(custom_logger)
        logger = get_audit_logger()

        assert logger.log_path == log_path
