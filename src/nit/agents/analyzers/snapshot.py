"""Snapshot/approval testing analyzer -- detects snapshot frameworks and files.

This analyzer:
1. Detects snapshot testing frameworks (Jest, Vitest, pytest syrupy/snapshottest, Go golden)
2. Discovers snapshot files in the project
3. Maps snapshot files to their corresponding test files
4. Identifies stale snapshots (no corresponding test file)
5. Produces a SnapshotAnalysisResult summarizing all findings
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Data models ──────────────────────────────────────────────────


@dataclass
class SnapshotFile:
    """A single snapshot file discovered in the project."""

    path: str
    """Path to the snapshot file relative to project root."""

    test_file: str = ""
    """Path to the corresponding test file, if identified."""

    snapshot_count: int = 0
    """Number of individual snapshots in this file."""

    is_stale: bool = False
    """Whether the snapshot is stale (no corresponding test file exists)."""

    framework: str = ""
    """Framework that produced this snapshot file."""


@dataclass
class SnapshotAnalysisResult:
    """Aggregated result of snapshot analysis across all discovered files."""

    snapshot_files: list[SnapshotFile] = field(default_factory=list)
    """All discovered snapshot files."""

    stale_count: int = 0
    """Number of stale snapshot files."""

    total_snapshots: int = 0
    """Total number of individual snapshots across all files."""

    framework: str = ""
    """Detected snapshot testing framework."""

    snapshot_dir: str = ""
    """Primary snapshot directory, if identified."""


# ── Detection ────────────────────────────────────────────────────


def detect_snapshot_framework(project_root: Path) -> str:
    """Detect the snapshot testing framework in use.

    Checks for:
    - Jest/Vitest: ``__snapshots__/`` directories containing ``*.snap`` files
    - pytest: ``syrupy`` or ``snapshottest`` in requirements or pyproject.toml
    - Go: ``testdata/`` directories with ``*.golden`` files

    Args:
        project_root: Root directory of the project.

    Returns:
        Framework name string, or empty string if none detected.
    """
    # Check for Jest/Vitest __snapshots__ directories
    snap_dirs = list(project_root.rglob("__snapshots__"))
    for snap_dir in snap_dirs:
        if any(snap_dir.glob("*.snap")):
            # Distinguish Jest vs Vitest by checking config files
            if _is_vitest_project(project_root):
                logger.info("Detected Vitest snapshot framework")
                return "vitest"
            logger.info("Detected Jest snapshot framework")
            return "jest"

    # Check for pytest snapshot frameworks in requirements and pyproject.toml
    pytest_framework = _detect_pytest_snapshot_framework(project_root)
    if pytest_framework:
        logger.info("Detected pytest snapshot framework: %s", pytest_framework)
        return pytest_framework

    # Check for Go golden files
    testdata_dirs = list(project_root.rglob("testdata"))
    for testdata_dir in testdata_dirs:
        if any(testdata_dir.glob("*.golden")):
            logger.info("Detected Go golden file framework")
            return "go_golden"

    return ""


def _is_vitest_project(project_root: Path) -> bool:
    """Check whether the project uses Vitest (as opposed to Jest).

    Args:
        project_root: Root directory of the project.

    Returns:
        True if Vitest configuration is detected.
    """
    vitest_configs = [
        "vitest.config.ts",
        "vitest.config.js",
        "vitest.config.mts",
        "vitest.config.mjs",
    ]
    return any((project_root / config).is_file() for config in vitest_configs)


def _detect_pytest_snapshot_framework(project_root: Path) -> str:
    """Detect pytest snapshot framework from dependency files.

    Checks requirements*.txt and pyproject.toml for syrupy or snapshottest.

    Args:
        project_root: Root directory of the project.

    Returns:
        Framework name string, or empty string if none detected.
    """
    # Check requirements*.txt files
    for req_file in project_root.glob("requirements*.txt"):
        try:
            content = req_file.read_text(encoding="utf-8").lower()
            if "syrupy" in content:
                return "pytest_syrupy"
            if "snapshottest" in content:
                return "pytest_snapshottest"
        except OSError as exc:
            logger.debug("Could not read %s: %s", req_file.name, exc)

    # Check pyproject.toml
    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            content = pyproject.read_text(encoding="utf-8").lower()
            if "syrupy" in content:
                return "pytest_syrupy"
            if "snapshottest" in content:
                return "pytest_snapshottest"
        except OSError as exc:
            logger.debug("Could not read pyproject.toml: %s", exc)

    return ""


# ── Discovery ────────────────────────────────────────────────────


def discover_snapshots(project_root: Path, framework: str) -> list[SnapshotFile]:
    """Discover snapshot files for the detected framework.

    Args:
        project_root: Root directory of the project.
        framework: Detected snapshot framework name.

    Returns:
        List of discovered SnapshotFile entries.
    """
    if framework in ("jest", "vitest"):
        return _discover_js_snapshots(project_root, framework)
    if framework in ("pytest_syrupy", "pytest_snapshottest"):
        return _discover_pytest_snapshots(project_root, framework)
    if framework == "go_golden":
        return _discover_go_golden_files(project_root)
    return []


def _discover_js_snapshots(project_root: Path, framework: str) -> list[SnapshotFile]:
    """Discover Jest/Vitest snapshot files.

    Finds all ``__snapshots__/*.snap`` files and maps each to its
    corresponding test file by removing the ``__snapshots__/`` path
    component and replacing ``.snap`` with common test file extensions.

    Args:
        project_root: Root directory of the project.
        framework: ``"jest"`` or ``"vitest"``.

    Returns:
        List of discovered SnapshotFile entries.
    """
    results: list[SnapshotFile] = []
    snap_files = sorted(project_root.rglob("__snapshots__/*.snap"))

    for snap_path in snap_files:
        rel_path = str(snap_path.relative_to(project_root))
        snapshot_count = _count_js_snapshots(snap_path)
        test_file = _find_js_test_file(project_root, snap_path)
        is_stale = test_file == ""

        results.append(
            SnapshotFile(
                path=rel_path,
                test_file=test_file,
                snapshot_count=snapshot_count,
                is_stale=is_stale,
                framework=framework,
            )
        )

    return results


def _count_js_snapshots(snap_path: Path) -> int:
    """Count individual snapshots in a ``.snap`` file.

    Counts occurrences of ``exports[`` which marks each snapshot entry.

    Args:
        snap_path: Absolute path to the ``.snap`` file.

    Returns:
        Number of snapshot entries found.
    """
    try:
        content = snap_path.read_text(encoding="utf-8")
        return content.count("exports[")
    except OSError as exc:
        logger.debug("Could not read snapshot file %s: %s", snap_path, exc)
        return 0


def _find_js_test_file(project_root: Path, snap_path: Path) -> str:
    """Find the corresponding test file for a JS/TS snapshot file.

    Removes ``__snapshots__/`` from the path and replaces ``.snap``
    with common test extensions.

    Args:
        project_root: Root directory of the project.
        snap_path: Absolute path to the ``.snap`` file.

    Returns:
        Relative path to the test file, or empty string if not found.
    """
    # The test file sits in the parent of __snapshots__/
    parent_dir = snap_path.parent.parent
    snap_stem = snap_path.stem  # e.g., "Button.test.tsx" from "Button.test.tsx.snap"

    test_extensions = [".ts", ".tsx", ".js", ".jsx"]
    for ext in test_extensions:
        candidate = parent_dir / f"{snap_stem}{ext}"
        if candidate.is_file():
            return str(candidate.relative_to(project_root))

    # Also try without the .snap suffix directly
    candidate = parent_dir / snap_stem
    if candidate.is_file():
        return str(candidate.relative_to(project_root))

    return ""


def _discover_pytest_snapshots(project_root: Path, framework: str) -> list[SnapshotFile]:
    """Discover pytest snapshot files (syrupy or snapshottest).

    Syrupy stores snapshots in ``__snapshots__/`` directories with
    ``.ambr`` extension.  snapshottest uses ``snapshots/`` directories.

    Args:
        project_root: Root directory of the project.
        framework: ``"pytest_syrupy"`` or ``"pytest_snapshottest"``.

    Returns:
        List of discovered SnapshotFile entries.
    """
    results: list[SnapshotFile] = []

    if framework == "pytest_syrupy":
        snap_files = sorted(project_root.rglob("__snapshots__/*.ambr"))
    else:
        snap_files = sorted(project_root.rglob("snapshots/*.txt"))

    for snap_path in snap_files:
        rel_path = str(snap_path.relative_to(project_root))
        results.append(
            SnapshotFile(
                path=rel_path,
                test_file="",
                snapshot_count=0,
                is_stale=False,
                framework=framework,
            )
        )

    return results


def _discover_go_golden_files(project_root: Path) -> list[SnapshotFile]:
    """Discover Go golden test files.

    Finds all ``testdata/*.golden`` files and maps them to test files
    in the parent directory.

    Args:
        project_root: Root directory of the project.

    Returns:
        List of discovered SnapshotFile entries.
    """
    results: list[SnapshotFile] = []
    golden_files = sorted(project_root.rglob("testdata/*.golden"))

    for golden_path in golden_files:
        rel_path = str(golden_path.relative_to(project_root))
        test_file = _find_go_test_file(project_root, golden_path)
        is_stale = test_file == ""

        results.append(
            SnapshotFile(
                path=rel_path,
                test_file=test_file,
                snapshot_count=1,
                is_stale=is_stale,
                framework="go_golden",
            )
        )

    return results


def _find_go_test_file(project_root: Path, golden_path: Path) -> str:
    """Find the corresponding Go test file for a golden file.

    Looks for ``*_test.go`` files in the parent of the ``testdata/`` directory.

    Args:
        project_root: Root directory of the project.
        golden_path: Absolute path to the ``.golden`` file.

    Returns:
        Relative path to the test file, or empty string if not found.
    """
    # testdata/ parent is the package directory
    package_dir = golden_path.parent.parent
    test_files = list(package_dir.glob("*_test.go"))
    if test_files:
        return str(test_files[0].relative_to(project_root))
    return ""


# ── Analysis ─────────────────────────────────────────────────────


def analyze_snapshots(project_root: Path) -> SnapshotAnalysisResult:
    """Analyze all snapshot files found in the project.

    Detects the snapshot framework, discovers snapshot files, and produces
    an aggregated analysis result including stale counts and totals.

    Args:
        project_root: Root directory of the project.

    Returns:
        SnapshotAnalysisResult summarizing all discovered snapshots.
    """
    framework = detect_snapshot_framework(project_root)
    if not framework:
        logger.info("No snapshot testing framework detected")
        return SnapshotAnalysisResult()

    snapshot_files = discover_snapshots(project_root, framework)
    total_snapshots = sum(sf.snapshot_count for sf in snapshot_files)
    stale_count = sum(1 for sf in snapshot_files if sf.is_stale)

    # Determine the primary snapshot directory
    snapshot_dir = ""
    if snapshot_files:
        first_path = snapshot_files[0].path
        if "__snapshots__" in first_path:
            snapshot_dir = "__snapshots__"
        elif "testdata" in first_path:
            snapshot_dir = "testdata"
        elif "snapshots" in first_path:
            snapshot_dir = "snapshots"

    logger.info(
        "Snapshot analysis: %d files, %d snapshots, %d stale, framework=%s",
        len(snapshot_files),
        total_snapshots,
        stale_count,
        framework,
    )

    return SnapshotAnalysisResult(
        snapshot_files=snapshot_files,
        stale_count=stale_count,
        total_snapshots=total_snapshots,
        framework=framework,
        snapshot_dir=snapshot_dir,
    )
