#!/usr/bin/env python3
"""
SystemDetector - Detects running services, applications and important paths.
"""

import os
import pwd
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

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

    # Services that should NOT be cloned to VM (host-specific, hardware-dependent, or hypervisor services)
    VM_EXCLUDED_SERVICES = {
        # Hypervisor/virtualization - no nested virt needed
        "libvirtd",
        "virtlogd",
        "libvirt-guests",
        "qemu-guest-agent",  # Host-side, VM has its own
        # Hardware-specific
        "bluetooth",
        "bluez",
        "upower",
        "thermald",
        "tlp",
        "power-profiles-daemon",
        # Display manager (VM has its own)
        "gdm",
        "gdm3",
        "sddm",
        "lightdm",
        # Snap-based duplicates (prefer APT versions)
        "snap.cups.cups-browsed",
        "snap.cups.cupsd",
        # Network hardware
        "ModemManager",
        "wpa_supplicant",
        # Host-specific desktop
        "accounts-daemon",
        "colord",
        "switcheroo-control",
    }

    # Common development/server services to look for
    INTERESTING_SERVICES = [
        "docker",
        "containerd",
        "podman",
        "nginx",
        "apache2",
        "httpd",
        "caddy",
        "postgresql",
        "mysql",
        "mariadb",
        "mongodb",
        "redis",
        "memcached",
        "elasticsearch",
        "kibana",
        "grafana",
        "prometheus",
        "jenkins",
        "gitlab-runner",
        "sshd",
        "rsync",
        "rabbitmq-server",
        "kafka",
        "nodejs",
        "pm2",
        "supervisor",
        "systemd-resolved",
        "cups",
        "bluetooth",
        "NetworkManager",
        "libvirtd",
        "virtlogd",
    ]

    # Interesting process names
    INTERESTING_PROCESSES = [
        "python",
        "python3",
        "node",
        "npm",
        "yarn",
        "pnpm",
        "java",
        "gradle",
        "mvn",
        "go",
        "cargo",
        "rustc",
        "docker",
        "docker-compose",
        "podman",
        "nginx",
        "apache",
        "httpd",
        "postgres",
        "mysql",
        "mongod",
        "redis-server",
        "code",
        "code-server",
        "cursor",
        "vim",
        "nvim",
        "emacs",
        "firefox",
        "chrome",
        "chromium",
        "jupyter",
        "jupyter-lab",
        "gunicorn",
        "uvicorn",
        "flask",
        "django",
        "webpack",
        "vite",
        "esbuild",
        "tmux",
        "screen",
        # IDEs and desktop apps
        "pycharm",
        "idea",
        "webstorm",
        "phpstorm",
        "goland",
        "clion",
        "rider",
        "datagrip",
        "sublime",
        "atom",
        "slack",
        "discord",
        "telegram",
        "spotify",
        "vlc",
        "gimp",
        "inkscape",
        "blender",
        "obs",
        "postman",
        "insomnia",
        "dbeaver",
        "windsurf",
    ]

    # Map process/service names to Ubuntu packages or snap packages
    # Format: "process_name": ("package_name", "install_type") where install_type is "apt" or "snap"
    APP_TO_PACKAGE_MAP = {
        "python": ("python3", "apt"),
        "python3": ("python3", "apt"),
        "pip": ("python3-pip", "apt"),
        "node": ("nodejs", "apt"),
        "npm": ("npm", "apt"),
        "yarn": ("yarnpkg", "apt"),
        "docker": ("docker.io", "apt"),
        "dockerd": ("docker.io", "apt"),
        "docker-compose": ("docker-compose", "apt"),
        "podman": ("podman", "apt"),
        "nginx": ("nginx", "apt"),
        "apache2": ("apache2", "apt"),
        "httpd": ("apache2", "apt"),
        "postgres": ("postgresql", "apt"),
        "postgresql": ("postgresql", "apt"),
        "mysql": ("mysql-server", "apt"),
        "mysqld": ("mysql-server", "apt"),
        "mongod": ("mongodb", "apt"),
        "mongodb": ("mongodb", "apt"),
        "redis-server": ("redis-server", "apt"),
        "redis": ("redis-server", "apt"),
        "vim": ("vim", "apt"),
        "nvim": ("neovim", "apt"),
        "emacs": ("emacs", "apt"),
        "firefox": ("firefox", "apt"),
        "chromium": ("chromium-browser", "apt"),
        "jupyter": ("jupyter-notebook", "apt"),
        "jupyter-lab": ("jupyterlab", "apt"),
        "gunicorn": ("gunicorn", "apt"),
        "uvicorn": ("uvicorn", "apt"),
        "tmux": ("tmux", "apt"),
        "screen": ("screen", "apt"),
        "git": ("git", "apt"),
        "curl": ("curl", "apt"),
        "wget": ("wget", "apt"),
        "ssh": ("openssh-client", "apt"),
        "sshd": ("openssh-server", "apt"),
        "go": ("golang", "apt"),
        "cargo": ("cargo", "apt"),
        "rustc": ("rustc", "apt"),
        "java": ("default-jdk", "apt"),
        "gradle": ("gradle", "apt"),
        "mvn": ("maven", "apt"),
        # Popular desktop apps (snap packages)
        "chrome": ("chromium", "snap"),
        "google-chrome": ("chromium", "snap"),
        "pycharm": ("pycharm-community", "snap"),
        "idea": ("intellij-idea-community", "snap"),
        "code": ("code", "snap"),
        "vscode": ("code", "snap"),
        "windsurf": ("windsurf", "deb"),
        "cursor": ("cursor", "deb"),
        "slack": ("slack", "snap"),
        "discord": ("discord", "snap"),
        "spotify": ("spotify", "snap"),
        "vlc": ("vlc", "apt"),
        "gimp": ("gimp", "apt"),
        "inkscape": ("inkscape", "apt"),
        "blender": ("blender", "apt"),
        "obs": ("obs-studio", "apt"),
        "telegram": ("telegram-desktop", "snap"),
        "postman": ("postman", "snap"),
        "insomnia": ("insomnia", "snap"),
        "dbeaver": ("dbeaver-ce", "snap"),
        "sublime": ("sublime-text", "snap"),
        "atom": ("atom", "snap"),
    }

    # Map applications to their config/data directories for complete cloning
    # These directories contain user settings, extensions, profiles, credentials
    APP_DATA_DIRS = {
        # Browsers - profiles, extensions, bookmarks, passwords
        "chrome": [".config/google-chrome", ".config/chromium"],
        "chromium": [".config/chromium"],
        "firefox": [
            "snap/firefox/common/.mozilla/firefox",
            "snap/firefox/common/.cache/mozilla/firefox",
            ".mozilla/firefox",
            ".cache/mozilla/firefox",
        ],
        # IDEs and editors - settings, extensions, projects history
        "code": [".config/Code", ".vscode", ".vscode-server"],
        "vscode": [".config/Code", ".vscode", ".vscode-server"],
        "windsurf": [".config/Windsurf", ".windsurf", "Windsurf"],
        "cursor": [".config/Cursor", ".cursor"],
        "pycharm": [
            "snap/pycharm-community/common/.config/JetBrains",
            "snap/pycharm-community/common/.local/share/JetBrains",
            "snap/pycharm-community/common/.cache/JetBrains",
            ".config/JetBrains",
            ".local/share/JetBrains",
            ".cache/JetBrains",
        ],
        "idea": [".config/JetBrains", ".local/share/JetBrains"],
        "webstorm": [".config/JetBrains", ".local/share/JetBrains"],
        "goland": [".config/JetBrains", ".local/share/JetBrains"],
        "sublime": [".config/sublime-text", ".config/sublime-text-3"],
        "atom": [".atom"],
        "vim": [".vim", ".vimrc", ".config/nvim"],
        "nvim": [".config/nvim", ".local/share/nvim"],
        "emacs": [".emacs.d", ".emacs"],
        "cursor": [".config/Cursor", ".cursor"],
        # Development tools
        "docker": [".docker"],
        "git": [".gitconfig", ".git-credentials", ".config/git"],
        "npm": [".npm", ".npmrc"],
        "yarn": [".yarn", ".yarnrc"],
        "pip": [".pip", ".config/pip"],
        "cargo": [".cargo"],
        "rustup": [".rustup"],
        "go": [".go", "go"],
        "gradle": [".gradle"],
        "maven": [".m2"],
        # Python environments
        "python": [".pyenv", ".virtualenvs", ".local/share/virtualenvs"],
        "python3": [".pyenv", ".virtualenvs", ".local/share/virtualenvs"],
        "conda": [".conda", "anaconda3", "miniconda3"],
        # Node.js
        "node": [".nvm", ".node", ".npm"],
        # Databases
        "postgres": [".pgpass", ".psqlrc", ".psql_history"],
        "mysql": [".my.cnf", ".mysql_history"],
        "mongodb": [".mongorc.js", ".dbshell"],
        "redis": [".rediscli_history"],
        # Communication apps
        "slack": [".config/Slack"],
        "discord": [".config/discord"],
        "telegram": [".local/share/TelegramDesktop"],
        "teams": [".config/Microsoft/Microsoft Teams"],
        # Other tools
        "postman": [".config/Postman"],
        "insomnia": [".config/Insomnia"],
        "dbeaver": [".local/share/DBeaverData"],
        "ssh": [".ssh"],
        "gpg": [".gnupg"],
        "aws": [".aws"],
        "gcloud": [".config/gcloud"],
        "kubectl": [".kube"],
        "terraform": [".terraform.d"],
        "ansible": [".ansible"],
        # General app data
        "spotify": [".config/spotify"],
        "vlc": [".config/vlc"],
        "gimp": [".config/GIMP", ".gimp-2.10"],
        "obs": [".config/obs-studio"],
    }

    def __init__(self):
        self.user = pwd.getpwuid(os.getuid()).pw_name
        self.home = Path.home()

    # ── Dynamic auto-discovery helpers ─────────────────────────────────────

    def _discover_xdg_dirs(self, app_name: str) -> list:
        """Discover app data via XDG Base Directory conventions.

        Most Linux GUI apps store data in:
          ~/.config/<Name>   (settings)
          ~/.local/share/<Name>  (persistent data)
          ~/.cache/<Name>    (cache — usually skip)
        For Electron apps the dir name often starts with uppercase.
        """
        variants = {app_name, app_name.capitalize(), app_name.title(),
                     app_name.lower(), app_name.upper()}
        # Common Electron patterns: "Code", "Windsurf", "Cursor", "Slack"
        # JetBrains: "JetBrains", "pycharm" etc.
        dirs_found = []
        xdg_roots = [
            self.home / ".config",
            self.home / ".local" / "share",
        ]
        for root in xdg_roots:
            if not root.is_dir():
                continue
            try:
                for entry in root.iterdir():
                    if not entry.is_dir():
                        continue
                    entry_lower = entry.name.lower()
                    if any(v.lower() in entry_lower for v in variants):
                        dirs_found.append(str(entry.relative_to(self.home)))
            except (PermissionError, OSError):
                pass

        # Also check dotfiles: ~/.vscode, ~/.windsurf, ~/.cursor, etc.
        for entry in self.home.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name.lstrip(".")
            if name.lower() in {v.lower() for v in variants}:
                dirs_found.append(str(entry.relative_to(self.home)))

        return dirs_found

    def _discover_snap_dirs(self, app_name: str) -> list:
        """Discover snap data dirs for an app.

        Snap apps store user data in ~/snap/<name>/common/.
        """
        dirs_found = []
        snap_base = self.home / "snap"
        if not snap_base.is_dir():
            return dirs_found
        try:
            for entry in snap_base.iterdir():
                if not entry.is_dir():
                    continue
                if app_name.lower() in entry.name.lower():
                    common = entry / "common"
                    if common.is_dir():
                        # Walk one level to find actual data dirs
                        try:
                            for sub in common.iterdir():
                                if sub.is_dir():
                                    dirs_found.append(
                                        str(sub.relative_to(self.home))
                                    )
                        except (PermissionError, OSError):
                            pass
                    # Also include the snap dir itself (for revision dirs)
                    dirs_found.append(str(entry.relative_to(self.home)))
        except (PermissionError, OSError):
            pass
        return dirs_found

    # Top-level dirs that are too broad to copy wholesale
    _TOO_BROAD_DIRS = frozenset({
        ".config", ".local", ".local/share", ".local/lib",
        ".cache", "snap", "Downloads", "Documents", "Desktop",
    })

    def _discover_proc_data_dirs(self, pid: int) -> list:
        """Discover config dirs by examining open file descriptors of a process.

        Reads /proc/<pid>/fd symlinks to find config/data directories the
        process has open. Filters to user home paths only.
        Extracts the app-specific subdir, e.g. .config/Windsurf not just .config.
        """
        dirs_found = set()
        fd_dir = Path(f"/proc/{pid}/fd")
        if not fd_dir.exists():
            return []
        try:
            for fd in fd_dir.iterdir():
                try:
                    target = fd.resolve()
                    target_str = str(target)
                    home_str = str(self.home)
                    if not target_str.startswith(home_str + "/"):
                        continue
                    # Skip cache, tmp, runtime
                    if "/.cache/" in target_str or "/tmp/" in target_str:
                        continue
                    if "/run/" in target_str:
                        continue
                    # Extract the app-specific config dir (2-3 levels under home)
                    rel = target.relative_to(self.home)
                    parts = rel.parts
                    if len(parts) >= 2:
                        candidate = str(Path(parts[0]) / parts[1])
                        # If top-level is too broad (e.g. .local/share), go deeper
                        if candidate in self._TOO_BROAD_DIRS and len(parts) >= 3:
                            candidate = str(Path(parts[0]) / parts[1] / parts[2])
                        if candidate not in self._TOO_BROAD_DIRS:
                            full = self.home / candidate
                            if full.is_dir():
                                dirs_found.add(candidate)
                    elif len(parts) == 1:
                        p = parts[0]
                        if p not in self._TOO_BROAD_DIRS and (self.home / p).is_dir():
                            dirs_found.add(p)
                except (OSError, ValueError):
                    continue
        except (PermissionError, OSError):
            pass
        return list(dirs_found)

    def _discover_desktop_app_name(self, exe_path: str) -> list:
        """Parse .desktop files to find canonical app name for an executable.

        Returns list of Name= values from .desktop files whose Exec= matches.
        """
        names = []
        desktop_dirs = [
            Path("/usr/share/applications"),
            self.home / ".local" / "share" / "applications",
            Path("/var/lib/snapd/desktop/applications"),
        ]
        exe_basename = Path(exe_path).name if exe_path else ""
        if not exe_basename:
            return names

        for ddir in desktop_dirs:
            if not ddir.is_dir():
                continue
            try:
                for df in ddir.glob("*.desktop"):
                    try:
                        text = df.read_text(errors="replace")
                        if exe_basename not in text:
                            continue
                        for line in text.splitlines():
                            if line.startswith("Name="):
                                names.append(line[5:].strip())
                                break
                    except (OSError, UnicodeDecodeError):
                        continue
            except (PermissionError, OSError):
                pass
        return names

    def auto_discover_app_data(self, applications: list) -> list:
        """Automatically discover ALL config/data dirs for detected apps.

        Combines 4 discovery strategies:
          1. Static registry (APP_DATA_DIRS) — fast, covers known apps
          2. XDG convention scan — catches any XDG-compliant app
          3. /proc/PID/fd probing — catches non-standard locations
          4. Snap dir discovery — catches snap-sandboxed apps

        Results are deduplicated and enriched with size info.
        """
        seen_paths: set = set()
        results: list = []

        def _add(rel_path: str, app: str, source: str) -> None:
            full = self.home / rel_path
            full_str = str(full)
            if full_str in seen_paths:
                return
            if not full.exists():
                return
            try:
                size = self._get_dir_size(full, max_depth=2)
            except Exception:
                size = 0
            seen_paths.add(full_str)
            results.append({
                "path": full_str,
                "app": app,
                "type": "app_data",
                "source": source,
                "size_mb": round(size / 1024 / 1024, 1),
            })

        # Collect all app names to probe
        app_names: set = set()
        app_pids: dict = {}  # name -> pid
        app_exes: dict = {}  # name -> exe path

        for app in applications:
            name = app.name.lower()
            app_names.add(name)
            app_pids[name] = app.pid
            app_exes[name] = getattr(app, "exe", "")

        # Always include core apps
        for core in ("firefox", "chrome", "chromium", "pycharm",
                      "windsurf", "code", "cursor"):
            app_names.add(core)

        # Strategy 1: Static registry
        for app_name in sorted(app_names):
            for pattern, dirs in self.APP_DATA_DIRS.items():
                if pattern not in app_name and app_name not in pattern:
                    continue
                snap_dirs = [d for d in dirs if d.startswith("snap/")]
                preferred = snap_dirs if any(
                    (self.home / d).exists() for d in snap_dirs
                ) else dirs
                for d in preferred:
                    _add(d, pattern, "static")

        # Strategy 2: XDG convention scan
        for app_name in sorted(app_names):
            for d in self._discover_xdg_dirs(app_name):
                _add(d, app_name, "xdg")

        # Strategy 3: Snap dir discovery
        for app_name in sorted(app_names):
            for d in self._discover_snap_dirs(app_name):
                _add(d, app_name, "snap")

        # Strategy 4: /proc/PID/fd probing (only for actually running apps)
        for app_name, pid in app_pids.items():
            for d in self._discover_proc_data_dirs(pid):
                _add(d, app_name, "proc")

        # Strategy 5: .desktop file names → additional XDG scan
        for app_name in sorted(app_names):
            exe = app_exes.get(app_name, "")
            for desktop_name in self._discover_desktop_app_name(exe):
                for d in self._discover_xdg_dirs(desktop_name):
                    _add(d, app_name, "desktop")

        # Sort by app name, then path
        results.sort(key=lambda x: (x["app"], x["path"]))
        return results

    def detect_app_data_dirs(self, applications: list) -> list:
        """Detect config/data directories for running applications.

        Uses auto_discover_app_data for comprehensive detection, then
        returns results in the legacy format (without 'source' field).
        """
        discovered = self.auto_discover_app_data(applications)
        # Return in legacy format
        return [
            {
                "path": d["path"],
                "app": d["app"],
                "type": d["type"],
                "size_mb": d["size_mb"],
            }
            for d in discovered
        ]

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
                capture_output=True,
                text=True,
                timeout=10,
            )

            for line in result.stdout.strip().split("\n")[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 4:
                    name = parts[0].replace(".service", "")

                    # Filter to interesting services
                    if any(
                        interesting in name.lower() for interesting in self.INTERESTING_SERVICES
                    ):
                        status = "running" if parts[3] == "running" else parts[3]

                        # Get description
                        desc = " ".join(parts[4:]) if len(parts) > 4 else ""

                        # Check if enabled
                        enabled = False
                        try:
                            en_result = subprocess.run(
                                ["systemctl", "is-enabled", name],
                                capture_output=True,
                                text=True,
                                timeout=5,
                            )
                            enabled = en_result.stdout.strip() == "enabled"
                        except:
                            pass

                        services.append(
                            DetectedService(
                                name=name, status=status, description=desc, enabled=enabled
                            )
                        )
        except Exception:
            pass

        return services

    def detect_applications(self) -> list:
        """Detect running applications/processes."""
        applications = []
        seen_names = set()

        for proc in psutil.process_iter(["pid", "name", "cmdline", "exe", "cwd", "memory_info"]):
            try:
                info = proc.info
                name = info["name"] or ""

                # Filter to interesting processes
                if not any(
                    interesting in name.lower() for interesting in self.INTERESTING_PROCESSES
                ):
                    continue

                # Skip duplicates by name (keep first)
                if name in seen_names:
                    continue
                seen_names.add(name)

                cmdline = " ".join(info["cmdline"] or [])[:200]
                exe = info["exe"] or ""
                cwd = info["cwd"] or ""
                mem = (info["memory_info"].rss / 1024 / 1024) if info["memory_info"] else 0

                applications.append(
                    DetectedApplication(
                        name=name,
                        pid=info["pid"],
                        cmdline=cmdline,
                        exe=exe,
                        working_dir=cwd,
                        memory_mb=round(mem, 1),
                    )
                )
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
                paths.append(
                    DetectedPath(
                        path=str(full_path),
                        type=path_type,
                        size_mb=round(size / 1024 / 1024, 1),
                        description=f"User {dirname}",
                    )
                )

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
                paths.append(
                    DetectedPath(
                        path=path,
                        type=path_type,
                        size_mb=round(size / 1024 / 1024, 1),
                        description=desc,
                    )
                )

        # Detect project directories (with .git, package.json, etc.)
        project_markers = [
            ".git",
            "package.json",
            "Cargo.toml",
            "go.mod",
            "pyproject.toml",
            "setup.py",
        ]
        for search_dir in [
            self.home / "projects",
            self.home / "code",
            self.home / "github",
            self.home,
        ]:
            if search_dir.exists():
                for item in search_dir.iterdir():
                    if item.is_dir() and not item.name.startswith("."):
                        for marker in project_markers:
                            if (item / marker).exists():
                                size = self._get_dir_size(item, max_depth=2)
                                if str(item) not in [p.path for p in paths]:
                                    paths.append(
                                        DetectedPath(
                                            path=str(item),
                                            type="project",
                                            size_mb=round(size / 1024 / 1024, 1),
                                            description=f"Project ({marker})",
                                        )
                                    )
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
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        containers.append({"name": parts[0], "image": parts[1], "status": parts[2]})
        except:
            pass
        return containers

    # Install commands for apps distributed as .deb (not in apt/snap repos)
    DEB_INSTALL_COMMANDS = {
        "windsurf": (
            "command -v windsurf >/dev/null 2>&1 || ("
            "curl -fsSL -o /tmp/windsurf.deb 'https://windsurf-stable.codeiumdata.com/linux-x64/stable/latest' && "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/windsurf.deb && rm -f /tmp/windsurf.deb"
            ") || true"
        ),
        "cursor": (
            "command -v cursor >/dev/null 2>&1 || ("
            "curl -fsSL -o /tmp/cursor.appimage 'https://downloader.cursor.sh/linux/appImage/x64' && "
            "chmod +x /tmp/cursor.appimage && "
            "mv /tmp/cursor.appimage /usr/local/bin/cursor"
            ") || true"
        ),
        "google-chrome": (
            "command -v google-chrome >/dev/null 2>&1 || ("
            "curl -fsSL -o /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/google-chrome.deb && rm -f /tmp/google-chrome.deb"
            ") || true"
        ),
    }

    def suggest_packages_for_apps(self, applications: list) -> dict:
        """Suggest packages based on detected applications.

        Returns:
            dict with 'apt', 'snap', and 'deb_commands' keys.
            'deb_commands' contains shell commands to install .deb/.appimage apps.
        """
        apt_packages = set()
        snap_packages = set()
        deb_commands = []
        seen_deb = set()

        for app in applications:
            app_name = app.name.lower()
            for key, (package, install_type) in self.APP_TO_PACKAGE_MAP.items():
                if key in app_name:
                    if install_type == "snap":
                        snap_packages.add(package)
                    elif install_type == "deb":
                        if key not in seen_deb and key in self.DEB_INSTALL_COMMANDS:
                            deb_commands.append(self.DEB_INSTALL_COMMANDS[key])
                            seen_deb.add(key)
                    else:
                        apt_packages.add(package)
                    break

        return {
            "apt": sorted(list(apt_packages)),
            "snap": sorted(list(snap_packages)),
            "deb_commands": deb_commands,
        }

    def suggest_packages_for_services(self, services: list) -> dict:
        """Suggest packages based on detected services.

        Returns:
            dict with 'apt' and 'snap' keys containing lists of packages
        """
        apt_packages = set()
        snap_packages = set()

        for service in services:
            service_name = service.name.lower()
            for key, (package, install_type) in self.APP_TO_PACKAGE_MAP.items():
                if key in service_name:
                    if install_type == "snap":
                        snap_packages.add(package)
                    else:
                        apt_packages.add(package)
                    break

        return {"apt": sorted(list(apt_packages)), "snap": sorted(list(snap_packages))}

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
