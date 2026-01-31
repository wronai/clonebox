#!/usr/bin/env python3
"""Health check probes for different protocols."""

import socket
import subprocess
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from .models import HealthCheckResult, HealthStatus, ProbeConfig

try:
    import urllib.request
    import urllib.error
except ImportError:
    urllib = None


class HealthProbe(ABC):
    """Abstract base class for health probes."""

    @abstractmethod
    def check(self, config: ProbeConfig) -> HealthCheckResult:
        """Execute health check and return result."""
        pass

    def _create_result(
        self,
        config: ProbeConfig,
        status: HealthStatus,
        duration_ms: float,
        **kwargs,
    ) -> HealthCheckResult:
        """Create a health check result."""
        return HealthCheckResult(
            probe_name=config.name,
            status=status,
            checked_at=datetime.now(),
            duration_ms=duration_ms,
            **kwargs,
        )


class HTTPProbe(HealthProbe):
    """HTTP/HTTPS health probe."""

    def check(self, config: ProbeConfig) -> HealthCheckResult:
        """Check HTTP endpoint."""
        if not config.url:
            return self._create_result(
                config,
                HealthStatus.UNHEALTHY,
                0,
                error="No URL configured",
            )

        start = time.time()
        try:
            req = urllib.request.Request(
                config.url,
                method=config.method,
                headers=config.headers or {},
            )

            with urllib.request.urlopen(req, timeout=config.timeout_seconds) as response:
                duration_ms = (time.time() - start) * 1000
                status_code = response.getcode()
                body = response.read().decode("utf-8", errors="replace")

                # Check status code
                if status_code != config.expected_status:
                    return self._create_result(
                        config,
                        HealthStatus.UNHEALTHY,
                        duration_ms,
                        message=f"Expected status {config.expected_status}, got {status_code}",
                        response_code=status_code,
                        response_body=body[:500],
                    )

                # Check body content
                if config.expected_body and config.expected_body not in body:
                    return self._create_result(
                        config,
                        HealthStatus.UNHEALTHY,
                        duration_ms,
                        message=f"Expected body content not found",
                        response_code=status_code,
                        response_body=body[:500],
                    )

                # Check JSON response
                if config.expected_json:
                    import json

                    try:
                        json_body = json.loads(body)
                        for key, expected_value in config.expected_json.items():
                            if json_body.get(key) != expected_value:
                                return self._create_result(
                                    config,
                                    HealthStatus.UNHEALTHY,
                                    duration_ms,
                                    message=f"JSON field '{key}' mismatch",
                                    response_code=status_code,
                                    details={"expected": expected_value, "got": json_body.get(key)},
                                )
                    except json.JSONDecodeError as e:
                        return self._create_result(
                            config,
                            HealthStatus.UNHEALTHY,
                            duration_ms,
                            message="Invalid JSON response",
                            error=str(e),
                        )

                return self._create_result(
                    config,
                    HealthStatus.HEALTHY,
                    duration_ms,
                    message="OK",
                    response_code=status_code,
                )

        except urllib.error.HTTPError as e:
            duration_ms = (time.time() - start) * 1000
            return self._create_result(
                config,
                HealthStatus.UNHEALTHY,
                duration_ms,
                error=f"HTTP error: {e.code}",
                response_code=e.code,
            )
        except urllib.error.URLError as e:
            duration_ms = (time.time() - start) * 1000
            return self._create_result(
                config,
                HealthStatus.UNHEALTHY,
                duration_ms,
                error=f"Connection error: {e.reason}",
            )
        except TimeoutError:
            duration_ms = (time.time() - start) * 1000
            return self._create_result(
                config,
                HealthStatus.TIMEOUT,
                duration_ms,
                error=f"Timeout after {config.timeout_seconds}s",
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return self._create_result(
                config,
                HealthStatus.UNHEALTHY,
                duration_ms,
                error=str(e),
            )


class TCPProbe(HealthProbe):
    """TCP port connectivity probe."""

    def check(self, config: ProbeConfig) -> HealthCheckResult:
        """Check TCP port connectivity."""
        if not config.port:
            return self._create_result(
                config,
                HealthStatus.UNHEALTHY,
                0,
                error="No port configured",
            )

        start = time.time()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(config.timeout_seconds)

            result = sock.connect_ex((config.host, config.port))
            duration_ms = (time.time() - start) * 1000
            sock.close()

            if result == 0:
                return self._create_result(
                    config,
                    HealthStatus.HEALTHY,
                    duration_ms,
                    message=f"Port {config.port} is open",
                    details={"host": config.host, "port": config.port},
                )
            else:
                return self._create_result(
                    config,
                    HealthStatus.UNHEALTHY,
                    duration_ms,
                    error=f"Port {config.port} is closed (code: {result})",
                    details={"host": config.host, "port": config.port},
                )

        except socket.timeout:
            duration_ms = (time.time() - start) * 1000
            return self._create_result(
                config,
                HealthStatus.TIMEOUT,
                duration_ms,
                error=f"Connection timeout to {config.host}:{config.port}",
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return self._create_result(
                config,
                HealthStatus.UNHEALTHY,
                duration_ms,
                error=str(e),
            )


class CommandProbe(HealthProbe):
    """Command execution probe."""

    def check(self, config: ProbeConfig) -> HealthCheckResult:
        """Execute command and check result."""
        if not config.command:
            return self._create_result(
                config,
                HealthStatus.UNHEALTHY,
                0,
                error="No command configured",
            )

        start = time.time()
        try:
            result = subprocess.run(
                config.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
            )
            duration_ms = (time.time() - start) * 1000

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            # Check exit code
            if result.returncode != config.expected_exit_code:
                return self._create_result(
                    config,
                    HealthStatus.UNHEALTHY,
                    duration_ms,
                    message=f"Exit code {result.returncode}, expected {config.expected_exit_code}",
                    exit_code=result.returncode,
                    stdout=stdout[:500],
                    stderr=stderr[:500],
                )

            # Check expected output
            if config.expected_output and config.expected_output not in stdout:
                return self._create_result(
                    config,
                    HealthStatus.UNHEALTHY,
                    duration_ms,
                    message=f"Expected output not found",
                    exit_code=result.returncode,
                    stdout=stdout[:500],
                    details={"expected": config.expected_output},
                )

            return self._create_result(
                config,
                HealthStatus.HEALTHY,
                duration_ms,
                message="OK",
                exit_code=result.returncode,
                stdout=stdout[:500] if stdout else None,
            )

        except subprocess.TimeoutExpired:
            duration_ms = (time.time() - start) * 1000
            return self._create_result(
                config,
                HealthStatus.TIMEOUT,
                duration_ms,
                error=f"Command timeout after {config.timeout_seconds}s",
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return self._create_result(
                config,
                HealthStatus.UNHEALTHY,
                duration_ms,
                error=str(e),
            )


class ScriptProbe(HealthProbe):
    """Script execution probe."""

    def check(self, config: ProbeConfig) -> HealthCheckResult:
        """Execute script and check result."""
        if not config.script_path:
            return self._create_result(
                config,
                HealthStatus.UNHEALTHY,
                0,
                error="No script path configured",
            )

        # Use CommandProbe with script path
        cmd_config = ProbeConfig(
            name=config.name,
            probe_type=config.probe_type,
            command=config.script_path,
            expected_exit_code=config.expected_exit_code,
            expected_output=config.expected_output,
            timeout_seconds=config.timeout_seconds,
        )

        cmd_probe = CommandProbe()
        return cmd_probe.check(cmd_config)


def get_probe(probe_type: str) -> HealthProbe:
    """Get probe instance by type."""
    from .models import ProbeType

    probes = {
        ProbeType.HTTP: HTTPProbe(),
        ProbeType.TCP: TCPProbe(),
        ProbeType.COMMAND: CommandProbe(),
        ProbeType.SCRIPT: ScriptProbe(),
    }

    if isinstance(probe_type, str):
        probe_type = ProbeType(probe_type)

    return probes.get(probe_type, CommandProbe())
