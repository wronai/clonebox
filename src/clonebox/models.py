#!/usr/bin/env python3
"""
Pydantic models for CloneBox configuration validation.
"""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class VMSettings(BaseModel):
    """VM-specific settings."""

    name: str = Field(default="clonebox-vm", description="VM name")
    ram_mb: int = Field(default=4096, ge=512, le=131072, description="RAM in MB")
    vcpus: int = Field(default=4, ge=1, le=128, description="Number of vCPUs")
    disk_size_gb: int = Field(default=10, ge=1, le=2048, description="Disk size in GB")
    gui: bool = Field(default=True, description="Enable SPICE graphics")
    base_image: Optional[str] = Field(default=None, description="Path to base qcow2 image")
    network_mode: str = Field(default="auto", description="Network mode: auto|default|user")
    username: str = Field(default="ubuntu", description="VM default username")
    password: str = Field(default="ubuntu", description="VM default password")

    @field_validator("name")
    @classmethod
    def name_must_be_valid(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("VM name cannot be empty")
        if len(v) > 64:
            raise ValueError("VM name must be <= 64 characters")
        return v.strip()

    @field_validator("network_mode")
    @classmethod
    def network_mode_must_be_valid(cls, v: str) -> str:
        valid_modes = {"auto", "default", "user"}
        if v not in valid_modes:
            raise ValueError(f"network_mode must be one of: {valid_modes}")
        return v


class CloneBoxConfig(BaseModel):
    """Complete CloneBox configuration with validation."""

    version: str = Field(default="1", description="Config version")
    generated: Optional[str] = Field(default=None, description="Generation timestamp")
    vm: VMSettings = Field(default_factory=VMSettings, description="VM settings")
    paths: Dict[str, str] = Field(default_factory=dict, description="Host:Guest path mappings")
    app_data_paths: Dict[str, str] = Field(
        default_factory=dict, description="Application data paths"
    )
    packages: List[str] = Field(default_factory=list, description="APT packages to install")
    snap_packages: List[str] = Field(default_factory=list, description="Snap packages to install")
    services: List[str] = Field(default_factory=list, description="Services to enable")
    post_commands: List[str] = Field(default_factory=list, description="Post-setup commands")
    detected: Optional[Dict[str, Any]] = Field(
        default=None, description="Auto-detected system info"
    )

    @field_validator("paths", "app_data_paths")
    @classmethod
    def paths_must_be_absolute(cls, v: Dict[str, str]) -> Dict[str, str]:
        for host_path, guest_path in v.items():
            if not host_path.startswith("/"):
                raise ValueError(f"Host path must be absolute: {host_path}")
            if not guest_path.startswith("/"):
                raise ValueError(f"Guest path must be absolute: {guest_path}")
        return v

    @model_validator(mode="before")
    @classmethod
    def handle_nested_vm(cls, data: Any) -> Any:
        """Handle both dict and nested vm structures."""
        if isinstance(data, dict):
            if "vm" in data and isinstance(data["vm"], dict):
                return data
            vm_fields = {"name", "ram_mb", "vcpus", "disk_size_gb", "gui", "base_image", 
                        "network_mode", "username", "password"}
            vm_data = {k: v for k, v in data.items() if k in vm_fields}
            if vm_data:
                data = {k: v for k, v in data.items() if k not in vm_fields}
                data["vm"] = vm_data
        return data

    def save(self, path: Path) -> None:
        """Save configuration to YAML file."""
        import yaml

        config_dict = self.model_dump(exclude_none=True)
        path.write_text(yaml.dump(config_dict, default_flow_style=False, sort_keys=False))

    @classmethod
    def load(cls, path: Path) -> "CloneBoxConfig":
        """Load configuration from YAML file."""
        import yaml

        if path.is_dir():
            path = path / ".clonebox.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        data = yaml.safe_load(path.read_text())
        return cls.model_validate(data)

    def to_vm_config(self) -> "VMConfigDataclass":
        """Convert to legacy VMConfig dataclass for compatibility."""
        from clonebox.cloner import VMConfig as VMConfigDataclass

        return VMConfigDataclass(
            name=self.vm.name,
            ram_mb=self.vm.ram_mb,
            vcpus=self.vm.vcpus,
            disk_size_gb=self.vm.disk_size_gb,
            gui=self.vm.gui,
            base_image=self.vm.base_image,
            paths=self.paths,
            packages=self.packages,
            snap_packages=self.snap_packages,
            services=self.services,
            post_commands=self.post_commands,
            network_mode=self.vm.network_mode,
            username=self.vm.username,
            password=self.vm.password,
        )


class ContainerConfig(BaseModel):
    name: str = Field(default_factory=lambda: f"clonebox-{uuid4().hex[:8]}")
    engine: Literal["auto", "podman", "docker"] = "auto"
    image: str = "ubuntu:22.04"
    workspace: Path = Path(".")
    extra_mounts: Dict[str, str] = Field(default_factory=dict)
    env_from_dotenv: bool = True
    packages: List[str] = Field(default_factory=list)
    ports: List[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def name_must_be_valid(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Container name cannot be empty")
        if len(v) > 64:
            raise ValueError("Container name must be <= 64 characters")
        return v.strip()

    @field_validator("extra_mounts")
    @classmethod
    def extra_mounts_must_be_absolute(cls, v: Dict[str, str]) -> Dict[str, str]:
        for host_path, container_path in v.items():
            if not str(host_path).startswith("/"):
                raise ValueError(f"Host path must be absolute: {host_path}")
            if not str(container_path).startswith("/"):
                raise ValueError(f"Container path must be absolute: {container_path}")
        return v

    @field_validator("ports")
    @classmethod
    def ports_must_be_valid(cls, v: List[str]) -> List[str]:
        for p in v:
            if not isinstance(p, str) or not p.strip():
                raise ValueError("Port mapping cannot be empty")
            if ":" in p:
                host, container = p.split(":", 1)
                if not host.isdigit() or not container.isdigit():
                    raise ValueError(f"Invalid port mapping: {p}")
            else:
                if not p.isdigit():
                    raise ValueError(f"Invalid port value: {p}")
        return v

    @property
    def mounts(self) -> Dict[str, str]:
        mounts: Dict[str, str] = {
            str(self.workspace.resolve()): "/workspace",
        }
        mounts.update(self.extra_mounts)
        return mounts

    def to_docker_run_cmd(self) -> List[str]:
        if self.engine == "auto":
            raise ValueError("engine must be resolved before generating run command")

        cmd: List[str] = [self.engine, "run", "-it", "--rm", "--name", self.name]

        for src, dst in self.mounts.items():
            cmd.extend(["-v", f"{src}:{dst}"])

        for p in self.ports:
            cmd.extend(["-p", p])

        cmd.append(self.image)
        return cmd


# Backwards compatibility alias
VMConfigModel = CloneBoxConfig
