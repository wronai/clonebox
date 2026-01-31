# CloneBox v2.0 - Implementation Roadmap

**Document Version:** 1.0  
**Date:** 2026-01-31  
**Status:** Draft for Review

---

## Executive Summary

This document outlines detailed implementation plans for 12 critical improvements to CloneBox, transforming it from a single-machine VM cloning tool into an enterprise-grade, secure, and extensible platform for workstation virtualization.

### Selected Improvements

| # | Improvement | Priority | Effort | Phase |
|---|-------------|----------|--------|-------|
| 1 | Secrets Isolation in cloud-init | Critical | Medium | 1 |
| 2 | Rollback on VM Creation Errors | Critical | Low | 1 |
| 4 | Snapshot Management | High | Medium | 2 |
| 6 | Advanced Health Checks | High | Medium | 2 |
| 7 | Resource Limits/Quotas | Medium | Low | 2 |
| 9 | Dependency Injection | Medium | High | 3 |
| 10 | Strong Typing | Medium | Medium | 3 |
| 11 | Multi-VM Orchestration | High | High | 4 |
| 12 | Plugin System | Medium | High | 4 |
| 13 | Remote VM Management | Medium | Medium | 4 |
| 16 | Structured Logging | Low | Low | 1 |
| 18 | Audit Logging | Medium | Medium | 3 |

---

## Phase 1: Foundation & Security (Weeks 1-4)

### 1. Secrets Isolation in Cloud-Init

#### Current State

```python
# cloner.py - Password exposed in plain text
password: ${VM_PASSWORD}  # Loaded from .env, but still in cloud-init ISO
```

The password is:
- Stored in `.env` file (good)
- Expanded and written to cloud-init user-data in plain text (bad)
- Visible in `user-data` file inside cloud-init ISO
- Persists on disk after VM creation

#### Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Secrets Architecture                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   .env      │    │  Vault/     │    │   SOPS      │     │
│  │   (local)   │    │  External   │    │   (git)     │     │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘     │
│         │                  │                  │             │
│         └──────────────────┼──────────────────┘             │
│                            ▼                                │
│                   ┌─────────────────┐                       │
│                   │ SecretsProvider │                       │
│                   │   (Abstract)    │                       │
│                   └────────┬────────┘                       │
│                            │                                │
│         ┌──────────────────┼──────────────────┐             │
│         ▼                  ▼                  ▼             │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐        │
│  │ EnvProvider│    │VaultProvider│   │SOPSProvider│        │
│  └────────────┘    └────────────┘    └────────────┘        │
│                            │                                │
│                            ▼                                │
│                   ┌─────────────────┐                       │
│                   │  cloud-init     │                       │
│                   │  (SSH keys +    │                       │
│                   │   one-time pwd) │                       │
│                   └─────────────────┘                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### Implementation

##### 1.1 New File: `src/clonebox/secrets.py`

```python
"""
Secrets management for CloneBox.
Supports multiple backends: env, vault, sops, age.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any
import os
import subprocess
import json
import secrets
import string


@dataclass
class SecretValue:
    """Represents a secret value with metadata."""
    key: str
    value: str
    source: str  # 'env', 'vault', 'sops', 'generated'
    expires_at: Optional[str] = None
    
    def __repr__(self) -> str:
        return f"SecretValue(key={self.key}, source={self.source}, value=***)"
    
    def redacted(self) -> str:
        """Return redacted version for logging."""
        return f"{self.value[:2]}***{self.value[-2:]}" if len(self.value) > 4 else "***"


class SecretsProvider(ABC):
    """Abstract base class for secrets providers."""
    
    @abstractmethod
    def get_secret(self, key: str) -> Optional[SecretValue]:
        """Retrieve a secret by key."""
        pass
    
    @abstractmethod
    def list_secrets(self) -> list[str]:
        """List available secret keys."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and available."""
        pass


class EnvSecretsProvider(SecretsProvider):
    """Load secrets from environment variables and .env files."""
    
    def __init__(self, env_file: Optional[Path] = None):
        self.env_file = env_file or Path(".env")
        self._cache: Dict[str, str] = {}
        self._load_env_file()
    
    def _load_env_file(self) -> None:
        if self.env_file.exists():
            with open(self.env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, _, value = line.partition('=')
                        self._cache[key.strip()] = value.strip().strip('"\'')
    
    def get_secret(self, key: str) -> Optional[SecretValue]:
        # Check environment first, then cache from file
        value = os.environ.get(key) or self._cache.get(key)
        if value:
            return SecretValue(key=key, value=value, source='env')
        return None
    
    def list_secrets(self) -> list[str]:
        return list(set(list(self._cache.keys()) + 
                       [k for k in os.environ.keys() if k.startswith('VM_') or k.startswith('CLONEBOX_')]))
    
    def is_available(self) -> bool:
        return True


class VaultSecretsProvider(SecretsProvider):
    """Load secrets from HashiCorp Vault."""
    
    def __init__(self, addr: Optional[str] = None, token: Optional[str] = None, path_prefix: str = "secret/clonebox"):
        self.addr = addr or os.environ.get('VAULT_ADDR', 'http://127.0.0.1:8200')
        self.token = token or os.environ.get('VAULT_TOKEN')
        self.path_prefix = path_prefix
        self._client = None
    
    def _get_client(self):
        if self._client is None:
            try:
                import hvac
                self._client = hvac.Client(url=self.addr, token=self.token)
            except ImportError:
                raise RuntimeError("hvac package required for Vault support: pip install hvac")
        return self._client
    
    def get_secret(self, key: str) -> Optional[SecretValue]:
        try:
            client = self._get_client()
            path = f"{self.path_prefix}/{key}"
            response = client.secrets.kv.v2.read_secret_version(path=path)
            value = response['data']['data'].get('value')
            if value:
                return SecretValue(key=key, value=value, source='vault')
        except Exception:
            pass
        return None
    
    def list_secrets(self) -> list[str]:
        try:
            client = self._get_client()
            response = client.secrets.kv.v2.list_secrets(path=self.path_prefix)
            return response['data']['keys']
        except Exception:
            return []
    
    def is_available(self) -> bool:
        try:
            client = self._get_client()
            return client.is_authenticated()
        except Exception:
            return False


class SOPSSecretsProvider(SecretsProvider):
    """Load secrets from SOPS-encrypted files."""
    
    def __init__(self, secrets_file: Optional[Path] = None):
        self.secrets_file = secrets_file or Path(".clonebox.secrets.yaml")
        self._cache: Optional[Dict[str, Any]] = None
    
    def _decrypt(self) -> Dict[str, Any]:
        if self._cache is not None:
            return self._cache
        
        if not self.secrets_file.exists():
            self._cache = {}
            return self._cache
        
        try:
            result = subprocess.run(
                ['sops', '-d', str(self.secrets_file)],
                capture_output=True,
                text=True,
                check=True
            )
            import yaml
            self._cache = yaml.safe_load(result.stdout) or {}
        except (subprocess.CalledProcessError, FileNotFoundError):
            self._cache = {}
        
        return self._cache
    
    def get_secret(self, key: str) -> Optional[SecretValue]:
        data = self._decrypt()
        # Support nested keys: "vm.password" -> data['vm']['password']
        parts = key.split('.')
        value = data
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        
        if isinstance(value, str):
            return SecretValue(key=key, value=value, source='sops')
        return None
    
    def list_secrets(self) -> list[str]:
        data = self._decrypt()
        return list(data.keys())
    
    def is_available(self) -> bool:
        try:
            subprocess.run(['sops', '--version'], capture_output=True, check=True)
            return self.secrets_file.exists()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False


class SecretsManager:
    """
    Unified secrets management with multiple provider fallback.
    
    Usage:
        secrets = SecretsManager()
        password = secrets.get('VM_PASSWORD')
        
        # Or with explicit provider
        secrets = SecretsManager(provider='vault')
    """
    
    PROVIDERS = {
        'env': EnvSecretsProvider,
        'vault': VaultSecretsProvider,
        'sops': SOPSSecretsProvider,
    }
    
    def __init__(self, provider: Optional[str] = None, **kwargs):
        self._providers: list[SecretsProvider] = []
        
        if provider:
            # Use specific provider
            if provider not in self.PROVIDERS:
                raise ValueError(f"Unknown provider: {provider}. Available: {list(self.PROVIDERS.keys())}")
            self._providers = [self.PROVIDERS[provider](**kwargs)]
        else:
            # Auto-detect and use all available providers
            for name, cls in self.PROVIDERS.items():
                try:
                    instance = cls(**kwargs)
                    if instance.is_available():
                        self._providers.append(instance)
                except Exception:
                    pass
            
            # Always have env as fallback
            if not any(isinstance(p, EnvSecretsProvider) for p in self._providers):
                self._providers.append(EnvSecretsProvider())
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a secret value, trying each provider in order."""
        for provider in self._providers:
            secret = provider.get_secret(key)
            if secret:
                return secret.value
        return default
    
    def get_secret(self, key: str) -> Optional[SecretValue]:
        """Get a SecretValue with metadata."""
        for provider in self._providers:
            secret = provider.get_secret(key)
            if secret:
                return secret
        return None
    
    def require(self, key: str) -> str:
        """Get a secret or raise an error if not found."""
        value = self.get(key)
        if value is None:
            raise ValueError(f"Required secret '{key}' not found in any provider")
        return value
    
    @staticmethod
    def generate_password(length: int = 24) -> str:
        """Generate a secure random password."""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    @staticmethod
    def generate_one_time_password() -> tuple[str, str]:
        """
        Generate a one-time password that expires on first login.
        Returns (password, cloud-init chpasswd config)
        """
        password = SecretsManager.generate_password(16)
        # Force password change on first login
        chpasswd_config = f"""
chpasswd:
  expire: true
  users:
    - name: ubuntu
      password: {password}
      type: text
"""
        return password, chpasswd_config


# SSH Key Management
@dataclass
class SSHKeyPair:
    """SSH key pair for VM authentication."""
    private_key: str
    public_key: str
    key_type: str = "ed25519"
    
    @classmethod
    def generate(cls, key_type: str = "ed25519") -> "SSHKeyPair":
        """Generate a new SSH key pair."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "key"
            subprocess.run([
                'ssh-keygen', '-t', key_type, '-N', '', '-f', str(key_path), '-q'
            ], check=True)
            
            private_key = key_path.read_text()
            public_key = key_path.with_suffix('.pub').read_text()
            
        return cls(private_key=private_key, public_key=public_key, key_type=key_type)
    
    @classmethod
    def from_file(cls, private_key_path: Path) -> "SSHKeyPair":
        """Load existing SSH key pair."""
        private_key = private_key_path.read_text()
        public_key = private_key_path.with_suffix('.pub').read_text()
        return cls(private_key=private_key, public_key=public_key)
    
    def save(self, private_key_path: Path) -> None:
        """Save key pair to files."""
        private_key_path.write_text(self.private_key)
        private_key_path.chmod(0o600)
        private_key_path.with_suffix('.pub').write_text(self.public_key)
```

##### 1.2 Cloud-Init Integration

Update `cloner.py` `_create_cloudinit_iso()`:

