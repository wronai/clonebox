#!/usr/bin/env python3
"""Health check manager for CloneBox VMs."""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import HealthCheckResult, HealthStatus, ProbeConfig, ProbeType, VMHealthState
from .probes import get_probe


class HealthCheckManager:
    """Manage health checks for VMs."""

    def __init__(self, config_dir: Optional[Path] = None):
        self._config_dir = config_dir or Path.home() / ".local/share/clonebox/health"
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._vm_states: Dict[str, VMHealthState] = {}

    def check(
        self,
        vm_name: str,
        probes: List[ProbeConfig],
    ) -> VMHealthState:
        """Run health checks for a VM.

        Args:
            vm_name: Name of VM to check
            probes: List of probe configurations

        Returns:
            VMHealthState with aggregated results
        """
        results = []

        for config in probes:
            if not config.enabled:
                continue

            probe = get_probe(config.probe_type)
            result = self._run_probe_with_retry(probe, config)
            results.append(result)

        # Calculate overall status
        overall = self._calculate_overall_status(results)

        # Update state
        state = self._update_vm_state(vm_name, overall, results)

        return state

    def check_single(self, config: ProbeConfig) -> HealthCheckResult:
        """Run a single health check.

        Args:
            config: Probe configuration

        Returns:
            HealthCheckResult
        """
        probe = get_probe(config.probe_type)
        return self._run_probe_with_retry(probe, config)

    def check_from_config(
        self,
        vm_name: str,
        config_path: Path,
    ) -> VMHealthState:
        """Run health checks from YAML config file.

        Args:
            vm_name: Name of VM
            config_path: Path to .clonebox.yaml

        Returns:
            VMHealthState with results
        """
        import yaml

        if not config_path.exists():
            return VMHealthState(
                vm_name=vm_name,
                overall_status=HealthStatus.UNKNOWN,
                last_check=datetime.now(),
            )

        config = yaml.safe_load(config_path.read_text())
        health_checks = config.get("health_checks", [])

        probes = []
        for hc in health_checks:
            probe_config = ProbeConfig.from_dict(hc)
            probes.append(probe_config)

        return self.check(vm_name, probes)

    def get_state(self, vm_name: str) -> Optional[VMHealthState]:
        """Get current health state for a VM."""
        return self._vm_states.get(vm_name)

    def wait_healthy(
        self,
        vm_name: str,
        probes: List[ProbeConfig],
        timeout: int = 300,
        check_interval: float = 5.0,
    ) -> bool:
        """Wait until VM becomes healthy.

        Args:
            vm_name: Name of VM
            probes: Probe configurations
            timeout: Maximum wait time in seconds
            check_interval: Time between checks

        Returns:
            True if healthy within timeout, False otherwise
        """
        start = time.time()

        while time.time() - start < timeout:
            state = self.check(vm_name, probes)

            if state.overall_status == HealthStatus.HEALTHY:
                return True

            time.sleep(check_interval)

        return False

    def create_default_probes(self, services: List[str]) -> List[ProbeConfig]:
        """Create default health probes for common services.

        Args:
            services: List of service names (e.g., ["nginx", "postgres"])

        Returns:
            List of ProbeConfig
        """
        defaults = {
            "nginx": ProbeConfig(
                name="nginx",
                probe_type=ProbeType.HTTP,
                url="http://localhost:80/",
                expected_status=200,
                timeout_seconds=5.0,
            ),
            "apache2": ProbeConfig(
                name="apache2",
                probe_type=ProbeType.HTTP,
                url="http://localhost:80/",
                expected_status=200,
                timeout_seconds=5.0,
            ),
            "postgres": ProbeConfig(
                name="postgres",
                probe_type=ProbeType.TCP,
                host="localhost",
                port=5432,
                timeout_seconds=3.0,
            ),
            "postgresql": ProbeConfig(
                name="postgresql",
                probe_type=ProbeType.TCP,
                host="localhost",
                port=5432,
                timeout_seconds=3.0,
            ),
            "mysql": ProbeConfig(
                name="mysql",
                probe_type=ProbeType.TCP,
                host="localhost",
                port=3306,
                timeout_seconds=3.0,
            ),
            "redis": ProbeConfig(
                name="redis",
                probe_type=ProbeType.COMMAND,
                command="redis-cli ping",
                expected_output="PONG",
                timeout_seconds=3.0,
            ),
            "mongodb": ProbeConfig(
                name="mongodb",
                probe_type=ProbeType.TCP,
                host="localhost",
                port=27017,
                timeout_seconds=3.0,
            ),
            "docker": ProbeConfig(
                name="docker",
                probe_type=ProbeType.COMMAND,
                command="docker info",
                expected_exit_code=0,
                timeout_seconds=5.0,
            ),
            "ssh": ProbeConfig(
                name="ssh",
                probe_type=ProbeType.TCP,
                host="localhost",
                port=22,
                timeout_seconds=3.0,
            ),
        }

        probes = []
        for service in services:
            service_lower = service.lower()
            if service_lower in defaults:
                probes.append(defaults[service_lower])
            else:
                # Create generic process check
                probes.append(
                    ProbeConfig(
                        name=service,
                        probe_type=ProbeType.COMMAND,
                        command=f"pgrep -x {service} || pgrep -f {service}",
                        expected_exit_code=0,
                        timeout_seconds=3.0,
                    )
                )

        return probes

    def _run_probe_with_retry(
        self,
        probe,
        config: ProbeConfig,
    ) -> HealthCheckResult:
        """Run probe with retry logic."""
        last_result = None

        for attempt in range(config.retries):
            result = probe.check(config)

            if result.is_healthy:
                return result

            last_result = result

            if attempt < config.retries - 1:
                time.sleep(config.retry_delay_seconds)

        return last_result or HealthCheckResult(
            probe_name=config.name,
            status=HealthStatus.UNKNOWN,
            checked_at=datetime.now(),
            duration_ms=0,
            error="No result after retries",
        )

    def _calculate_overall_status(
        self,
        results: List[HealthCheckResult],
    ) -> HealthStatus:
        """Calculate overall health status from results."""
        if not results:
            return HealthStatus.UNKNOWN

        statuses = [r.status for r in results]

        # All healthy = healthy
        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY

        # Any unhealthy = unhealthy
        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY

        # Any timeout = degraded
        if any(s == HealthStatus.TIMEOUT for s in statuses):
            return HealthStatus.DEGRADED

        # Mix of healthy and unknown = degraded
        return HealthStatus.DEGRADED

    def _update_vm_state(
        self,
        vm_name: str,
        overall: HealthStatus,
        results: List[HealthCheckResult],
    ) -> VMHealthState:
        """Update VM health state with new results."""
        if vm_name not in self._vm_states:
            self._vm_states[vm_name] = VMHealthState(
                vm_name=vm_name,
                overall_status=overall,
                last_check=datetime.now(),
            )

        state = self._vm_states[vm_name]
        state.overall_status = overall
        state.last_check = datetime.now()
        state.check_results = results
        state.total_checks += 1

        if overall == HealthStatus.HEALTHY:
            state.consecutive_successes += 1
            state.consecutive_failures = 0
        else:
            state.consecutive_failures += 1
            state.consecutive_successes = 0
            state.total_failures += 1

        return state

    def export_metrics(self, vm_name: str) -> Dict[str, Any]:
        """Export health metrics in Prometheus format."""
        state = self._vm_states.get(vm_name)
        if not state:
            return {}

        metrics = {
            "clonebox_health_status": 1 if state.overall_status == HealthStatus.HEALTHY else 0,
            "clonebox_health_consecutive_failures": state.consecutive_failures,
            "clonebox_health_consecutive_successes": state.consecutive_successes,
            "clonebox_health_total_checks": state.total_checks,
            "clonebox_health_failure_rate": state.failure_rate,
        }

        for result in state.check_results:
            probe_name = result.probe_name.replace("-", "_")
            metrics[f"clonebox_probe_{probe_name}_healthy"] = 1 if result.is_healthy else 0
            metrics[f"clonebox_probe_{probe_name}_duration_ms"] = result.duration_ms

        return metrics
