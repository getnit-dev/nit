"""Tests for nit memory CLI commands (U.2.1, U.2.2, U.2.3, U.2.4)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nit.cli import cli
from nit.memory.global_memory import GlobalMemory
from nit.memory.package_memory_manager import PackageMemoryManager


@pytest.fixture
def runner() -> CliRunner:
    """Create Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def project_with_memory(tmp_path: Path) -> Path:
    """Create a temporary project with some memory data."""
    # Create project structure
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()

    # Create global memory with test data
    global_memory = GlobalMemory(tmp_path)
    global_memory.set_conventions({"naming": "snake_case", "assertions": "expect"})
    global_memory.add_known_pattern("pattern1", {"framework": "pytest"})
    global_memory.add_known_pattern("pattern2", {"framework": "vitest"})
    global_memory.add_failed_pattern("bad_pattern", "syntax error", {"file": "test.py"})
    global_memory.update_stats(successful=True, tests_generated=5, tests_passing=4)

    # Create package memory with test data
    manager = PackageMemoryManager(tmp_path)
    pkg_memory = manager.get_package_memory("api")
    pkg_memory.set_test_patterns({"test_prefix": "test_", "mock_style": "unittest.mock"})
    pkg_memory.add_known_issue("flaky test", "use retry decorator")
    pkg_memory.add_coverage_snapshot(85.5)
    pkg_memory.add_llm_feedback("improvement", "Consider using fixtures")

    return tmp_path


# ══════════════════════════════════════════════════════════════════════════════
# U.2.1: nit memory show — display global memory
# ══════════════════════════════════════════════════════════════════════════════


def test_memory_show_global(runner: CliRunner, project_with_memory: Path) -> None:
    """Test U.2.1: Display global memory in human-readable format."""
    result = runner.invoke(cli, ["memory", "show", "--path", str(project_with_memory)])

    assert result.exit_code == 0
    output = result.output

    # Check that output contains global memory sections
    assert "Global Memory" in output
    assert "Conventions:" in output
    assert "snake_case" in output
    assert "expect" in output
    assert "Known Patterns" in output
    assert "pattern1" in output
    assert "Failed Patterns" in output
    assert "bad_pattern" in output
    assert "Statistics:" in output
    assert "Total runs: 1" in output


def test_memory_show_global_json(runner: CliRunner, project_with_memory: Path) -> None:
    """Test U.2.1: Display global memory as JSON."""
    result = runner.invoke(
        cli, ["memory", "show", "--path", str(project_with_memory), "--json-output"]
    )

    assert result.exit_code == 0

    # Parse JSON output
    data = json.loads(result.output)

    assert "conventions" in data
    assert data["conventions"]["naming"] == "snake_case"
    assert "known_patterns" in data
    assert len(data["known_patterns"]) == 2
    assert "failed_patterns" in data
    assert len(data["failed_patterns"]) == 1
    assert "generation_stats" in data
    assert data["generation_stats"]["total_runs"] == 1


def test_memory_show_empty_global(runner: CliRunner, tmp_path: Path) -> None:
    """Test U.2.1: Display global memory when empty."""
    # Create empty project
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()
    GlobalMemory(tmp_path)  # Initialize but don't add data

    result = runner.invoke(cli, ["memory", "show", "--path", str(tmp_path)])

    assert result.exit_code == 0
    output = result.output

    # Check that output shows empty state
    assert "Global Memory" in output
    assert "No conventions recorded" in output or "Conventions:" in output
    assert "No known patterns recorded" in output or "Known Patterns" in output


# ══════════════════════════════════════════════════════════════════════════════
# U.2.2: nit memory show --package <path> — display package memory
# ══════════════════════════════════════════════════════════════════════════════


def test_memory_show_package(runner: CliRunner, project_with_memory: Path) -> None:
    """Test U.2.2: Display package-specific memory."""
    result = runner.invoke(
        cli, ["memory", "show", "--path", str(project_with_memory), "--package", "api"]
    )

    assert result.exit_code == 0
    output = result.output

    # Check that output contains package memory sections
    assert "Package Memory: api" in output
    assert "Test Patterns:" in output
    assert "test_prefix" in output
    assert "unittest.mock" in output
    assert "Known Issues" in output
    assert "flaky test" in output
    assert "Coverage:" in output
    assert "85.5%" in output
    assert "LLM Feedback" in output
    assert "Consider using fixtures" in output