```python
def _create_cloudinit_iso(self, vm_dir: Path, config: VMConfig) -> Path:
    """Create cloud-init ISO with secure credential handling."""
    from clonebox.secrets import SecretsManager, SSHKeyPair
    
    secrets = SecretsManager()
    
    # Determine authentication method
    auth_method = config.auth_method or 'ssh_key'  # New config field
    
    if auth_method == 'ssh_key':
        # Preferred: SSH key authentication
        ssh_key_path = vm_dir / "ssh_key"
        
        if config.ssh_public_key:
            # User provided their own key
            ssh_authorized_keys = [config.ssh_public_key]
        else:
            # Generate new key pair for this VM
            key_pair = SSHKeyPair.generate()
            key_pair.save(ssh_key_path)
            ssh_authorized_keys = [key_pair.public_key]
        
        user_data = f"""#cloud-config
users:
  - name: {config.username}
    groups: sudo, docker, libvirt
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
{chr(10).join(f'      - {key}' for key in ssh_authorized_keys)}
    lock_passwd: true  # Disable password login

# Disable password authentication in SSH
ssh_pwauth: false
"""
        console.print(f"[green]✓[/green] SSH key saved to: {ssh_key_path}")
        console.print(f"[dim]  Connect with: ssh -i {ssh_key_path} {config.username}@<VM_IP>[/dim]")
        
    elif auth_method == 'one_time_password':
        # One-time password that must be changed on first login
        otp, chpasswd_config = SecretsManager.generate_one_time_password()
        
        user_data = f"""#cloud-config
users:
  - name: {config.username}
    groups: sudo, docker, libvirt
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL

{chpasswd_config}

# Display password on console (one-time)
bootcmd:
  - echo "===================="
  - echo "ONE-TIME PASSWORD: {otp}"
  - echo "You MUST change this on first login!"
  - echo "===================="
"""
        console.print(f"[yellow]⚠[/yellow] One-time password will be shown on VM console")
        console.print(f"[dim]  Password MUST be changed on first login[/dim]")
        
    else:
        # Legacy: password from secrets (deprecated)
        password = secrets.require('VM_PASSWORD')
        # ... existing implementation with deprecation warning
        console.print(f"[yellow]⚠ DEPRECATED:[/yellow] Password auth will be removed in v3.0")
    
    # ... rest of cloud-init generation
```

##### 1.3 New Config Schema

```yaml
# .clonebox.yaml
version: '2'
vm:
  name: my-vm
  auth:
    method: ssh_key  # ssh_key | one_time_password | password (deprecated)
    ssh_public_key: "ssh-ed25519 AAAA... user@host"  # Optional, auto-generated if not provided
  
  # Legacy (deprecated, will warn)
  # password: ${VM_PASSWORD}

secrets:
  provider: auto  # auto | env | vault | sops
  vault:
    addr: https://vault.example.com
    path: secret/clonebox
  sops:
    file: .clonebox.secrets.yaml
```

#### Testing Plan

```python
# tests/test_secrets.py
class TestSecretsManager:
    def test_env_provider_loads_dotenv(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("VM_PASSWORD=secret123\n")
        
        secrets = SecretsManager(env_file=env_file)
        assert secrets.get('VM_PASSWORD') == 'secret123'
    
    def test_generate_password_strength(self):
        password = SecretsManager.generate_password(24)
        assert len(password) == 24
        assert any(c.isupper() for c in password)
        assert any(c.islower() for c in password)
        assert any(c.isdigit() for c in password)
    
    def test_ssh_key_generation(self):
        key_pair = SSHKeyPair.generate()
        assert key_pair.private_key.startswith('-----BEGIN OPENSSH PRIVATE KEY-----')
        assert 'ssh-ed25519' in key_pair.public_key
    
    def test_vault_provider_fallback_to_env(self, monkeypatch):
        # Vault unavailable, should fall back to env
        monkeypatch.setenv('VM_PASSWORD', 'env_password')
        secrets = SecretsManager()
        assert secrets.get('VM_PASSWORD') == 'env_password'
```

---

### 2. Rollback on VM Creation Errors

#### Current State

In `cloner.py` `create_vm()`:
- Disk image created
- Cloud-init ISO generated
- If `defineXML()` fails, artifacts remain on disk
- No cleanup mechanism

#### Proposed Solution

```python
# src/clonebox/rollback.py
"""
Transactional rollback support for CloneBox operations.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, List
import shutil
import logging

log = logging.getLogger(__name__)


@dataclass
class RollbackAction:
    """A single rollback action."""
    description: str
    action: Callable[[], None]
    critical: bool = True  # If True, failure stops rollback chain


@dataclass
class RollbackContext:
    """
    Context manager for transactional operations with automatic rollback.
    
    Usage:
        with RollbackContext("create VM") as ctx:
            ctx.add_file(disk_path)  # Will be deleted on error
            ctx.add_directory(vm_dir)  # Will be deleted on error
            ctx.add_action("stop VM", lambda: cloner.stop_vm(name))
            
            # If any exception occurs, all registered items are cleaned up
            do_risky_operation()
    """
    operation_name: str
    _files: List[Path] = field(default_factory=list)
    _directories: List[Path] = field(default_factory=list)
    _actions: List[RollbackAction] = field(default_factory=list)
    _committed: bool = False
    _console: Optional["Console"] = None
    
    def add_file(self, path: Path, description: Optional[str] = None) -> Path:
        """Register a file for cleanup on rollback."""
        self._files.append(path)
        log.debug(f"Registered file for rollback: {path}")
        return path
    
    def add_directory(self, path: Path, description: Optional[str] = None) -> Path:
        """Register a directory for cleanup on rollback."""
        self._directories.append(path)
        log.debug(f"Registered directory for rollback: {path}")
        return path
    
    def add_action(self, description: str, action: Callable[[], None], critical: bool = False) -> None:
        """Register a custom rollback action."""
        self._actions.append(RollbackAction(description=description, action=action, critical=critical))
        log.debug(f"Registered action for rollback: {description}")
    
    def add_libvirt_domain(self, conn, domain_name: str) -> None:
        """Register a libvirt domain for cleanup."""
        def cleanup_domain():
            try:
                dom = conn.lookupByName(domain_name)
                if dom.isActive():
                    dom.destroy()
                dom.undefine()
            except Exception as e:
                log.warning(f"Failed to cleanup domain {domain_name}: {e}")
        
        self._actions.append(RollbackAction(
            description=f"undefine domain {domain_name}",
            action=cleanup_domain,
            critical=False
        ))
    
    def commit(self) -> None:
        """Mark operation as successful, preventing rollback."""
        self._committed = True
        log.info(f"Operation '{self.operation_name}' committed successfully")
    
    def rollback(self) -> List[str]:
        """Execute rollback actions. Returns list of errors."""
        errors = []
        
        if self._console:
            self._console.print(f"[yellow]Rolling back '{self.operation_name}'...[/yellow]")
        
        # Execute custom actions first (in reverse order)
        for action in reversed(self._actions):
            try:
                log.info(f"Rollback action: {action.description}")
                action.action()
            except Exception as e:
                error_msg = f"Rollback action '{action.description}' failed: {e}"
                errors.append(error_msg)
                log.error(error_msg)
                if action.critical:
                    break
        
        # Delete files
        for path in reversed(self._files):
            try:
                if path.exists():
                    path.unlink()
                    log.info(f"Deleted file: {path}")
            except Exception as e:
                errors.append(f"Failed to delete {path}: {e}")
        
        # Delete directories
        for path in reversed(self._directories):
            try:
                if path.exists():
                    shutil.rmtree(path)
                    log.info(f"Deleted directory: {path}")
            except Exception as e:
                errors.append(f"Failed to delete {path}: {e}")
        
        return errors
    
    def __enter__(self) -> "RollbackContext":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None and not self._committed:
            errors = self.rollback()
            if errors and self._console:
                self._console.print("[red]Rollback completed with errors:[/red]")
                for error in errors:
                    self._console.print(f"  [dim]- {error}[/dim]")
        return False  # Don't suppress the exception


@contextmanager
def vm_creation_transaction(cloner: "SelectiveVMCloner", config: "VMConfig", console=None):
    """
    Context manager for VM creation with automatic rollback.
    
    Usage:
        with vm_creation_transaction(cloner, config, console) as ctx:
            vm_dir = ctx.add_directory(images_dir / config.name)
            vm_dir.mkdir(parents=True, exist_ok=True)
            
            disk_path = ctx.add_file(vm_dir / "root.qcow2")
            create_disk(disk_path)
            
            ctx.add_libvirt_domain(cloner.conn, config.name)
            cloner.conn.defineXML(xml)
            
            ctx.commit()  # Success!
    """
    ctx = RollbackContext(
        operation_name=f"create VM '{config.name}'",
        _console=console
    )
    try:
        yield ctx
    except Exception:
        if not ctx._committed:
            ctx.rollback()
        raise
```

##### Integration in `cloner.py`

```python
def create_vm(self, config: VMConfig, console=None, replace: bool = False) -> str:
    """Create a VM with only selected applications/paths."""
    from clonebox.rollback import vm_creation_transaction
    
    with vm_creation_transaction(self, config, console) as ctx:
        # Create VM directory
        images_dir = self.get_images_dir()
        vm_dir = ctx.add_directory(images_dir / config.name)
        vm_dir.mkdir(parents=True, exist_ok=True)
        
        # Create disk
        root_disk = ctx.add_file(vm_dir / "root.qcow2")
        self._create_disk(root_disk, config, console)
        
        # Create cloud-init ISO
        cloudinit_iso = ctx.add_file(self._create_cloudinit_iso(vm_dir, config))
        
        # Generate and define VM
        xml = self._generate_vm_xml(config, root_disk, cloudinit_iso)
        ctx.add_libvirt_domain(self.conn, config.name)
        
        try:
            self.conn.defineXML(xml)
        except libvirt.libvirtError as e:
            raise VMCreationError(f"Failed to define VM: {e}") from e
        
        # Start if requested
        if config.autostart:
            self.start_vm(config.name, console=console)
        
        # All good - commit transaction
        ctx.commit()
        
        return config.name
```

---

### 16. Structured Logging

#### Current State

```python
# Scattered print statements
print(f"Creating VM {name}...")
console.print(f"[green]✓[/green] VM created")
```

#### Proposed Solution

```python
# src/clonebox/logging.py
"""
Structured logging for CloneBox using structlog.
"""
import structlog
import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_file: Optional[Path] = None,
    console_output: bool = True
) -> None:
    """
    Configure structured logging for CloneBox.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_output: If True, output JSON format (good for log aggregation)
        log_file: Optional file path for log output
        console_output: If True, also output to console
    """
    
    # Shared processors for all outputs
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    
    if json_output:
        # JSON output for production/aggregation
        renderer = structlog.processors.JSONRenderer()
    else:
        # Human-readable output for development
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
        )
    
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging
    handlers = []
    
    if console_output:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=shared_processors,
        ))
        handlers.append(console_handler)
    
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),  # Always JSON for files
            foreign_pre_chain=shared_processors,
        ))
        handlers.append(file_handler)
    
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper()),
        handlers=handlers,
    )


def get_logger(name: str = "clonebox") -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


# Context managers for operation tracking
from contextlib import contextmanager

@contextmanager
def log_operation(logger: structlog.stdlib.BoundLogger, operation: str, **kwargs):
    """
    Context manager for logging operation start/end.
    
    Usage:
        with log_operation(log, "create_vm", vm_name="my-vm"):
            # do stuff
    """
    log = logger.bind(operation=operation, **kwargs)
    start_time = datetime.now()
    log.info(f"{operation}.started")
    
    try:
        yield log
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        log.info(f"{operation}.completed", duration_ms=round(duration_ms, 2))
    except Exception as e:
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        log.error(f"{operation}.failed", 
                  error=str(e), 
                  error_type=type(e).__name__,
                  duration_ms=round(duration_ms, 2))
        raise
```

##### Usage in Code

```python
# src/clonebox/cloner.py
from clonebox.logging import get_logger, log_operation

log = get_logger(__name__)

class SelectiveVMCloner:
    def create_vm(self, config: VMConfig, console=None, replace: bool = False) -> str:
        with log_operation(log, "vm.create", vm_name=config.name, ram_mb=config.ram_mb):
            log.debug("vm.create.disk", path=str(disk_path), size_gb=config.disk_size_gb)
            # ...
            log.info("vm.create.cloudinit_generated", packages=len(config.packages))
            # ...
        
        return config.name
    
    def start_vm(self, vm_name: str, open_viewer: bool = True) -> bool:
        with log_operation(log, "vm.start", vm_name=vm_name, open_viewer=open_viewer):
            # ...
            log.info("vm.start.viewer_opened", viewer="virt-viewer")
```

##### Log Output Examples

