"""
Secrets management for CloneBox.
Supports multiple backends: env, vault, sops, age.
"""

import json
import os
import secrets
import string
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
    def list_secrets(self) -> List[str]:
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
            try:
                with open(self.env_file) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, value = line.partition("=")
                            self._cache[key.strip()] = value.strip().strip("'\"")
            except (FileNotFoundError, OSError):
                return

    def get_secret(self, key: str) -> Optional[SecretValue]:
        # Check environment first, then cache from file
        value = os.environ.get(key) or self._cache.get(key)
        if value:
            return SecretValue(key=key, value=value, source="env")
        return None

    def list_secrets(self) -> List[str]:
        return list(
            set(
                list(self._cache.keys())
                + [
                    k
                    for k in os.environ.keys()
                    if k.startswith("VM_") or k.startswith("CLONEBOX_")
                ]
            )
        )

    def is_available(self) -> bool:
        return True


class VaultSecretsProvider(SecretsProvider):
    """Load secrets from HashiCorp Vault."""

    def __init__(
        self,
        addr: Optional[str] = None,
        token: Optional[str] = None,
        path_prefix: str = "secret/clonebox",
    ):
        self.addr = addr or os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
        self.token = token or os.environ.get("VAULT_TOKEN")
        self.path_prefix = path_prefix
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import hvac

                self._client = hvac.Client(url=self.addr, token=self.token)
            except ImportError:
                raise RuntimeError(
                    "hvac package required for Vault support: pip install hvac"
                )
        return self._client

    def get_secret(self, key: str) -> Optional[SecretValue]:
        try:
            client = self._get_client()
            path = f"{self.path_prefix}/{key}"
            response = client.secrets.kv.v2.read_secret_version(path=path)
            value = response["data"]["data"].get("value")
            if value:
                return SecretValue(key=key, value=value, source="vault")
        except Exception:
            pass
        return None

    def list_secrets(self) -> List[str]:
        try:
            client = self._get_client()
            response = client.secrets.kv.v2.list_secrets(path=self.path_prefix)
            return response["data"]["keys"]
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
                ["sops", "-d", str(self.secrets_file)],
                capture_output=True,
                text=True,
                check=True,
            )
            import yaml

            self._cache = yaml.safe_load(result.stdout) or {}
        except (subprocess.CalledProcessError, FileNotFoundError):
            self._cache = {}

        return self._cache

    def get_secret(self, key: str) -> Optional[SecretValue]:
        data = self._decrypt()
        # Support nested keys: "vm.password" -> data['vm']['password']
        parts = key.split(".")
        value = data
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None

        if isinstance(value, str):
            return SecretValue(key=key, value=value, source="sops")
        return None

    def list_secrets(self) -> List[str]:
        data = self._decrypt()
        return list(data.keys())

    def is_available(self) -> bool:
        try:
            subprocess.run(["sops", "--version"], capture_output=True, check=True)
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
        "env": EnvSecretsProvider,
        "vault": VaultSecretsProvider,
        "sops": SOPSSecretsProvider,
    }

    def __init__(self, provider: Optional[str] = None, **kwargs):
        self._providers: List[SecretsProvider] = []

        if provider:
            # Use specific provider
            if provider not in self.PROVIDERS:
                raise ValueError(
                    f"Unknown provider: {provider}. Available: {list(self.PROVIDERS.keys())}"
                )
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
        return "".join(secrets.choice(alphabet) for _ in range(length))

    @staticmethod
    def generate_one_time_password() -> Tuple[str, str]:
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
            subprocess.run(
                ["ssh-keygen", "-t", key_type, "-N", "", "-f", str(key_path), "-q"],
                check=True,
            )

            private_key = key_path.read_text()
            public_key = key_path.with_suffix(".pub").read_text()

        return cls(private_key=private_key, public_key=public_key, key_type=key_type)

    @classmethod
    def from_file(cls, private_key_path: Path) -> "SSHKeyPair":
        """Load existing SSH key pair."""
        private_key = private_key_path.read_text()
        public_key = private_key_path.with_suffix(".pub").read_text()
        return cls(private_key=private_key, public_key=public_key)

    def save(self, private_key_path: Path) -> None:
        """Save key pair to files."""
        private_key_path.write_text(self.private_key)
        private_key_path.chmod(0o600)
        private_key_path.with_suffix(".pub").write_text(self.public_key)
