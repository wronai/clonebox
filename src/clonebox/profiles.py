import pkgutil
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def load_profile(profile_name: str, search_paths: list[Path]) -> Optional[Dict[str, Any]]:
    """Load profile YAML from ~/.clonebox.d/, .clonebox.d/, templates/profiles/"""
    search_paths = search_paths or []

    profile_paths = [
        Path.home() / ".clonebox.d" / f"{profile_name}.yaml",
        Path.cwd() / ".clonebox.d" / f"{profile_name}.yaml",
    ]

    for base in search_paths:
        profile_paths.insert(0, base / "templates" / "profiles" / f"{profile_name}.yaml")
        profile_paths.insert(0, base / f"{profile_name}.yaml")

    for profile_path in profile_paths:
        if profile_path.exists():
            return yaml.safe_load(profile_path.read_text())

    data = pkgutil.get_data("clonebox", f"templates/profiles/{profile_name}.yaml")
    if data is not None:
        return yaml.safe_load(data.decode())

    return None


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_with_profile(
    base_config: Dict[str, Any],
    profile_name: Optional[str] = None,
    *,
    profile: Optional[Dict[str, Any]] = None,
    search_paths: Optional[list[Path]] = None,
) -> Dict[str, Any]:
    """Merge profile OVER base config (profile wins)."""
    if profile is not None:
        if not isinstance(profile, dict):
            return base_config
        return _deep_merge(base_config, profile)

    if not profile_name:
        return base_config

    loaded = load_profile(profile_name, search_paths or [])
    if not loaded or not isinstance(loaded, dict):
        return base_config

    return _deep_merge(base_config, loaded)
