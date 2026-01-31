# Advanced Health Checks

**Status:** 📝 Planned  
**Priority:** High  
**Estimated Effort:** 1.5 weeks  
**Dependencies:** 11-structured-logging

## Problem Statement

Current health checks are primitive:
- Only check if process is running (`ps aux | grep`)
- No deep service validation
- No HTTP endpoint checks
- No database connectivity tests
- No custom health scripts

Example of current limitation:
```python
# Current: just checks process exists
if "nginx" in ps_output:
    status = "running"  # But is it actually serving traffic?
```

## Proposed Solution

Pluggable health probe system with multiple probe types:

```yaml
# .clonebox.yaml
health_checks:
  - name: nginx
    type: http
    url: http://localhost:80/health
    expected_status: 200
    timeout: 5s
    interval: 30s
    
  - name: postgres
    type: tcp
    host: localhost
    port: 5432
    timeout: 3s
    
  - name: redis
    type: command
    exec: "redis-cli ping"
    expected_output: "PONG"
    
  - name: api
    type: http
    url: http://localhost:8000/api/health
    expected_json:
      status: "ok"
    
  - name: custom
    type: script
    path: /opt/health/check-app.sh
    exit_code: 0
```

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    HealthCheckManager                        │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐   │
│  │  HTTP     │ │   TCP     │ │  Command  │ │  Script   │   │
│  │  Probe    │ │   Probe   │ │  Probe    │ │  Probe    │   │
│  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └─────┬─────┘   │
│        │             │             │             │          │
│        └─────────────┼─────────────┼─────────────┘          │
│                      │             │                        │
│              ┌───────▼─────────────▼───────┐               │
│              │     HealthProbe Interface    │               │
│              └──────────────┬───────────────┘               │
│                             │                               │
│              ┌──────────────▼───────────────┐               │
│              │      HealthCheckResult       │               │
│              └──────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    HealthCheckScheduler                      │
│  • Periodic checks                                          │
│  • Retry logic                                              │
│  • Alerting                                                 │
│  • Metrics export                                           │
└─────────────────────────────────────────────────────────────┘
```

### Core Models

```python
# src/clonebox/health/models.py
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List

class HealthStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"

class ProbeType(Enum):
    HTTP = "http"
    TCP = "tcp"
    COMMAND = "command"
    SCRIPT = "script"
    GRPC = "grpc"
    DNS = "dns"
    DISK = "disk"
    MEMORY = "memory"

@dataclass
class HealthCheckConfig:
    """Configuration for a single health check."""
    name: str
    probe_type: ProbeType
    
    # Timing
    interval: timedelta = timedelta(seconds=30)
    timeout: timedelta = timedelta(seconds=5)
    
    # Retry logic
    failure_threshold: int = 3  # failures before unhealthy
    success_threshold: int = 1  # successes before healthy
    
    # Probe-specific config
    config: Dict[str, Any] = field(default_factory=dict)
    
    # Actions
    on_failure: Optional[str] = None  # Command to run on failure
    on_recovery: Optional[str] = None  # Command to run on recovery
    
    # Metadata
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    critical: bool = False  # If True, VM considered unhealthy if this fails

@dataclass
class HealthCheckResult:
    """Result of a single health check execution."""
    name: str
    status: HealthStatus
    
    # Timing
    timestamp: datetime
    duration_ms: float
    
    # Details
    message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    
    # For tracking
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "message": self.message,
            "details": self.details,
        }

@dataclass
class VMHealthReport:
    """Aggregated health report for a VM."""
    vm_name: str
    overall_status: HealthStatus
    timestamp: datetime
    
    checks: List[HealthCheckResult]
    
    # Aggregated stats
    total_checks: int = 0
    healthy_checks: int = 0
    unhealthy_checks: int = 0
    degraded_checks: int = 0
    
    def __post_init__(self):
        self.total_checks = len(self.checks)
        self.healthy_checks = sum(1 for c in self.checks if c.status == HealthStatus.HEALTHY)
        self.unhealthy_checks = sum(1 for c in self.checks if c.status == HealthStatus.UNHEALTHY)
        self.degraded_checks = sum(1 for c in self.checks if c.status == HealthStatus.DEGRADED)
```

### Health Probe Interface

```python
# src/clonebox/health/probes/base.py
from abc import ABC, abstractmethod
from typing import Optional
import time