def test_memory_show_package_json(runner: CliRunner, project_with_memory: Path) -> None:
    """Test U.2.2: Display package memory as JSON."""
    result = runner.invoke(
        cli,
        [
            "memory",
            "show",
            "--path",
            str(project_with_memory),
            "--package",
            "api",
            "--json-output",
        ],
    )

    assert result.exit_code == 0

    # Parse JSON output
    data = json.loads(result.output)

    assert data["package_name"] == "api"
    assert "test_patterns" in data
    assert data["test_patterns"]["test_prefix"] == "test_"
    assert "known_issues" in data
    assert len(data["known_issues"]) == 1
    assert "coverage_history" in data
    assert len(data["coverage_history"]) == 1
    assert "llm_feedback" in data
    assert len(data["llm_feedback"]) == 1


def test_memory_show_package_nonexistent(runner: CliRunner, tmp_path: Path) -> None:
    """Test U.2.2: Display memory for package that doesn't exist yet."""
    # Create empty project
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()

    result = runner.invoke(
        cli, ["memory", "show", "--path", str(tmp_path), "--package", "nonexistent"]
    )

    # Should succeed but show empty memory
    assert result.exit_code == 0
    output = result.output
    assert "Package Memory: nonexistent" in output


# ══════════════════════════════════════════════════════════════════════════════
# U.2.3: nit memory reset — clear all memory
# ══════════════════════════════════════════════════════════════════════════════


def test_memory_reset_global_with_confirm_flag(
    runner: CliRunner, project_with_memory: Path
) -> None:
    """Test U.2.3: Clear global memory with --confirm flag."""
    # Verify memory exists
    memory = GlobalMemory(project_with_memory)
    assert len(memory.get_known_patterns()) == 2

    # Reset with --confirm flag
    result = runner.invoke(
        cli, ["memory", "reset", "--path", str(project_with_memory), "--confirm"]
    )

    assert result.exit_code == 0
    assert "Cleared global memory" in result.output

    # Verify memory was cleared
    memory = GlobalMemory(project_with_memory)
    assert len(memory.get_known_patterns()) == 0
    assert len(memory.get_conventions()) == 0
    assert memory.get_stats()["total_runs"] == 0


def test_memory_reset_global_interactive_yes(runner: CliRunner, project_with_memory: Path) -> None:
    """Test U.2.3: Clear global memory with interactive confirmation (yes)."""
    # Reset with interactive confirmation
    result = runner.invoke(
        cli, ["memory", "reset", "--path", str(project_with_memory)], input="y\n"
    )

    assert result.exit_code == 0
    assert "Clear ALL global memory?" in result.output
    assert "Cleared global memory" in result.output


def test_memory_reset_global_interactive_no(runner: CliRunner, project_with_memory: Path) -> None:
    """Test U.2.3: Cancel global memory reset with interactive confirmation (no)."""
    # Verify memory exists
    memory = GlobalMemory(project_with_memory)
    patterns_before = len(memory.get_known_patterns())

    # Reset with interactive confirmation (decline)
    result = runner.invoke(
        cli, ["memory", "reset", "--path", str(project_with_memory)], input="n\n"
    )

    assert result.exit_code == 0
    assert "Clear ALL global memory?" in result.output
    assert "Reset cancelled" in result.output

    # Verify memory was NOT cleared
    memory = GlobalMemory(project_with_memory)
    assert len(memory.get_known_patterns()) == patterns_before


def test_memory_reset_package_with_confirm(runner: CliRunner, project_with_memory: Path) -> None:
    """Test U.2.3: Clear package memory with --confirm flag."""
    # Verify memory exists
    manager = PackageMemoryManager(project_with_memory)
    pkg_memory = manager.get_package_memory("api")
    assert len(pkg_memory.get_known_issues()) == 1

    # Reset package memory
    result = runner.invoke(
        cli,
        [
            "memory",
            "reset",
            "--path",
            str(project_with_memory),
            "--package",
            "api",
            "--confirm",
        ],
    )

    assert result.exit_code == 0
    assert "Cleared memory for package: api" in result.output

    # Verify package memory was cleared - create a new manager instance
    # to ensure we're not using cached data
    new_manager = PackageMemoryManager(project_with_memory)
    new_pkg_memory = new_manager.get_package_memory("api")
    assert len(new_pkg_memory.get_known_issues()) == 0
    assert len(new_pkg_memory.get_test_patterns()) == 0


