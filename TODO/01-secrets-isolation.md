# Secrets Isolation in Cloud-Init

**Status:** 📝 Planned  
**Priority:** Critical  
**Estimated Effort:** 2-3 weeks  
**Dependencies:** None

## Problem Statement

Currently, CloneBox stores VM credentials in plain text within cloud-init user-data:

```yaml
# .clonebox.yaml
vm:
  username: ubuntu
  password: ${VM_PASSWORD}  # Loaded from .env but stored in ISO
```

Issues:
1. **Password in cloud-init ISO** - readable by anyone with disk access
2. **`.env` file** - often accidentally committed to git
3. **No encryption at rest** - secrets visible in VM artifacts
4. **Single auth method** - only password, no SSH keys support
5. **No secrets rotation** - manual process, error-prone

## Proposed Solution

Multi-layered secrets management with pluggable providers:

```yaml
# .clonebox.yaml v2
vm:
  auth:
    method: ssh_key  # ssh_key | password | both
    ssh_keys:
      - ~/.ssh/id_ed25519.pub
      - github:username  # fetch from GitHub
    password:
      provider: vault   # env | vault | sops | age | 1password
      path: secret/clonebox/vms/dev
      key: password
```

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    CloneBox CLI                         │
├─────────────────────────────────────────────────────────┤
│                 SecretsManager                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │   Env   │ │  Vault  │ │  SOPS   │ │   Age   │       │
│  │Provider │ │Provider │ │Provider │ │Provider │       │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘       │
│       └──────────┬┴──────────┬┴──────────┬┘            │
│                  │           │           │              │
│            ┌─────▼───────────▼───────────▼─────┐       │
│            │      SecretProvider Interface      │       │
│            └─────────────────┬─────────────────┘       │
│                              │                          │
│            ┌─────────────────▼─────────────────┐       │
│            │         cloud-init builder         │       │
│            │    (secrets injected at runtime)   │       │
│            └───────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

### Secret Provider Interface

```python
# src/clonebox/secrets/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum

class SecretType(Enum):
    PASSWORD = "password"
    SSH_KEY = "ssh_key"
    API_KEY = "api_key"
    CERTIFICATE = "certificate"

@dataclass
class Secret:
    """Represents a retrieved secret."""
    value: str
    secret_type: SecretType
    metadata: Dict[str, Any]
    expires_at: Optional[datetime] = None
    
    def __repr__(self) -> str:
        return f"Secret(type={self.secret_type}, redacted=***)"
    
    def __str__(self) -> str:
        return "***REDACTED***"

class SecretProvider(ABC):
    """Base interface for secret providers."""
    
    name: str
    
    @abstractmethod
    def get_secret(self, path: str, key: Optional[str] = None) -> Secret:
        """Retrieve a secret from the provider."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is configured and accessible."""
        pass
    
    def rotate_secret(self, path: str) -> Secret:
        """Rotate a secret (optional, not all providers support)."""
        raise NotImplementedError(f"{self.name} doesn't support rotation")
    
    def list_secrets(self, prefix: str) -> list[str]:
        """List available secrets (optional)."""
        raise NotImplementedError(f"{self.name} doesn't support listing")
```

### Provider Implementations

