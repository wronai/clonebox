#!/usr/bin/env python3
"""Data models for health check system."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional


class HealthStatus(Enum):
    """Health check status."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"


class ProbeType(Enum):
    """Type of health probe."""

    HTTP = "http"
    TCP = "tcp"
    COMMAND = "command"
    SCRIPT = "script"


@dataclass
class ProbeConfig:
    """Configuration for a health probe."""

    name: str
    probe_type: ProbeType
    enabled: bool = True

    # Timing
    timeout_seconds: float = 5.0
    interval_seconds: float = 30.0
    retries: int = 3
    retry_delay_seconds: float = 1.0

    # HTTP probe
    url: Optional[str] = None
    method: str = "GET"
    expected_status: int = 200
    expected_body: Optional[str] = None
    expected_json: Optional[Dict[str, Any]] = None
    headers: Dict[str, str] = field(default_factory=dict)

    # TCP probe
    host: str = "localhost"
    port: Optional[int] = None

    # Command probe
    command: Optional[str] = None
    expected_output: Optional[str] = None
    expected_exit_code: int = 0

    # Script probe
    script_path: Optional[str] = None

    # Thresholds
    failure_threshold: int = 3  # Consecutive failures before unhealthy
    success_threshold: int = 1  # Consecutive successes before healthy

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "type": self.probe_type.value,
            "enabled": self.enabled,
            "timeout": self.timeout_seconds,
            "interval": self.interval_seconds,
            "retries": self.retries,
            "url": self.url,
            "method": self.method,
            "expected_status": self.expected_status,
            "expected_body": self.expected_body,
            "expected_json": self.expected_json,
            "headers": self.headers,
            "host": self.host,
            "port": self.port,
            "command": self.command,
            "expected_output": self.expected_output,
            "expected_exit_code": self.expected_exit_code,
            "script_path": self.script_path,
            "failure_threshold": self.failure_threshold,
            "success_threshold": self.success_threshold,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProbeConfig":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            probe_type=ProbeType(data.get("type", "command")),
            enabled=data.get("enabled", True),
            timeout_seconds=data.get("timeout", 5.0),
            interval_seconds=data.get("interval", 30.0),
            retries=data.get("retries", 3),
            url=data.get("url"),
            method=data.get("method", "GET"),
            expected_status=data.get("expected_status", 200),
            expected_body=data.get("expected_body"),
            expected_json=data.get("expected_json"),
            headers=data.get("headers", {}),
            host=data.get("host", "localhost"),
            port=data.get("port"),
            command=data.get("command") or data.get("exec"),
            expected_output=data.get("expected_output"),
            expected_exit_code=data.get("expected_exit_code", data.get("exit_code", 0)),
            script_path=data.get("script_path") or data.get("path"),
            failure_threshold=data.get("failure_threshold", 3),
            success_threshold=data.get("success_threshold", 1),
        )


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    probe_name: str
    status: HealthStatus
    checked_at: datetime
    duration_ms: float

    message: Optional[str] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    # Response info (for HTTP)
    response_code: Optional[int] = None
    response_body: Optional[str] = None

    # Command info
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "probe_name": self.probe_name,
            "status": self.status.value,
            "checked_at": self.checked_at.isoformat(),
            "duration_ms": self.duration_ms,
            "message": self.message,
            "error": self.error,
            "details": self.details,
            "response_code": self.response_code,
            "exit_code": self.exit_code,
        }

    @property
    def is_healthy(self) -> bool:
        """Check if result indicates healthy status."""
        return self.status == HealthStatus.HEALTHY


@dataclass
class VMHealthState:
    """Aggregated health state for a VM."""

    vm_name: str
    overall_status: HealthStatus
    last_check: datetime
    check_results: List[HealthCheckResult] = field(default_factory=list)

    # Counters
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_checks: int = 0
    total_failures: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "vm_name": self.vm_name,
            "overall_status": self.overall_status.value,
            "last_check": self.last_check.isoformat(),
            "check_results": [r.to_dict() for r in self.check_results],
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_checks": self.total_checks,
            "total_failures": self.total_failures,
        }

    @property
    def failure_rate(self) -> float:
        """Calculate failure rate percentage."""
        if self.total_checks == 0:
            return 0.0
        return (self.total_failures / self.total_checks) * 100
