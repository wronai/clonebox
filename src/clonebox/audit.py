"""
Audit logging for CloneBox operations.
Records all significant actions for compliance and debugging.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, Generator
import json
import os
import threading
import hashlib


class AuditEventType(Enum):
    """Types of auditable events."""
    # VM Operations
    VM_CREATE = "vm.create"
    VM_START = "vm.start"
    VM_STOP = "vm.stop"
    VM_DELETE = "vm.delete"
    VM_RESTART = "vm.restart"
    VM_SNAPSHOT_CREATE = "vm.snapshot.create"
    VM_SNAPSHOT_RESTORE = "vm.snapshot.restore"
    VM_SNAPSHOT_DELETE = "vm.snapshot.delete"
    VM_EXPORT = "vm.export"
    VM_IMPORT = "vm.import"

    # Configuration
    CONFIG_CREATE = "config.create"
    CONFIG_MODIFY = "config.modify"
    CONFIG_DELETE = "config.delete"
    CONFIG_LOAD = "config.load"

    # Secrets
    SECRETS_ACCESS = "secrets.access"
    SECRETS_MODIFY = "secrets.modify"

    # Authentication
    AUTH_SSH_KEY_GENERATED = "auth.ssh_key.generated"
    AUTH_PASSWORD_GENERATED = "auth.password.generated"

    # Health
    HEALTH_CHECK_RUN = "health.check.run"
    HEALTH_CHECK_FAILED = "health.check.failed"
    HEALTH_CHECK_PASSED = "health.check.passed"

    # Repair
    REPAIR_TRIGGERED = "repair.triggered"
    REPAIR_COMPLETED = "repair.completed"
    REPAIR_FAILED = "repair.failed"

    # Container Operations
    CONTAINER_UP = "container.up"
    CONTAINER_STOP = "container.stop"
    CONTAINER_RM = "container.rm"

    # P2P Operations
    P2P_EXPORT = "p2p.export"
    P2P_IMPORT = "p2p.import"
    P2P_SYNC_KEY = "p2p.sync_key"

    # System
    SYSTEM_ERROR = "system.error"
    SYSTEM_WARNING = "system.warning"
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"


class AuditOutcome(Enum):
    """Outcome of an audited operation."""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    DENIED = "denied"
    SKIPPED = "skipped"


@dataclass
class AuditEvent:
    """A single audit event."""
    event_type: AuditEventType
    timestamp: datetime
    outcome: AuditOutcome

    # Actor information
    user: str
    hostname: str
    pid: int

    # Target information
    target_type: Optional[str] = None  # "vm", "config", "snapshot", "container"
    target_name: Optional[str] = None

    # Details
    details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None

    # Correlation
    correlation_id: Optional[str] = None
    parent_event_id: Optional[str] = None

    # Computed
    event_id: str = field(default_factory=lambda: "")

    def __post_init__(self) -> None:
        if not self.event_id:
            content = f"{self.timestamp.isoformat()}{self.event_type.value}{self.user}{self.pid}"
            self.event_id = hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "outcome": self.outcome.value,
            "actor": {
                "user": self.user,
                "hostname": self.hostname,
                "pid": self.pid,
            },
            "target": {
                "type": self.target_type,
                "name": self.target_name,
            } if self.target_type else None,
            "details": self.details,
            "error_message": self.error_message,
            "correlation_id": self.correlation_id,
            "parent_event_id": self.parent_event_id,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEvent":
        """Create from dictionary."""
        actor = data.get("actor", {})
        target = data.get("target", {}) or {}
        return cls(
            event_id=data.get("event_id", ""),
            event_type=AuditEventType(data["event_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            outcome=AuditOutcome(data["outcome"]),
            user=actor.get("user", "unknown"),
            hostname=actor.get("hostname", "unknown"),
            pid=actor.get("pid", 0),
            target_type=target.get("type"),
            target_name=target.get("name"),
            details=data.get("details", {}),
            error_message=data.get("error_message"),
            correlation_id=data.get("correlation_id"),
            parent_event_id=data.get("parent_event_id"),
        )


@dataclass
class AuditContext:
    """Context for an audited operation."""
    _logger: "AuditLogger"
    _event_type: AuditEventType
    _target_type: Optional[str]
    _target_name: Optional[str]
    _details: Dict[str, Any] = field(default_factory=dict)
    _outcome: AuditOutcome = AuditOutcome.SUCCESS
    _error: Optional[str] = None

    def add_detail(self, key: str, value: Any) -> None:
        """Add a detail to the audit event."""
        self._details[key] = value

    def set_outcome(self, outcome: AuditOutcome) -> None:
        """Set the outcome (overrides automatic detection)."""
        self._outcome = outcome

    def set_error(self, error: str) -> None:
        """Set error message."""
        self._error = error
        self._outcome = AuditOutcome.FAILURE


class AuditLogger:
    """
    Audit logger that writes events to file and/or external systems.

    Usage:
        audit = AuditLogger()

        with audit.operation(AuditEventType.VM_CREATE, target_type="vm", target_name="my-vm") as ctx:
            ctx.add_detail("disk_size_gb", 30)
            # do stuff

        # Or manually
        audit.log(AuditEventType.VM_START, outcome=AuditOutcome.SUCCESS, ...)
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        enabled: bool = True,
        console_echo: bool = False,
    ):
        self.enabled = enabled
        self.console_echo = console_echo
        self._lock = threading.Lock()
        self._correlation_id: Optional[str] = None

        # Determine log path
        if log_path:
            self.log_path = log_path
        else:
            # Use user-local path by default
            local_share = Path.home() / ".local" / "share" / "clonebox"
            self.log_path = local_share / "audit.log"

        # Get actor info once
        self._user = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
        try:
            self._hostname = os.uname().nodename
        except AttributeError:
            import socket
            self._hostname = socket.gethostname()
        self._pid = os.getpid()

        # Ensure log directory exists
        if self.enabled:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        event_type: AuditEventType,
        outcome: AuditOutcome,
        target_type: Optional[str] = None,
        target_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> AuditEvent:
        """Log an audit event."""
        event = AuditEvent(
            event_type=event_type,
            timestamp=datetime.now(),
            outcome=outcome,
            user=self._user,
            hostname=self._hostname,
            pid=self._pid,
            target_type=target_type,
            target_name=target_name,
            details=details or {},
            error_message=error_message,
            correlation_id=self._correlation_id,
        )

        if self.enabled:
            self._write_event(event)

        return event

    def _write_event(self, event: AuditEvent) -> None:
        """Write event to log file."""
        with self._lock:
            try:
                with open(self.log_path, "a") as f:
                    f.write(event.to_json() + "\n")
            except Exception as e:
                import sys
                print(f"Audit log write failed: {e}", file=sys.stderr)
                print(event.to_json(), file=sys.stderr)

        if self.console_echo:
            print(f"[AUDIT] {event.event_type.value}: {event.outcome.value}")

    def set_correlation_id(self, correlation_id: str) -> None:
        """Set correlation ID for subsequent events."""
        self._correlation_id = correlation_id

    def clear_correlation_id(self) -> None:
        """Clear correlation ID."""
        self._correlation_id = None

    @contextmanager
    def operation(
        self,
        event_type: AuditEventType,
        target_type: Optional[str] = None,
        target_name: Optional[str] = None,
    ) -> Generator[AuditContext, None, None]:
        """
        Context manager for auditing an operation.

        Usage:
            with audit.operation(AuditEventType.VM_CREATE, "vm", "my-vm") as ctx:
                ctx.add_detail("config_path", "/path/to/config")
                do_operation()
        """
        ctx = AuditContext(
            _logger=self,
            _event_type=event_type,
            _target_type=target_type,
            _target_name=target_name,
        )
        try:
            yield ctx
            if ctx._outcome == AuditOutcome.SUCCESS:
                pass  # Keep success
        except Exception as e:
            ctx._outcome = AuditOutcome.FAILURE
            ctx._error = str(e)
            raise
        finally:
            self.log(
                event_type=event_type,
                outcome=ctx._outcome,
                target_type=target_type,
                target_name=target_name,
                details=ctx._details,
                error_message=ctx._error,
            )