```python
# src/clonebox/secrets/providers/env.py
import os
from pathlib import Path
from ..base import SecretProvider, Secret, SecretType

class EnvSecretProvider(SecretProvider):
    """Load secrets from environment variables or .env file."""
    
    name = "env"
    
    def __init__(self, env_file: Optional[Path] = None):
        self.env_file = env_file or Path(".env")
        self._load_env_file()
    
    def _load_env_file(self) -> None:
        if self.env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(self.env_file)
    
    def get_secret(self, path: str, key: Optional[str] = None) -> Secret:
        # path is the env var name for this provider
        var_name = key or path
        value = os.environ.get(var_name)
        
        if value is None:
            raise SecretNotFoundError(f"Environment variable {var_name} not set")
        
        return Secret(
            value=value,
            secret_type=SecretType.PASSWORD,
            metadata={"source": "environment", "var_name": var_name}
        )
    
    def is_available(self) -> bool:
        return True  # Always available


# src/clonebox/secrets/providers/vault.py
class VaultSecretProvider(SecretProvider):
    """HashiCorp Vault integration."""
    
    name = "vault"
    
    def __init__(
        self,
        addr: Optional[str] = None,
        token: Optional[str] = None,
        role_id: Optional[str] = None,
        secret_id: Optional[str] = None,
    ):
        self.addr = addr or os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
        self._client = None
        self._init_client(token, role_id, secret_id)
    
    def _init_client(self, token, role_id, secret_id) -> None:
        import hvac
        
        self._client = hvac.Client(url=self.addr)
        
        if token:
            self._client.token = token
        elif role_id and secret_id:
            # AppRole authentication
            self._client.auth.approle.login(
                role_id=role_id,
                secret_id=secret_id
            )
        elif os.environ.get("VAULT_TOKEN"):
            self._client.token = os.environ["VAULT_TOKEN"]
        else:
            raise SecretProviderConfigError("No Vault authentication provided")
    
    def get_secret(self, path: str, key: Optional[str] = None) -> Secret:
        try:
            response = self._client.secrets.kv.v2.read_secret_version(path=path)
            data = response["data"]["data"]
            
            value = data.get(key) if key else data
            if value is None:
                raise SecretNotFoundError(f"Key {key} not found in {path}")
            
            return Secret(
                value=value if isinstance(value, str) else str(value),
                secret_type=SecretType.PASSWORD,
                metadata={
                    "source": "vault",
                    "path": path,
                    "version": response["data"]["metadata"]["version"]
                }
            )
        except Exception as e:
            raise SecretRetrievalError(f"Failed to get secret from Vault: {e}")
    
    def is_available(self) -> bool:
        try:
            return self._client.is_authenticated()
        except Exception:
            return False
    
    def rotate_secret(self, path: str) -> Secret:
        # Generate new password
        import secrets
        new_password = secrets.token_urlsafe(32)
        
        # Store in Vault
        self._client.secrets.kv.v2.create_or_update_secret(
            path=path,
            secret={"password": new_password}
        )
        
        return self.get_secret(path, "password")


# src/clonebox/secrets/providers/sops.py
class SOPSSecretProvider(SecretProvider):
    """Mozilla SOPS encrypted files."""
    
    name = "sops"
    
    def __init__(self, file_path: Path):
        self.file_path = file_path
    
    def get_secret(self, path: str, key: Optional[str] = None) -> Secret:
        import subprocess
        import json
        
        result = subprocess.run(
            ["sops", "-d", "--output-type", "json", str(self.file_path)],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise SecretRetrievalError(f"SOPS decryption failed: {result.stderr}")
        
        data = json.loads(result.stdout)
        
        # Navigate path like "vm.password"
        value = data
        for part in path.split("."):
            value = value.get(part)
            if value is None:
                raise SecretNotFoundError(f"Path {path} not found in SOPS file")
        
        return Secret(
            value=value,
            secret_type=SecretType.PASSWORD,
            metadata={"source": "sops", "file": str(self.file_path)}
        )
    
    def is_available(self) -> bool:
        import shutil
        return shutil.which("sops") is not None and self.file_path.exists()


# src/clonebox/secrets/providers/age.py
class AgeSecretProvider(SecretProvider):
    """Age encryption for secrets."""
    
    name = "age"
    
    def __init__(self, identity_file: Path, encrypted_file: Path):
        self.identity_file = identity_file
        self.encrypted_file = encrypted_file
    
    def get_secret(self, path: str, key: Optional[str] = None) -> Secret:
        import subprocess
        
        result = subprocess.run(
            ["age", "-d", "-i", str(self.identity_file), str(self.encrypted_file)],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise SecretRetrievalError(f"Age decryption failed: {result.stderr}")
        
        # Parse decrypted content (assuming YAML or JSON)
        import yaml
        data = yaml.safe_load(result.stdout)
        
        return Secret(
            value=data.get(path, data.get(key, result.stdout.strip())),
            secret_type=SecretType.PASSWORD,
            metadata={"source": "age"}
        )
    
    def is_available(self) -> bool:
        import shutil
        return (
            shutil.which("age") is not None 
            and self.identity_file.exists() 
            and self.encrypted_file.exists()
        )
```

