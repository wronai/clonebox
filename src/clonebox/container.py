#!/usr/bin/env python3

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from clonebox.models import ContainerConfig


class ContainerCloner:
    def __init__(self, engine: str = "auto"):
        self.engine = self._resolve_engine(engine)

    def _resolve_engine(self, engine: str) -> str:
        if engine == "auto":
            return self.detect_engine()
        if engine not in {"podman", "docker"}:
            raise ValueError("engine must be one of: auto, podman, docker")
        if shutil.which(engine) is None:
            raise RuntimeError(f"Container engine not found: {engine}")
        self._run([engine, "--version"], check=True)
        return engine

    def detect_engine(self) -> str:
        if shutil.which("podman") is not None:
            try:
                self._run(["podman", "--version"], check=True)
                return "podman"
            except Exception:
                pass

        if shutil.which("docker") is not None:
            try:
                self._run(["docker", "--version"], check=True)
                return "docker"
            except Exception:
                pass

        raise RuntimeError("No container engine found (podman/docker)")

    def _run(
        self,
        cmd: List[str],
        check: bool = True,
        capture_output: bool = True,
        text: bool = True,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, check=check, capture_output=capture_output, text=text)

    def build_dockerfile(self, config: ContainerConfig) -> str:
        lines: List[str] = [f"FROM {config.image}"]

        if config.packages:
            pkgs = " ".join(config.packages)
            lines.append(
                "RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y "
                + pkgs
                + " && rm -rf /var/lib/apt/lists/*"
            )

        lines.append("WORKDIR /workspace")
        lines.append('CMD ["bash"]')
        return "\n".join(lines) + "\n"

    def build_image(self, config: ContainerConfig, tag: Optional[str] = None) -> str:
        if tag is None:
            tag = f"{config.name}:latest"

        dockerfile = self.build_dockerfile(config)
        workspace = Path(config.workspace).resolve()

        with tempfile.NamedTemporaryFile(prefix="clonebox-dockerfile-", delete=False) as f:
            dockerfile_path = Path(f.name)
            f.write(dockerfile.encode())

        try:
            self._run(
                [
                    self.engine,
                    "build",
                    "-f",
                    str(dockerfile_path),
                    "-t",
                    tag,
                    str(workspace),
                ],
                check=True,
            )
        finally:
            try:
                dockerfile_path.unlink()
            except Exception:
                pass

        return tag

    def create_container(
        self,
        workspace_path: Path,
        name: str,
        image: str = "ubuntu:22.04",
        profile: Optional[str] = None,
        mounts: Optional[List[str]] = None,
        ports: Optional[List[str]] = None,
        packages: Optional[List[str]] = None,
        detach: bool = False,
        console=None,
    ) -> str:
        """Create and start a container."""
        from clonebox.models import ContainerConfig
        
        config = ContainerConfig(
            name=name,
            image=image,
            workspace=str(workspace_path),
            packages=packages or [],
            mounts=self._parse_mounts(mounts or []),
            ports=ports or [],
        )
        
        self.up(config, detach=detach, remove=False)
        return name

    def attach_container(self, container_id: str) -> None:
        """Attach to a running container."""
        subprocess.run([self.engine, "attach", container_id])

    def stop_container(self, container_id: str, console=None) -> None:
        """Stop a container."""
        self.stop(container_id)

    def list_containers(self, all: bool = True) -> List[Dict[str, Any]]:
        """List containers."""
        containers = self.ps(all=all)
        for c in containers:
            c["id"] = c.get("name", "")
            c["workspace"] = ""
        return containers

    def remove_container(self, container_id: str, console=None) -> None:
        """Remove a container."""
        self.rm(container_id, force=True)

    def _parse_mounts(self, mounts: List[str]) -> Dict[str, str]:
        """Parse mount strings into dict."""
        result = {}
        for mount in mounts:
            parts = mount.split(":")
            if len(parts) == 2:
                result[parts[0]] = parts[1]
            else:
                result[mount] = mount
        return result

    def up(self, config: ContainerConfig, detach: bool = False, remove: bool = True) -> None:
        engine = self._resolve_engine(config.engine if config.engine != "auto" else self.engine)

        image = config.image
        if config.packages:
            image = self.build_image(config)

        cmd: List[str] = [engine, "run"]
        cmd.append("-d" if detach else "-it")

        if remove:
            cmd.append("--rm")

        cmd.extend(["--name", config.name])
        cmd.extend(["-w", "/workspace"])

        env_file = Path(config.workspace) / ".env"
        if config.env_from_dotenv and env_file.exists():
            cmd.extend(["--env-file", str(env_file)])

        for src, dst in config.mounts.items():
            cmd.extend(["-v", f"{src}:{dst}"])

        for p in config.ports:
            cmd.extend(["-p", p])

        cmd.append(image)

        if detach:
            cmd.extend(["sleep", "infinity"])
        else:
            cmd.append("bash")

        subprocess.run(cmd, check=True)

    def stop(self, name: str) -> None:
        subprocess.run([self.engine, "stop", name], check=True)

    def rm(self, name: str, force: bool = False) -> None:
        cmd = [self.engine, "rm"]
        if force:
            cmd.append("-f")
        cmd.append(name)
        subprocess.run(cmd, check=True)

    def ps(self, all: bool = False) -> List[Dict[str, Any]]:
        if self.engine == "podman":
            cmd = ["podman", "ps", "--format", "json"]
            if all:
                cmd.append("-a")
            result = self._run(cmd, check=True)
            try:
                parsed = json.loads(result.stdout or "[]")
            except json.JSONDecodeError:
                return []

            items: List[Dict[str, Any]] = []
            for c in parsed:
                name = ""
                names = c.get("Names")
                if isinstance(names, list) and names:
                    name = str(names[0])
                elif isinstance(names, str):
                    name = names

                items.append(
                    {
                        "name": name,
                        "image": c.get("Image") or c.get("ImageName") or "",
                        "status": c.get("State") or c.get("Status") or "",
                        "ports": c.get("Ports") or [],
                    }
                )
            return items

        cmd = ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
        if all:
            cmd.insert(2, "-a")

        result = self._run(cmd, check=True)
        items: List[Dict[str, Any]] = []
        for line in (result.stdout or "").splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            name = parts[0] if len(parts) > 0 else ""
            image = parts[1] if len(parts) > 1 else ""
            status = parts[2] if len(parts) > 2 else ""
            ports = parts[3] if len(parts) > 3 else ""
            items.append({"name": name, "image": image, "status": status, "ports": ports})
        return items
