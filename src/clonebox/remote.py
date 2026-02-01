"""
Remote VM management for CloneBox.
Execute CloneBox operations on remote hosts via SSH.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse
import json
import subprocess
import tempfile


@dataclass
class RemoteConnection:
    """Remote libvirt connection configuration."""
    uri: str
    ssh_key: Optional[Path] = None
    ssh_user: Optional[str] = None
    ssh_host: Optional[str] = None
    ssh_port: int = 22

    @classmethod
    def from_string(cls, connection_string: str) -> "RemoteConnection":
        """
        Parse connection string.

        Formats:
        - qemu+ssh://user@host/system
        - qemu+ssh://user@host:port/system
        - user@host
        - user@host:port
        - ssh://user@host
        """
        if connection_string.startswith("qemu"):
            parsed = urlparse(connection_string)
            return cls(
                uri=connection_string,
                ssh_user=parsed.username,
                ssh_host=parsed.hostname,
                ssh_port=parsed.port or 22,
            )

        # Parse SSH-style connection
        if "@" in connection_string:
            user, host = connection_string.split("@", 1)
        else:
            user, host = None, connection_string

        # Extract port if present
        port = 22
        if ":" in host:
            host, port_str = host.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                pass

        uri = f"qemu+ssh://{user}@{host}/system" if user else f"qemu+ssh://{host}/system"

        return cls(
            uri=uri,
            ssh_user=user,
            ssh_host=host,
            ssh_port=port,
        )

    def get_libvirt_uri(self) -> str:
        """Get the libvirt connection URI."""
        return self.uri

    def get_ssh_target(self) -> str:
        """Get SSH connection target (user@host)."""
        if self.ssh_user and self.ssh_host:
            return f"{self.ssh_user}@{self.ssh_host}"
        elif self.ssh_host:
            return self.ssh_host
        else:
            parsed = urlparse(self.uri)
            if parsed.username and parsed.hostname:
                return f"{parsed.username}@{parsed.hostname}"
            return parsed.hostname or ""


@dataclass
class RemoteCommandResult:
    """Result of a remote command execution."""
    success: bool
    stdout: str
    stderr: str
    returncode: int


class RemoteCloner:
    """
    Execute CloneBox operations on remote hosts.

    Usage:
        remote = RemoteCloner("user@server")
        remote.list_vms()
        remote.create_vm(config)
        remote.start_vm("my-vm")
    """

    def __init__(
        self,
        connection: str | RemoteConnection,
        ssh_key: Optional[Path] = None,
        verify: bool = True,
    ):
        if isinstance(connection, str):
            self.connection = RemoteConnection.from_string(connection)
        else:
            self.connection = connection

        if ssh_key:
            self.connection.ssh_key = ssh_key

        if verify:
            self._verify_connection()

    def _verify_connection(self) -> None:
        """Verify SSH connection to remote host."""
        result = self._run_remote(["echo", "ok"], timeout=10)

        if not result.success:
            raise ConnectionError(
                f"Cannot connect to {self.connection.get_ssh_target()}: {result.stderr}"
            )

    def _build_ssh_command(self) -> List[str]:
        """Build base SSH command with options."""
        ssh_cmd = ["ssh"]

        # Connection options
        ssh_cmd.extend(["-o", "ConnectTimeout=10"])
        ssh_cmd.extend(["-o", "StrictHostKeyChecking=accept-new"])
        ssh_cmd.extend(["-o", "BatchMode=yes"])

        # SSH key
        if self.connection.ssh_key:
            ssh_cmd.extend(["-i", str(self.connection.ssh_key)])

        # Port
        if self.connection.ssh_port != 22:
            ssh_cmd.extend(["-p", str(self.connection.ssh_port)])

        # Target
        ssh_cmd.append(self.connection.get_ssh_target())

        return ssh_cmd

    def _run_remote(
        self,
        command: List[str],
        timeout: Optional[int] = None,
    ) -> RemoteCommandResult:
        """Run a command on the remote host."""
        ssh_cmd = self._build_ssh_command()
        ssh_cmd.extend(command)

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return RemoteCommandResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return RemoteCommandResult(
                success=False,
                stdout="",
                stderr="Command timed out",
                returncode=-1,
            )
        except Exception as e:
            return RemoteCommandResult(
                success=False,
                stdout="",
                stderr=str(e),
                returncode=-1,
            )

    def _run_clonebox(
        self,
        args: List[str],
        timeout: Optional[int] = None,
    ) -> RemoteCommandResult:
        """Run a clonebox command on the remote host."""
        return self._run_remote(["clonebox"] + args, timeout=timeout)

    def is_clonebox_installed(self) -> bool:
        """Check if CloneBox is installed on remote host."""
        result = self._run_remote(["which", "clonebox"], timeout=10)
        return result.success

    def get_clonebox_version(self) -> Optional[str]:
        """Get CloneBox version on remote host."""
        result = self._run_clonebox(["--version"], timeout=10)
        if result.success:
            return result.stdout.strip()
        return None

    def list_vms(self, user_session: bool = False) -> List[Dict[str, Any]]:
        """List VMs on remote host."""
        args = ["list", "--json"]
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=30)

        if not result.success:
            raise RuntimeError(f"Failed to list VMs: {result.stderr}")

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            # Try to parse line by line if not JSON
            vms = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    vms.append({"name": line.strip()})
            return vms

    def get_status(
        self,
        vm_name: str,
        user_session: bool = False,
    ) -> Dict[str, Any]:
        """Get VM status on remote host."""
        args = ["status", vm_name]
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=30)

        if not result.success:
            raise RuntimeError(f"Failed to get status: {result.stderr}")

        # Try to parse as JSON, otherwise return raw
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw_output": result.stdout, "status": "unknown"}

    def create_vm(
        self,
        config: Dict[str, Any],
        start: bool = True,
        user_session: bool = False,
    ) -> str:
        """Create VM on remote host from config dict."""
        import yaml

        # Write config to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(config, f)
            local_config = Path(f.name)

        try:
            # Copy config to remote
            remote_config = f"/tmp/clonebox-{local_config.stem}.yaml"
            self._copy_to_remote(local_config, remote_config)

            # Create VM
            args = ["clone", remote_config]
            if start:
                args.append("--run")
            if user_session:
                args.append("--user")

            result = self._run_clonebox(args, timeout=600)

            if not result.success:
                raise RuntimeError(f"Failed to create VM: {result.stderr}")

            return result.stdout.strip()

        finally:
            local_config.unlink(missing_ok=True)

    def create_vm_from_file(
        self,
        config_path: Path,
        start: bool = True,
        user_session: bool = False,
    ) -> str:
        """Create VM on remote host from local config file."""
        # Copy config to remote
        remote_config = f"/tmp/clonebox-{config_path.name}"
        self._copy_to_remote(config_path, remote_config)

        # Create VM
        args = ["clone", remote_config]
        if start:
            args.append("--run")
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=600)

        if not result.success:
            raise RuntimeError(f"Failed to create VM: {result.stderr}")

        return result.stdout.strip()

    def start_vm(
        self,
        vm_name: str,
        user_session: bool = False,
    ) -> None:
        """Start VM on remote host."""
        args = ["start", vm_name]
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=60)
        if not result.success:
            raise RuntimeError(f"Failed to start VM: {result.stderr}")

    def stop_vm(
        self,
        vm_name: str,
        force: bool = False,
        user_session: bool = False,
    ) -> None:
        """Stop VM on remote host."""
        args = ["stop", vm_name]
        if force:
            args.append("--force")
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=60)
        if not result.success:
            raise RuntimeError(f"Failed to stop VM: {result.stderr}")

    def restart_vm(
        self,
        vm_name: str,
        user_session: bool = False,
    ) -> None:
        """Restart VM on remote host."""
        args = ["restart", vm_name]
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=120)
        if not result.success:
            raise RuntimeError(f"Failed to restart VM: {result.stderr}")

    def delete_vm(
        self,
        vm_name: str,
        keep_storage: bool = False,
        user_session: bool = False,
    ) -> None:
        """Delete VM on remote host."""
        args = ["delete", vm_name, "--yes"]
        if keep_storage:
            args.append("--keep-storage")
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=60)
        if not result.success:
            raise RuntimeError(f"Failed to delete VM: {result.stderr}")

    def exec_in_vm(
        self,
        vm_name: str,
        command: str,
        timeout: int = 30,
        user_session: bool = False,
    ) -> str:
        """Execute command in VM on remote host."""
        args = ["exec", vm_name, "--timeout", str(timeout)]
        if user_session:
            args.append("--user")
        args.extend(["--", command])

        result = self._run_clonebox(args, timeout=timeout + 30)
        if not result.success:
            raise RuntimeError(f"Failed to exec in VM: {result.stderr}")

        return result.stdout

    def snapshot_create(
        self,
        vm_name: str,
        snapshot_name: str,
        description: Optional[str] = None,
        user_session: bool = False,
    ) -> None:
        """Create snapshot on remote host."""
        args = ["snapshot", "create", vm_name, "--name", snapshot_name]
        if description:
            args.extend(["--description", description])
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=120)
        if not result.success:
            raise RuntimeError(f"Failed to create snapshot: {result.stderr}")

    def snapshot_restore(
        self,
        vm_name: str,
        snapshot_name: str,
        user_session: bool = False,
    ) -> None:
        """Restore snapshot on remote host."""
        args = ["snapshot", "restore", vm_name, "--name", snapshot_name]
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=120)
        if not result.success:
            raise RuntimeError(f"Failed to restore snapshot: {result.stderr}")

    def snapshot_list(
        self,
        vm_name: str,
        user_session: bool = False,
    ) -> List[Dict[str, Any]]:
        """List snapshots on remote host."""
        args = ["snapshot", "list", vm_name]
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=30)
        if not result.success:
            raise RuntimeError(f"Failed to list snapshots: {result.stderr}")

        # Parse output
        snapshots = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                snapshots.append({"name": line.strip()})
        return snapshots

    def health_check(
        self,
        vm_name: str,
        user_session: bool = False,
    ) -> Dict[str, Any]:
        """Run health check on remote host."""
        args = ["health", vm_name]
        if user_session:
            args.append("--user")

        result = self._run_clonebox(args, timeout=120)

        return {
            "success": result.success,
            "output": result.stdout,
            "errors": result.stderr if not result.success else None,
        }

    def _copy_to_remote(self, local_path: Path, remote_path: str) -> None:
        """Copy file to remote host."""
        scp_cmd = ["scp"]

        if self.connection.ssh_key:
            scp_cmd.extend(["-i", str(self.connection.ssh_key)])

        if self.connection.ssh_port != 22:
            scp_cmd.extend(["-P", str(self.connection.ssh_port)])

        scp_cmd.append(str(local_path))
        scp_cmd.append(f"{self.connection.get_ssh_target()}:{remote_path}")

        result = subprocess.run(scp_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to copy file: {result.stderr}")

    def _copy_from_remote(self, remote_path: str, local_path: Path) -> None:
        """Copy file from remote host."""
        scp_cmd = ["scp"]

        if self.connection.ssh_key:
            scp_cmd.extend(["-i", str(self.connection.ssh_key)])

        if self.connection.ssh_port != 22:
            scp_cmd.extend(["-P", str(self.connection.ssh_port)])

        scp_cmd.append(f"{self.connection.get_ssh_target()}:{remote_path}")
        scp_cmd.append(str(local_path))

        result = subprocess.run(scp_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to copy file: {result.stderr}")


def connect(connection_string: str, **kwargs) -> RemoteCloner:
    """
    Convenience function to create a RemoteCloner.

    Usage:
        remote = connect("user@server")
        vms = remote.list_vms()
    """
    return RemoteCloner(connection_string, **kwargs)
