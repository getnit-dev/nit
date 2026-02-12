"""Tests for memory synchronization module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nit.cli import _try_pull_memory, _try_push_memory
from nit.memory.sync import (
    apply_pull_response,
    build_push_payload,
    get_sync_version,
    set_sync_version,
)


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Create a minimal project root with .nit/memory/ structure."""
    memory_dir = tmp_path / ".nit" / "memory"
    memory_dir.mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# get_sync_version / set_sync_version
# ---------------------------------------------------------------------------


def test_sync_version_returns_zero_when_missing(project_root: Path) -> None:
    assert get_sync_version(project_root) == 0


def test_sync_version_roundtrip(project_root: Path) -> None:
    set_sync_version(project_root, 42)
    assert get_sync_version(project_root) == 42


def test_sync_version_overwrites(project_root: Path) -> None:
    set_sync_version(project_root, 1)
    set_sync_version(project_root, 5)
    assert get_sync_version(project_root) == 5


def test_sync_version_corrupted_file(project_root: Path) -> None:
    meta_path = project_root / ".nit" / "memory" / "sync_meta.json"
    meta_path.write_text("not json", encoding="utf-8")
    assert get_sync_version(project_root) == 0


# ---------------------------------------------------------------------------
# build_push_payload
# ---------------------------------------------------------------------------


def test_build_push_payload_empty_memory(project_root: Path) -> None:
    payload = build_push_payload(project_root, source="local")

    assert payload["source"] == "local"
    assert payload["baseVersion"] == 0
    assert payload["global"]["conventions"] == {}
    assert payload["global"]["knownPatterns"] == []
    assert payload["global"]["failedPatterns"] == []
    assert isinstance(payload["global"]["generationStats"], dict)


def test_build_push_payload_with_patterns(project_root: Path) -> None:
    global_path = project_root / ".nit" / "memory" / "global.json"
    global_path.write_text(
        json.dumps(
            {
                "conventions": {"language": "python"},
                "known_patterns": [
                    {
                        "pattern": "pytest works",
                        "success_count": 3,
                        "last_used": "2025-01-01T00:00:00",
                        "context": {"framework": "pytest"},
                    }
                ],
                "failed_patterns": [
                    {
                        "pattern": "mock failed",
                        "reason": "import error",
                        "timestamp": "2025-01-01T00:00:00",
                        "context": {"framework": "pytest"},
                    }
                ],
                "generation_stats": {"total_runs": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = build_push_payload(project_root)

    assert payload["global"]["conventions"] == {"language": "python"}
    assert len(payload["global"]["knownPatterns"]) == 1
    assert payload["global"]["knownPatterns"][0]["pattern"] == "pytest works"
    assert len(payload["global"]["failedPatterns"]) == 1
    assert payload["global"]["generationStats"]["total_runs"] == 5


def test_build_push_payload_with_packages(project_root: Path) -> None:
    # Create global memory
    global_path = project_root / ".nit" / "memory" / "global.json"
    global_path.write_text(
        json.dumps(
            {
                "conventions": {},
                "known_patterns": [],
                "failed_patterns": [],
                "generation_stats": {},
            }
        ),
        encoding="utf-8",
    )

    # Create a package memory
    packages_dir = project_root / ".nit" / "memory" / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    pkg_path = packages_dir / "package_web.json"
    pkg_path.write_text(
        json.dumps(
            {
                "package_name": "web",
                "test_patterns": {"naming": "describe/it"},
                "known_issues": [{"issue": "timeout on CI", "workaround": None}],
                "coverage_history": [],
                "llm_feedback": [],
            }
        ),
        encoding="utf-8",
    )

    payload = build_push_payload(project_root)

    assert "packages" in payload
    assert "web" in payload["packages"]
    assert payload["packages"]["web"]["testPatterns"] == {"naming": "describe/it"}
    assert len(payload["packages"]["web"]["knownIssues"]) == 1


def test_build_push_payload_includes_project_id(project_root: Path) -> None:
    payload = build_push_payload(project_root, project_id="proj-123")
    assert payload["projectId"] == "proj-123"


def test_build_push_payload_includes_base_version(project_root: Path) -> None:
    set_sync_version(project_root, 7)
    payload = build_push_payload(project_root)
    assert payload["baseVersion"] == 7


# ---------------------------------------------------------------------------
# apply_pull_response
# ---------------------------------------------------------------------------


def test_apply_pull_response_writes_global(project_root: Path) -> None:
    response: dict[str, Any] = {
        "version": 3,
        "global": {
            "conventions": {"language": "typescript"},
            "knownPatterns": [
                {
                    "pattern": "vitest ok",
                    "success_count": 2,
                    "last_used": "2025-06-01",
                    "context": {},
                }
            ],
            "failedPatterns": [],
            "generationStats": {"total_runs": 10},
        },
        "packages": {},
    }

    apply_pull_response(project_root, response)

    global_path = project_root / ".nit" / "memory" / "global.json"
    assert global_path.exists()
    data = json.loads(global_path.read_text(encoding="utf-8"))
    assert data["conventions"] == {"language": "typescript"}
    assert len(data["known_patterns"]) == 1
    assert data["known_patterns"][0]["pattern"] == "vitest ok"
    assert data["generation_stats"]["total_runs"] == 10

    assert get_sync_version(project_root) == 3


def test_apply_pull_response_writes_packages(project_root: Path) -> None:
    response: dict[str, Any] = {
        "version": 2,
        "global": {
            "conventions": {},
            "knownPatterns": [],
            "failedPatterns": [],
            "generationStats": {},
        },
        "packages": {
            "api": {
                "testPatterns": {"mocking": "jest.mock"},
                "knownIssues": [],
                "coverageHistory": [{"timestamp": "2025-01-01", "coverage_percent": 80.0}],
                "llmFeedback": [],
            }
        },
    }

    apply_pull_response(project_root, response)

    pkg_path = project_root / ".nit" / "memory" / "packages" / "package_api.json"
    assert pkg_path.exists()
    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    assert data["test_patterns"] == {"mocking": "jest.mock"}
    assert len(data["coverage_history"]) == 1


def test_apply_pull_response_empty_noop(project_root: Path) -> None:
    """Applying a version-0 response should not modify local files."""
    apply_pull_response(project_root, {"version": 0, "global": None, "packages": {}})

    global_path = project_root / ".nit" / "memory" / "global.json"
    assert not global_path.exists()
    assert get_sync_version(project_root) == 0


def test_apply_pull_response_no_global_key(project_root: Path) -> None:
    """Version > 0 but no global key should still update sync version."""
    apply_pull_response(project_root, {"version": 5})
    assert get_sync_version(project_root) == 5


# ---------------------------------------------------------------------------
# Guard tests: local-only path
# ---------------------------------------------------------------------------


def test_try_pull_memory_noop_when_disabled(tmp_path: Path) -> None:
    """_try_pull_memory should be a no-op when platform mode is disabled."""
    config = MagicMock()
    config.platform.normalized_mode = "disabled"

    with patch("nit.utils.platform_client.pull_platform_memory") as mock_pull:
        _try_pull_memory(config, tmp_path, ci_mode=False)
        mock_pull.assert_not_called()


def test_try_push_memory_noop_when_disabled(tmp_path: Path) -> None:
    """_try_push_memory should be a no-op when platform mode is disabled."""
    config = MagicMock()
    config.platform.normalized_mode = "disabled"

    with patch("nit.utils.platform_client.push_platform_memory") as mock_push:
        _try_push_memory(config, tmp_path, ci_mode=False, source="local")
        mock_push.assert_not_called()
