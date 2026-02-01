"""Tests for multi-VM orchestrator module."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from clonebox.orchestrator import (
    Orchestrator,
    OrchestrationPlan,
    OrchestrationResult,
    OrchestratedVM,
    VMOrchestrationState,
    load_compose_file,
)


class TestOrchestratedVM:
    """Test OrchestratedVM dataclass."""

    def test_create_vm(self):
        """Test creating an orchestrated VM."""
        vm = OrchestratedVM(
            name="test-vm",
            config_path=Path("/path/to/config.yaml"),
            depends_on=["other-vm"],
        )

        assert vm.name == "test-vm"
        assert vm.depends_on == ["other-vm"]
        assert vm.state == VMOrchestrationState.PENDING

    def test_vm_with_health_check(self):
        """Test VM with health check configuration."""
        vm = OrchestratedVM(
            name="test-vm",
            health_check={"type": "http", "url": "http://localhost:8080/health"},
        )

        assert vm.health_check["type"] == "http"
        assert vm.health_check_passed is False


class TestOrchestrator:
    """Test Orchestrator class."""

    @pytest.fixture
    def simple_compose(self, tmp_path):
        """Create a simple compose file."""
        compose = {
            "version": "1",
            "vms": {
                "frontend": {
                    "config": "./frontend/.clonebox.yaml",
                    "depends_on": ["backend"],
                },
                "backend": {
                    "config": "./backend/.clonebox.yaml",
                    "depends_on": ["database"],
                },
                "database": {
                    "config": "./db/.clonebox.yaml",
                },
            },
        }
        compose_path = tmp_path / "clonebox-compose.yaml"
        with open(compose_path, "w") as f:
            yaml.dump(compose, f)
        return compose_path

    @pytest.fixture
    def circular_compose(self, tmp_path):
        """Create a compose file with circular dependency."""
        compose = {
            "version": "1",
            "vms": {
                "a": {"config": "./a/.clonebox.yaml", "depends_on": ["b"]},
                "b": {"config": "./b/.clonebox.yaml", "depends_on": ["c"]},
                "c": {"config": "./c/.clonebox.yaml", "depends_on": ["a"]},
            },
        }
        compose_path = tmp_path / "circular.yaml"
        with open(compose_path, "w") as f:
            yaml.dump(compose, f)
        return compose_path

    def test_load_compose_file(self, simple_compose):
        """Test loading compose file."""
        config = load_compose_file(simple_compose)

        assert config["version"] == "1"
        assert "frontend" in config["vms"]
        assert "backend" in config["vms"]
        assert "database" in config["vms"]

    def test_load_invalid_version(self, tmp_path):
        """Test loading compose file with invalid version."""
        compose = {"version": "99", "vms": {}}
        compose_path = tmp_path / "invalid.yaml"
        with open(compose_path, "w") as f:
            yaml.dump(compose, f)

        with pytest.raises(ValueError, match="Unsupported compose version"):
            load_compose_file(compose_path)

    def test_orchestrator_from_file(self, simple_compose):
        """Test creating orchestrator from file."""
        orch = Orchestrator.from_file(simple_compose, user_session=True)

        assert orch.user_session is True
        assert len(orch.plan.vms) == 3

    def test_topological_sort(self, simple_compose):
        """Test dependency ordering."""
        orch = Orchestrator.from_file(simple_compose)

        # database should be first (no deps)
        # backend should be second (depends on database)
        # frontend should be last (depends on backend)
        start_order = orch.plan.start_order

        # Find indices
        db_level = next(i for i, level in enumerate(start_order) if "database" in level)
        be_level = next(i for i, level in enumerate(start_order) if "backend" in level)
        fe_level = next(i for i, level in enumerate(start_order) if "frontend" in level)

        assert db_level < be_level < fe_level

    def test_stop_order_is_reverse(self, simple_compose):
        """Test that stop order is reverse of start order."""
        orch = Orchestrator.from_file(simple_compose)

        # Flatten orders
        start_flat = [vm for level in orch.plan.start_order for vm in level]
        stop_flat = [vm for level in orch.plan.stop_order for vm in level]

        # Stop order should be reverse
        assert stop_flat == list(reversed(start_flat))

    def test_circular_dependency_detection(self, circular_compose):
        """Test that circular dependencies are detected."""
        with pytest.raises(ValueError, match="Circular dependency"):
            Orchestrator.from_file(circular_compose)

    def test_unknown_dependency(self, tmp_path):
        """Test that unknown dependencies are detected."""
        compose = {
            "version": "1",
            "vms": {
                "a": {"config": "./a/.clonebox.yaml", "depends_on": ["nonexistent"]},
            },
        }
        compose_path = tmp_path / "unknown.yaml"
        with open(compose_path, "w") as f:
            yaml.dump(compose, f)

        with pytest.raises(ValueError, match="unknown VM"):
            Orchestrator.from_file(compose_path)

    def test_get_vms_with_dependencies(self, simple_compose):
        """Test getting VMs with their dependencies."""
        orch = Orchestrator.from_file(simple_compose)

        # Requesting frontend should include backend and database
        vms = orch._get_vms_with_dependencies(["frontend"])

        assert "frontend" in vms
        assert "backend" in vms
        assert "database" in vms

    def test_get_vms_with_dependencies_single(self, simple_compose):
        """Test getting single VM without dependencies."""
        orch = Orchestrator.from_file(simple_compose)

        vms = orch._get_vms_with_dependencies(["database"])

        assert "database" in vms
        assert "frontend" not in vms
        assert "backend" not in vms

    def test_status(self, simple_compose):
        """Test getting orchestration status."""
        orch = Orchestrator.from_file(simple_compose)

        # Mock cloner
        mock_cloner = MagicMock()
        mock_cloner.get_vm_info.return_value = {"state": "running"}
        orch._cloner = mock_cloner

        status = orch.status()

        assert "frontend" in status
        assert "backend" in status
        assert "database" in status
        assert status["frontend"]["orchestration_state"] == "pending"


class TestOrchestrationPlan:
    """Test OrchestrationPlan dataclass."""

    def test_plan_creation(self):
        """Test creating an orchestration plan."""
        vms = {
            "vm1": OrchestratedVM(name="vm1"),
            "vm2": OrchestratedVM(name="vm2", depends_on=["vm1"]),
        }

        plan = OrchestrationPlan(
            vms=vms,
            start_order=[["vm1"], ["vm2"]],
            stop_order=[["vm2"], ["vm1"]],
            volumes={},
            networks={},
            defaults={},
        )

        assert len(plan.vms) == 2
        assert plan.start_order == [["vm1"], ["vm2"]]
        assert plan.stop_order == [["vm2"], ["vm1"]]


class TestOrchestrationResult:
    """Test OrchestrationResult dataclass."""

    def test_successful_result(self):
        """Test successful orchestration result."""
        result = OrchestrationResult(
            success=True,
            states={"vm1": VMOrchestrationState.RUNNING},
            errors={},
            duration_seconds=5.5,
        )

        assert result.success is True
        assert result.duration_seconds == 5.5

    def test_failed_result(self):
        """Test failed orchestration result."""
        result = OrchestrationResult(
            success=False,
            states={"vm1": VMOrchestrationState.FAILED},
            errors={"vm1": "Connection failed"},
            duration_seconds=2.0,
        )

        assert result.success is False
        assert "vm1" in result.errors


class TestParallelStartGroups:
    """Test parallel start group detection."""

    def test_independent_vms_same_group(self, tmp_path):
        """Test that independent VMs are in the same start group."""
        compose = {
            "version": "1",
            "vms": {
                "a": {"config": "./a/.clonebox.yaml"},
                "b": {"config": "./b/.clonebox.yaml"},
                "c": {"config": "./c/.clonebox.yaml"},
            },
        }
        compose_path = tmp_path / "parallel.yaml"
        with open(compose_path, "w") as f:
            yaml.dump(compose, f)

        orch = Orchestrator.from_file(compose_path)

        # All should be in the same start group
        assert len(orch.plan.start_order) == 1
        assert set(orch.plan.start_order[0]) == {"a", "b", "c"}

    def test_mixed_dependencies(self, tmp_path):
        """Test complex dependency graph."""
        # Graph:
        # a -> c
        # b -> c
        # c (no deps)
        # d -> a, b
        compose = {
            "version": "1",
            "vms": {
                "a": {"config": "./a/.clonebox.yaml", "depends_on": ["c"]},
                "b": {"config": "./b/.clonebox.yaml", "depends_on": ["c"]},
                "c": {"config": "./c/.clonebox.yaml"},
                "d": {"config": "./d/.clonebox.yaml", "depends_on": ["a", "b"]},
            },
        }
        compose_path = tmp_path / "mixed.yaml"
        with open(compose_path, "w") as f:
            yaml.dump(compose, f)

        orch = Orchestrator.from_file(compose_path)

        # Level 0: c
        # Level 1: a, b (can be parallel)
        # Level 2: d
        assert len(orch.plan.start_order) == 3
        assert orch.plan.start_order[0] == ["c"]
        assert set(orch.plan.start_order[1]) == {"a", "b"}
        assert orch.plan.start_order[2] == ["d"]