class HealthProbe(ABC):
    """Base interface for health probes."""
    
    probe_type: ProbeType
    
    @abstractmethod
    async def check(self, config: HealthCheckConfig) -> HealthCheckResult:
        """Execute the health check."""
        pass
    
    def _create_result(
        self,
        config: HealthCheckConfig,
        status: HealthStatus,
        start_time: float,
        message: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> HealthCheckResult:
        """Helper to create result with timing."""
        duration_ms = (time.time() - start_time) * 1000
        
        return HealthCheckResult(
            name=config.name,
            status=status,
            timestamp=datetime.now(),
            duration_ms=duration_ms,
            message=message,
            details=details or {},
        )
```

### Probe Implementations

```python
# src/clonebox/health/probes/http.py
import aiohttp
import asyncio
from typing import Optional, Dict, Any

class HTTPProbe(HealthProbe):
    """HTTP/HTTPS health probe."""
    
    probe_type = ProbeType.HTTP
    
    async def check(self, config: HealthCheckConfig) -> HealthCheckResult:
        start_time = time.time()
        
        url = config.config.get("url")
        method = config.config.get("method", "GET")
        expected_status = config.config.get("expected_status", 200)
        expected_body = config.config.get("expected_body")
        expected_json = config.config.get("expected_json")
        headers = config.config.get("headers", {})
        
        timeout = aiohttp.ClientTimeout(total=config.timeout.total_seconds())
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(method, url, headers=headers) as response:
                    body = await response.text()
                    
                    details = {
                        "status_code": response.status,
                        "content_length": len(body),
                        "headers": dict(response.headers),
                    }
                    
                    # Check status code
                    if response.status != expected_status:
                        return self._create_result(
                            config, HealthStatus.UNHEALTHY, start_time,
                            f"Expected status {expected_status}, got {response.status}",
                            details,
                        )
                    
                    # Check body content
                    if expected_body and expected_body not in body:
                        return self._create_result(
                            config, HealthStatus.UNHEALTHY, start_time,
                            f"Expected body content not found",
                            details,
                        )
                    
                    # Check JSON response
                    if expected_json:
                        try:
                            json_body = await response.json()
                            for key, value in expected_json.items():
                                if json_body.get(key) != value:
                                    return self._create_result(
                                        config, HealthStatus.UNHEALTHY, start_time,
                                        f"JSON mismatch: {key}={json_body.get(key)}, expected {value}",
                                        {**details, "json": json_body},
                                    )
                        except Exception as e:
                            return self._create_result(
                                config, HealthStatus.UNHEALTHY, start_time,
                                f"Invalid JSON response: {e}",
                                details,
                            )
                    
                    return self._create_result(
                        config, HealthStatus.HEALTHY, start_time,
                        f"HTTP {response.status} OK",
                        details,
                    )
                    
        except asyncio.TimeoutError:
            return self._create_result(
                config, HealthStatus.UNHEALTHY, start_time,
                f"Timeout after {config.timeout.total_seconds()}s",
            )
        except aiohttp.ClientError as e:
            return self._create_result(
                config, HealthStatus.UNHEALTHY, start_time,
                f"Connection error: {e}",
            )


# src/clonebox/health/probes/tcp.py
import asyncio
import socket

class TCPProbe(HealthProbe):
    """TCP port connectivity probe."""
    
    probe_type = ProbeType.TCP
    
    async def check(self, config: HealthCheckConfig) -> HealthCheckResult:
        start_time = time.time()
        
        host = config.config.get("host", "localhost")
        port = config.config.get("port")
        
        if not port:
            return self._create_result(
                config, HealthStatus.UNKNOWN, start_time,
                "Port not specified",
            )
        
        try:
            # Use asyncio for non-blocking connect
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=config.timeout.total_seconds(),
            )
            writer.close()
            await writer.wait_closed()
            
            return self._create_result(
                config, HealthStatus.HEALTHY, start_time,
                f"TCP {host}:{port} reachable",
                {"host": host, "port": port},
            )
            
        except asyncio.TimeoutError:
            return self._create_result(
                config, HealthStatus.UNHEALTHY, start_time,
                f"Timeout connecting to {host}:{port}",
            )
        except (OSError, ConnectionRefusedError) as e:
            return self._create_result(
                config, HealthStatus.UNHEALTHY, start_time,
                f"Connection failed: {e}",
            )


# src/clonebox/health/probes/command.py
import asyncio
import subprocess