### Secrets Manager

```python
# src/clonebox/secrets/manager.py
from typing import Dict, Type, Optional
from .base import SecretProvider, Secret
from .providers import EnvSecretProvider, VaultSecretProvider, SOPSSecretProvider

class SecretsManager:
    """Central manager for all secret operations."""
    
    _providers: Dict[str, Type[SecretProvider]] = {
        "env": EnvSecretProvider,
        "vault": VaultSecretProvider,
        "sops": SOPSSecretProvider,
        "age": AgeSecretProvider,
    }
    
    def __init__(self):
        self._instances: Dict[str, SecretProvider] = {}
    
    @classmethod
    def register_provider(cls, name: str, provider_class: Type[SecretProvider]) -> None:
        """Register a custom secret provider."""
        cls._providers[name] = provider_class
    
    def get_provider(self, name: str, **config) -> SecretProvider:
        """Get or create a provider instance."""
        cache_key = f"{name}:{hash(frozenset(config.items()))}"
        
        if cache_key not in self._instances:
            if name not in self._providers:
                raise ValueError(f"Unknown secret provider: {name}")
            
            provider_class = self._providers[name]
            self._instances[cache_key] = provider_class(**config)
        
        return self._instances[cache_key]
    
    def resolve_secret(self, secret_config: dict) -> Secret:
        """Resolve a secret from configuration."""
        provider_name = secret_config.get("provider", "env")
        path = secret_config.get("path", "")
        key = secret_config.get("key")
        
        # Extract provider-specific config
        provider_config = {
            k: v for k, v in secret_config.items() 
            if k not in ("provider", "path", "key")
        }
        
        provider = self.get_provider(provider_name, **provider_config)
        
        if not provider.is_available():
            raise SecretProviderUnavailable(
                f"Provider {provider_name} is not available. "
                f"Check configuration and dependencies."
            )
        
        return provider.get_secret(path, key)
```

### SSH Key Management

```python
# src/clonebox/secrets/ssh.py
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
import subprocess
import urllib.request

@dataclass
class SSHPublicKey:
    key: str
    comment: str
    key_type: str  # ssh-ed25519, ssh-rsa, etc.
    source: str    # file, github, gitlab

class SSHKeyManager:
    """Manage SSH keys for VM authentication."""
    
    def __init__(self):
        self.keys: List[SSHPublicKey] = []
    
    def add_from_file(self, path: Path) -> SSHPublicKey:
        """Load SSH public key from file."""
        if not path.exists():
            # Try adding .pub suffix
            pub_path = path.with_suffix(path.suffix + ".pub")
            if pub_path.exists():
                path = pub_path
            else:
                raise FileNotFoundError(f"SSH key not found: {path}")
        
        content = path.read_text().strip()
        parts = content.split(None, 2)
        
        key = SSHPublicKey(
            key=content,
            key_type=parts[0],
            comment=parts[2] if len(parts) > 2 else str(path),
            source=f"file:{path}"
        )
        self.keys.append(key)
        return key
    
    def add_from_github(self, username: str) -> List[SSHPublicKey]:
        """Fetch SSH keys from GitHub."""
        url = f"https://github.com/{username}.keys"
        
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                content = response.read().decode("utf-8")
        except Exception as e:
            raise SSHKeyFetchError(f"Failed to fetch keys from GitHub: {e}")
        
        added = []
        for line in content.strip().split("\n"):
            if line:
                parts = line.split(None, 2)
                key = SSHPublicKey(
                    key=line,
                    key_type=parts[0],
                    comment=f"github:{username}",
                    source=f"github:{username}"
                )
                self.keys.append(key)
                added.append(key)
        
        return added
    
    def add_from_gitlab(self, username: str, instance: str = "gitlab.com") -> List[SSHPublicKey]:
        """Fetch SSH keys from GitLab."""
        url = f"https://{instance}/{username}.keys"
        # Similar implementation to GitHub
        pass
    
    def generate_authorized_keys(self) -> str:
        """Generate authorized_keys content."""
        return "\n".join(key.key for key in self.keys)
    
    def generate_cloud_init_ssh_section(self) -> dict:
        """Generate cloud-init ssh_authorized_keys section."""
        return {
            "ssh_authorized_keys": [key.key for key in self.keys],
            "disable_root": True,
            "ssh_pwauth": False if self.keys else True,
        }
```

