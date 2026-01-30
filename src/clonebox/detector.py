#!/usr/bin/env python3
"""
SystemDetector - Detects running services, applications and important paths.
"""

import os
import subprocess
import pwd
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import psutil


@dataclass
class DetectedService:
    """A detected systemd service."""
    name: str
    status: str  # running, stopped, failed
    description: str = ""
    enabled: bool = False


@dataclass
class DetectedApplication:
    """A detected running application."""
    name: str
    pid: int
    cmdline: str
    exe: str
    working_dir: str = ""
    memory_mb: float = 0.0


@dataclass
class DetectedPath:
    """A detected important path."""
    path: str
    type: str  # config, data, project, home
    size_mb: float = 0.0
    description: str = ""


@dataclass
class SystemSnapshot:
    """Complete snapshot of detected system state."""
    services: list = field(default_factory=list)
    applications: list = field(default_factory=list)
    paths: list = field(default_factory=list)
    
    @property
    def running_services(self) -> list:
        return [s for s in self.services if s.status == "running"]
    
    @property
    def running_apps(self) -> list:
        return self.applications


class SystemDetector:
    """Detects running services, applications and important paths on the system."""
    
    # Common development/server services to look for
    INTERESTING_SERVICES = [
        "docker", "containerd", "podman",
        "nginx", "apache2", "httpd", "caddy",
        "postgresql", "mysql", "mariadb", "mongodb", "redis", "memcached",
        "elasticsearch", "kibana", "grafana", "prometheus",
        "jenkins", "gitlab-runner",
        "sshd", "rsync",
        "rabbitmq-server", "kafka",
        "nodejs", "pm2",
        "supervisor", "systemd-resolved",
        "cups", "bluetooth", "NetworkManager",
        "libvirtd", "virtlogd",
    ]
    
    # Interesting process names
    INTERESTING_PROCESSES = [
        "python", "python3", "node", "npm", "yarn", "pnpm",
        "java", "gradle", "mvn",
        "go", "cargo", "rustc",
        "docker", "docker-compose", "podman",
        "nginx", "apache", "httpd",
        "postgres", "mysql", "mongod", "redis-server",
        "code", "code-server", "cursor",
        "vim", "nvim", "emacs",
        "firefox", "chrome", "chromium",
        "jupyter", "jupyter-lab",
        "gunicorn", "uvicorn", "flask", "django",
        "webpack", "vite", "esbuild",
        "tmux", "screen",
    ]
    
    def __init__(self):
        self.user = pwd.getpwuid(os.getuid()).pw_name
        self.home = Path.home()
    
    def detect_all(self) -> SystemSnapshot:
        """Detect all services, applications and paths."""
        return SystemSnapshot(
            services=self.detect_services(),
            applications=self.detect_applications(),
            paths=self.detect_paths(),
        )
    
    def detect_services(self) -> list:
        """Detect systemd services."""
        services = []
        
        try:
            # Get all services
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--plain"],
                capture_output=True, text=True, timeout=10
            )
            
            for line in result.stdout.strip().split("\n")[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 4:
                    name = parts[0].replace(".service", "")
                    
                    # Filter to interesting services
                    if any(interesting in name.lower() for interesting in self.INTERESTING_SERVICES):
                        status = "running" if parts[3] == "running" else parts[3]
                        
                        # Get description
                        desc = " ".join(parts[4:]) if len(parts) > 4 else ""
                        
                        # Check if enabled
                        enabled = False
                        try:
                            en_result = subprocess.run(
                                ["systemctl", "is-enabled", name],
                                capture_output=True, text=True, timeout=5
                            )
                            enabled = en_result.stdout.strip() == "enabled"
                        except:
                            pass
                        
                        services.append(DetectedService(
                            name=name,
                            status=status,
                            description=desc,
                            enabled=enabled
                        ))
        except Exception:
            pass
        
        return services
    
    def detect_applications(self) -> list:
        """Detect running applications/processes."""
        applications = []
        seen_names = set()
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe', 'cwd', 'memory_info']):
            try:
                info = proc.info
                name = info['name'] or ""
                
                # Filter to interesting processes
                if not any(interesting in name.lower() for interesting in self.INTERESTING_PROCESSES):
                    continue
                
                # Skip duplicates by name (keep first)
                if name in seen_names:
                    continue
                seen_names.add(name)
                
                cmdline = " ".join(info['cmdline'] or [])[:200]
                exe = info['exe'] or ""
                cwd = info['cwd'] or ""
                mem = (info['memory_info'].rss / 1024 / 1024) if info['memory_info'] else 0
                
                applications.append(DetectedApplication(
                    name=name,
                    pid=info['pid'],
                    cmdline=cmdline,
                    exe=exe,
                    working_dir=cwd,
                    memory_mb=round(mem, 1)
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        # Sort by memory usage
        applications.sort(key=lambda x: x.memory_mb, reverse=True)
        return applications
    
    def detect_paths(self) -> list:
        """Detect important paths (projects, configs, data)."""
        paths = []
        
        # User home subdirectories
        important_home_dirs = [
            ("projects", "project"),
            ("workspace", "project"),
            ("code", "project"),
            ("dev", "project"),
            ("work", "project"),
            ("repos", "project"),
            ("github", "project"),
            ("gitlab", "project"),
            (".config", "config"),
            (".local/share", "data"),
            (".ssh", "config"),
            (".docker", "config"),
            (".kube", "config"),
            (".npm", "config"),
            (".cargo", "config"),
            (".rustup", "data"),
            (".pyenv", "data"),
            (".nvm", "data"),
            (".vscode", "config"),
            ("Documents", "data"),
            ("Downloads", "data"),
        ]
        
        for dirname, path_type in important_home_dirs:
            full_path = self.home / dirname
            if full_path.exists() and full_path.is_dir():
                size = self._get_dir_size(full_path, max_depth=1)
                paths.append(DetectedPath(
                    path=str(full_path),
                    type=path_type,
                    size_mb=round(size / 1024 / 1024, 1),
                    description=f"User {dirname}"
                ))
        
        # System paths that might be interesting
        system_paths = [
            ("/var/www", "data", "Web server root"),
            ("/var/lib/docker", "data", "Docker data"),
            ("/var/lib/postgresql", "data", "PostgreSQL data"),
            ("/var/lib/mysql", "data", "MySQL data"),
            ("/opt", "data", "Optional software"),
            ("/etc/nginx", "config", "Nginx config"),
            ("/etc/apache2", "config", "Apache config"),
        ]
        
        for path, path_type, desc in system_paths:
            p = Path(path)
            if p.exists():
                size = self._get_dir_size(p, max_depth=1)
                paths.append(DetectedPath(
                    path=path,
                    type=path_type,
                    size_mb=round(size / 1024 / 1024, 1),
                    description=desc
                ))
        
        # Detect project directories (with .git, package.json, etc.)
        project_markers = [".git", "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py"]
        for search_dir in [self.home / "projects", self.home / "code", self.home / "github", self.home]:
            if search_dir.exists():
                for item in search_dir.iterdir():
                    if item.is_dir() and not item.name.startswith("."):
                        for marker in project_markers:
                            if (item / marker).exists():
                                size = self._get_dir_size(item, max_depth=2)
                                if str(item) not in [p.path for p in paths]:
                                    paths.append(DetectedPath(
                                        path=str(item),
                                        type="project",
                                        size_mb=round(size / 1024 / 1024, 1),
                                        description=f"Project ({marker})"
                                    ))
                                break
        
        # Sort by type then path
        paths.sort(key=lambda x: (x.type, x.path))
        return paths
    
    def _get_dir_size(self, path: Path, max_depth: int = 2) -> int:
        """Get approximate directory size in bytes."""
        total = 0
        if not path.exists():
            return 0
        try:
            for item in path.iterdir():
                if item.is_file():
                    try:
                        total += item.stat().st_size
                    except:
                        pass
                elif item.is_dir() and max_depth > 0 and not item.is_symlink():
                    total += self._get_dir_size(item, max_depth - 1)
        except (PermissionError, FileNotFoundError, OSError):
            pass
        return total
    
    def detect_docker_containers(self) -> list:
        """Detect running Docker containers."""
        containers = []
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        containers.append({
                            "name": parts[0],
                            "image": parts[1],
                            "status": parts[2]
                        })
        except:
            pass
        return containers
    
    def get_system_info(self) -> dict:
        """Get basic system information."""
        return {
            "hostname": os.uname().nodename,
            "user": self.user,
            "home": str(self.home),
            "cpu_count": psutil.cpu_count(),
            "memory_total_gb": round(psutil.virtual_memory().total / 1024 / 1024 / 1024, 1),
            "memory_available_gb": round(psutil.virtual_memory().available / 1024 / 1024 / 1024, 1),
            "disk_total_gb": round(psutil.disk_usage("/").total / 1024 / 1024 / 1024, 1),
            "disk_free_gb": round(psutil.disk_usage("/").free / 1024 / 1024 / 1024, 1),
        }