**Development (console):**
```
2026-01-31T12:00:00.123Z [info     ] vm.create.started          vm_name=my-vm ram_mb=4096
2026-01-31T12:00:00.234Z [debug    ] vm.create.disk             path=/home/user/.local/share/libvirt/images/my-vm/root.qcow2 size_gb=30
2026-01-31T12:00:05.456Z [info     ] vm.create.completed        vm_name=my-vm duration_ms=5333.12
```

**Production (JSON):**
```json
{"timestamp": "2026-01-31T12:00:00.123Z", "level": "info", "event": "vm.create.started", "vm_name": "my-vm", "ram_mb": 4096}
{"timestamp": "2026-01-31T12:00:05.456Z", "level": "info", "event": "vm.create.completed", "vm_name": "my-vm", "duration_ms": 5333.12}
```

---

## Phase 2: Features (Weeks 5-10)

### 4. Snapshot Management

#### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Snapshot Architecture                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  VM: my-dev-env                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ root.qcow2 (base)                                   │   │
│  │     │                                               │   │
│  │     ├── snapshot-2026-01-30-clean-install          │   │
│  │     │       │                                       │   │
│  │     │       └── snapshot-2026-01-31-before-upgrade │   │
│  │     │               │                               │   │
│  │     │               └── [current state]            │   │
│  │     │                                               │   │
│  │     └── snapshot-2026-01-28-experiment (branched)  │   │
│  │                                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Metadata: ~/.local/share/clonebox/snapshots/my-dev-env/   │
│  ├── manifest.json                                          │
│  ├── clean-install.meta.json                               │
│  └── before-upgrade.meta.json                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### Implementation

```python
# src/clonebox/snapshots.py
"""
Snapshot management for CloneBox VMs.
Supports internal (qcow2) and external snapshots.
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import json
import subprocess


@dataclass
class SnapshotMetadata:
    """Metadata for a VM snapshot."""
    name: str
    vm_name: str
    created_at: datetime
    description: Optional[str] = None
    parent: Optional[str] = None  # Parent snapshot name
    tags: List[str] = field(default_factory=list)
    size_bytes: int = 0
    snapshot_type: str = "internal"  # internal | external
    
    # State captured
    memory_included: bool = False
    disk_only: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "vm_name": self.vm_name,
            "created_at": self.created_at.isoformat(),
            "description": self.description,
            "parent": self.parent,
            "tags": self.tags,
            "size_bytes": self.size_bytes,
            "snapshot_type": self.snapshot_type,
            "memory_included": self.memory_included,
            "disk_only": self.disk_only,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SnapshotMetadata":
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


class SnapshotManager:
    """
    Manage VM snapshots using libvirt and qemu-img.
    
    Supports:
    - Internal snapshots (stored in qcow2 file)
    - External snapshots (separate files)
    - Snapshot trees (branching)
    - Restore with rollback safety
    """
    
    def __init__(self, conn, metadata_dir: Optional[Path] = None):
        self.conn = conn
        self.metadata_dir = metadata_dir or Path.home() / ".local/share/clonebox/snapshots"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_vm_metadata_dir(self, vm_name: str) -> Path:
        """Get metadata directory for a specific VM."""
        path = self.metadata_dir / vm_name
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def _save_metadata(self, metadata: SnapshotMetadata) -> None:
        """Save snapshot metadata to disk."""
        meta_file = self._get_vm_metadata_dir(metadata.vm_name) / f"{metadata.name}.meta.json"
        with open(meta_file, 'w') as f:
            json.dump(metadata.to_dict(), f, indent=2)
    
    def _load_metadata(self, vm_name: str, snapshot_name: str) -> Optional[SnapshotMetadata]:
        """Load snapshot metadata from disk."""
        meta_file = self._get_vm_metadata_dir(vm_name) / f"{snapshot_name}.meta.json"
        if not meta_file.exists():
            return None
        with open(meta_file) as f:
            return SnapshotMetadata.from_dict(json.load(f))
    
    def create(
        self,
        vm_name: str,
        snapshot_name: str,
        description: Optional[str] = None,
        include_memory: bool = False,
        tags: Optional[List[str]] = None,
        console=None
    ) -> SnapshotMetadata:
        """
        Create a new snapshot of a VM.
        
        Args:
            vm_name: Name of the VM
            snapshot_name: Name for the snapshot
            description: Optional description
            include_memory: If True, include RAM state (VM must be running)
            tags: Optional tags for organization
            console: Rich console for output
        
        Returns:
            SnapshotMetadata for the created snapshot
        """
        from clonebox.logging import get_logger, log_operation
        log = get_logger(__name__)
        
        with log_operation(log, "snapshot.create", vm_name=vm_name, snapshot_name=snapshot_name):
            # Get domain
            try:
                dom = self.conn.lookupByName(vm_name)
            except Exception as e:
                raise SnapshotError(f"VM '{vm_name}' not found: {e}")
            
            # Validate state
            is_running = dom.isActive()
            if include_memory and not is_running:
                raise SnapshotError("Cannot include memory for stopped VM")
            
            # Check for duplicate name
            existing = self.list(vm_name)
            if snapshot_name in [s.name for s in existing]:
                raise SnapshotError(f"Snapshot '{snapshot_name}' already exists")
            
            # Get current snapshot (parent)
            current = dom.snapshotCurrent() if dom.snapshotNum() > 0 else None
            parent_name = current.getName() if current else None
            
            # Build snapshot XML
            snapshot_xml = f"""
            <domainsnapshot>
                <name>{snapshot_name}</name>
                <description>{description or ''}</description>
                <memory snapshot='{"internal" if include_memory else "no"}'/>
                <disks>
                    <disk name='vda' snapshot='internal'/>
                </disks>
            </domainsnapshot>
            """
            
            # Create snapshot
            flags = 0
            if not include_memory:
                flags |= libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY
            
            try:
                snapshot = dom.snapshotCreateXML(snapshot_xml, flags)
            except libvirt.libvirtError as e:
                raise SnapshotError(f"Failed to create snapshot: {e}")
            
            # Save metadata
            metadata = SnapshotMetadata(
                name=snapshot_name,
                vm_name=vm_name,
                created_at=datetime.now(),
                description=description,
                parent=parent_name,
                tags=tags or [],
                memory_included=include_memory,
                disk_only=not include_memory,
            )
            self._save_metadata(metadata)
            
            if console:
                console.print(f"[green]✓[/green] Snapshot '{snapshot_name}' created")
            
            log.info("snapshot.created", snapshot_name=snapshot_name, parent=parent_name)
            return metadata
    
    def list(self, vm_name: str) -> List[SnapshotMetadata]:
        """List all snapshots for a VM."""
        try:
            dom = self.conn.lookupByName(vm_name)
        except Exception:
            return []
        
        snapshots = []
        for snap in dom.listAllSnapshots():
            name = snap.getName()
            metadata = self._load_metadata(vm_name, name)
            if metadata:
                snapshots.append(metadata)
            else:
                # Create basic metadata from libvirt
                xml = snap.getXMLDesc()
                # Parse XML for basic info
                snapshots.append(SnapshotMetadata(
                    name=name,
                    vm_name=vm_name,
                    created_at=datetime.now(),  # Approximate
                ))
        
        return sorted(snapshots, key=lambda s: s.created_at)
    
    def restore(
        self,
        vm_name: str,
        snapshot_name: str,
        create_backup: bool = True,
        console=None
    ) -> None:
        """
        Restore VM to a snapshot.
        
        Args:
            vm_name: Name of the VM
            snapshot_name: Name of snapshot to restore
            create_backup: If True, create a backup snapshot before restore
            console: Rich console for output
        """
        from clonebox.logging import get_logger, log_operation
        log = get_logger(__name__)
        
        with log_operation(log, "snapshot.restore", vm_name=vm_name, snapshot_name=snapshot_name):
            dom = self.conn.lookupByName(vm_name)
            
            # Find snapshot
            try:
                snapshot = dom.snapshotLookupByName(snapshot_name)
            except libvirt.libvirtError:
                raise SnapshotError(f"Snapshot '{snapshot_name}' not found")
            
            # Create backup if requested
            if create_backup:
                backup_name = f"pre-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                self.create(vm_name, backup_name, 
                           description=f"Auto-backup before restore to {snapshot_name}",
                           tags=["auto-backup", "pre-restore"],
                           console=console)
                log.info("snapshot.backup_created", backup_name=backup_name)
            
            # Stop VM if running
            was_running = dom.isActive()
            if was_running:
                dom.destroy()
                log.info("snapshot.vm_stopped")
            
            # Restore
            try:
                dom.revertToSnapshot(snapshot)
            except libvirt.libvirtError as e:
                raise SnapshotError(f"Failed to restore snapshot: {e}")
            
            # Restart if was running
            if was_running:
                dom.create()
                log.info("snapshot.vm_restarted")
            
            if console:
                console.print(f"[green]✓[/green] Restored to snapshot '{snapshot_name}'")
    
    def delete(self, vm_name: str, snapshot_name: str, console=None) -> None:
        """Delete a snapshot."""
        dom = self.conn.lookupByName(vm_name)
        
        try:
            snapshot = dom.snapshotLookupByName(snapshot_name)
            snapshot.delete()
        except libvirt.libvirtError as e:
            raise SnapshotError(f"Failed to delete snapshot: {e}")
        
        # Remove metadata
        meta_file = self._get_vm_metadata_dir(vm_name) / f"{snapshot_name}.meta.json"
        meta_file.unlink(missing_ok=True)
        
        if console:
            console.print(f"[green]✓[/green] Snapshot '{snapshot_name}' deleted")
    
    def get_tree(self, vm_name: str) -> Dict[str, Any]:
        """Get snapshot tree structure for visualization."""
        snapshots = self.list(vm_name)
        
        # Build tree
        tree = {"name": "root", "children": []}
        nodes = {None: tree}
        
        for snap in snapshots:
            node = {"name": snap.name, "metadata": snap, "children": []}
            nodes[snap.name] = node
            parent = nodes.get(snap.parent, tree)
            parent["children"].append(node)
        
        return tree


class SnapshotError(Exception):
    """Snapshot operation failed."""
    pass
```

##### CLI Integration

```python
# In cli.py - add snapshot subcommands

def cmd_snapshot_create(args) -> None:
    """Create a VM snapshot."""
    vm_name, config_file = _resolve_vm_name_and_config_file(args.path)
    conn_uri = "qemu:///session" if args.user else "qemu:///system"
    
    import libvirt
    conn = libvirt.open(conn_uri)
    
    from clonebox.snapshots import SnapshotManager
    manager = SnapshotManager(conn)
    
    metadata = manager.create(
        vm_name=vm_name,
        snapshot_name=args.name,
        description=args.description,
        include_memory=args.memory,
        tags=args.tag or [],
        console=console
    )
    
    console.print(f"\n[bold]Snapshot created:[/bold]")
    console.print(f"  Name: {metadata.name}")
    console.print(f"  Created: {metadata.created_at}")
    if metadata.parent:
        console.print(f"  Parent: {metadata.parent}")


def cmd_snapshot_list(args) -> None:
    """List VM snapshots."""
    vm_name, _ = _resolve_vm_name_and_config_file(args.path)
    conn_uri = "qemu:///session" if args.user else "qemu:///system"
    
    import libvirt
    conn = libvirt.open(conn_uri)
    
    from clonebox.snapshots import SnapshotManager
    manager = SnapshotManager(conn)
    
    snapshots = manager.list(vm_name)
    
    if not snapshots:
        console.print(f"No snapshots for VM '{vm_name}'")
        return
    
    table = Table(title=f"Snapshots for {vm_name}")
    table.add_column("Name")
    table.add_column("Created")
    table.add_column("Description")
    table.add_column("Tags")
    
    for snap in snapshots:
        table.add_row(
            snap.name,
            snap.created_at.strftime("%Y-%m-%d %H:%M"),
            snap.description or "",
            ", ".join(snap.tags) if snap.tags else ""
        )
    
    console.print(table)


# Add to argparse
snapshot_parser = subparsers.add_parser('snapshot', help='Manage VM snapshots')
snapshot_sub = snapshot_parser.add_subparsers(dest='snapshot_cmd')

create_parser = snapshot_sub.add_parser('create', help='Create snapshot')
create_parser.add_argument('path', nargs='?', default='.')
create_parser.add_argument('--name', '-n', required=True, help='Snapshot name')
create_parser.add_argument('--description', '-d', help='Description')
create_parser.add_argument('--memory', '-m', action='store_true', help='Include memory')
create_parser.add_argument('--tag', '-t', action='append', help='Add tag')
create_parser.add_argument('--user', action='store_true')

list_parser = snapshot_sub.add_parser('list', help='List snapshots')
list_parser.add_argument('path', nargs='?', default='.')
list_parser.add_argument('--user', action='store_true')

restore_parser = snapshot_sub.add_parser('restore', help='Restore snapshot')
restore_parser.add_argument('path', nargs='?', default='.')
restore_parser.add_argument('--name', '-n', required=True, help='Snapshot name')
restore_parser.add_argument('--no-backup', action='store_true', help='Skip backup')
restore_parser.add_argument('--user', action='store_true')

delete_parser = snapshot_sub.add_parser('delete', help='Delete snapshot')
delete_parser.add_argument('path', nargs='?', default='.')
delete_parser.add_argument('--name', '-n', required=True, help='Snapshot name')
delete_parser.add_argument('--user', action='store_true')
```