### Updated Cloud-Init Builder

```python
# src/clonebox/cloudinit/builder.py
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from ..secrets.manager import SecretsManager
from ..secrets.ssh import SSHKeyManager

@dataclass
class AuthConfig:
    method: str = "ssh_key"  # ssh_key, password, both
    ssh_keys: List[str] = None
    password_config: Optional[Dict[str, Any]] = None

class CloudInitBuilder:
    """Build cloud-init configuration with secure secrets handling."""
    
    def __init__(
        self,
        secrets_manager: SecretsManager,
        ssh_manager: SSHKeyManager
    ):
        self.secrets = secrets_manager
        self.ssh = ssh_manager
    
    def build_user_data(
        self,
        username: str,
        auth_config: AuthConfig,
        packages: List[str],
        services: List[str],
        runcmd: List[str],
    ) -> str:
        """Build user-data YAML with secure secret injection."""
        
        user_data = {
            "users": [self._build_user_config(username, auth_config)],
            "package_update": True,
            "package_upgrade": True,
            "packages": packages,
            "runcmd": runcmd,
        }
        
        # Add SSH configuration
        if auth_config.method in ("ssh_key", "both"):
            user_data.update(self.ssh.generate_cloud_init_ssh_section())
        
        return "#cloud-config\n" + yaml.dump(user_data, default_flow_style=False)
    
    def _build_user_config(self, username: str, auth_config: AuthConfig) -> dict:
        """Build user configuration with appropriate auth."""
        user = {
            "name": username,
            "sudo": "ALL=(ALL) NOPASSWD:ALL",
            "shell": "/bin/bash",
            "groups": ["sudo", "docker", "libvirt"],
        }
        
        # Add SSH keys
        if auth_config.method in ("ssh_key", "both") and auth_config.ssh_keys:
            for key_spec in auth_config.ssh_keys:
                if key_spec.startswith("github:"):
                    self.ssh.add_from_github(key_spec.split(":", 1)[1])
                elif key_spec.startswith("gitlab:"):
                    self.ssh.add_from_gitlab(key_spec.split(":", 1)[1])
                else:
                    self.ssh.add_from_file(Path(key_spec).expanduser())
            
            user["ssh_authorized_keys"] = [k.key for k in self.ssh.keys]
        
        # Add password (resolved at build time, not stored)
        if auth_config.method in ("password", "both") and auth_config.password_config:
            secret = self.secrets.resolve_secret(auth_config.password_config)
            # Use hashed password for security
            import crypt
            hashed = crypt.crypt(secret.value, crypt.mksalt(crypt.METHOD_SHA512))
            user["passwd"] = hashed
            user["lock_passwd"] = False
        
        return user
```

### Configuration Schema Update

```yaml
# .clonebox.yaml v2 schema
version: '2'

vm:
  name: my-dev-vm
  
  # New auth section
  auth:
    # Authentication method: ssh_key (recommended), password, or both
    method: ssh_key
    
    # SSH keys - multiple sources supported
    ssh_keys:
      - ~/.ssh/id_ed25519.pub           # Local file
      - ~/.ssh/id_rsa.pub               # Another local file
      - github:myusername               # Fetch from GitHub
      - gitlab:myusername@gitlab.com    # Fetch from GitLab
    
    # Password configuration (optional with ssh_key method)
    password:
      provider: vault                    # env | vault | sops | age
      # Provider-specific options:
      # For env:
      #   var_name: VM_PASSWORD
      # For vault:
      path: secret/clonebox/vms/dev
      key: password
      # For sops:
      #   file: secrets.yaml
      #   path: vm.password
      # For age:
      #   identity: ~/.age/key.txt
      #   file: secrets.age

  # Legacy support (deprecated, will be removed in v3)
  # username: ubuntu
  # password: ${VM_PASSWORD}
```

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)

