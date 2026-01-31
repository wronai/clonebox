import json
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest


@pytest.mark.e2e
@pytest.mark.container
def test_container_full_workflow(tmp_path):
    """E2E: clonebox container up → ps → stop → rm."""

    engine = None
    if shutil.which("podman") is not None:
        engine = "podman"
    elif shutil.which("docker") is not None:
        engine = "docker"

    if engine is None:
        pytest.skip("podman/docker not available")

    (tmp_path / "test.py").write_text("print('Hello from container!')\n")

    name = f"clonebox-test-{uuid4().hex[:8]}"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "clonebox",
            "container",
            "up",
            str(tmp_path),
            "--engine",
            engine,
            "--name",
            name,
            "--detach",
        ],
        check=True,
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clonebox",
            "container",
            "ps",
            "--engine",
            engine,
            "--json",
            "-a",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    containers = json.loads(result.stdout or "[]")
    assert any(c.get("name") == name for c in containers)

    subprocess.run(
        [sys.executable, "-m", "clonebox", "container", "stop", "--engine", engine, name],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "clonebox", "container", "rm", "--engine", engine, name],
        check=True,
    )