class CommandProbe(HealthProbe):
    """Command execution probe."""
    
    probe_type = ProbeType.COMMAND
    
    async def check(self, config: HealthCheckConfig) -> HealthCheckResult:
        start_time = time.time()
        
        command = config.config.get("exec")
        expected_output = config.config.get("expected_output")
        expected_exit_code = config.config.get("exit_code", 0)
        shell = config.config.get("shell", True)
        
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=config.timeout.total_seconds(),
            )
            
            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()
            
            details = {
                "exit_code": proc.returncode,
                "stdout": stdout_str[:500],  # Limit output
                "stderr": stderr_str[:500],
            }
            
            # Check exit code
            if proc.returncode != expected_exit_code:
                return self._create_result(
                    config, HealthStatus.UNHEALTHY, start_time,
                    f"Exit code {proc.returncode}, expected {expected_exit_code}",
                    details,
                )
            
            # Check output
            if expected_output and expected_output not in stdout_str:
                return self._create_result(
                    config, HealthStatus.UNHEALTHY, start_time,
                    f"Expected output not found",
                    details,
                )
            
            return self._create_result(
                config, HealthStatus.HEALTHY, start_time,
                f"Command successful",
                details,
            )
            
        except asyncio.TimeoutError:
            return self._create_result(
                config, HealthStatus.UNHEALTHY, start_time,
                f"Command timeout",
            )
        except Exception as e:
            return self._create_result(
                config, HealthStatus.UNHEALTHY, start_time,
                f"Execution error: {e}",
            )


# src/clonebox/health/probes/resource.py
class DiskProbe(HealthProbe):
    """Disk space health probe."""
    
    probe_type = ProbeType.DISK
    
    async def check(self, config: HealthCheckConfig) -> HealthCheckResult:
        start_time = time.time()
        
        path = config.config.get("path", "/")
        warning_threshold = config.config.get("warning_percent", 80)
        critical_threshold = config.config.get("critical_percent", 90)
        
        try:
            import shutil
            total, used, free = shutil.disk_usage(path)
            percent_used = (used / total) * 100
            
            details = {
                "path": path,
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "free_gb": round(free / (1024**3), 2),
                "percent_used": round(percent_used, 1),
            }
            
            if percent_used >= critical_threshold:
                return self._create_result(
                    config, HealthStatus.UNHEALTHY, start_time,
                    f"Disk {percent_used:.1f}% full (critical)",
                    details,
                )
            elif percent_used >= warning_threshold:
                return self._create_result(
                    config, HealthStatus.DEGRADED, start_time,
                    f"Disk {percent_used:.1f}% full (warning)",
                    details,
                )
            else:
                return self._create_result(
                    config, HealthStatus.HEALTHY, start_time,
                    f"Disk {percent_used:.1f}% used",
                    details,
                )
                
        except Exception as e:
            return self._create_result(
                config, HealthStatus.UNKNOWN, start_time,
                f"Failed to check disk: {e}",
            )


