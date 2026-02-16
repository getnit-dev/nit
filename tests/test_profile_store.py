"""Tests for profile persistence (src/nit/models/store.py)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from nit.models.store import is_profile_stale, load_profile


def test_load_profile_non_dict_returns_none(tmp_path: Path) -> None:
    """When profile.json contains a list (not a dict), load_profile returns None."""
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()
    (nit_dir / "profile.json").write_text(json.dumps(["not", "a", "dict"]))
    assert load_profile(tmp_path) is None


def test_is_profile_stale_git_index_newer(tmp_path: Path) -> None:
    """When git index is newer than profile, is_profile_stale returns True."""
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()
    pfile = nit_dir / "profile.json"
    pfile.write_text("{}")

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    # Ensure git index is newer
    time.sleep(0.01)
    (git_dir / "index").write_text("index")

    assert is_profile_stale(tmp_path) is True


def test_is_profile_stale_git_index_older(tmp_path: Path) -> None:
    """When git index is older than profile, is_profile_stale returns False."""
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    # Write git index first
    (git_dir / "index").write_text("index")
    time.sleep(0.01)
    # Then write profile (newer)
    pfile = nit_dir / "profile.json"
    pfile.write_text("{}")

    assert is_profile_stale(tmp_path) is False