class AuditQuery:
    """Query audit logs."""

    def __init__(self, log_path: Optional[Path] = None):
        if log_path:
            self.log_path = log_path
        else:
            self.log_path = Path.home() / ".local" / "share" / "clonebox" / "audit.log"

    def query(
        self,
        event_type: Optional[AuditEventType] = None,
        target_name: Optional[str] = None,
        user: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        outcome: Optional[AuditOutcome] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """Query audit events with filters."""
        results: List[AuditEvent] = []

        if not self.log_path.exists():
            return results

        with open(self.log_path) as f:
            for line in f:
                if len(results) >= limit:
                    break

                try:
                    data = json.loads(line)

                    # Apply filters
                    if event_type and data.get("event_type") != event_type.value:
                        continue
                    if target_name:
                        target = data.get("target") or {}
                        if target.get("name") != target_name:
                            continue
                    if user:
                        actor = data.get("actor") or {}
                        if actor.get("user") != user:
                            continue
                    if outcome and data.get("outcome") != outcome.value:
                        continue

                    event_time = datetime.fromisoformat(data["timestamp"])
                    if start_time and event_time < start_time:
                        continue
                    if end_time and event_time > end_time:
                        continue

                    event = AuditEvent.from_dict(data)
                    results.append(event)

                except (json.JSONDecodeError, KeyError, ValueError):
                    continue

        return results

    def get_recent(self, count: int = 20) -> List[AuditEvent]:
        """Get most recent audit events."""
        all_events = self.query(limit=10000)
        return all_events[-count:] if len(all_events) > count else all_events

    def get_by_target(self, target_name: str, limit: int = 50) -> List[AuditEvent]:
        """Get events for a specific target."""
        return self.query(target_name=target_name, limit=limit)

    def get_failures(self, limit: int = 50) -> List[AuditEvent]:
        """Get failed events."""
        return self.query(outcome=AuditOutcome.FAILURE, limit=limit)

    def get_by_correlation(self, correlation_id: str) -> List[AuditEvent]:
        """Get events by correlation ID."""
        results: List[AuditEvent] = []

        if not self.log_path.exists():
            return results

        with open(self.log_path) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if data.get("correlation_id") == correlation_id:
                        results.append(AuditEvent.from_dict(data))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue

        return results


# Global audit logger
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def set_audit_logger(logger: AuditLogger) -> None:
    """Set the global audit logger (useful for testing)."""
    global _audit_logger
    _audit_logger = logger


def audit_operation(
    event_type: AuditEventType,
    target_type: Optional[str] = None,
    target_name: Optional[str] = None,
) -> Generator[AuditContext, None, None]:
    """
    Convenience function for auditing an operation.

    Usage:
        with audit_operation(AuditEventType.VM_CREATE, "vm", "my-vm") as ctx:
            ctx.add_detail("config_path", "/path/to/config")
            do_operation()
    """
    return get_audit_logger().operation(event_type, target_type, target_name)