def test_memory_reset_package_interactive_yes(runner: CliRunner, project_with_memory: Path) -> None:
    """Test U.2.3: Clear package memory with interactive confirmation (yes)."""
    result = runner.invoke(
        cli,
        ["memory", "reset", "--path", str(project_with_memory), "--package", "api"],
        input="y\n",
    )

    assert result.exit_code == 0
    assert "Clear memory for package 'api'?" in result.output
    assert "Cleared memory for package: api" in result.output


# ══════════════════════════════════════════════════════════════════════════════
# U.2.4: nit memory export — export as markdown
# ══════════════════════════════════════════════════════════════════════════════


def test_memory_export_global_stdout(runner: CliRunner, project_with_memory: Path) -> None:
    """Test U.2.4: Export global memory as markdown to stdout."""
    result = runner.invoke(cli, ["memory", "export", "--path", str(project_with_memory)])

    assert result.exit_code == 0
    output = result.output

    # Check markdown structure
    assert "# Global Memory Report" in output
    assert "## Conventions" in output
    assert "- **naming**: snake_case" in output
    assert "## Known Patterns" in output
    assert "### Pattern 1" in output
    assert "- **Pattern**: `pattern1`" in output
    assert "## Failed Patterns" in output
    assert "### Failed Pattern 1" in output
    assert "- **Pattern**: `bad_pattern`" in output
    assert "## Generation Statistics" in output
    assert "- **Total Runs**: 1" in output


def test_memory_export_global_to_file(
    runner: CliRunner, project_with_memory: Path, tmp_path: Path
) -> None:
    """Test U.2.4: Export global memory to file."""
    output_file = tmp_path / "global_memory.md"

    result = runner.invoke(
        cli,
        [
            "memory",
            "export",
            "--path",
            str(project_with_memory),
            "--output",
            str(output_file),
        ],
    )

    assert result.exit_code == 0
    assert "Exported memory to" in result.output
    assert "global_memory.md" in result.output

    # Verify file was created and contains expected content
    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")
    assert "# Global Memory Report" in content
    assert "## Conventions" in content
    assert "- **naming**: snake_case" in content


def test_memory_export_package_stdout(runner: CliRunner, project_with_memory: Path) -> None:
    """Test U.2.4: Export package memory as markdown to stdout."""
    result = runner.invoke(
        cli, ["memory", "export", "--path", str(project_with_memory), "--package", "api"]
    )

    assert result.exit_code == 0
    output = result.output

    # Check markdown structure
    assert "# Package Memory Report: api" in output
    assert "## Test Patterns" in output
    assert "- **test_prefix**: test_" in output
    assert "## Known Issues" in output
    assert "### Issue 1" in output
    assert "- **Issue**: flaky test" in output
    assert "- **Workaround**: use retry decorator" in output
    assert "## Coverage History" in output
    assert "Total snapshots: 1" in output
    assert "85.5%" in output
    assert "## LLM Feedback" in output
    assert "### Feedback 1" in output
    assert "- **Type**: improvement" in output


def test_memory_export_package_to_file(
    runner: CliRunner, project_with_memory: Path, tmp_path: Path
) -> None:
    """Test U.2.4: Export package memory to file."""
    output_file = tmp_path / "api_memory.md"

    result = runner.invoke(
        cli,
        [
            "memory",
            "export",
            "--path",
            str(project_with_memory),
            "--package",
            "api",
            "--output",
            str(output_file),
        ],
    )

    assert result.exit_code == 0
    assert "Exported memory to" in result.output
    assert "api_memory.md" in result.output

    # Verify file was created and contains expected content
    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")
    assert "# Package Memory Report: api" in content
    assert "## Test Patterns" in content


def test_memory_export_empty_global(runner: CliRunner, tmp_path: Path) -> None:
    """Test U.2.4: Export empty global memory."""
    # Create empty project
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()
    GlobalMemory(tmp_path)  # Initialize but don't add data

    result = runner.invoke(cli, ["memory", "export", "--path", str(tmp_path)])

    assert result.exit_code == 0
    output = result.output

    # Check markdown shows empty sections
    assert "# Global Memory Report" in output
    assert "*No conventions recorded*" in output
    assert "*No known patterns recorded*" in output
    assert "*No failed patterns recorded*" in output


# ══════════════════════════════════════════════════════════════════════════════
# Edge cases and integration tests
# ══════════════════════════════════════════════════════════════════════════════