class MemoryProbe(HealthProbe):
    """Memory usage health probe."""
    
    probe_type = ProbeType.MEMORY
    
    async def check(self, config: HealthCheckConfig) -> HealthCheckResult:
        start_time = time.time()
        
        warning_threshold = config.config.get("warning_percent", 80)
        critical_threshold = config.config.get("critical_percent", 90)
        
        try:
            import psutil
            mem = psutil.virtual_memory()
            
            details = {
                "total_gb": round(mem.total / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "percent_used": mem.percent,
            }
            
            if mem.percent >= critical_threshold:
                status = HealthStatus.UNHEALTHY
                message = f"Memory {mem.percent}% used (critical)"
            elif mem.percent >= warning_threshold:
                status = HealthStatus.DEGRADED
                message = f"Memory {mem.percent}% used (warning)"
            else:
                status = HealthStatus.HEALTHY
                message = f"Memory {mem.percent}% used"
            
            return self._create_result(config, status, start_time, message, details)
            
        except Exception as e:
            return self._create_result(
                config, HealthStatus.UNKNOWN, start_time,
                f"Failed to check memory: {e}",
            )
```

### Health Check Manager

```python
# src/clonebox/health/manager.py
import asyncio
from typing import Dict, List, Optional, Type
from datetime import datetime

class HealthCheckManager:
    """Manage and execute health checks."""
    
    _probe_registry: Dict[ProbeType, Type[HealthProbe]] = {
        ProbeType.HTTP: HTTPProbe,
        ProbeType.TCP: TCPProbe,
        ProbeType.COMMAND: CommandProbe,
        ProbeType.DISK: DiskProbe,
        ProbeType.MEMORY: MemoryProbe,
    }
    
    def __init__(self, vm_executor: Optional['VMExecutor'] = None):
        self.vm_executor = vm_executor
        self._check_states: Dict[str, HealthCheckResult] = {}
    
    @classmethod
    def register_probe(cls, probe_type: ProbeType, probe_class: Type[HealthProbe]) -> None:
        """Register a custom probe type."""
        cls._probe_registry[probe_type] = probe_class
    
    def _get_probe(self, probe_type: ProbeType) -> HealthProbe:
        """Get probe instance for type."""
        if probe_type not in self._probe_registry:
            raise ValueError(f"Unknown probe type: {probe_type}")
        return self._probe_registry[probe_type]()
    
    async def run_check(self, config: HealthCheckConfig) -> HealthCheckResult:
        """Run a single health check."""
        probe = self._get_probe(config.probe_type)
        result = await probe.check(config)
        
        # Update consecutive counters
        prev_result = self._check_states.get(config.name)
        if prev_result:
            if result.is_healthy():
                result.consecutive_successes = prev_result.consecutive_successes + 1
                result.consecutive_failures = 0
            else:
                result.consecutive_failures = prev_result.consecutive_failures + 1
                result.consecutive_successes = 0
        else:
            result.consecutive_successes = 1 if result.is_healthy() else 0
            result.consecutive_failures = 0 if result.is_healthy() else 1
        
        # Apply thresholds
        if result.consecutive_failures >= config.failure_threshold:
            result.status = HealthStatus.UNHEALTHY
        elif result.consecutive_failures > 0:
            result.status = HealthStatus.DEGRADED
        
        # Store state
        self._check_states[config.name] = result
        
        # Execute failure/recovery actions
        await self._handle_status_change(config, prev_result, result)
        
        return result
    
    async def run_all_checks(
        self,
        configs: List[HealthCheckConfig],
        parallel: bool = True,
    ) -> VMHealthReport:
        """Run all health checks and return report."""
        if parallel:
            results = await asyncio.gather(
                *[self.run_check(c) for c in configs],
                return_exceptions=True,
            )
            # Handle exceptions
            results = [
                r if isinstance(r, HealthCheckResult)
                else HealthCheckResult(
                    name="unknown",
                    status=HealthStatus.UNKNOWN,
                    timestamp=datetime.now(),
                    duration_ms=0,
                    message=str(r),
                )
                for r in results
            ]
        else:
            results = []
            for config in configs:
                results.append(await self.run_check(config))
        
        # Determine overall status
        overall = self._calculate_overall_status(results, configs)
        
        return VMHealthReport(
            vm_name="",  # Set by caller
            overall_status=overall,
            timestamp=datetime.now(),
            checks=results,
        )
    
    def _calculate_overall_status(
        self,
        results: List[HealthCheckResult],
        configs: List[HealthCheckConfig],
    ) -> HealthStatus:
        """Calculate overall VM health status."""
        config_map = {c.name: c for c in configs}
        
        # Check critical services
        for result in results:
            config = config_map.get(result.name)
            if config and config.critical and result.status == HealthStatus.UNHEALTHY:
                return HealthStatus.UNHEALTHY
        
        # Count statuses
        unhealthy = sum(1 for r in results if r.status == HealthStatus.UNHEALTHY)
        degraded = sum(1 for r in results if r.status == HealthStatus.DEGRADED)
        
        if unhealthy > 0:
            return HealthStatus.DEGRADED
        elif degraded > 0:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY
    
    async def _handle_status_change(
        self,
        config: HealthCheckConfig,
        prev_result: Optional[HealthCheckResult],
        new_result: HealthCheckResult,
    ) -> None:
        """Handle status transitions."""
        if not prev_result:
            return
        
        prev_healthy = prev_result.is_healthy()
        now_healthy = new_result.is_healthy()
        
        # Transition to unhealthy
        if prev_healthy and not now_healthy and config.on_failure:
            await self._execute_action(config.on_failure)
        
        # Transition to healthy
        if not prev_healthy and now_healthy and config.on_recovery:
            await self._execute_action(config.on_recovery)
    
    async def _execute_action(self, command: str) -> None:
        """Execute a health check action."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as e:
            # Log but don't fail
            pass
```

### Health Check Scheduler

```python
# src/clonebox/health/scheduler.py
import asyncio
from typing import Dict, List, Callable, Optional
from datetime import datetime

class HealthCheckScheduler:
    """Schedule periodic health checks."""
    
    def __init__(
        self,
        manager: HealthCheckManager,
        on_report: Optional[Callable[[VMHealthReport], None]] = None,
    ):
        self.manager = manager
        self.on_report = on_report
        self._tasks: Dict[str, asyncio.Task] = {}
        self._running = False
    
    async def start(self, configs: List[HealthCheckConfig]) -> None:
        """Start scheduled health checks."""
        self._running = True
        
        for config in configs:
            task = asyncio.create_task(
                self._check_loop(config),
                name=f"health-check-{config.name}",
            )
            self._tasks[config.name] = task
    
    async def stop(self) -> None:
        """Stop all scheduled checks."""
        self._running = False
        
        for task in self._tasks.values():
            task.cancel()
        
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
    
    async def _check_loop(self, config: HealthCheckConfig) -> None:
        """Run check in a loop."""
        while self._running:
            try:
                result = await self.manager.run_check(config)
                
                if self.on_report:
                    # Create single-check report
                    report = VMHealthReport(
                        vm_name="",
                        overall_status=result.status,
                        timestamp=datetime.now(),
                        checks=[result],
                    )
                    self.on_report(report)
                
                await asyncio.sleep(config.interval.total_seconds())
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log and continue
                await asyncio.sleep(config.interval.total_seconds())
```

### Configuration Schema

```yaml
# .clonebox.yaml
health_checks:
  # HTTP endpoint check
  - name: api-health
    type: http
    url: http://localhost:8000/health
    method: GET
    expected_status: 200
    expected_json:
      status: "ok"
    timeout: 5s
    interval: 30s
    failure_threshold: 3
    critical: true
    on_failure: "systemctl restart uvicorn"
    
  # TCP port check
  - name: postgres
    type: tcp
    host: localhost
    port: 5432
    timeout: 3s
    interval: 60s
    critical: true
    
  # Redis check
  - name: redis
    type: command
    exec: "redis-cli ping"
    expected_output: "PONG"
    timeout: 2s
    interval: 30s
    
  # Disk space check
  - name: disk-root
    type: disk
    path: /
    warning_percent: 80
    critical_percent: 90
    interval: 300s
    
  # Memory check  
  - name: memory
    type: memory
    warning_percent: 80
    critical_percent: 95
    interval: 60s
    
  # Custom script
  - name: app-health
    type: script
    path: /opt/health/check-app.sh
    exit_code: 0
    timeout: 10s
    interval: 60s
```

## CLI Commands

```bash
# Run all health checks once
clonebox health check my-vm

# Watch health continuously
clonebox health watch my-vm --interval 30

# Check specific probe
clonebox health check my-vm --probe api-health

# Output as JSON
clonebox health check my-vm --json

# Show health history
clonebox health history my-vm --last 24h
```

## Testing Strategy

```python
class TestHealthProbes:
    @pytest.mark.asyncio
    async def test_http_probe_success(self, aiohttp_server):
        config = HealthCheckConfig(
            name="test",
            probe_type=ProbeType.HTTP,
            config={"url": f"{aiohttp_server}/health", "expected_status": 200},
        )
        
        probe = HTTPProbe()
        result = await probe.check(config)
        
        assert result.status == HealthStatus.HEALTHY
    
    @pytest.mark.asyncio
    async def test_tcp_probe_connection_refused(self):
        config = HealthCheckConfig(
            name="test",
            probe_type=ProbeType.TCP,
            config={"host": "localhost", "port": 59999},
        )
        
        probe = TCPProbe()
        result = await probe.check(config)
        
        assert result.status == HealthStatus.UNHEALTHY
    
    @pytest.mark.asyncio
    async def test_command_probe_exit_code(self):
        config = HealthCheckConfig(
            name="test",
            probe_type=ProbeType.COMMAND,
            config={"exec": "exit 1", "exit_code": 0},
        )
        
        probe = CommandProbe()
        result = await probe.check(config)
        
        assert result.status == HealthStatus.UNHEALTHY
```

## Implementation Timeline

| Day | Task |
|-----|------|
| 1-2 | Core models, probe interface |
| 3-4 | HTTP, TCP, Command probes |
| 5-6 | Disk, Memory probes, Manager |
| 7-8 | Scheduler, CLI integration |
| 9-10 | Testing, documentation |