---

### 6. Advanced Health Checks

#### Architecture

```yaml
# .clonebox.yaml - Health check configuration
health_checks:
  # TCP port check
  - name: postgres
    type: tcp
    port: 5432
    timeout: 5s
    interval: 30s
    retries: 3
    
  # HTTP endpoint check
  - name: api
    type: http
    url: http://localhost:8000/health
    method: GET
    expected_status: [200, 204]
    expected_body_contains: "ok"
    timeout: 10s
    headers:
      Authorization: "Bearer ${API_TOKEN}"
    
  # Command execution check
  - name: redis
    type: command
    exec: "redis-cli ping"
    expected_output: "PONG"
    expected_exit_code: 0
    timeout: 5s
    
  # File existence check
  - name: config
    type: file
    path: /etc/myapp/config.yaml
    should_exist: true
    min_size: 100  # bytes
    
  # Process check
  - name: nginx-worker
    type: process
    name: "nginx: worker"
    min_count: 2
    max_count: 8
    
  # Disk space check
  - name: root-disk
    type: disk
    path: /
    min_free_percent: 10
    min_free_bytes: 1G
    
  # Memory check
  - name: memory
    type: memory
    max_used_percent: 90
    
  # Custom script
  - name: database-connectivity
    type: script
    path: /opt/scripts/check_db.sh
    timeout: 30s
    env:
      DB_HOST: localhost
      DB_PORT: 5432
```

#### Implementation

```python
# src/clonebox/health.py
"""
Advanced health check system for CloneBox VMs.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any, Type
import socket
import subprocess
import re
import time


class HealthStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    name: str
    status: HealthStatus
    message: str
    duration_ms: float
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


class HealthCheck(ABC):
    """Base class for health checks."""
    
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.timeout = self._parse_duration(config.get('timeout', '5s'))
        self.retries = config.get('retries', 1)
    
    @staticmethod
    def _parse_duration(duration: str) -> float:
        """Parse duration string like '5s', '100ms', '1m' to seconds."""
        match = re.match(r'^(\d+(?:\.\d+)?)(ms|s|m|h)?$', duration)
        if not match:
            return 5.0
        
        value, unit = float(match.group(1)), match.group(2) or 's'
        multipliers = {'ms': 0.001, 's': 1, 'm': 60, 'h': 3600}
        return value * multipliers.get(unit, 1)
    
    @staticmethod
    def _parse_bytes(size: str) -> int:
        """Parse size string like '1G', '500M', '1024K' to bytes."""
        match = re.match(r'^(\d+(?:\.\d+)?)(B|K|M|G|T)?$', size.upper())
        if not match:
            return 0
        
        value, unit = float(match.group(1)), match.group(2) or 'B'
        multipliers = {'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
        return int(value * multipliers.get(unit, 1))
    
    @abstractmethod
    def check(self, executor: "HealthCheckExecutor") -> HealthCheckResult:
        """Execute the health check."""
        pass
    
    def run(self, executor: "HealthCheckExecutor") -> HealthCheckResult:
        """Run check with retries."""
        last_result = None
        
        for attempt in range(self.retries):
            start = time.time()
            try:
                result = self.check(executor)
                result.duration_ms = (time.time() - start) * 1000
                
                if result.status == HealthStatus.HEALTHY:
                    return result
                
                last_result = result
            except Exception as e:
                last_result = HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=str(e),
                    duration_ms=(time.time() - start) * 1000,
                )
            
            if attempt < self.retries - 1:
                time.sleep(1)
        
        return last_result


class TCPHealthCheck(HealthCheck):
    """Check if a TCP port is open."""
    
    def check(self, executor: "HealthCheckExecutor") -> HealthCheckResult:
        port = self.config['port']
        host = self.config.get('host', 'localhost')
        
        try:
            # Execute check inside VM
            result = executor.exec_in_vm(
                f"timeout {self.timeout} bash -c 'echo > /dev/tcp/{host}/{port}' 2>/dev/null && echo OK || echo FAIL"
            )
            
            if result and 'OK' in result:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message=f"Port {port} is open",
                    duration_ms=0,
                    details={"host": host, "port": port}
                )
            else:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Port {port} is not responding",
                    duration_ms=0,
                    details={"host": host, "port": port}
                )
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"TCP check failed: {e}",
                duration_ms=0,
            )


class HTTPHealthCheck(HealthCheck):
    """Check HTTP endpoint."""
    
    def check(self, executor: "HealthCheckExecutor") -> HealthCheckResult:
        url = self.config['url']
        method = self.config.get('method', 'GET')
        expected_status = self.config.get('expected_status', [200])
        expected_body = self.config.get('expected_body_contains')
        
        if isinstance(expected_status, int):
            expected_status = [expected_status]
        
        # Build curl command
        curl_cmd = f"curl -s -o /tmp/health_body -w '%{{http_code}}' -X {method}"
        
        # Add headers
        for key, value in self.config.get('headers', {}).items():
            curl_cmd += f" -H '{key}: {value}'"
        
        curl_cmd += f" --max-time {int(self.timeout)} '{url}'"
        
        try:
            result = executor.exec_in_vm(curl_cmd)
            
            if not result:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message="No response from curl",
                    duration_ms=0,
                )
            
            status_code = int(result.strip())
            
            if status_code not in expected_status:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"HTTP {status_code}, expected {expected_status}",
                    duration_ms=0,
                    details={"status_code": status_code, "url": url}
                )
            
            # Check body if required
            if expected_body:
                body = executor.exec_in_vm("cat /tmp/health_body")
                if expected_body not in (body or ''):
                    return HealthCheckResult(
                        name=self.name,
                        status=HealthStatus.UNHEALTHY,
                        message=f"Response body missing '{expected_body}'",
                        duration_ms=0,
                        details={"status_code": status_code, "url": url}
                    )
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message=f"HTTP {status_code} OK",
                duration_ms=0,
                details={"status_code": status_code, "url": url}
            )
            
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"HTTP check failed: {e}",
                duration_ms=0,
            )


class CommandHealthCheck(HealthCheck):
    """Execute a command and check output."""
    
    def check(self, executor: "HealthCheckExecutor") -> HealthCheckResult:
        command = self.config['exec']
        expected_output = self.config.get('expected_output')
        expected_exit = self.config.get('expected_exit_code', 0)
        
        try:
            result = executor.exec_in_vm(command, timeout=int(self.timeout))
            
            if result is None:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message="Command execution failed",
                    duration_ms=0,
                )
            
            # Check output
            if expected_output and expected_output not in result:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Output missing '{expected_output}'",
                    duration_ms=0,
                    details={"output": result[:200]}
                )
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message="Command succeeded",
                duration_ms=0,
                details={"output": result[:200]}
            )
            
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Command failed: {e}",
                duration_ms=0,
            )


class DiskHealthCheck(HealthCheck):
    """Check disk space."""
    
    def check(self, executor: "HealthCheckExecutor") -> HealthCheckResult:
        path = self.config['path']
        min_free_percent = self.config.get('min_free_percent', 10)
        min_free_bytes = self._parse_bytes(self.config.get('min_free_bytes', '0'))
        
        try:
            # Get disk usage
            result = executor.exec_in_vm(f"df -B1 '{path}' | tail -1")
            
            if not result:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNKNOWN,
                    message="Could not get disk info",
                    duration_ms=0,
                )
            
            parts = result.split()
            if len(parts) < 4:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNKNOWN,
                    message="Invalid df output",
                    duration_ms=0,
                )
            
            total = int(parts[1])
            used = int(parts[2])
            available = int(parts[3])
            used_percent = (used / total) * 100 if total > 0 else 0
            free_percent = 100 - used_percent
            
            details = {
                "path": path,
                "total_bytes": total,
                "used_bytes": used,
                "available_bytes": available,
                "used_percent": round(used_percent, 1),
                "free_percent": round(free_percent, 1),
            }
            
            # Check thresholds
            if free_percent < min_free_percent:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Low disk space: {free_percent:.1f}% free (min: {min_free_percent}%)",
                    duration_ms=0,
                    details=details,
                )
            
            if min_free_bytes > 0 and available < min_free_bytes:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Low disk space: {available} bytes free",
                    duration_ms=0,
                    details=details,
                )
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message=f"Disk OK: {free_percent:.1f}% free",
                duration_ms=0,
                details=details,
            )
            
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Disk check failed: {e}",
                duration_ms=0,
            )


class MemoryHealthCheck(HealthCheck):
    """Check memory usage."""
    
    def check(self, executor: "HealthCheckExecutor") -> HealthCheckResult:
        max_used_percent = self.config.get('max_used_percent', 90)
        
        try:
            result = executor.exec_in_vm("free -b | grep Mem")
            
            if not result:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNKNOWN,
                    message="Could not get memory info",
                    duration_ms=0,
                )
            
            parts = result.split()
            total = int(parts[1])
            used = int(parts[2])
            available = int(parts[6]) if len(parts) > 6 else total - used
            used_percent = (used / total) * 100 if total > 0 else 0
            
            details = {
                "total_bytes": total,
                "used_bytes": used,
                "available_bytes": available,
                "used_percent": round(used_percent, 1),
            }
            
            if used_percent > max_used_percent:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"High memory usage: {used_percent:.1f}% (max: {max_used_percent}%)",
                    duration_ms=0,
                    details=details,
                )
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message=f"Memory OK: {used_percent:.1f}% used",
                duration_ms=0,
                details=details,
            )
            
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Memory check failed: {e}",
                duration_ms=0,
            )


class ProcessHealthCheck(HealthCheck):
    """Check if processes are running."""
    
    def check(self, executor: "HealthCheckExecutor") -> HealthCheckResult:
        process_name = self.config['name']
        min_count = self.config.get('min_count', 1)
        max_count = self.config.get('max_count')
        
        try:
            result = executor.exec_in_vm(f"pgrep -c -f '{process_name}' || echo 0")
            count = int(result.strip()) if result else 0
            
            details = {
                "process_name": process_name,
                "count": count,
                "min_count": min_count,
                "max_count": max_count,
            }
            
            if count < min_count:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Process count {count} < {min_count}",
                    duration_ms=0,
                    details=details,
                )
            
            if max_count and count > max_count:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.DEGRADED,
                    message=f"Process count {count} > {max_count}",
                    duration_ms=0,
                    details=details,
                )
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message=f"Process OK: {count} running",
                duration_ms=0,
                details=details,
            )
            
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Process check failed: {e}",
                duration_ms=0,
            )


# Registry of check types
HEALTH_CHECK_TYPES: Dict[str, Type[HealthCheck]] = {
    'tcp': TCPHealthCheck,
    'http': HTTPHealthCheck,
    'command': CommandHealthCheck,
    'disk': DiskHealthCheck,
    'memory': MemoryHealthCheck,
    'process': ProcessHealthCheck,
}


class HealthCheckExecutor:
    """Executes health checks against a VM."""
    
    def __init__(self, vm_name: str, conn_uri: str):
        self.vm_name = vm_name
        self.conn_uri = conn_uri
    
    def exec_in_vm(self, command: str, timeout: int = 10) -> Optional[str]:
        """Execute command in VM using QEMU Guest Agent."""
        # Reuse existing _qga_exec from cli.py
        from clonebox.cli import _qga_exec
        return _qga_exec(self.vm_name, self.conn_uri, command, timeout)
    
    def run_checks(self, checks_config: List[Dict[str, Any]]) -> List[HealthCheckResult]:
        """Run all configured health checks."""
        results = []
        
        for check_config in checks_config:
            check_type = check_config.get('type')
            check_name = check_config.get('name', check_type)
            
            if check_type not in HEALTH_CHECK_TYPES:
                results.append(HealthCheckResult(
                    name=check_name,
                    status=HealthStatus.UNKNOWN,
                    message=f"Unknown check type: {check_type}",
                    duration_ms=0,
                ))
                continue
            
            check_class = HEALTH_CHECK_TYPES[check_type]
            check = check_class(check_name, check_config)
            result = check.run(self)
            results.append(result)
        
        return results
    
    def get_overall_status(self, results: List[HealthCheckResult]) -> HealthStatus:
        """Determine overall health status from individual results."""
        if not results:
            return HealthStatus.UNKNOWN
        
        statuses = [r.status for r in results]
        
        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        elif any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.UNKNOWN
```

