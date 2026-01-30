#!/usr/bin/env python3

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clonebox.container import ContainerCloner
from clonebox.models import ContainerConfig


def _which_side_effect(mapping):
    def which(name):
        return mapping.get(name)

    return which


class TestContainerClonerEngineDetection:
    def test_detect_engine_prefers_podman(self, monkeypatch):
        monkeypatch.setattr(
            "clonebox.container.shutil.which",
            _which_side_effect({"podman": "/usr/bin/podman", "docker": "/usr/bin/docker"}),
        )

        def fake_run(self, cmd, check=True, capture_output=True, text=True):
            return MagicMock(returncode=0, stdout="podman version", stderr="")

        monkeypatch.setattr("clonebox.container.ContainerCloner._run", fake_run)

        c = ContainerCloner(engine="auto")
        assert c.engine == "podman"

    def test_detect_engine_fallbacks_to_docker(self, monkeypatch):
        monkeypatch.setattr(
            "clonebox.container.shutil.which",
            _which_side_effect({"podman": "/usr/bin/podman", "docker": "/usr/bin/docker"}),
        )

        def fake_run(self, cmd, check=True, capture_output=True, text=True):
            if cmd[0] == "podman":
                raise RuntimeError("podman broken")
            return MagicMock(returncode=0, stdout="docker version", stderr="")

        monkeypatch.setattr("clonebox.container.ContainerCloner._run", fake_run)

        c = ContainerCloner(engine="auto")
        assert c.engine == "docker"

    def test_detect_engine_errors_when_none_found(self, monkeypatch):
        monkeypatch.setattr(
            "clonebox.container.shutil.which",
            _which_side_effect({"podman": None, "docker": None}),
        )

        c = ContainerCloner.__new__(ContainerCloner)
        c.engine = "auto"
        with pytest.raises(RuntimeError, match="No container engine found"):
            c.detect_engine()


