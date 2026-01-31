from pathlib import Path

import pytest

from clonebox.profiles import load_profile, merge_with_profile


def test_profile_loader_finds_default_profiles(tmp_path: Path):
    (tmp_path / "templates" / "profiles").mkdir(parents=True)
    (tmp_path / "templates" / "profiles" / "ml-dev.yaml").write_text(
        """
container:
  image: python:3.11-slim
""".lstrip()
    )

    profile = load_profile("ml-dev", [tmp_path])
    assert profile["container"]["image"] == "python:3.11-slim"


def test_profile_merges_over_base():
    base = {"container": {"image": "ubuntu:22.04"}}
    prof = {"container": {"image": "python:3.11-slim"}}

    merged = merge_with_profile(base, profile=prof)
    assert merged["container"]["image"] == "python:3.11-slim"


def test_profile_deep_merge_nested_dicts():
    base = {"container": {"env": {"A": "1", "B": "2"}, "image": "ubuntu:22.04"}}
    prof = {"container": {"env": {"B": "override", "C": "3"}}}

    merged = merge_with_profile(base, profile=prof)
    assert merged["container"]["image"] == "ubuntu:22.04"
    assert merged["container"]["env"] == {"A": "1", "B": "override", "C": "3"}


def test_merge_with_profile_invalid_profile_is_noop():
    base = {"container": {"image": "ubuntu:22.04"}}
    merged = merge_with_profile(base, profile=123)  # type: ignore[arg-type]
    assert merged == base


def test_load_profile_prefers_search_paths_over_builtins(tmp_path: Path):
    # Put profile in a search path
    (tmp_path / "templates" / "profiles").mkdir(parents=True)
    (tmp_path / "templates" / "profiles" / "ml-dev.yaml").write_text(
        """
container:
  image: python:3.11-slim
""".lstrip()
    )

    profile = load_profile("ml-dev", [tmp_path])
    assert profile is not None
    assert profile["container"]["image"] == "python:3.11-slim"