---

### 7. Resource Limits/Quotas

#### Implementation

```python
# src/clonebox/resources.py
"""
Resource limits and quotas for CloneBox VMs.
"""
from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class ResourceLimits:
    """Resource limits for a VM."""
    # CPU
    cpu_shares: int = 1024  # Relative CPU weight (default: 1024)
    cpu_period: int = 100000  # CFS period in microseconds
    cpu_quota: int = -1  # CFS quota (-1 = unlimited)
    vcpu_pin: Optional[str] = None  # CPU pinning (e.g., "0-3" or "0,2,4")
    
    # Memory
    memory_limit: Optional[str] = None  # e.g., "8G"
    memory_swap_limit: Optional[str] = None  # e.g., "16G"
    memory_soft_limit: Optional[str] = None  # e.g., "6G"
    
    # I/O
    blkio_weight: int = 500  # 100-1000, default 500
    blkio_read_bps: Optional[str] = None  # e.g., "100M"
    blkio_write_bps: Optional[str] = None  # e.g., "50M"
    blkio_read_iops: Optional[int] = None
    blkio_write_iops: Optional[int] = None
    
    # Network
    network_bandwidth_in: Optional[str] = None  # e.g., "100Mbps"
    network_bandwidth_out: Optional[str] = None
    
    @staticmethod
    def _parse_bytes(size: str) -> int:
        """Parse size string to bytes."""
        match = re.match(r'^(\d+(?:\.\d+)?)(B|K|M|G|T)?$', size.upper())
        if not match:
            raise ValueError(f"Invalid size: {size}")
        
        value, unit = float(match.group(1)), match.group(2) or 'B'
        multipliers = {'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
        return int(value * multipliers[unit])
    
    @staticmethod
    def _parse_bandwidth(bw: str) -> int:
        """Parse bandwidth string to bits per second."""
        match = re.match(r'^(\d+(?:\.\d+)?)(bps|Kbps|Mbps|Gbps)?$', bw)
        if not match:
            raise ValueError(f"Invalid bandwidth: {bw}")
        
        value, unit = float(match.group(1)), match.group(2) or 'bps'
        multipliers = {'bps': 1, 'Kbps': 1000, 'Mbps': 1000000, 'Gbps': 1000000000}
        return int(value * multipliers[unit])
    
    def to_libvirt_cputune(self) -> str:
        """Generate libvirt cputune XML."""
        xml_parts = ["<cputune>"]
        
        xml_parts.append(f"  <shares>{self.cpu_shares}</shares>")
        
        if self.cpu_quota > 0:
            xml_parts.append(f"  <period>{self.cpu_period}</period>")
            xml_parts.append(f"  <quota>{self.cpu_quota}</quota>")
        
        if self.vcpu_pin:
            # Parse pinning (e.g., "0-3" -> pin vcpu 0 to cpu 0, vcpu 1 to cpu 1, etc.)
            if '-' in self.vcpu_pin:
                start, end = map(int, self.vcpu_pin.split('-'))
                cpus = list(range(start, end + 1))
            else:
                cpus = [int(c) for c in self.vcpu_pin.split(',')]
            
            for i, cpu in enumerate(cpus):
                xml_parts.append(f"  <vcpupin vcpu='{i}' cpuset='{cpu}'/>")
        
        xml_parts.append("</cputune>")
        return "\n".join(xml_parts)
    
    def to_libvirt_memtune(self) -> str:
        """Generate libvirt memtune XML."""
        xml_parts = ["<memtune>"]
        
        if self.memory_limit:
            limit_kb = self._parse_bytes(self.memory_limit) // 1024
            xml_parts.append(f"  <hard_limit unit='KiB'>{limit_kb}</hard_limit>")
        
        if self.memory_soft_limit:
            soft_kb = self._parse_bytes(self.memory_soft_limit) // 1024
            xml_parts.append(f"  <soft_limit unit='KiB'>{soft_kb}</soft_limit>")
        
        if self.memory_swap_limit:
            swap_kb = self._parse_bytes(self.memory_swap_limit) // 1024
            xml_parts.append(f"  <swap_hard_limit unit='KiB'>{swap_kb}</swap_hard_limit>")
        
        xml_parts.append("</memtune>")
        return "\n".join(xml_parts) if len(xml_parts) > 2 else ""
    
    def to_libvirt_blkiotune(self) -> str:
        """Generate libvirt blkiotune XML."""
        xml_parts = ["<blkiotune>"]
        
        xml_parts.append(f"  <weight>{self.blkio_weight}</weight>")
        
        # Device-specific throttling would go here
        # For now, we set global weight only
        
        xml_parts.append("</blkiotune>")
        return "\n".join(xml_parts)
    
    def to_tc_commands(self, interface: str = "eth0") -> list[str]:
        """Generate tc commands for network bandwidth limiting."""
        commands = []
        
        if self.network_bandwidth_out:
            rate_bps = self._parse_bandwidth(self.network_bandwidth_out)
            rate_kbit = rate_bps // 1000
            commands.extend([
                f"tc qdisc del dev {interface} root 2>/dev/null || true",
                f"tc qdisc add dev {interface} root tbf rate {rate_kbit}kbit burst 32kbit latency 400ms",
            ])
        
        return commands


def apply_resource_limits(config: "VMConfig", limits: ResourceLimits) -> str:
    """
    Apply resource limits to VM XML configuration.
    Returns modified XML string.
    """
    # This would be called from _generate_vm_xml
    # Insert cputune, memtune, blkiotune sections
    pass
```

##### Config Schema

```yaml
# .clonebox.yaml
vm:
  name: my-vm
  ram_mb: 4096
  vcpus: 4
  
  limits:
    # CPU limits
    cpu_shares: 1024          # Relative weight (default: 1024)
    cpu_quota_percent: 200    # Max CPU% (200 = 2 full cores)
    vcpu_pin: "0-3"           # Pin to specific CPUs
    
    # Memory limits  
    memory_limit: 8G          # Hard limit
    memory_soft_limit: 6G     # Soft limit (for OOM scoring)
    memory_swap_limit: 16G    # Swap limit
    
    # I/O limits
    blkio_weight: 500         # 100-1000
    blkio_read_bps: 100M      # Read bandwidth limit
    blkio_write_bps: 50M      # Write bandwidth limit
    
    # Network limits
    network_bandwidth_in: 100Mbps
    network_bandwidth_out: 50Mbps
```

---

## Phase 3: Architecture (Weeks 11-16)

### 9. Dependency Injection

#### Current Problems

```python
# Current: Hardcoded dependencies
class SelectiveVMCloner:
    def __init__(self, conn_uri=None, user_session=False):
        import libvirt
        self.conn = libvirt.open(conn_uri)  # Hardcoded!
```

#### Proposed Architecture

```python
# src/clonebox/di.py
"""
Dependency Injection container for CloneBox.
"""
from dataclasses import dataclass, field
from typing import TypeVar, Generic, Callable, Dict, Any, Optional, Type
from contextlib import contextmanager
import threading


T = TypeVar('T')


class DIContainer:
    """
    Simple dependency injection container.
    
    Usage:
        container = DIContainer()
        
        # Register factory
        container.register(LibvirtConnection, lambda: libvirt.open("qemu:///session"))
        
        # Register singleton
        container.register_singleton(SecretsManager, SecretsManager)
        
        # Resolve
        conn = container.resolve(LibvirtConnection)
    """
    
    def __init__(self):
        self._factories: Dict[Type, Callable[[], Any]] = {}
        self._singletons: Dict[Type, Any] = {}
        self._singleton_types: set = set()
        self._lock = threading.Lock()
    
    def register(self, interface: Type[T], factory: Callable[[], T]) -> None:
        """Register a factory for a type."""
        self._factories[interface] = factory
    
    def register_singleton(self, interface: Type[T], factory: Callable[[], T]) -> None:
        """Register a singleton factory."""
        self._factories[interface] = factory
        self._singleton_types.add(interface)
    
    def register_instance(self, interface: Type[T], instance: T) -> None:
        """Register an existing instance as singleton."""
        self._singletons[interface] = instance
    
    def resolve(self, interface: Type[T]) -> T:
        """Resolve a dependency."""
        # Check for existing singleton
        if interface in self._singletons:
            return self._singletons[interface]
        
        # Get factory
        if interface not in self._factories:
            raise KeyError(f"No factory registered for {interface}")
        
        factory = self._factories[interface]
        
        # Create instance
        with self._lock:
            # Double-check for singleton
            if interface in self._singletons:
                return self._singletons[interface]
            
            instance = factory()
            
            # Store singleton
            if interface in self._singleton_types:
                self._singletons[interface] = instance
            
            return instance
    
    @contextmanager
    def scope(self):
        """Create a scoped container that inherits from parent."""
        scoped = ScopedContainer(self)
        try:
            yield scoped
        finally:
            scoped.dispose()


class ScopedContainer(DIContainer):
    """Scoped container that inherits from parent and cleans up on exit."""
    
    def __init__(self, parent: DIContainer):
        super().__init__()
        self._parent = parent
        self._disposables: list = []
    
    def resolve(self, interface: Type[T]) -> T:
        try:
            return super().resolve(interface)
        except KeyError:
            return self._parent.resolve(interface)
    
    def dispose(self):
        """Clean up scoped resources."""
        for disposable in reversed(self._disposables):
            try:
                if hasattr(disposable, 'close'):
                    disposable.close()
                elif hasattr(disposable, 'dispose'):
                    disposable.dispose()
            except Exception:
                pass


# Protocol definitions for interfaces
from typing import Protocol, runtime_checkable


@runtime_checkable
class ILibvirtConnection(Protocol):
    """Interface for libvirt connection."""
    
    def lookupByName(self, name: str) -> Any: ...
    def defineXML(self, xml: str) -> Any: ...
    def listAllDomains(self) -> list: ...
    def close(self) -> None: ...


@runtime_checkable
class ISecretsProvider(Protocol):
    """Interface for secrets provider."""
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]: ...
    def require(self, key: str) -> str: ...


@runtime_checkable
class ILogger(Protocol):
    """Interface for logger."""
    
    def info(self, msg: str, **kwargs) -> None: ...
    def error(self, msg: str, **kwargs) -> None: ...
    def debug(self, msg: str, **kwargs) -> None: ...


# Global container
_container: Optional[DIContainer] = None


def get_container() -> DIContainer:
    """Get the global DI container."""
    global _container
    if _container is None:
        _container = DIContainer()
        _setup_defaults(_container)
    return _container


def _setup_defaults(container: DIContainer) -> None:
    """Setup default registrations."""
    from clonebox.secrets import SecretsManager
    from clonebox.logging import get_logger
    
    # Secrets manager (singleton)
    container.register_singleton(ISecretsProvider, SecretsManager)
    
    # Logger (singleton)
    container.register_singleton(ILogger, lambda: get_logger("clonebox"))


# Decorator for dependency injection
from functools import wraps
import inspect


def inject(func: Callable) -> Callable:
    """
    Decorator that automatically injects dependencies based on type hints.
    
    Usage:
        @inject
        def my_function(conn: ILibvirtConnection, secrets: ISecretsProvider):
            pass
    """
    sig = inspect.signature(func)
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        container = get_container()
        
        # Get parameters that need injection
        bound = sig.bind_partial(*args, **kwargs)
        
        for param_name, param in sig.parameters.items():
            if param_name in bound.arguments:
                continue
            
            if param.annotation != inspect.Parameter.empty:
                try:
                    kwargs[param_name] = container.resolve(param.annotation)
                except KeyError:
                    pass
        
        return func(*args, **kwargs)
    
    return wrapper
```