class TestContainerClonerBuild:
    def test_build_dockerfile_includes_packages(self, tmp_path):
        cfg = ContainerConfig(
            engine="podman",
            image="ubuntu:22.04",
            workspace=tmp_path,
            packages=["curl", "git"],
        )
        c = ContainerCloner.__new__(ContainerCloner)
        c.engine = "podman"

        dockerfile = c.build_dockerfile(cfg)
        assert "FROM ubuntu:22.04" in dockerfile
        assert "apt-get install -y curl git" in dockerfile
        assert "WORKDIR /workspace" in dockerfile

    def test_build_image_calls_engine_build(self, monkeypatch, tmp_path):
        (tmp_path / "file.txt").write_text("x")
        cfg = ContainerConfig(engine="podman", workspace=tmp_path, packages=["curl"])

        calls = []

        def fake_run(self, cmd, check=True, capture_output=True, text=True):
            calls.append(cmd)
            return MagicMock(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr("clonebox.container.ContainerCloner._run", fake_run)

        c = ContainerCloner.__new__(ContainerCloner)
        c.engine = "podman"

        tag = c.build_image(cfg, tag="myimg:latest")
        assert tag == "myimg:latest"
        assert calls
        cmd = calls[0]
        assert cmd[0] == "podman"
        assert cmd[1] == "build"
        assert "-t" in cmd and "myimg:latest" in cmd
        assert str(tmp_path.resolve()) == cmd[-1]

        dockerfile_path = Path(cmd[cmd.index("-f") + 1])
        assert not dockerfile_path.exists()


class TestContainerClonerUpAndPs:
    def test_up_runs_interactive_with_env_file(self, monkeypatch, tmp_path):
        (tmp_path / ".env").write_text("FOO=bar\n")

        cfg = ContainerConfig(engine="podman", name="test", workspace=tmp_path)

        monkeypatch.setattr(
            "clonebox.container.shutil.which", _which_side_effect({"podman": "/usr/bin/podman"})
        )

        def fake_run_version(self, cmd, check=True, capture_output=True, text=True):
            return MagicMock(returncode=0, stdout="podman version", stderr="")

        monkeypatch.setattr("clonebox.container.ContainerCloner._run", fake_run_version)

        called = {}

        def fake_subprocess_run(cmd, check=True):
            called["cmd"] = cmd
            return MagicMock(returncode=0)

        monkeypatch.setattr("clonebox.container.subprocess.run", fake_subprocess_run)

        c = ContainerCloner(engine="podman")
        c.up(cfg, detach=False)

        cmd = called["cmd"]
        assert cmd[0] == "podman"
        assert cmd[1] == "run"
        assert "--env-file" in cmd
        assert str(tmp_path / ".env") in cmd
        assert "-v" in cmd
        assert "bash" in cmd

    def test_up_detach_runs_sleep_infinity(self, monkeypatch, tmp_path):
        cfg = ContainerConfig(engine="podman", name="test", workspace=tmp_path)

        monkeypatch.setattr(
            "clonebox.container.shutil.which", _which_side_effect({"podman": "/usr/bin/podman"})
        )

        def fake_run_version(self, cmd, check=True, capture_output=True, text=True):
            return MagicMock(returncode=0, stdout="podman version", stderr="")

        monkeypatch.setattr("clonebox.container.ContainerCloner._run", fake_run_version)

        called = {}

        def fake_subprocess_run(cmd, check=True):
            called["cmd"] = cmd
            return MagicMock(returncode=0)

        monkeypatch.setattr("clonebox.container.subprocess.run", fake_subprocess_run)

        c = ContainerCloner(engine="podman")
        c.up(cfg, detach=True)

        cmd = called["cmd"]
        assert "-d" in cmd
        assert cmd[-2:] == ["sleep", "infinity"]

    def test_ps_docker_parses_tab_format(self, monkeypatch):
        def fake_run(self, cmd, check=True, capture_output=True, text=True):
            return MagicMock(
                returncode=0,
                stdout="c1\tubuntu:22.04\tUp 2 seconds\t0.0.0.0:8080->80/tcp\n",
                stderr="",
            )

        monkeypatch.setattr("clonebox.container.ContainerCloner._run", fake_run)

        c = ContainerCloner.__new__(ContainerCloner)
        c.engine = "docker"

        items = c.ps(all=False)
        assert len(items) == 1
        assert items[0]["name"] == "c1"
        assert items[0]["image"] == "ubuntu:22.04"

    def test_ps_podman_json_uses_a_when_all(self, monkeypatch):
        captured = {}

        def fake_run(self, cmd, check=True, capture_output=True, text=True):
            captured["cmd"] = cmd
            return MagicMock(
                returncode=0,
                stdout='[{"Names":["c1"],"Image":"ubuntu:22.04","State":"running","Ports":[]}]',
                stderr="",
            )

        monkeypatch.setattr("clonebox.container.ContainerCloner._run", fake_run)

        c = ContainerCloner.__new__(ContainerCloner)
        c.engine = "podman"

        items = c.ps(all=True)
        assert captured["cmd"][:3] == ["podman", "ps", "-a"]
        assert items[0]["name"] == "c1"


class TestContainerClonerStopRm:
    def test_stop_calls_engine(self, monkeypatch):
        called = {}

        def fake_subprocess_run(cmd, check=True):
            called["cmd"] = cmd
            return MagicMock(returncode=0)

        monkeypatch.setattr("clonebox.container.subprocess.run", fake_subprocess_run)

        c = ContainerCloner.__new__(ContainerCloner)
        c.engine = "podman"
        c.stop("c1")
        assert called["cmd"] == ["podman", "stop", "c1"]

    def test_rm_force_adds_f(self, monkeypatch):
        called = {}

        def fake_subprocess_run(cmd, check=True):
            called["cmd"] = cmd
            return MagicMock(returncode=0)

        monkeypatch.setattr("clonebox.container.subprocess.run", fake_subprocess_run)

        c = ContainerCloner.__new__(ContainerCloner)
        c.engine = "docker"
        c.rm("c1", force=True)
        assert called["cmd"] == ["docker", "rm", "-f", "c1"]
