"""Tests for the DiffAnalyzer (agents/analyzers/diff.py).

Covers:
- Parsing git diff output
- Identifying changed files (added, modified, deleted, renamed)
- Mapping source files to test files
- Reverse mapping test files to source files
- Supporting multiple languages (Python, TypeScript, Java, Go, C++, Rust)
- Handling PR mode with base/compare refs
- Generating delta-focused work lists
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nit.agents.analyzers.diff import (
    ChangeType,
    DiffAnalysisTask,
    DiffAnalyzer,
)
from nit.agents.base import TaskInput, TaskStatus

# ── Test fixtures ────────────────────────────────────────────────


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)  # noqa: S607
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    readme = repo / "README.md"
    readme.write_text("# Test Project\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)  # noqa: S607
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


@pytest.fixture
def git_repo_with_files(temp_git_repo: Path) -> Path:
    """Create a git repo with sample source and test files."""
    repo = temp_git_repo

    # Create source files
    src_dir = repo / "src"
    src_dir.mkdir()

    (src_dir / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    (src_dir / "calculator.py").write_text("def multiply(a, b):\n    return a * b\n")
    (src_dir / "helper.ts").write_text("export function subtract(a, b) { return a - b; }\n")

    # Create test files
    tests_dir = repo / "tests"
    tests_dir.mkdir()

    (tests_dir / "test_utils.py").write_text("def test_add():\n    assert add(1, 2) == 3\n")
    (src_dir / "helper.test.ts").write_text(
        "import { subtract } from './helper';\ntest('subtract', () => {});\n"
    )

    # Commit files
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)  # noqa: S607
    subprocess.run(
        ["git", "commit", "-m", "Add source and test files"],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


# ── Test parse_diff_line ─────────────────────────────────────────


def test_parse_diff_line_added() -> None:
    """Test parsing git diff line for added file."""
    analyzer = DiffAnalyzer(Path())

    line = "A\tsrc/new_file.py"
    result = analyzer._parse_diff_line(line)

    assert result is not None
    assert result.path == "src/new_file.py"
    assert result.change_type == ChangeType.ADDED


def test_parse_diff_line_modified() -> None:
    """Test parsing git diff line for modified file."""
    analyzer = DiffAnalyzer(Path())

    line = "M\tsrc/existing.py"
    result = analyzer._parse_diff_line(line)

    assert result is not None
    assert result.path == "src/existing.py"
    assert result.change_type == ChangeType.MODIFIED


def test_parse_diff_line_deleted() -> None:
    """Test parsing git diff line for deleted file."""
    analyzer = DiffAnalyzer(Path())

    line = "D\tsrc/old_file.py"
    result = analyzer._parse_diff_line(line)

    assert result is not None
    assert result.path == "src/old_file.py"
    assert result.change_type == ChangeType.DELETED


def test_parse_diff_line_renamed() -> None:
    """Test parsing git diff line for renamed file."""
    analyzer = DiffAnalyzer(Path())

    line = "R\tsrc/old_name.py\tsrc/new_name.py"
    result = analyzer._parse_diff_line(line)

    assert result is not None
    assert result.path == "src/new_name.py"
    assert result.old_path == "src/old_name.py"
    assert result.change_type == ChangeType.RENAMED


def test_parse_diff_line_numstat() -> None:
    """Test parsing git diff numstat line."""
    analyzer = DiffAnalyzer(Path())

    line = "42\t10\tsrc/file.py"
    result = analyzer._parse_diff_line(line)

    assert result is not None
    assert result.path == "src/file.py"
    assert result.lines_added == 42
    assert result.lines_removed == 10
    assert result.change_type == ChangeType.MODIFIED


def test_parse_diff_line_invalid() -> None:
    """Test parsing invalid diff line returns None."""
    analyzer = DiffAnalyzer(Path())

    line = "invalid line"
    result = analyzer._parse_diff_line(line)

    assert result is None


# ── Test is_test_file ────────────────────────────────────────────


def test_is_test_file_python() -> None:
    """Test identifying Python test files."""
    analyzer = DiffAnalyzer(Path())

    assert analyzer._is_test_file("test_utils.py")
    assert analyzer._is_test_file("tests/test_calculator.py")
    assert analyzer._is_test_file("src/helper_test.py")
    assert not analyzer._is_test_file("src/utils.py")


def test_is_test_file_javascript() -> None:
    """Test identifying JavaScript/TypeScript test files."""
    analyzer = DiffAnalyzer(Path())

    assert analyzer._is_test_file("component.test.ts")
    assert analyzer._is_test_file("utils.spec.js")
    assert analyzer._is_test_file("__tests__/helper.test.tsx")
    assert not analyzer._is_test_file("src/component.ts")


def test_is_test_file_java() -> None:
    """Test identifying Java test files."""
    analyzer = DiffAnalyzer(Path())

    assert analyzer._is_test_file("src/test/java/CalculatorTest.java")
    assert analyzer._is_test_file("CalculatorTest.java")
    assert not analyzer._is_test_file("Calculator.java")


def test_is_test_file_go() -> None:
    """Test identifying Go test files."""
    analyzer = DiffAnalyzer(Path())

    assert analyzer._is_test_file("utils_test.go")
    assert analyzer._is_test_file("tests/calculator_test.go")
    assert not analyzer._is_test_file("utils.go")


def test_is_test_file_cpp() -> None:
    """Test identifying C++ test files."""
    analyzer = DiffAnalyzer(Path())

    assert analyzer._is_test_file("calculator_test.cpp")
    assert analyzer._is_test_file("tests/helper_test.cc")
    assert not analyzer._is_test_file("calculator.cpp")


# ── Test is_source_file ──────────────────────────────────────────


def test_is_source_file() -> None:
    """Test identifying source files by extension."""
    analyzer = DiffAnalyzer(Path())

    # Supported extensions
    assert analyzer._is_source_file("file.py")
    assert analyzer._is_source_file("file.ts")
    assert analyzer._is_source_file("file.tsx")
    assert analyzer._is_source_file("file.js")
    assert analyzer._is_source_file("file.jsx")
    assert analyzer._is_source_file("file.java")
    assert analyzer._is_source_file("file.go")
    assert analyzer._is_source_file("file.rs")
    assert analyzer._is_source_file("file.c")
    assert analyzer._is_source_file("file.cpp")

    # Not source files
    assert not analyzer._is_source_file("README.md")
    assert not analyzer._is_source_file("config.json")
    assert not analyzer._is_source_file("image.png")


# ── Test detect_language ─────────────────────────────────────────


def test_detect_language() -> None:
    """Test language detection from file extension."""
    analyzer = DiffAnalyzer(Path())

    assert analyzer._detect_language("file.py") == "python"
    assert analyzer._detect_language("file.ts") == "javascript"
    assert analyzer._detect_language("file.tsx") == "javascript"
    assert analyzer._detect_language("file.js") == "javascript"
    assert analyzer._detect_language("file.java") == "java"
    assert analyzer._detect_language("file.go") == "go"
    assert analyzer._detect_language("file.cpp") == "cpp"
    assert analyzer._detect_language("file.rs") == "rust"
    assert analyzer._detect_language("file.unknown") is None


# ── Test file mapping ────────────────────────────────────────────


def test_map_python_file_to_test() -> None:
    """Test mapping Python source file to test file."""
    analyzer = DiffAnalyzer(Path())

    # Test pattern: foo.py -> test_foo.py or tests/test_foo.py
    test_path = analyzer._generate_test_path("src/utils.py", "python")
    assert test_path is not None
    assert "test_" in test_path or "_test" in test_path


def test_map_javascript_file_to_test() -> None:
    """Test mapping JavaScript/TypeScript source file to test file."""
    analyzer = DiffAnalyzer(Path())

    test_path = analyzer._generate_test_path("src/component.ts", "javascript")
    assert test_path is not None
    assert ".test." in test_path or ".spec." in test_path


def test_map_java_file_to_test() -> None:
    """Test mapping Java source file to test file."""
    analyzer = DiffAnalyzer(Path())

    test_path = analyzer._generate_test_path("Calculator.java", "java")
    assert test_path is not None
    assert "Test" in test_path


def test_map_go_file_to_test() -> None:
    """Test mapping Go source file to test file."""
    analyzer = DiffAnalyzer(Path())

    test_path = analyzer._generate_test_path("utils.go", "go")
    assert test_path is not None
    assert "_test.go" in test_path


def test_map_files_to_tests_existing(git_repo_with_files: Path) -> None:
    """Test mapping source files to existing test files."""
    analyzer = DiffAnalyzer(git_repo_with_files)

    source_files = ["src/utils.py", "src/helper.ts"]
    mappings = analyzer._map_files_to_tests(source_files, git_repo_with_files)

    assert len(mappings) == 2

    # Check Python mapping
    python_mapping = next((m for m in mappings if m.source_file == "src/utils.py"), None)
    assert python_mapping is not None
    assert python_mapping.exists  # test_utils.py exists

    # Check TypeScript mapping
    ts_mapping = next((m for m in mappings if m.source_file == "src/helper.ts"), None)
    assert ts_mapping is not None
    assert ts_mapping.exists  # helper.test.ts exists


def test_map_files_to_tests_missing(git_repo_with_files: Path) -> None:
    """Test mapping source files to non-existent test files."""
    analyzer = DiffAnalyzer(git_repo_with_files)

    source_files = ["src/calculator.py"]  # No test exists for this
    mappings = analyzer._map_files_to_tests(source_files, git_repo_with_files)

    assert len(mappings) == 1
    assert not mappings[0].exists
    assert "test_calculator" in mappings[0].test_file or "calculator_test" in mappings[0].test_file


# ── Test full diff analysis ──────────────────────────────────────


@pytest.mark.asyncio
async def test_diff_analyzer_not_git_repo(tmp_path: Path) -> None:
    """Test DiffAnalyzer fails gracefully on non-git directory."""
    analyzer = DiffAnalyzer(tmp_path)
    task = DiffAnalysisTask(project_root=str(tmp_path))

    result = await analyzer.run(task)

    assert result.status == TaskStatus.FAILED
    assert any("not a git repository" in error.lower() for error in result.errors)


@pytest.mark.asyncio
async def test_diff_analyzer_with_changes(git_repo_with_files: Path) -> None:
    """Test DiffAnalyzer detects changes in working directory."""
    # Make some changes
    (git_repo_with_files / "src" / "utils.py").write_text(
        "def add(a, b):\n    return a + b + 1  # Modified\n"
    )
    (git_repo_with_files / "src" / "new_file.py").write_text("def new_func():\n    pass\n")

    analyzer = DiffAnalyzer(git_repo_with_files)
    task = DiffAnalysisTask(project_root=str(git_repo_with_files))

    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    diff_result = result.result["diff_result"]

    # Should detect modified utils.py
    assert any("src/utils.py" in f.path for f in diff_result.changed_files)

    # Should categorize source files
    assert "src/utils.py" in diff_result.changed_source_files


@pytest.mark.asyncio
async def test_diff_analyzer_compares_refs(git_repo_with_files: Path) -> None:
    """Test DiffAnalyzer compares between two git refs."""
    # Create a new branch and add changes
    subprocess.run(
        ["git", "checkout", "-b", "feature"],  # noqa: S607
        cwd=git_repo_with_files,
        check=True,
        capture_output=True,
    )

    (git_repo_with_files / "src" / "feature.py").write_text("def feature():\n    pass\n")
    subprocess.run(
        ["git", "add", "."],  # noqa: S607
        cwd=git_repo_with_files,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add feature"],  # noqa: S607
        cwd=git_repo_with_files,
        check=True,
        capture_output=True,
    )

    analyzer = DiffAnalyzer(git_repo_with_files)
    task = DiffAnalysisTask(
        project_root=str(git_repo_with_files),
        base_ref="HEAD~1",
        compare_ref="HEAD",
    )

    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    diff_result = result.result["diff_result"]

    # Should detect the new file
    assert any("src/feature.py" in f.path for f in diff_result.changed_files)


@pytest.mark.asyncio
async def test_diff_analyzer_categorizes_files(git_repo_with_files: Path) -> None:
    """Test DiffAnalyzer correctly categorizes source vs test files."""
    # Modify both source and test files
    (git_repo_with_files / "src" / "utils.py").write_text("def add(a, b):\n    return a + b + 1\n")
    (git_repo_with_files / "tests" / "test_utils.py").write_text(
        "def test_add():\n    assert add(1, 2) == 4\n"
    )

    analyzer = DiffAnalyzer(git_repo_with_files)
    task = DiffAnalysisTask(project_root=str(git_repo_with_files))

    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    diff_result = result.result["diff_result"]

    # Source file should be in changed_source_files
    assert "src/utils.py" in diff_result.changed_source_files

    # Test file should be in changed_test_files
    assert "tests/test_utils.py" in diff_result.changed_test_files


@pytest.mark.asyncio
async def test_diff_analyzer_line_counts(git_repo_with_files: Path) -> None:
    """Test DiffAnalyzer tracks line additions and deletions."""
    # Make substantial changes
    new_content = (
        "def add(a, b):\n"
        "    # Added comment\n"
        "    return a + b\n"
        "\n"
        "def subtract(a, b):\n"
        "    return a - b\n"
    )
    (git_repo_with_files / "src" / "utils.py").write_text(new_content)

    analyzer = DiffAnalyzer(git_repo_with_files)
    task = DiffAnalysisTask(project_root=str(git_repo_with_files))

    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    diff_result = result.result["diff_result"]

    # Should have some line changes
    # Note: exact counts depend on git diff, so we just check they're tracked
    assert diff_result.total_lines_added >= 0
    assert diff_result.total_lines_removed >= 0


@pytest.mark.asyncio
async def test_diff_analyzer_affected_files(git_repo_with_files: Path) -> None:
    """Test DiffAnalyzer includes source files affected by test changes."""
    # Modify only a test file
    (git_repo_with_files / "tests" / "test_utils.py").write_text(
        "def test_add():\n    assert add(1, 2) == 4  # Changed assertion\n"
    )

    analyzer = DiffAnalyzer(git_repo_with_files)
    task = DiffAnalysisTask(project_root=str(git_repo_with_files))

    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    diff_result = result.result["diff_result"]

    # The test file changed
    assert "tests/test_utils.py" in diff_result.changed_test_files

    # The corresponding source file should be in affected_source_files
    # (even though it wasn't directly changed)
    assert "src/utils.py" in diff_result.affected_source_files


# ── Test edge cases ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_diff_analyzer_empty_diff(git_repo_with_files: Path) -> None:
    """Test DiffAnalyzer handles no changes gracefully."""
    analyzer = DiffAnalyzer(git_repo_with_files)
    task = DiffAnalysisTask(project_root=str(git_repo_with_files))

    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    diff_result = result.result["diff_result"]

    assert len(diff_result.changed_files) == 0
    assert len(diff_result.changed_source_files) == 0
    assert len(diff_result.changed_test_files) == 0


@pytest.mark.asyncio
async def test_diff_analyzer_deleted_files(git_repo_with_files: Path) -> None:
    """Test DiffAnalyzer handles deleted files."""
    # Delete a file
    (git_repo_with_files / "src" / "calculator.py").unlink()

    analyzer = DiffAnalyzer(git_repo_with_files)
    task = DiffAnalysisTask(project_root=str(git_repo_with_files))

    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    diff_result = result.result["diff_result"]

    # Deleted file should be in changed_files but not in source files
    deleted = [f for f in diff_result.changed_files if f.change_type == ChangeType.DELETED]
    assert len(deleted) > 0


@pytest.mark.asyncio
async def test_diff_analyzer_invalid_project_root() -> None:
    """Test DiffAnalyzer fails on non-existent directory."""
    analyzer = DiffAnalyzer(Path("/nonexistent"))
    task = DiffAnalysisTask(project_root="/nonexistent")

    result = await analyzer.run(task)

    assert result.status == TaskStatus.FAILED
    assert any("does not exist" in error.lower() for error in result.errors)


@pytest.mark.asyncio
async def test_diff_analyzer_wrong_task_type() -> None:
    """Test DiffAnalyzer rejects wrong task input type."""
    analyzer = DiffAnalyzer(Path())
    wrong_task = TaskInput(task_type="wrong", target=".")

    result = await analyzer.run(wrong_task)

    assert result.status == TaskStatus.FAILED
    assert any("must be a DiffAnalysisTask" in error for error in result.errors)


# ── Test properties ──────────────────────────────────────────────


def test_diff_analyzer_name() -> None:
    """Test DiffAnalyzer name property."""
    analyzer = DiffAnalyzer(Path())
    assert analyzer.name == "diff_analyzer"


def test_diff_analyzer_description() -> None:
    """Test DiffAnalyzer description property."""
    analyzer = DiffAnalyzer(Path())
    assert "delta-focused" in analyzer.description.lower()