def test_memory_show_handles_multiple_packages(runner: CliRunner, tmp_path: Path) -> None:
    """Test showing memory for multiple packages in a monorepo."""
    # Create project structure
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()

    # Create memory for multiple packages
    manager = PackageMemoryManager(tmp_path)
    for pkg_name in ["api", "web", "mobile"]:
        pkg_memory = manager.get_package_memory(pkg_name)
        pkg_memory.set_test_patterns({f"{pkg_name}_pattern": "value"})

    # Test each package
    for pkg_name in ["api", "web", "mobile"]:
        result = runner.invoke(
            cli, ["memory", "show", "--path", str(tmp_path), "--package", pkg_name]
        )
        assert result.exit_code == 0
        assert f"Package Memory: {pkg_name}" in result.output
        assert f"{pkg_name}_pattern" in result.output


def test_memory_commands_create_directory_structure(runner: CliRunner, tmp_path: Path) -> None:
    """Test that memory commands create necessary directories if missing."""
    # Don't create .nit directory upfront

    # Show should work even without .nit directory
    result = runner.invoke(cli, ["memory", "show", "--path", str(tmp_path)])
    assert result.exit_code == 0

    # Export should work
    result = runner.invoke(cli, ["memory", "export", "--path", str(tmp_path)])
    assert result.exit_code == 0


def test_memory_reset_and_verify(runner: CliRunner, project_with_memory: Path) -> None:
    """Test full workflow: show → reset → verify empty."""
    # 1. Show that memory has data
    result = runner.invoke(cli, ["memory", "show", "--path", str(project_with_memory)])
    assert result.exit_code == 0
    assert "pattern1" in result.output

    # 2. Reset memory
    result = runner.invoke(
        cli, ["memory", "reset", "--path", str(project_with_memory), "--confirm"]
    )
    assert result.exit_code == 0

    # 3. Show that memory is now empty
    result = runner.invoke(cli, ["memory", "show", "--path", str(project_with_memory)])
    assert result.exit_code == 0
    assert "pattern1" not in result.output


def test_memory_export_multiple_patterns(runner: CliRunner, tmp_path: Path) -> None:
    """Test export with many patterns to verify truncation and formatting."""
    # Create project with lots of data
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()

    memory = GlobalMemory(tmp_path)

    # Add many patterns
    for i in range(10):
        memory.add_known_pattern(f"pattern_{i}", {"index": i})
        memory.add_failed_pattern(f"bad_pattern_{i}", f"reason_{i}")

    result = runner.invoke(cli, ["memory", "export", "--path", str(tmp_path)])

    assert result.exit_code == 0
    output = result.output

    # All patterns should be in export
    assert "### Pattern 1" in output
    assert "### Pattern 10" in output
    assert "### Failed Pattern 1" in output
    assert "### Failed Pattern 10" in output


def test_memory_show_truncates_long_lists(runner: CliRunner, tmp_path: Path) -> None:
    """Test that show command truncates long lists appropriately."""
    # Create project with lots of data
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()

    memory = GlobalMemory(tmp_path)

    # Add many patterns (more than display limit of 5)
    for i in range(10):
        memory.add_known_pattern(f"pattern_{i}", {"index": i})

    result = runner.invoke(cli, ["memory", "show", "--path", str(tmp_path)])

    assert result.exit_code == 0
    output = result.output

    # Should show truncation message
    assert "... and 5 more" in output


def test_memory_package_name_sanitization(runner: CliRunner, tmp_path: Path) -> None:
    """Test that package names with special characters are handled correctly."""
    # Create project structure
    nit_dir = tmp_path / ".nit"
    nit_dir.mkdir()

    # Create memory for package with slashes in name
    manager = PackageMemoryManager(tmp_path)
    pkg_memory = manager.get_package_memory("packages/api/v1")
    pkg_memory.set_test_patterns({"pattern": "value"})

    # Show should work
    result = runner.invoke(
        cli,
        ["memory", "show", "--path", str(tmp_path), "--package", "packages/api/v1"],
    )
    assert result.exit_code == 0
    assert "Package Memory: packages/api/v1" in result.output

    # Export should work
    result = runner.invoke(
        cli,
        ["memory", "export", "--path", str(tmp_path), "--package", "packages/api/v1"],
    )
    assert result.exit_code == 0
    assert "# Package Memory Report: packages/api/v1" in result.output