##### Refactored Cloner

```python
# src/clonebox/cloner.py
from clonebox.di import ILibvirtConnection, ISecretsProvider, ILogger, inject, get_container


class SelectiveVMCloner:
    """
    VM cloner with dependency injection support.
    """
    
    def __init__(
        self,
        conn: Optional[ILibvirtConnection] = None,
        secrets: Optional[ISecretsProvider] = None,
        logger: Optional[ILogger] = None,
        user_session: bool = False
    ):
        container = get_container()
        
        self.user_session = user_session
        self.conn_uri = "qemu:///session" if user_session else "qemu:///system"
        
        # Use injected or resolve from container
        self.secrets = secrets or container.resolve(ISecretsProvider)
        self.log = logger or container.resolve(ILogger)
        
        # Connection can be injected for testing
        if conn:
            self.conn = conn
        else:
            self._connect()
    
    def _connect(self) -> None:
        """Connect to libvirt."""
        try:
            import libvirt
            self.conn = libvirt.open(self.conn_uri)
        except Exception as e:
            self.log.error("libvirt.connection_failed", error=str(e))
            raise


# Testing becomes much easier:
class TestSelectiveVMCloner:
    def test_create_vm_with_mock_connection(self):
        # Create mock
        mock_conn = Mock(spec=ILibvirtConnection)
        mock_conn.lookupByName.side_effect = libvirt.libvirtError("not found")
        
        # Inject mock
        cloner = SelectiveVMCloner(conn=mock_conn)
        
        # Test
        cloner.create_vm(config)
        mock_conn.defineXML.assert_called_once()
```

---

### 10. Strong Typing

#### Type Definitions

```python
# src/clonebox/types.py
"""
Type definitions for CloneBox.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TypedDict, Optional, List, Dict, Any, Literal, Union
from typing_extensions import NotRequired


# Enums
class VMState(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    PAUSED = "paused"
    UNKNOWN = "unknown"


class NetworkMode(Enum):
    AUTO = "auto"
    DEFAULT = "default"
    USER = "user"
    BRIDGE = "bridge"


class AuthMethod(Enum):
    SSH_KEY = "ssh_key"
    ONE_TIME_PASSWORD = "one_time_password"
    PASSWORD = "password"  # Deprecated


class HealthStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


# TypedDicts for config files
class VMSettingsDict(TypedDict):
    name: str
    ram_mb: NotRequired[int]
    vcpus: NotRequired[int]
    disk_size_gb: NotRequired[int]
    gui: NotRequired[bool]
    base_image: NotRequired[str]
    network_mode: NotRequired[Literal["auto", "default", "user", "bridge"]]
    username: NotRequired[str]
    auth: NotRequired["AuthConfigDict"]


class AuthConfigDict(TypedDict):
    method: Literal["ssh_key", "one_time_password", "password"]
    ssh_public_key: NotRequired[str]


class SecretsConfigDict(TypedDict):
    provider: NotRequired[Literal["auto", "env", "vault", "sops"]]
    vault: NotRequired["VaultConfigDict"]
    sops: NotRequired["SOPSConfigDict"]


class VaultConfigDict(TypedDict):
    addr: str
    path: NotRequired[str]
    token: NotRequired[str]


class SOPSConfigDict(TypedDict):
    file: str


class HealthCheckConfigDict(TypedDict):
    name: str
    type: Literal["tcp", "http", "command", "disk", "memory", "process", "file", "script"]
    timeout: NotRequired[str]
    interval: NotRequired[str]
    retries: NotRequired[int]
    # Type-specific fields...


class ResourceLimitsDict(TypedDict):
    cpu_shares: NotRequired[int]
    cpu_quota_percent: NotRequired[int]
    vcpu_pin: NotRequired[str]
    memory_limit: NotRequired[str]
    memory_soft_limit: NotRequired[str]
    blkio_weight: NotRequired[int]
    blkio_read_bps: NotRequired[str]
    blkio_write_bps: NotRequired[str]
    network_bandwidth_in: NotRequired[str]
    network_bandwidth_out: NotRequired[str]


class CloneBoxConfigDict(TypedDict):
    version: str
    generated: NotRequired[str]
    vm: VMSettingsDict
    services: NotRequired[List[str]]
    packages: NotRequired[List[str]]
    snap_packages: NotRequired[List[str]]
    post_commands: NotRequired[List[str]]
    paths: NotRequired[Dict[str, str]]
    app_data_paths: NotRequired[Dict[str, str]]
    health_checks: NotRequired[List[HealthCheckConfigDict]]
    limits: NotRequired[ResourceLimitsDict]
    secrets: NotRequired[SecretsConfigDict]


# Dataclasses for runtime
@dataclass(frozen=True)
class VMInfo:
    """Information about a VM."""
    name: str
    state: VMState
    uuid: str
    memory_kb: int
    vcpus: int
    autostart: bool
    persistent: bool


@dataclass
class ValidationResult:
    """Result of a validation check."""
    category: str
    name: str
    passed: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Complete validation report."""
    vm_name: str
    timestamp: datetime
    results: List[ValidationResult]
    
    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)
    
    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)
    
    @property
    def total(self) -> int:
        return len(self.results)
    
    @property
    def overall_status(self) -> Literal["pass", "partial", "fail"]:
        if self.failed == 0:
            return "pass"
        elif self.passed > 0:
            return "partial"
        return "fail"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "vm_name": self.vm_name,
            "timestamp": self.timestamp.isoformat(),
            "summary": {
                "passed": self.passed,
                "failed": self.failed,
                "total": self.total,
                "status": self.overall_status,
            },
            "results": [
                {
                    "category": r.category,
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "details": r.details,
                }
                for r in self.results
            ],
        }


@dataclass
class OperationResult:
    """Result of an operation."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duration_ms: float = 0


# Type aliases
PathMapping = Dict[str, str]  # host_path -> guest_path
ServiceList = List[str]
PackageList = List[str]
```

---

### 18. Audit Logging

#### Implementation

```python
# src/clonebox/audit.py
"""
Audit logging for CloneBox operations.
Records all significant actions for compliance and debugging.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List
import json
import os
import threading
import hashlib


class AuditEventType(Enum):
    # VM Operations
    VM_CREATE = "vm.create"
    VM_START = "vm.start"
    VM_STOP = "vm.stop"
    VM_DELETE = "vm.delete"
    VM_SNAPSHOT_CREATE = "vm.snapshot.create"
    VM_SNAPSHOT_RESTORE = "vm.snapshot.restore"
    VM_SNAPSHOT_DELETE = "vm.snapshot.delete"
    VM_EXPORT = "vm.export"
    VM_IMPORT = "vm.import"
    
    # Configuration
    CONFIG_CREATE = "config.create"
    CONFIG_MODIFY = "config.modify"
    CONFIG_DELETE = "config.delete"
    
    # Secrets
    SECRETS_ACCESS = "secrets.access"
    SECRETS_MODIFY = "secrets.modify"
    
    # Authentication
    AUTH_SSH_KEY_GENERATED = "auth.ssh_key.generated"
    AUTH_PASSWORD_GENERATED = "auth.password.generated"
    
    # Health
    HEALTH_CHECK_RUN = "health.check.run"
    HEALTH_CHECK_FAILED = "health.check.failed"
    
    # Repair
    REPAIR_TRIGGERED = "repair.triggered"
    REPAIR_COMPLETED = "repair.completed"
    
    # System
    SYSTEM_ERROR = "system.error"
    SYSTEM_WARNING = "system.warning"


class AuditOutcome(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    DENIED = "denied"


@dataclass
class AuditEvent:
    """A single audit event."""
    event_type: AuditEventType
    timestamp: datetime
    outcome: AuditOutcome
    
    # Actor information
    user: str
    hostname: str
    pid: int
    
    # Target information
    target_type: Optional[str] = None  # "vm", "config", "snapshot"
    target_name: Optional[str] = None
    
    # Details
    details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    
    # Correlation
    correlation_id: Optional[str] = None
    parent_event_id: Optional[str] = None
    
    # Computed
    event_id: str = field(default_factory=lambda: "")
    
    def __post_init__(self):
        if not self.event_id:
            # Generate unique event ID
            content = f"{self.timestamp.isoformat()}{self.event_type.value}{self.user}{self.pid}"
            self.event_id = hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "outcome": self.outcome.value,
            "actor": {
                "user": self.user,
                "hostname": self.hostname,
                "pid": self.pid,
            },
            "target": {
                "type": self.target_type,
                "name": self.target_name,
            } if self.target_type else None,
            "details": self.details,
            "error_message": self.error_message,
            "correlation_id": self.correlation_id,
            "parent_event_id": self.parent_event_id,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class AuditLogger:
    """
    Audit logger that writes events to file and/or external systems.
    
    Usage:
        audit = AuditLogger()
        
        with audit.operation("vm.create", target_type="vm", target_name="my-vm") as ctx:
            # do stuff
            ctx.add_detail("disk_size_gb", 30)
            
        # Or manually
        audit.log(AuditEventType.VM_START, outcome=AuditOutcome.SUCCESS, ...)
    """
    
    def __init__(
        self,
        log_path: Optional[Path] = None,
        enabled: bool = True,
        console_echo: bool = False,
    ):
        self.log_path = log_path or Path("/var/log/clonebox/audit.log")
        self.enabled = enabled
        self.console_echo = console_echo
        self._lock = threading.Lock()
        self._correlation_id: Optional[str] = None
        
        # Get actor info once
        self._user = os.environ.get('USER', 'unknown')
        self._hostname = os.uname().nodename
        self._pid = os.getpid()
        
        # Ensure log directory exists
        if self.enabled:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def log(
        self,
        event_type: AuditEventType,
        outcome: AuditOutcome,
        target_type: Optional[str] = None,
        target_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> AuditEvent:
        """Log an audit event."""
        event = AuditEvent(
            event_type=event_type,
            timestamp=datetime.now(),
            outcome=outcome,
            user=self._user,
            hostname=self._hostname,
            pid=self._pid,
            target_type=target_type,
            target_name=target_name,
            details=details or {},
            error_message=error_message,
            correlation_id=self._correlation_id,
        )
        
        if self.enabled:
            self._write_event(event)
        
        return event
    
    def _write_event(self, event: AuditEvent) -> None:
        """Write event to log file."""
        with self._lock:
            try:
                with open(self.log_path, 'a') as f:
                    f.write(event.to_json() + '\n')
            except Exception as e:
                # Fallback to stderr if log file fails
                import sys
                print(f"Audit log write failed: {e}", file=sys.stderr)
                print(event.to_json(), file=sys.stderr)
        
        if self.console_echo:
            print(f"[AUDIT] {event.event_type.value}: {event.outcome.value}")
    
    def set_correlation_id(self, correlation_id: str) -> None:
        """Set correlation ID for subsequent events."""
        self._correlation_id = correlation_id
    
    def clear_correlation_id(self) -> None:
        """Clear correlation ID."""
        self._correlation_id = None
    
    from contextlib import contextmanager
    
    @contextmanager
    def operation(
        self,
        event_type: AuditEventType,
        target_type: Optional[str] = None,
        target_name: Optional[str] = None,
    ):
        """
        Context manager for auditing an operation.
        
        Usage:
            with audit.operation(AuditEventType.VM_CREATE, "vm", "my-vm") as ctx:
                ctx.add_detail("config_path", "/path/to/config")
                do_operation()
        """
        ctx = AuditContext(self, event_type, target_type, target_name)
        try:
            yield ctx
            ctx._outcome = AuditOutcome.SUCCESS
        except Exception as e:
            ctx._outcome = AuditOutcome.FAILURE
            ctx._error = str(e)
            raise
        finally:
            self.log(
                event_type=event_type,
                outcome=ctx._outcome,
                target_type=target_type,
                target_name=target_name,
                details=ctx._details,
                error_message=ctx._error,
            )


@dataclass
class AuditContext:
    """Context for an audited operation."""
    _logger: AuditLogger
    _event_type: AuditEventType
    _target_type: Optional[str]
    _target_name: Optional[str]
    _details: Dict[str, Any] = field(default_factory=dict)
    _outcome: AuditOutcome = AuditOutcome.SUCCESS
    _error: Optional[str] = None
    
    def add_detail(self, key: str, value: Any) -> None:
        """Add a detail to the audit event."""
        self._details[key] = value
    
    def set_outcome(self, outcome: AuditOutcome) -> None:
        """Set the outcome (overrides automatic detection)."""
        self._outcome = outcome
    
    def set_error(self, error: str) -> None:
        """Set error message."""
        self._error = error


# Query interface for audit logs
class AuditQuery:
    """Query audit logs."""
    
    def __init__(self, log_path: Path):
        self.log_path = log_path
    
    def query(
        self,
        event_type: Optional[AuditEventType] = None,
        target_name: Optional[str] = None,
        user: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        outcome: Optional[AuditOutcome] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """Query audit events with filters."""
        results = []
        
        if not self.log_path.exists():
            return results
        
        with open(self.log_path) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    
                    # Apply filters
                    if event_type and data.get('event_type') != event_type.value:
                        continue
                    if target_name and data.get('target', {}).get('name') != target_name:
                        continue
                    if user and data.get('actor', {}).get('user') != user:
                        continue
                    if outcome and data.get('outcome') != outcome.value:
                        continue
                    
                    event_time = datetime.fromisoformat(data['timestamp'])
                    if start_time and event_time < start_time:
                        continue
                    if end_time and event_time > end_time:
                        continue
                    
                    # Parse event
                    event = AuditEvent(
                        event_id=data['event_id'],
                        event_type=AuditEventType(data['event_type']),
                        timestamp=event_time,
                        outcome=AuditOutcome(data['outcome']),
                        user=data['actor']['user'],
                        hostname=data['actor']['hostname'],
                        pid=data['actor']['pid'],
                        target_type=data.get('target', {}).get('type'),
                        target_name=data.get('target', {}).get('name'),
                        details=data.get('details', {}),
                        error_message=data.get('error_message'),
                        correlation_id=data.get('correlation_id'),
                    )
                    results.append(event)
                    
                    if len(results) >= limit:
                        break
                        
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        
        return results


# Global audit logger
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
```

