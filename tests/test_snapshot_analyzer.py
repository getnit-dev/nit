"""Tests for the snapshot/approval testing analyzer and builder.

Covers:
- Detecting snapshot testing frameworks (Jest, Vitest, pytest, Go golden)
- Discovering snapshot files in various project layouts
- Counting snapshots in .snap files
- Mapping snapshot files to their corresponding test files
- Identifying stale snapshots (no corresponding test file)
- Full analysis pipeline integration
- Generating test plans from analysis results
- Handling empty projects with no snapshots
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.agents.analyzers.snapshot import (
    SnapshotAnalysisResult,
    SnapshotFile,
    analyze_snapshots,
    detect_snapshot_framework,
    discover_snapshots,
)
from nit.agents.builders.snapshot import SnapshotTestBuilder

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture()
def jest_project(tmp_path: Path) -> Path:
    """Create a project with Jest snapshot files."""
    snap_dir = tmp_path / "src" / "components" / "__snapshots__"
    snap_dir.mkdir(parents=True)
    (snap_dir / "Button.test.tsx.snap").write_text(
        "exports[`Button renders correctly 1`] = `<button>Click</button>`;\n"
        "exports[`Button renders disabled 1`] = `<button disabled>Click</button>`;\n",
        encoding="utf-8",
    )
    # Create the corresponding test file
    test_dir = snap_dir.parent
    (test_dir / "Button.test.tsx").write_text(
        "import { render } from '@testing-library/react';\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def vitest_project(tmp_path: Path) -> Path:
    """Create a project with Vitest snapshot files and vitest config."""
    (tmp_path / "vitest.config.ts").write_text("export default {}\n", encoding="utf-8")
    snap_dir = tmp_path / "src" / "__snapshots__"
    snap_dir.mkdir(parents=True)
    (snap_dir / "utils.test.ts.snap").write_text(
        'exports[`format date 1`] = `"2024-01-01"`;\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / "utils.test.ts").write_text(
        "import { format } from './utils';\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def go_golden_project(tmp_path: Path) -> Path:
    """Create a project with Go golden test files."""
    testdata_dir = tmp_path / "pkg" / "parser" / "testdata"
    testdata_dir.mkdir(parents=True)
    (testdata_dir / "simple.golden").write_text("expected output\n", encoding="utf-8")
    (testdata_dir / "complex.golden").write_text("complex output\n", encoding="utf-8")
    # Create a Go test file in the package directory
    pkg_dir = testdata_dir.parent
    (pkg_dir / "parser_test.go").write_text("package parser\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def empty_project(tmp_path: Path) -> Path:
    """Create an empty project with no snapshot files."""
    (tmp_path / "src").mkdir()
    return tmp_path


# ── detect_snapshot_framework ────────────────────────────────────


def test_detect_jest_snapshots(jest_project: Path) -> None:
    """detect_snapshot_framework should detect Jest from __snapshots__/*.snap."""
    framework = detect_snapshot_framework(jest_project)
    assert framework == "jest"


def test_detect_vitest_snapshots(vitest_project: Path) -> None:
    """detect_snapshot_framework should detect Vitest when vitest config exists."""
    framework = detect_snapshot_framework(vitest_project)
    assert framework == "vitest"


def test_detect_pytest_syrupy_in_requirements(tmp_path: Path) -> None:
    """detect_snapshot_framework should detect syrupy in requirements.txt."""
    (tmp_path / "requirements-dev.txt").write_text("pytest\nsyrupy>=4.0.0\n", encoding="utf-8")
    framework = detect_snapshot_framework(tmp_path)
    assert framework == "pytest_syrupy"


def test_detect_pytest_snapshottest_in_pyproject(tmp_path: Path) -> None:
    """detect_snapshot_framework should detect snapshottest in pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text(
        '[project.optional-dependencies]\ndev = ["snapshottest"]\n',
        encoding="utf-8",
    )
    framework = detect_snapshot_framework(tmp_path)
    assert framework == "pytest_snapshottest"


def test_detect_go_golden_files(go_golden_project: Path) -> None:
    """detect_snapshot_framework should detect Go golden files in testdata/."""
    framework = detect_snapshot_framework(go_golden_project)
    assert framework == "go_golden"


def test_detect_returns_empty_when_no_framework(empty_project: Path) -> None:
    """detect_snapshot_framework should return empty string when nothing found."""
    framework = detect_snapshot_framework(empty_project)
    assert framework == ""


# ── discover_snapshots ───────────────────────────────────────────


def test_discover_jest_snap_files(jest_project: Path) -> None:
    """discover_snapshots should find Jest .snap files."""
    snapshots = discover_snapshots(jest_project, "jest")
    assert len(snapshots) == 1
    assert snapshots[0].path.endswith(".snap")
    assert snapshots[0].framework == "jest"


def test_discover_counts_snapshots_in_snap_file(jest_project: Path) -> None:
    """discover_snapshots should count exports[ occurrences in .snap files."""
    snapshots = discover_snapshots(jest_project, "jest")
    assert snapshots[0].snapshot_count == 2


def test_discover_maps_snap_to_test_file(jest_project: Path) -> None:
    """discover_snapshots should map snapshot files to corresponding test files."""
    snapshots = discover_snapshots(jest_project, "jest")
    assert snapshots[0].test_file != ""
    assert "Button.test.tsx" in snapshots[0].test_file


def test_discover_marks_stale_when_no_test_file(tmp_path: Path) -> None:
    """discover_snapshots should mark snapshot as stale when test file is missing."""
    snap_dir = tmp_path / "src" / "__snapshots__"
    snap_dir.mkdir(parents=True)
    (snap_dir / "Missing.test.ts.snap").write_text(
        "exports[`test 1`] = `value`;\n", encoding="utf-8"
    )
    snapshots = discover_snapshots(tmp_path, "jest")
    assert len(snapshots) == 1
    assert snapshots[0].is_stale is True
    assert snapshots[0].test_file == ""


def test_discover_vitest_snap_files(vitest_project: Path) -> None:
    """discover_snapshots should find Vitest .snap files."""
    snapshots = discover_snapshots(vitest_project, "vitest")
    assert len(snapshots) == 1
    assert snapshots[0].framework == "vitest"


def test_discover_go_golden_files(go_golden_project: Path) -> None:
    """discover_snapshots should find Go .golden files in testdata/."""
    snapshots = discover_snapshots(go_golden_project, "go_golden")
    assert len(snapshots) == 2
    paths = {sf.path for sf in snapshots}
    assert any("simple.golden" in p for p in paths)
    assert any("complex.golden" in p for p in paths)


def test_discover_go_golden_maps_to_test_file(go_golden_project: Path) -> None:
    """discover_snapshots should map golden files to Go test files."""
    snapshots = discover_snapshots(go_golden_project, "go_golden")
    for snap in snapshots:
        assert snap.test_file != ""
        assert snap.test_file.endswith("_test.go")


def test_discover_returns_empty_for_unknown_framework(tmp_path: Path) -> None:
    """discover_snapshots should return empty list for unknown framework."""
    snapshots = discover_snapshots(tmp_path, "unknown_framework")
    assert snapshots == []


# ── analyze_snapshots ────────────────────────────────────────────


def test_analyze_jest_project(jest_project: Path) -> None:
    """analyze_snapshots should produce a full analysis for a Jest project."""
    result = analyze_snapshots(jest_project)
    assert result.framework == "jest"
    assert len(result.snapshot_files) == 1
    assert result.total_snapshots == 2
    assert result.snapshot_dir == "__snapshots__"


def test_analyze_counts_total_snapshots(tmp_path: Path) -> None:
    """analyze_snapshots should count total snapshots across multiple files."""
    snap_dir1 = tmp_path / "src" / "a" / "__snapshots__"
    snap_dir1.mkdir(parents=True)
    (snap_dir1 / "A.test.ts.snap").write_text(
        "exports[`test A 1`] = `a`;\nexports[`test A 2`] = `b`;\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "a" / "A.test.ts").write_text("test", encoding="utf-8")

    snap_dir2 = tmp_path / "src" / "b" / "__snapshots__"
    snap_dir2.mkdir(parents=True)
    (snap_dir2 / "B.test.ts.snap").write_text(
        "exports[`test B 1`] = `c`;\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "b" / "B.test.ts").write_text("test", encoding="utf-8")

    result = analyze_snapshots(tmp_path)
    assert result.total_snapshots == 3
    assert len(result.snapshot_files) == 2


def test_analyze_identifies_stale_snapshots(tmp_path: Path) -> None:
    """analyze_snapshots should identify and count stale snapshot files."""
    snap_dir = tmp_path / "src" / "__snapshots__"
    snap_dir.mkdir(parents=True)
    (snap_dir / "Orphan.test.ts.snap").write_text(
        "exports[`orphan 1`] = `val`;\n", encoding="utf-8"
    )
    # No corresponding test file

    result = analyze_snapshots(tmp_path)
    assert result.stale_count == 1
    assert result.snapshot_files[0].is_stale is True


def test_analyze_empty_project(empty_project: Path) -> None:
    """analyze_snapshots should return empty result for project with no snapshots."""
    result = analyze_snapshots(empty_project)
    assert result.framework == ""
    assert result.snapshot_files == []
    assert result.total_snapshots == 0
    assert result.stale_count == 0


def test_analyze_go_golden_project(go_golden_project: Path) -> None:
    """analyze_snapshots should detect and analyze Go golden files."""
    result = analyze_snapshots(go_golden_project)
    assert result.framework == "go_golden"
    assert len(result.snapshot_files) == 2
    assert result.snapshot_dir == "testdata"


# ── SnapshotTestBuilder ─────────────────────────────────────────


def test_builder_generates_stale_cleanup_tests() -> None:
    """SnapshotTestBuilder should generate stale_cleanup tests for stale snapshots."""
    analysis = SnapshotAnalysisResult(
        snapshot_files=[
            SnapshotFile(
                path="src/__snapshots__/Old.test.ts.snap",
                test_file="",
                snapshot_count=3,
                is_stale=True,
                framework="jest",
            ),
        ],
        stale_count=1,
        total_snapshots=3,
        framework="jest",
    )

    builder = SnapshotTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    stale_cases = [tc for tc in test_cases if tc.test_type == "stale_cleanup"]
    assert len(stale_cases) == 1
    assert "stale" in stale_cases[0].description.lower()


def test_builder_generates_snapshot_review_tests() -> None:
    """SnapshotTestBuilder should generate snapshot_review tests for all files."""
    analysis = SnapshotAnalysisResult(
        snapshot_files=[
            SnapshotFile(
                path="src/__snapshots__/App.test.tsx.snap",
                test_file="src/App.test.tsx",
                snapshot_count=5,
                is_stale=False,
                framework="jest",
            ),
        ],
        stale_count=0,
        total_snapshots=5,
        framework="jest",
    )

    builder = SnapshotTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    review_cases = [tc for tc in test_cases if tc.test_type == "snapshot_review"]
    assert len(review_cases) == 1
    assert "5 snapshot(s)" in review_cases[0].description


def test_builder_generates_snapshot_update_test() -> None:
    """SnapshotTestBuilder should generate a snapshot_update test when snapshots exist."""
    analysis = SnapshotAnalysisResult(
        snapshot_files=[
            SnapshotFile(
                path="src/__snapshots__/App.test.tsx.snap",
                test_file="src/App.test.tsx",
                snapshot_count=2,
                is_stale=False,
                framework="jest",
            ),
        ],
        stale_count=0,
        total_snapshots=2,
        framework="jest",
    )

    builder = SnapshotTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    update_cases = [tc for tc in test_cases if tc.test_type == "snapshot_update"]
    assert len(update_cases) == 1
    assert "jest" in update_cases[0].description.lower()


def test_builder_handles_empty_analysis() -> None:
    """SnapshotTestBuilder should return empty list for empty analysis."""
    analysis = SnapshotAnalysisResult()
    builder = SnapshotTestBuilder()
    test_cases = builder.generate_test_plan(analysis)
    assert test_cases == []


def test_builder_test_name_slugification() -> None:
    """SnapshotTestBuilder should produce valid test names from file paths."""
    analysis = SnapshotAnalysisResult(
        snapshot_files=[
            SnapshotFile(
                path="src/components/__snapshots__/My Component.test.tsx.snap",
                test_file="",
                snapshot_count=1,
                is_stale=True,
                framework="jest",
            ),
        ],
        stale_count=1,
        total_snapshots=1,
        framework="jest",
    )

    builder = SnapshotTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    for tc in test_cases:
        # Test names should only contain valid identifier characters
        assert tc.test_name.replace("_", "").isalnum()