def test_memory_commands_with_nonexistent_path(runner: CliRunner) -> None:
    """Test that memory commands handle nonexistent paths gracefully."""
    nonexistent = "/nonexistent/path/to/project"

    # Show should fail gracefully
    result = runner.invoke(cli, ["memory", "show", "--path", nonexistent])
    assert result.exit_code != 0

    # Export should fail gracefully
    result = runner.invoke(cli, ["memory", "export", "--path", nonexistent])
    assert result.exit_code != 0

    # Reset should fail gracefully
    result = runner.invoke(cli, ["memory", "reset", "--path", nonexistent, "--confirm"])
    assert result.exit_code != 0


# ══════════════════════════════════════════════════════════════════════════════
# Memory pull/push commands
# ══════════════════════════════════════════════════════════════════════════════


def _mock_disabled_config() -> MagicMock:
    """Build a mock NitConfig with platform disabled."""
    config = MagicMock()
    config.platform.normalized_mode = "disabled"
    config.platform.url = ""
    config.platform.api_key = ""
    config.platform.mode = "disabled"
    config.platform.user_id = ""
    config.platform.project_id = ""
    config.platform.key_hash = ""
    return config


def _mock_platform_config() -> MagicMock:
    """Build a mock NitConfig with platform enabled."""
    config = MagicMock()
    config.platform.normalized_mode = "byok"
    config.platform.url = "https://platform.getnit.dev"
    config.platform.api_key = "nit_test_key"
    config.platform.mode = "byok"
    config.platform.user_id = "user-1"
    config.platform.project_id = "proj-1"
    config.platform.key_hash = "hash-1"
    return config


def test_memory_pull_no_platform_configured(runner: CliRunner, project_with_memory: Path) -> None:
    """Pull should print error and exit when platform is disabled."""
    with patch("nit.cli.load_config", return_value=_mock_disabled_config()):
        result = runner.invoke(cli, ["memory", "pull", "--path", str(project_with_memory)])

    assert result.exit_code != 0
    assert "Platform not configured" in result.output


def test_memory_push_no_platform_configured(runner: CliRunner, project_with_memory: Path) -> None:
    """Push should print error and exit when platform is disabled."""
    with patch("nit.cli.load_config", return_value=_mock_disabled_config()):
        result = runner.invoke(cli, ["memory", "push", "--path", str(project_with_memory)])

    assert result.exit_code != 0
    assert "Platform not configured" in result.output


def test_memory_pull_success(runner: CliRunner, project_with_memory: Path) -> None:
    """Pull should download memory and update local files."""
    pull_response = {
        "version": 3,
        "global": {
            "conventions": {"lang": "python"},
            "knownPatterns": [
                {
                    "pattern": "remote pattern",
                    "success_count": 1,
                    "last_used": "2025-06-01",
                    "context": {},
                }
            ],
            "failedPatterns": [],
            "generationStats": {"total_runs": 10},
        },
        "packages": {},
    }

    with (
        patch("nit.cli.load_config", return_value=_mock_platform_config()),
        patch(
            "nit.utils.platform_client.pull_platform_memory",
            return_value=pull_response,
        ) as mock_pull,
    ):
        result = runner.invoke(cli, ["memory", "pull", "--path", str(project_with_memory)])

    assert result.exit_code == 0
    assert "Pulled memory from platform" in result.output
    mock_pull.assert_called_once()


def test_memory_pull_no_remote_memory(runner: CliRunner, project_with_memory: Path) -> None:
    """Pull should report no memory when platform returns version 0."""
    with (
        patch("nit.cli.load_config", return_value=_mock_platform_config()),
        patch(
            "nit.utils.platform_client.pull_platform_memory",
            return_value={"version": 0, "global": None, "packages": {}},
        ),
    ):
        result = runner.invoke(cli, ["memory", "pull", "--path", str(project_with_memory)])

    assert result.exit_code == 0
    assert "No memory on platform" in result.output


def test_memory_push_success(runner: CliRunner, project_with_memory: Path) -> None:
    """Push should upload memory and report result."""
    push_response = {"version": 5, "merged": True}

    with (
        patch("nit.cli.load_config", return_value=_mock_platform_config()),
        patch(
            "nit.utils.platform_client.push_platform_memory",
            return_value=push_response,
        ) as mock_push,
    ):
        result = runner.invoke(cli, ["memory", "push", "--path", str(project_with_memory)])

    assert result.exit_code == 0
    assert "merged with existing" in result.output
    mock_push.assert_called_once()