---

## Phase 4: Advanced Features (Weeks 17-24)

### 11. Multi-VM Orchestration

#### Config Schema

```yaml
# clonebox-compose.yaml
version: '1'

# Shared defaults
defaults:
  vm:
    ram_mb: 2048
    vcpus: 2
    network_mode: bridge
  limits:
    memory_limit: 4G

# VM definitions
vms:
  frontend:
    config: ./frontend/.clonebox.yaml
    depends_on:
      - backend
    health_check:
      type: http
      url: http://localhost:3000/health
      timeout: 30s
    
  backend:
    config: ./backend/.clonebox.yaml
    depends_on:
      - database
      - cache
    environment:
      DATABASE_URL: "postgres://db:5432/app"
      REDIS_URL: "redis://cache:6379"
    health_check:
      type: http
      url: http://localhost:8000/health
    
  database:
    template: postgres-15
    vm:
      ram_mb: 4096
      disk_size_gb: 50
    volumes:
      - pgdata:/var/lib/postgresql/data
    health_check:
      type: tcp
      port: 5432
    
  cache:
    template: redis-7
    vm:
      ram_mb: 1024
    health_check:
      type: command
      exec: "redis-cli ping"
      expected_output: "PONG"

# Shared volumes
volumes:
  pgdata:
    driver: local
    size: 50G

# Networks
networks:
  default:
    driver: bridge
    subnet: 192.168.100.0/24
```

#### Implementation

```python
# src/clonebox/orchestrator.py
"""
Multi-VM orchestration for CloneBox.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Set
from enum import Enum
import yaml
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict


class VMOrchestrationState(Enum):
    PENDING = "pending"
    CREATING = "creating"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class OrchestratedVM:
    """A VM within an orchestration."""
    name: str
    config_path: Optional[Path]
    template: Optional[str]
    depends_on: List[str]
    health_check: Optional[Dict[str, Any]]
    environment: Dict[str, str]
    volumes: Dict[str, str]
    state: VMOrchestrationState = VMOrchestrationState.PENDING
    error: Optional[str] = None
    ip_address: Optional[str] = None


@dataclass
class OrchestrationPlan:
    """Execution plan for orchestration."""
    vms: Dict[str, OrchestratedVM]
    start_order: List[List[str]]  # Groups of VMs that can start in parallel
    volumes: Dict[str, Dict[str, Any]]
    networks: Dict[str, Dict[str, Any]]


class Orchestrator:
    """
    Orchestrate multiple VMs with dependencies.
    
    Usage:
        orch = Orchestrator("clonebox-compose.yaml")
        orch.up()  # Start all VMs in dependency order
        orch.down()  # Stop all VMs
        orch.status()  # Get status of all VMs
    """
    
    def __init__(self, compose_file: Path, cloner: "SelectiveVMCloner"):
        self.compose_file = Path(compose_file)
        self.cloner = cloner
        self.config = self._load_config()
        self.plan = self._create_plan()
        self._executor = ThreadPoolExecutor(max_workers=4)
    
    def _load_config(self) -> Dict[str, Any]:
        """Load and validate compose configuration."""
        with open(self.compose_file) as f:
            config = yaml.safe_load(f)
        
        # Validate version
        if config.get('version') != '1':
            raise ValueError(f"Unsupported compose version: {config.get('version')}")
        
        return config
    
    def _create_plan(self) -> OrchestrationPlan:
        """Create execution plan from configuration."""
        vms = {}
        defaults = self.config.get('defaults', {})
        
        for name, vm_config in self.config.get('vms', {}).items():
            # Merge with defaults
            merged_config = {**defaults.get('vm', {}), **vm_config.get('vm', {})}
            
            vms[name] = OrchestratedVM(
                name=name,
                config_path=Path(vm_config['config']) if 'config' in vm_config else None,
                template=vm_config.get('template'),
                depends_on=vm_config.get('depends_on', []),
                health_check=vm_config.get('health_check'),
                environment=vm_config.get('environment', {}),
                volumes=vm_config.get('volumes', {}),
            )
        
        # Calculate start order using topological sort
        start_order = self._topological_sort(vms)
        
        return OrchestrationPlan(
            vms=vms,
            start_order=start_order,
            volumes=self.config.get('volumes', {}),
            networks=self.config.get('networks', {}),
        )
    
    def _topological_sort(self, vms: Dict[str, OrchestratedVM]) -> List[List[str]]:
        """
        Topological sort with parallel group detection.
        Returns list of groups, where VMs in same group can start in parallel.
        """
        # Build dependency graph
        in_degree = {name: 0 for name in vms}
        dependents = defaultdict(list)
        
        for name, vm in vms.items():
            for dep in vm.depends_on:
                if dep not in vms:
                    raise ValueError(f"VM '{name}' depends on unknown VM '{dep}'")
                in_degree[name] += 1
                dependents[dep].append(name)
        
        # Kahn's algorithm with level tracking
        levels = []
        current_level = [name for name, degree in in_degree.items() if degree == 0]
        
        while current_level:
            levels.append(current_level)
            next_level = []
            
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
    
    def up(self, services: Optional[List[str]] = None, parallel: bool = True) -> Dict[str, VMOrchestrationState]:
        """
        Start VMs in dependency order.
        
        Args:
            services: Specific VMs to start (and their dependencies)
            parallel: If True, start independent VMs in parallel
        
        Returns:
            Dict mapping VM names to their final states
        """
        from clonebox.logging import get_logger, log_operation
        from clonebox.audit import get_audit_logger, AuditEventType
        
        log = get_logger(__name__)
        audit = get_audit_logger()
        
        # Determine which VMs to start
        if services:
            to_start = self._get_vms_with_dependencies(services)
        else:
            to_start = set(self.plan.vms.keys())
        
        results = {}
        
        with audit.operation(AuditEventType.VM_CREATE, "orchestration", str(self.compose_file)):
            for level in self.plan.start_order:
                # Filter to only VMs we're starting
                level_vms = [name for name in level if name in to_start]
                
                if not level_vms:
                    continue
                
                log.info("orchestrator.starting_level", vms=level_vms)
                
                if parallel and len(level_vms) > 1:
                    # Start in parallel
                    futures = {
                        self._executor.submit(self._start_vm, name): name
                        for name in level_vms
                    }
                    
                    for future in as_completed(futures):
                        name = futures[future]
                        try:
                            results[name] = future.result()
                        except Exception as e:
                            log.error("orchestrator.vm_failed", vm_name=name, error=str(e))
                            results[name] = VMOrchestrationState.FAILED
                            self.plan.vms[name].error = str(e)
                else:
                    # Start sequentially
                    for name in level_vms:
                        try:
                            results[name] = self._start_vm(name)
                        except Exception as e:
                            log.error("orchestrator.vm_failed", vm_name=name, error=str(e))
                            results[name] = VMOrchestrationState.FAILED
                            self.plan.vms[name].error = str(e)
        
        return results
    
    def _start_vm(self, name: str) -> VMOrchestrationState:
        """Start a single VM."""
        from clonebox.logging import get_logger
        log = get_logger(__name__)
        
        vm = self.plan.vms[name]
        vm.state = VMOrchestrationState.CREATING
        
        log.info("orchestrator.vm_starting", vm_name=name)
        
        # Load config or use template
        if vm.config_path:
            from clonebox.cli import load_clonebox_config, create_vm_from_config
            config = load_clonebox_config(vm.config_path)
        elif vm.template:
            config = self._load_template(vm.template)
        else:
            raise ValueError(f"VM '{name}' has no config or template")
        
        # Apply environment variables
        if vm.environment:
            config.setdefault('environment', {}).update(vm.environment)
        
        # Create and start
        create_vm_from_config(config, start=True, user_session=self.cloner.user_session)
        
        vm.state = VMOrchestrationState.STARTING
        
        # Wait for health check
        if vm.health_check:
            self._wait_for_health(name, vm.health_check)
        
        vm.state = VMOrchestrationState.RUNNING
        log.info("orchestrator.vm_running", vm_name=name)
        
        return vm.state
    
    def _get_vms_with_dependencies(self, services: List[str]) -> Set[str]:
        """Get set of VMs including all dependencies."""
        result = set()
        to_process = list(services)
        
        while to_process:
            name = to_process.pop()
            if name in result:
                continue
            
            if name not in self.plan.vms:
                raise ValueError(f"Unknown VM: {name}")
            
            result.add(name)
            to_process.extend(self.plan.vms[name].depends_on)
        
        return result
    
    def down(self, services: Optional[List[str]] = None, timeout: int = 30) -> None:
        """Stop all VMs in reverse dependency order."""
        from clonebox.logging import get_logger
        log = get_logger(__name__)
        
        # Reverse the start order
        stop_order = list(reversed(self.plan.start_order))
        
        for level in stop_order:
            for name in level:
                if services and name not in services:
                    continue
                
                try:
                    log.info("orchestrator.vm_stopping", vm_name=name)
                    self.cloner.stop_vm(name)
                    self.plan.vms[name].state = VMOrchestrationState.STOPPED
                except Exception as e:
                    log.error("orchestrator.vm_stop_failed", vm_name=name, error=str(e))
    
    def status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all VMs."""
        result = {}
        
        for name, vm in self.plan.vms.items():
            result[name] = {
                "state": vm.state.value,
                "depends_on": vm.depends_on,
                "ip_address": vm.ip_address,
                "error": vm.error,
            }
        
        return result
    
    def _wait_for_health(self, name: str, health_config: Dict[str, Any], timeout: int = 300) -> None:
        """Wait for VM to pass health check."""
        from clonebox.health import HealthCheckExecutor, HEALTH_CHECK_TYPES
        import time
        
        check_type = health_config['type']
        if check_type not in HEALTH_CHECK_TYPES:
            return
        
        executor = HealthCheckExecutor(name, self.cloner.conn_uri)
        check_class = HEALTH_CHECK_TYPES[check_type]
        check = check_class(f"{name}-health", health_config)
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            result = check.run(executor)
            if result.status.value == "healthy":
                return
            time.sleep(5)
        
        raise TimeoutError(f"VM '{name}' health check timed out after {timeout}s")
    
    def _load_template(self, template_name: str) -> Dict[str, Any]:
        """Load a VM template."""
        # Templates could be in ~/.clonebox/templates/ or bundled
        template_paths = [
            Path.home() / ".clonebox" / "templates" / f"{template_name}.yaml",
            Path(__file__).parent / "templates" / f"{template_name}.yaml",
        ]
        
        for path in template_paths:
            if path.exists():
                with open(path) as f:
                    return yaml.safe_load(f)
        
        raise ValueError(f"Template not found: {template_name}")
```