1. **Create secrets module structure**
   ```
   src/clonebox/secrets/
   ├── __init__.py
   ├── base.py          # Interfaces and base classes
   ├── exceptions.py    # Custom exceptions
   ├── manager.py       # SecretsManager
   ├── ssh.py           # SSHKeyManager
   └── providers/
       ├── __init__.py
       ├── env.py
       ├── vault.py
       ├── sops.py
       └── age.py
   ```

2. **Implement EnvSecretProvider** (backward compatible)

3. **Implement SSHKeyManager**

4. **Update models.py with new auth schema**

### Phase 2: Provider Implementations (Week 2)

1. **VaultSecretProvider with AppRole auth**
2. **SOPSSecretProvider**
3. **AgeSecretProvider**
4. **Unit tests for all providers**

### Phase 3: Integration (Week 3)

1. **Update CloudInitBuilder**
2. **Update CLI commands**
3. **Migration tool for v1 configs**
4. **Documentation**
5. **Integration tests**

## API Changes

### New CLI Options

```bash
# Use SSH key authentication (default in v2)
clonebox clone . --auth ssh

# Use password from Vault
clonebox clone . --auth password --secret-provider vault --secret-path secret/vms/dev

# Add SSH key from GitHub
clonebox clone . --ssh-key github:username

# Rotate VM password
clonebox secret rotate my-vm --provider vault
```

### New Python API

```python
from clonebox.secrets import SecretsManager, SSHKeyManager
from clonebox.secrets.providers import VaultSecretProvider

# Configure secrets
secrets = SecretsManager()
secrets.register_provider("custom", MyCustomProvider)

# Use in cloner
cloner = SelectiveVMCloner(
    secrets_manager=secrets,
    ssh_manager=SSHKeyManager()
)
```

## Migration Guide

### From v1 to v2 Config

```bash
# Automatic migration
clonebox config migrate .clonebox.yaml

# Manual steps:
# 1. Move password to secrets provider
# 2. Add SSH keys
# 3. Update auth section
```

### Backward Compatibility

- v1 configs will continue to work with deprecation warning
- `password: ${VM_PASSWORD}` syntax mapped to `env` provider
- Automatic migration offered on first use

## Testing Strategy

```python
# tests/test_secrets.py
class TestSecretsManager:
    def test_env_provider_loads_from_dotenv(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_SECRET=mysecret")
        
        provider = EnvSecretProvider(env_file)
        secret = provider.get_secret("TEST_SECRET")
        
        assert secret.value == "mysecret"
        assert secret.secret_type == SecretType.PASSWORD
    
    def test_vault_provider_requires_auth(self):
        with pytest.raises(SecretProviderConfigError):
            VaultSecretProvider()  # No auth provided
    
    @pytest.mark.integration
    def test_vault_integration(self, vault_server):
        provider = VaultSecretProvider(
            addr=vault_server.addr,
            token=vault_server.root_token
        )
        # ... test actual Vault operations

class TestSSHKeyManager:
    def test_load_from_file(self, tmp_path):
        key_file = tmp_path / "id_ed25519.pub"
        key_file.write_text("ssh-ed25519 AAAA... user@host")
        
        manager = SSHKeyManager()
        key = manager.add_from_file(key_file)
        
        assert key.key_type == "ssh-ed25519"
    
    @pytest.mark.network
    def test_fetch_from_github(self):
        manager = SSHKeyManager()
        keys = manager.add_from_github("torvalds")
        
        assert len(keys) > 0
```

## Security Considerations

1. **Never log secrets** - All `Secret` objects redact on `__str__`
2. **Memory safety** - Clear secrets from memory after use
3. **Audit trail** - Log secret access (not values)
4. **Least privilege** - Vault tokens scoped to specific paths
5. **Rotation support** - Built-in for Vault provider
