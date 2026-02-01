from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .models import PolicyFile
from .validators import extract_hostname, is_host_allowed


class PolicyValidationError(ValueError):
    pass


class PolicyViolationError(PermissionError):
    pass


DEFAULT_PROJECT_POLICY_FILES = (".clonebox-policy.yaml", ".clonebox-policy.yml")
DEFAULT_GLOBAL_POLICY_FILE = Path.home() / ".clonebox.d" / "policy.yaml"


@dataclass(frozen=True)
class PolicyEngine:
    policy: PolicyFile
    source: Path

    @classmethod
    def load(cls, path: Path) -> "PolicyEngine":
        try:
            raw = yaml.safe_load(path.read_text())
        except Exception as e:
            raise PolicyValidationError(f"Failed to read policy file {path}: {e}")

        if not isinstance(raw, dict):
            raise PolicyValidationError("Policy file must be a YAML mapping")

        try:
            policy = PolicyFile.model_validate(raw)
        except Exception as e:
            raise PolicyValidationError(str(e))

        return cls(policy=policy, source=path)

    @classmethod
    def find_policy_file(cls, start: Optional[Path] = None) -> Optional[Path]:
        start_path = (start or Path.cwd()).expanduser().resolve()
        if start_path.is_file():
            start_path = start_path.parent

        current = start_path
        while True:
            for name in DEFAULT_PROJECT_POLICY_FILES:
                candidate = current / name
                if candidate.exists() and candidate.is_file():
                    return candidate

            if current.parent == current:
                break
            current = current.parent

        if DEFAULT_GLOBAL_POLICY_FILE.exists() and DEFAULT_GLOBAL_POLICY_FILE.is_file():
            return DEFAULT_GLOBAL_POLICY_FILE

        return None

    @classmethod
    def load_effective(cls, start: Optional[Path] = None) -> Optional["PolicyEngine"]:
        policy_path = cls.find_policy_file(start=start)
        if not policy_path:
            return None
        return cls.load(policy_path)

    def assert_url_allowed(self, url: str) -> None:
        network = self.policy.policies.network
        if network is None:
            return

        hostname = extract_hostname(url)
        if not hostname:
            raise PolicyViolationError(f"URL has no hostname: {url}")

        if not is_host_allowed(hostname, network.allowlist, network.blocklist):
            raise PolicyViolationError(f"Network access denied by policy: {hostname}")
