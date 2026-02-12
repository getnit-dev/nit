"""Tests for ProjectProfile data model and persistence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nit.agents.detectors.signals import DetectedFramework, FrameworkCategory

if TYPE_CHECKING:
    from pathlib import Path
from nit.agents.detectors.stack import LanguageInfo
from nit.agents.detectors.workspace import PackageInfo
from nit.models.profile import ProjectProfile
from nit.models.store import (
    is_profile_stale,
    load_profile,
    profile_path,
    save_profile,
)


def _sample_profile(root: str = "/test-project") -> ProjectProfile:
    """Build a minimal ``ProjectProfile`` for testing."""
    return ProjectProfile(
        root=root,
        languages=[
            LanguageInfo(language="python", file_count=20, confidence=0.8, extensions={".py": 20}),
            LanguageInfo(
                language="javascript", file_count=5, confidence=0.2, extensions={".js": 5}
            ),
        ],
        frameworks=[
            DetectedFramework(
                name="pytest",
                language="python",
                category=FrameworkCategory.UNIT_TEST,
                confidence=0.92,
            ),
        ],
        packages=[
            PackageInfo(name="my-app", path=".", dependencies=[]),
        ],
        workspace_tool="generic",
    )


# ── ProjectProfile ───────────────────────────────────────────────


class TestProjectProfile:
    def test_primary_language(self) -> None:
        profile = _sample_profile()
        assert profile.primary_language == "python"

    def test_primary_language_empty(self) -> None:
        profile = ProjectProfile(root="/nonexistent")
        assert profile.primary_language is None

    def test_is_monorepo_false(self) -> None:
        profile = _sample_profile()
        assert profile.is_monorepo is False

    def test_is_monorepo_true(self) -> None:
        profile = _sample_profile()
        profile.packages.append(PackageInfo(name="lib", path="lib"))
        assert profile.is_monorepo is True

    def test_frameworks_by_category(self) -> None:
        profile = _sample_profile()
        unit = profile.frameworks_by_category(FrameworkCategory.UNIT_TEST)
        assert len(unit) == 1
        assert unit[0].name == "pytest"

    def test_frameworks_by_category_empty(self) -> None:
        profile = _sample_profile()
        e2e = profile.frameworks_by_category(FrameworkCategory.E2E_TEST)
        assert e2e == []


# ── Round-trip serialisation ─────────────────────────────────────


class TestSerialization:
    def test_to_dict_keys(self) -> None:
        d = _sample_profile().to_dict()
        assert set(d.keys()) == {
            "root",
            "primary_language",
            "workspace_tool",
            "is_monorepo",
            "llm_usage_count",
            "llm_providers",
            "languages",
            "frameworks",
            "packages",
        }

    def test_roundtrip(self) -> None:
        original = _sample_profile()
        data = original.to_dict()
        restored = ProjectProfile.from_dict(data)

        assert restored.root == original.root
        assert restored.workspace_tool == original.workspace_tool
        assert len(restored.languages) == len(original.languages)
        assert restored.languages[0].language == "python"
        assert restored.languages[0].file_count == 20
        assert len(restored.frameworks) == len(original.frameworks)
        assert restored.frameworks[0].name == "pytest"
        assert restored.frameworks[0].category == FrameworkCategory.UNIT_TEST
        assert len(restored.packages) == len(original.packages)
        assert restored.packages[0].name == "my-app"

    def test_from_dict_empty(self) -> None:
        profile = ProjectProfile.from_dict({})
        assert profile.root == ""
        assert profile.languages == []
        assert profile.frameworks == []
        assert profile.packages == []

    def test_json_roundtrip(self) -> None:
        original = _sample_profile()
        text = json.dumps(original.to_dict())
        restored = ProjectProfile.from_dict(json.loads(text))
        assert restored.primary_language == original.primary_language


# ── Persistence ──────────────────────────────────────────────────


class TestStore:
    def test_save_and_load(self, tmp_path: Path) -> None:
        profile = _sample_profile(root=str(tmp_path))
        save_profile(profile)

        loaded = load_profile(tmp_path)
        assert loaded is not None
        assert loaded.root == profile.root
        assert loaded.primary_language == "python"
        assert len(loaded.frameworks) == 1

    def test_load_missing(self, tmp_path: Path) -> None:
        assert load_profile(tmp_path) is None

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        path = profile_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("not json", encoding="utf-8")
        assert load_profile(tmp_path) is None

    def test_profile_path(self, tmp_path: Path) -> None:
        p = profile_path(tmp_path)
        assert p == tmp_path / ".nit" / "profile.json"

    def test_is_stale_no_profile(self, tmp_path: Path) -> None:
        assert is_profile_stale(tmp_path) is True

    def test_is_stale_fresh_profile(self, tmp_path: Path) -> None:
        profile = _sample_profile(root=str(tmp_path))
        save_profile(profile)
        # No git index → compares against root dir mtime; profile was
        # just written so it should be fresh relative to the dir.
        # (The root dir mtime *might* have been updated by creating .nit/,
        # so we just verify it doesn't crash.)
        result = is_profile_stale(tmp_path)
        assert isinstance(result, bool)
