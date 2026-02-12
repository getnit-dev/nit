"""Memory synchronization between local storage and platform."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from nit.memory.global_memory import GlobalMemory
from nit.memory.package_memory import PackageMemory
from nit.memory.package_memory_manager import PackageMemoryManager

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_SYNC_META_FILE = "sync_meta.json"


def build_push_payload(
    project_root: Path,
    *,
    source: str = "local",
    project_id: str | None = None,
) -> dict[str, Any]:
    """Build the memory push payload from local files.

    Args:
        project_root: Root directory of the project.
        source: Source identifier (``"local"`` or ``"ci"``).
        project_id: Platform project ID (optional, resolved by API key).

    Returns:
        Dictionary payload ready to POST to ``/api/v1/memory``.
    """
    global_memory = GlobalMemory(project_root)
    global_data = global_memory.to_dict()

    payload: dict[str, Any] = {
        "baseVersion": get_sync_version(project_root),
        "source": source,
        "global": {
            "conventions": global_data.get("conventions", {}),
            "knownPatterns": global_data.get("known_patterns", []),
            "failedPatterns": global_data.get("failed_patterns", []),
            "generationStats": global_data.get("generation_stats", {}),
        },
    }

    if project_id:
        payload["projectId"] = project_id

    # Collect package memories
    manager = PackageMemoryManager(project_root)
    package_names = manager.list_packages()
    if package_names:
        packages: dict[str, Any] = {}
        for name in package_names:
            pkg = manager.get_package_memory(name)
            pkg_data = pkg.to_dict()
            packages[name] = {
                "testPatterns": pkg_data.get("test_patterns", {}),
                "knownIssues": pkg_data.get("known_issues", []),
                "coverageHistory": pkg_data.get("coverage_history", []),
                "llmFeedback": pkg_data.get("llm_feedback", []),
            }
        payload["packages"] = packages

    return payload


def apply_pull_response(
    project_root: Path,
    response: dict[str, Any],
) -> None:
    """Apply pulled memory data to local files.

    Overwrites local memory with the merged state from the platform.

    Args:
        project_root: Root directory of the project.
        response: Response dict from ``GET /api/v1/memory``.
    """
    version = response.get("version", 0)
    if not isinstance(version, int) or version <= 0:
        return

    global_data = response.get("global")
    if isinstance(global_data, dict):
        memory = GlobalMemory(project_root)
        memory._data = {
            "conventions": global_data.get("conventions", {}),
            "known_patterns": global_data.get("knownPatterns", []),
            "failed_patterns": global_data.get("failedPatterns", []),
            "generation_stats": global_data.get("generationStats", {}),
        }
        memory._save()

    packages = response.get("packages")
    if isinstance(packages, dict):
        for name, pkg_data in packages.items():
            if not isinstance(pkg_data, dict):
                continue
            pkg = PackageMemory(project_root, name)
            pkg._data = {
                "package_name": name,
                "test_patterns": pkg_data.get("testPatterns", {}),
                "known_issues": pkg_data.get("knownIssues", []),
                "coverage_history": pkg_data.get("coverageHistory", []),
                "llm_feedback": pkg_data.get("llmFeedback", []),
            }
            pkg._save()

    set_sync_version(project_root, version)


def get_sync_version(project_root: Path) -> int:
    """Read the last-synced version from ``.nit/memory/sync_meta.json``.

    Returns:
        The version number, or ``0`` if no sync has occurred.
    """
    meta_path = project_root / ".nit" / "memory" / _SYNC_META_FILE
    if not meta_path.exists():
        return 0

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        version = data.get("version", 0)
        return version if isinstance(version, int) else 0
    except (json.JSONDecodeError, OSError):
        return 0


def set_sync_version(project_root: Path, version: int) -> None:
    """Write the last-synced version to ``.nit/memory/sync_meta.json``."""
    meta_path = project_root / ".nit" / "memory" / _SYNC_META_FILE
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(
            {"version": version, "last_sync": datetime.now(UTC).isoformat()},
            indent=2,
        ),
        encoding="utf-8",
    )
