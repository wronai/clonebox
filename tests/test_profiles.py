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