---

### 12. Plugin System

```python
# src/clonebox/plugins.py
"""
Plugin system for CloneBox extensibility.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any, Type
import importlib.util
import sys


@dataclass
class PluginMetadata:
    """Plugin metadata."""
    name: str
    version: str
    description: str
    author: str
    hooks: List[str]


class Plugin(ABC):
    """Base class for CloneBox plugins."""
    
    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        pass
    
    def on_load(self) -> None:
        """Called when plugin is loaded."""
        pass
    
    def on_unload(self) -> None:
        """Called when plugin is unloaded."""
        pass


class DetectorPlugin(Plugin):
    """Plugin for extending system detection."""
    
    @abstractmethod
    def detect(self) -> List[Dict[str, Any]]:
        """Detect resources."""
        pass


class HealthCheckPlugin(Plugin):
    """Plugin for custom health checks."""
    
    @abstractmethod
    def check(self, executor: "HealthCheckExecutor") -> "HealthCheckResult":
        """Run health check."""
        pass


class ProvisionerPlugin(Plugin):
    """Plugin for VM provisioning."""
    
    @abstractmethod
    def provision(self, vm_name: str, config: Dict[str, Any]) -> None:
        """Provision VM after creation."""
        pass


class PluginManager:
    """
    Manage CloneBox plugins.
    
    Plugins are loaded from:
    - ~/.clonebox/plugins/
    - /etc/clonebox/plugins/
    - Entry points: clonebox.plugins
    """
    
    PLUGIN_DIRS = [
        Path.home() / ".clonebox" / "plugins",
        Path("/etc/clonebox/plugins"),
    ]
    
    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._hooks: Dict[str, List[Plugin]] = {}
    
    def discover(self) -> List[PluginMetadata]:
        """Discover available plugins."""
        discovered = []
        
        # Discover from directories
        for plugin_dir in self.PLUGIN_DIRS:
            if plugin_dir.exists():
                for path in plugin_dir.glob("*.py"):
                    try:
                        metadata = self._load_metadata(path)
                        if metadata:
                            discovered.append(metadata)
                    except Exception:
                        pass
        
        # Discover from entry points
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group='clonebox.plugins')
            for ep in eps:
                try:
                    plugin_class = ep.load()
                    plugin = plugin_class()
                    discovered.append(plugin.metadata)
                except Exception:
                    pass
        except ImportError:
            pass
        
        return discovered
    
    def load(self, name: str) -> Plugin:
        """Load a plugin by name."""
        if name in self._plugins:
            return self._plugins[name]
        
        # Try to find and load plugin
        plugin = self._find_and_load(name)
        
        if plugin is None:
            raise ValueError(f"Plugin not found: {name}")
        
        # Register hooks
        for hook in plugin.metadata.hooks:
            self._hooks.setdefault(hook, []).append(plugin)
        
        plugin.on_load()
        self._plugins[name] = plugin
        
        return plugin
    
    def unload(self, name: str) -> None:
        """Unload a plugin."""
        if name not in self._plugins:
            return
        
        plugin = self._plugins[name]
        plugin.on_unload()
        
        # Remove from hooks
        for hook in plugin.metadata.hooks:
            if hook in self._hooks:
                self._hooks[hook] = [p for p in self._hooks[hook] if p != plugin]
        
        del self._plugins[name]
    
    def get_hooks(self, hook_name: str) -> List[Plugin]:
        """Get all plugins registered for a hook."""
        return self._hooks.get(hook_name, [])
    
    def _find_and_load(self, name: str) -> Optional[Plugin]:
        """Find and load a plugin by name."""
        # Try directories
        for plugin_dir in self.PLUGIN_DIRS:
            path = plugin_dir / f"{name}.py"
            if path.exists():
                return self._load_from_file(path)
        
        # Try entry points
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group='clonebox.plugins')
            for ep in eps:
                if ep.name == name:
                    plugin_class = ep.load()
                    return plugin_class()
        except ImportError:
            pass
        
        return None
    
    def _load_from_file(self, path: Path) -> Plugin:
        """Load a plugin from a Python file."""
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)
        
        # Find Plugin subclass
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and 
                issubclass(attr, Plugin) and 
                attr is not Plugin and
                not attr.__name__.endswith('Plugin')):
                return attr()
        
        raise ValueError(f"No Plugin class found in {path}")
    
    def _load_metadata(self, path: Path) -> Optional[PluginMetadata]:
        """Load metadata without fully loading the plugin."""
        try:
            with open(path) as f:
                content = f.read()
            
            # Simple parsing of docstring metadata
            if '"""' in content:
                docstring = content.split('"""')[1]
                # Parse YAML-like metadata from docstring
                # This is a simplified version
                return PluginMetadata(
                    name=path.stem,
                    version="0.0.0",
                    description=docstring.strip().split('\n')[0],
                    author="unknown",
                    hooks=[],
                )
        except Exception:
            pass
        
        return None
```

---

### 13. Remote VM Management

```python
# src/clonebox/remote.py
"""
Remote VM management for CloneBox.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse
import subprocess


@dataclass
class RemoteConnection:
    """Remote libvirt connection configuration."""
    uri: str
    ssh_key: Optional[Path] = None
    ssh_user: Optional[str] = None
    ssh_port: int = 22
    
    @classmethod
    def from_string(cls, connection_string: str) -> "RemoteConnection":
        """
        Parse connection string.
        
        Formats:
        - qemu+ssh://user@host/system
        - user@host
        - ssh://user@host
        """
        if connection_string.startswith("qemu"):
            return cls(uri=connection_string)
        
        # Parse SSH-style connection
        if "@" in connection_string:
            user, host = connection_string.split("@", 1)
        else:
            user, host = None, connection_string
        
        # Extract port if present
        port = 22
        if ":" in host:
            host, port_str = host.rsplit(":", 1)
            port = int(port_str)
        
        uri = f"qemu+ssh://{user}@{host}/system" if user else f"qemu+ssh://{host}/system"
        
        return cls(uri=uri, ssh_user=user, ssh_port=port)
    
    def get_libvirt_uri(self) -> str:
        """Get the libvirt connection URI."""
        return self.uri


class RemoteCloner:
    """
    Execute CloneBox operations on remote hosts.
    
    Usage:
        remote = RemoteCloner("user@server")
        remote.list_vms()
        remote.create_vm(config)
    """
    
    def __init__(self, connection: RemoteConnection):
        self.connection = connection
        self._verify_connection()
    
    def _verify_connection(self) -> None:
        """Verify SSH connection to remote host."""
        parsed = urlparse(self.connection.uri)
        host = parsed.hostname
        
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", f"{parsed.username}@{host}", "echo", "ok"],
            capture_output=True,
            text=True,
        )
        
        if result.returncode != 0:
            raise ConnectionError(f"Cannot connect to {host}: {result.stderr}")
    
    def _run_remote(self, command: List[str]) -> subprocess.CompletedProcess:
        """Run a command on the remote host."""
        parsed = urlparse(self.connection.uri)
        host = f"{parsed.username}@{parsed.hostname}" if parsed.username else parsed.hostname
        
        ssh_cmd = ["ssh"]
        if self.connection.ssh_key:
            ssh_cmd.extend(["-i", str(self.connection.ssh_key)])
        ssh_cmd.extend(["-p", str(self.connection.ssh_port)])
        ssh_cmd.append(host)
        ssh_cmd.extend(command)
        
        return subprocess.run(ssh_cmd, capture_output=True, text=True)
    
    def list_vms(self) -> List[Dict[str, Any]]:
        """List VMs on remote host."""
        result = self._run_remote(["clonebox", "list", "--json"])
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to list VMs: {result.stderr}")
        
        import json
        return json.loads(result.stdout)
    
    def create_vm(self, config: Dict[str, Any]) -> str:
        """Create VM on remote host."""
        import json
        import tempfile
        
        # Write config to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(config, f)
            local_config = f.name
        
        # Copy config to remote
        parsed = urlparse(self.connection.uri)
        host = f"{parsed.username}@{parsed.hostname}" if parsed.username else parsed.hostname
        remote_config = f"/tmp/clonebox-{Path(local_config).stem}.yaml"
        
        subprocess.run(["scp", local_config, f"{host}:{remote_config}"], check=True)
        
        # Create VM
        result = self._run_remote([
            "clonebox", "clone", "--config", remote_config, "--run"
        ])
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create VM: {result.stderr}")
        
        return result.stdout.strip()
    
    def start_vm(self, vm_name: str) -> None:
        """Start VM on remote host."""
        result = self._run_remote(["clonebox", "start", vm_name])
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start VM: {result.stderr}")
    
    def stop_vm(self, vm_name: str) -> None:
        """Stop VM on remote host."""
        result = self._run_remote(["clonebox", "stop", vm_name])
        if result.returncode != 0:
            raise RuntimeError(f"Failed to stop VM: {result.stderr}")
    
    def delete_vm(self, vm_name: str) -> None:
        """Delete VM on remote host."""
        result = self._run_remote(["clonebox", "delete", vm_name, "--yes"])
        if result.returncode != 0:
            raise RuntimeError(f"Failed to delete VM: {result.stderr}")
    
    def get_status(self, vm_name: str) -> Dict[str, Any]:
        """Get VM status on remote host."""
        result = self._run_remote(["clonebox", "status", vm_name, "--json"])
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get status: {result.stderr}")
        
        import json
        return json.loads(result.stdout)
```

---

## Implementation Timeline

```
Week 1-2:   Phase 1 - Secrets Isolation, Rollback
Week 3-4:   Phase 1 - Structured Logging, integration
Week 5-7:   Phase 2 - Snapshot Management
Week 8-10:  Phase 2 - Advanced Health Checks, Resource Limits
Week 11-13: Phase 3 - Dependency Injection, Strong Typing
Week 14-16: Phase 3 - Audit Logging
Week 17-20: Phase 4 - Multi-VM Orchestration
Week 21-24: Phase 4 - Plugin System, Remote Management
```

## Testing Strategy

Each feature requires:
1. Unit tests with mocked dependencies
2. Integration tests with real libvirt (when available)
3. E2E tests for user workflows
4. Performance benchmarks for critical paths

## Migration Path

1. All changes backward compatible with v1 config format
2. Deprecation warnings for legacy features
3. Migration guide for each breaking change
4. v2 config format opt-in, becomes default in v3

---

*Document generated for CloneBox v2.0 planning*
