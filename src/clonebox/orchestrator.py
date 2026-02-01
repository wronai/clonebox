"""
Multi-VM orchestration for CloneBox.
Manages multiple VMs with dependencies, shared networks, and coordinated lifecycle.
"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Set, Callable
import threading
import time
import yaml


class VMOrchestrationState(Enum):
    """State of a VM within orchestration."""
    PENDING = "pending"
    CREATING = "creating"
    STARTING = "starting"
    RUNNING = "running"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class OrchestratedVM:
    """A VM within an orchestration."""
    name: str
    config_path: Optional[Path] = None
    template: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    health_check: Optional[Dict[str, Any]] = None
    environment: Dict[str, str] = field(default_factory=dict)
    volumes: Dict[str, str] = field(default_factory=dict)
    vm_overrides: Dict[str, Any] = field(default_factory=dict)
    state: VMOrchestrationState = VMOrchestrationState.PENDING
    error: Optional[str] = None
    ip_address: Optional[str] = None
    start_time: Optional[float] = None
    health_check_passed: bool = False


@dataclass
class OrchestrationPlan:
    """Execution plan for orchestration."""
    vms: Dict[str, OrchestratedVM]
    start_order: List[List[str]]  # Groups of VMs that can start in parallel
    stop_order: List[List[str]]  # Reverse of start_order
    volumes: Dict[str, Dict[str, Any]]
    networks: Dict[str, Dict[str, Any]]
    defaults: Dict[str, Any]


@dataclass
class OrchestrationResult:
    """Result of an orchestration operation."""
    success: bool
    states: Dict[str, VMOrchestrationState]
    errors: Dict[str, str]
    duration_seconds: float


class Orchestrator:
    """
    Orchestrate multiple VMs with dependencies.

    Usage:
        orch = Orchestrator.from_file("clonebox-compose.yaml")
        result = orch.up()  # Start all VMs in dependency order
        orch.down()  # Stop all VMs
        status = orch.status()  # Get status of all VMs
    """

    def __init__(
        self,
        config: Dict[str, Any],
        cloner: Optional[Any] = None,
        user_session: bool = False,
        max_workers: int = 4,
    ):
        self.config = config
        self.user_session = user_session
        self.max_workers = max_workers
        self._cloner = cloner
        self._executor: Optional[ThreadPoolExecutor] = None
        self._lock = threading.Lock()

        # Parse and validate configuration
        self.plan = self._create_plan()

    @classmethod
    def from_file(
        cls,
        compose_file: Path,
        cloner: Optional[Any] = None,
        user_session: bool = False,
    ) -> "Orchestrator":
        """Create orchestrator from compose file."""
        compose_path = Path(compose_file)
        if not compose_path.exists():
            raise FileNotFoundError(f"Compose file not found: {compose_path}")

        with open(compose_path) as f:
            config = yaml.safe_load(f)

        return cls(config, cloner=cloner, user_session=user_session)

    @property
    def cloner(self) -> Any:
        """Get or create VM cloner."""
        if self._cloner is None:
            from clonebox.cloner import SelectiveVMCloner
            self._cloner = SelectiveVMCloner(user_session=self.user_session)
        return self._cloner

    def _create_plan(self) -> OrchestrationPlan:
        """Create execution plan from configuration."""
        vms: Dict[str, OrchestratedVM] = {}
        defaults = self.config.get("defaults", {})

        for name, vm_config in self.config.get("vms", {}).items():
            vms[name] = OrchestratedVM(
                name=name,
                config_path=Path(vm_config["config"]) if "config" in vm_config else None,
                template=vm_config.get("template"),
                depends_on=vm_config.get("depends_on", []),
                health_check=vm_config.get("health_check"),
                environment=vm_config.get("environment", {}),
                volumes=vm_config.get("volumes", {}),
                vm_overrides=vm_config.get("vm", {}),
            )

        # Calculate start order using topological sort
        start_order = self._topological_sort(vms)
        # Stop order is reverse
        stop_order = [list(reversed(group)) for group in reversed(start_order)]

        return OrchestrationPlan(
            vms=vms,
            start_order=start_order,
            stop_order=stop_order,
            volumes=self.config.get("volumes", {}),
            networks=self.config.get("networks", {}),
            defaults=defaults,
        )

    def _topological_sort(self, vms: Dict[str, OrchestratedVM]) -> List[List[str]]:
        """
        Topological sort with parallel group detection.
        Returns list of groups, where VMs in same group can start in parallel.
        """
        # Build dependency graph
        in_degree: Dict[str, int] = {name: 0 for name in vms}
        dependents: Dict[str, List[str]] = defaultdict(list)

        for name, vm in vms.items():
            for dep in vm.depends_on:
                if dep not in vms:
                    raise ValueError(f"VM '{name}' depends on unknown VM '{dep}'")
                in_degree[name] += 1
                dependents[dep].append(name)

        # Kahn's algorithm with level tracking
        levels: List[List[str]] = []
        current_level = [name for name, degree in in_degree.items() if degree == 0]

        while current_level:
            levels.append(sorted(current_level))  # Sort for deterministic order
            next_level: List[str] = []

            for name in current_level:
                for dependent in dependents[name]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_level.append(dependent)

            current_level = next_level

        # Check for cycles
        if sum(len(level) for level in levels) != len(vms):
            raise ValueError("Circular dependency detected in VM configuration")

        return levels

    def _get_vms_with_dependencies(self, services: List[str]) -> Set[str]:
        """Get VMs and all their dependencies."""
        to_include: Set[str] = set()
        to_process = list(services)

        while to_process:
            vm_name = to_process.pop()
            if vm_name in to_include:
                continue
            if vm_name not in self.plan.vms:
                raise ValueError(f"Unknown VM: {vm_name}")

            to_include.add(vm_name)
            vm = self.plan.vms[vm_name]
            to_process.extend(vm.depends_on)

        return to_include

    def _start_vm(self, vm_name: str, console: Optional[Any] = None) -> bool:
        """Start a single VM."""
        vm = self.plan.vms[vm_name]

        with self._lock:
            vm.state = VMOrchestrationState.CREATING
            vm.start_time = time.time()

        try:
            # Load VM config
            if vm.config_path and vm.config_path.exists():
                from clonebox.cli import load_clonebox_config, create_vm_from_config
                config = load_clonebox_config(vm.config_path)

                # Apply overrides from compose file
                if vm.vm_overrides:
                    if "vm" in config:
                        config["vm"].update(vm.vm_overrides)
                    else:
                        config.update(vm.vm_overrides)

                # Apply environment variables
                if vm.environment:
                    config.setdefault("environment", {}).update(vm.environment)

                # Create VM
                with self._lock:
                    vm.state = VMOrchestrationState.STARTING

                create_vm_from_config(
                    config,
                    start=True,
                    user_session=self.user_session,
                    replace=False,
                )

            elif vm.template:
                # TODO: Support template-based VM creation
                raise NotImplementedError(f"Template-based VMs not yet implemented: {vm.template}")

            else:
                raise ValueError(f"VM '{vm_name}' has neither config nor template")

            with self._lock:
                vm.state = VMOrchestrationState.RUNNING

            # Run health check if configured
            if vm.health_check:
                if self._run_health_check(vm_name):
                    with self._lock:
                        vm.state = VMOrchestrationState.HEALTHY
                        vm.health_check_passed = True
                else:
                    with self._lock:
                        vm.state = VMOrchestrationState.UNHEALTHY

            return True

        except Exception as e:
            with self._lock:
                vm.state = VMOrchestrationState.FAILED
                vm.error = str(e)
            return False

    def _stop_vm(self, vm_name: str, force: bool = False, console: Optional[Any] = None) -> bool:
        """Stop a single VM."""
        vm = self.plan.vms[vm_name]

        with self._lock:
            vm.state = VMOrchestrationState.STOPPING

        try:
            self.cloner.stop_vm(vm_name, force=force, console=console)

            with self._lock:
                vm.state = VMOrchestrationState.STOPPED

            return True

        except Exception as e:
            with self._lock:
                vm.error = str(e)
            return False

    def _run_health_check(self, vm_name: str, timeout: int = 60) -> bool:
        """Run health check for a VM."""
        vm = self.plan.vms[vm_name]
        if not vm.health_check:
            return True

        check_type = vm.health_check.get("type", "tcp")
        check_timeout = vm.health_check.get("timeout", "30s")

        # Parse timeout
        if isinstance(check_timeout, str):
            if check_timeout.endswith("s"):
                timeout = int(check_timeout[:-1])
            elif check_timeout.endswith("m"):
                timeout = int(check_timeout[:-1]) * 60

        conn_uri = "qemu:///session" if self.user_session else "qemu:///system"
        start = time.time()

        while time.time() - start < timeout:
            try:
                from clonebox.cli import _qga_exec

                if check_type == "tcp":
                    port = vm.health_check.get("port", 22)
                    result = _qga_exec(
                        vm_name, conn_uri,
                        f"timeout 5 bash -c 'echo > /dev/tcp/localhost/{port}' 2>/dev/null && echo OK || echo FAIL",
                        timeout=10
                    )
                    if result and "OK" in result:
                        return True

                elif check_type == "http":
                    url = vm.health_check.get("url", "http://localhost/health")
                    result = _qga_exec(
                        vm_name, conn_uri,
                        f"curl -s -o /dev/null -w '%{{http_code}}' '{url}' 2>/dev/null",
                        timeout=10
                    )
                    if result:
                        status_code = int(result.strip())
                        expected = vm.health_check.get("expected_status", [200])
                        if isinstance(expected, int):
                            expected = [expected]
                        if status_code in expected:
                            return True

                elif check_type == "command":
                    cmd = vm.health_check.get("exec", "true")
                    expected_output = vm.health_check.get("expected_output")
                    result = _qga_exec(vm_name, conn_uri, cmd, timeout=10)
                    if result is not None:
                        if expected_output:
                            if expected_output in result:
                                return True
                        else:
                            return True

            except Exception:
                pass

            time.sleep(2)

        return False

    def up(
        self,
        services: Optional[List[str]] = None,
        parallel: bool = True,
        console: Optional[Any] = None,
    ) -> OrchestrationResult:
        """
        Start VMs in dependency order.

        Args:
            services: Specific VMs to start (and their dependencies)
            parallel: If True, start independent VMs in parallel
            console: Rich console for output

        Returns:
            OrchestrationResult with final states
        """
        from clonebox.audit import get_audit_logger, AuditEventType, AuditOutcome

        start_time = time.time()
        audit = get_audit_logger()

        # Determine which VMs to start
        if services:
            to_start = self._get_vms_with_dependencies(services)
        else:
            to_start = set(self.plan.vms.keys())

        errors: Dict[str, str] = {}

        with audit.operation(AuditEventType.VM_START, "orchestration", "compose") as ctx:
            ctx.add_detail("vms", list(to_start))
            ctx.add_detail("parallel", parallel)

            self._executor = ThreadPoolExecutor(max_workers=self.max_workers if parallel else 1)

            try:
                for level in self.plan.start_order:
                    # Filter to VMs we want to start
                    level_vms = [vm for vm in level if vm in to_start]
                    if not level_vms:
                        continue

                    if parallel:
                        # Start all VMs in this level in parallel
                        futures: Dict[Future, str] = {}
                        for vm_name in level_vms:
                            future = self._executor.submit(self._start_vm, vm_name, console)
                            futures[future] = vm_name

                        # Wait for all to complete
                        for future in as_completed(futures):
                            vm_name = futures[future]
                            try:
                                success = future.result()
                                if not success:
                                    vm = self.plan.vms[vm_name]
                                    errors[vm_name] = vm.error or "Unknown error"
                            except Exception as e:
                                errors[vm_name] = str(e)

                    else:
                        # Start sequentially
                        for vm_name in level_vms:
                            success = self._start_vm(vm_name, console)
                            if not success:
                                vm = self.plan.vms[vm_name]
                                errors[vm_name] = vm.error or "Unknown error"

            finally:
                self._executor.shutdown(wait=True)
                self._executor = None

        duration = time.time() - start_time
        states = {name: vm.state for name, vm in self.plan.vms.items()}

        return OrchestrationResult(
            success=len(errors) == 0,
            states=states,
            errors=errors,
            duration_seconds=duration,
        )

    def down(
        self,
        services: Optional[List[str]] = None,
        force: bool = False,
        console: Optional[Any] = None,
    ) -> OrchestrationResult:
        """
        Stop VMs in reverse dependency order.

        Args:
            services: Specific VMs to stop
            force: Force stop if graceful fails
            console: Rich console for output

        Returns:
            OrchestrationResult with final states
        """
        from clonebox.audit import get_audit_logger, AuditEventType

        start_time = time.time()
        audit = get_audit_logger()

        # Determine which VMs to stop
        if services:
            to_stop = set(services)
        else:
            to_stop = set(self.plan.vms.keys())

        errors: Dict[str, str] = {}

        with audit.operation(AuditEventType.VM_STOP, "orchestration", "compose") as ctx:
            ctx.add_detail("vms", list(to_stop))
            ctx.add_detail("force", force)

            for level in self.plan.stop_order:
                level_vms = [vm for vm in level if vm in to_stop]
                for vm_name in level_vms:
                    success = self._stop_vm(vm_name, force=force, console=console)
                    if not success:
                        vm = self.plan.vms[vm_name]
                        errors[vm_name] = vm.error or "Unknown error"

        duration = time.time() - start_time
        states = {name: vm.state for name, vm in self.plan.vms.items()}

        return OrchestrationResult(
            success=len(errors) == 0,
            states=states,
            errors=errors,
            duration_seconds=duration,
        )

    def restart(
        self,
        services: Optional[List[str]] = None,
        console: Optional[Any] = None,
    ) -> OrchestrationResult:
        """Restart VMs (down then up)."""
        down_result = self.down(services=services, console=console)
        if not down_result.success:
            return down_result
        return self.up(services=services, console=console)

    def status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all VMs in the orchestration."""
        result: Dict[str, Dict[str, Any]] = {}

        for name, vm in self.plan.vms.items():
            # Try to get actual VM state from libvirt
            try:
                vm_info = self.cloner.get_vm_info(name)
                actual_state = vm_info.get("state", "unknown") if vm_info else "not_found"
            except Exception:
                actual_state = "unknown"

            result[name] = {
                "name": name,
                "orchestration_state": vm.state.value,
                "actual_state": actual_state,
                "depends_on": vm.depends_on,
                "health_check_passed": vm.health_check_passed,
                "error": vm.error,
                "ip_address": vm.ip_address,
            }

        return result

    def logs(self, vm_name: str, follow: bool = False, lines: int = 100) -> Optional[str]:
        """Get logs from a VM."""
        if vm_name not in self.plan.vms:
            raise ValueError(f"Unknown VM: {vm_name}")

        conn_uri = "qemu:///session" if self.user_session else "qemu:///system"

        try:
            from clonebox.cli import _qga_exec
            cmd = f"journalctl -n {lines}" if not follow else "journalctl -f"
            return _qga_exec(vm_name, conn_uri, cmd, timeout=30)
        except Exception:
            return None

    def exec(self, vm_name: str, command: str, timeout: int = 30) -> Optional[str]:
        """Execute command in a VM."""
        if vm_name not in self.plan.vms:
            raise ValueError(f"Unknown VM: {vm_name}")

        conn_uri = "qemu:///session" if self.user_session else "qemu:///system"

        try:
            from clonebox.cli import _qga_exec
            return _qga_exec(vm_name, conn_uri, command, timeout=timeout)
        except Exception:
            return None


def load_compose_file(path: Path) -> Dict[str, Any]:
    """Load and validate a compose file."""
    with open(path) as f:
        config = yaml.safe_load(f)

    version = config.get("version", "1")
    if version not in ("1", 1):
        raise ValueError(f"Unsupported compose version: {version}")

    if "vms" not in config:
        raise ValueError("Compose file must define 'vms' section")

    return config
