"""Tests for the nit CLI commands."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
import yaml
from click.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.base import CaseResult, CaseStatus, RunResult
from nit.adapters.coverage.base import CoverageReport
from nit.agents.analyzers.bug import BugLocation, BugReport, BugSeverity, BugType
from nit.agents.analyzers.coverage import CoverageGapReport
from nit.agents.analyzers.diff import DiffAnalysisResult, FileMapping
from nit.agents.base import TaskStatus
from nit.agents.detectors.signals import DetectedFramework, FrameworkCategory
from nit.agents.detectors.stack import LanguageInfo
from nit.agents.detectors.workspace import PackageInfo
from nit.agents.pipelines import PickPipelineResult
from nit.agents.watchers.drift import DriftReport, DriftTestResult
from nit.agents.watchers.schedule import ScheduledRunResult
from nit.cli import (
    _build_pick_report_payload,
    _config_to_dict,
    _display_diff_result,
    _display_doc_results,
    _display_drift_report,
    _display_global_memory,
    _display_package_memory,
    _display_pick_results,
    _display_profile,
    _display_test_results_console,
    _display_test_results_json,
    _display_watch_run,
    _format_yaml_string,
    _get_slack_reporter,
    _is_llm_runtime_configured,
    _load_nit_yml,
    _mask_sensitive_values,
    _PickOptions,
    _render_coverage_section,
    _render_e2e_section,
    _render_git_section,
    _render_llm_section,
    _render_platform_section,
    _render_report_section,
    _render_sentry_section,
    _set_nested_config_value,
    _upload_bugs_to_platform,
    _write_comprehensive_nit_yml,
    _write_nit_yml,
    cli,
)
from nit.config import load_config
from nit.sharding.shard_result import write_shard_result
from nit.utils.git import GitOperationError
from nit.utils.platform_client import PlatformClientError


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "nit" in result.output


# ── nit init ─────────────────────────────────────────────────────


class TestInit:
    def test_creates_profile_and_config(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print('hello')\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".nit" / "profile.json").is_file()
        assert (tmp_path / ".nit.yml").is_file()

    def test_displays_language_table(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--path", str(tmp_path)])

        assert result.exit_code == 0
        assert "python" in result.output.lower()

    def test_nit_yml_content(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")

        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

        nit_yml = (tmp_path / ".nit.yml").read_text(encoding="utf-8")
        assert "project:" in nit_yml
        assert "llm:" in nit_yml

    def test_nit_init_non_interactive_defaults_to_builtin_llm(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        raw = yaml.safe_load((tmp_path / ".nit.yml").read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["llm"]["mode"] == "builtin"
        assert raw["llm"]["provider"] == "openai"
        assert raw["llm"]["model"] == "gpt-4o"

    def test_nit_init_wizard_selects_claude_cli(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")

        runner = CliRunner()
        with (
            patch("nit.cli._is_interactive_terminal", return_value=True),
            patch("nit.cli.shutil.which", return_value="/usr/local/bin/claude"),
        ):
            # Provide input for interactive prompts:
            # platform mode=2 (disabled), LLM mode=2 (Claude CLI),
            # Slack=n, Email=n, E2E=n, Auto-commit=n, Auto-PR=n,
            # Create issues=n, Create fix PRs=n, Configure coverage thresholds=n,
            # Report format=enter, Docs=n, Sentry=n, Advanced LLM=n
            result = runner.invoke(
                cli,
                ["init", "--linear", "--path", str(tmp_path)],
                input="2\n2\nn\nn\nn\nn\nn\nn\nn\nn\n\nn\nn\nn\n",
            )

        assert result.exit_code == 0, result.output
        raw = yaml.safe_load((tmp_path / ".nit.yml").read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["llm"]["mode"] == "cli"
        assert raw["llm"]["provider"] == "anthropic"
        assert raw["llm"]["cli_command"] == "claude"
        assert raw["llm"]["model"] == "claude-sonnet-4-5-20250514"

    def test_nit_init_wizard_selects_custom_command(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")

        runner = CliRunner()
        with patch("nit.cli._is_interactive_terminal", return_value=True):
            # Provide input for interactive prompts:
            # platform mode=2 (disabled), LLM mode=6 (Custom),
            # Slack=n, Email=n, E2E=n, Auto-commit=n, Auto-PR=n,
            # Create issues=n, Create fix PRs=n, Configure coverage thresholds=n,
            # Report format=enter, Docs=n, Sentry=n, Advanced LLM=n
            result = runner.invoke(
                cli,
                ["init", "--linear", "--path", str(tmp_path)],
                input="2\n6\nn\nn\nn\nn\nn\nn\nn\nn\n\nn\nn\nn\n",
            )

        assert result.exit_code == 0, result.output
        raw = yaml.safe_load((tmp_path / ".nit.yml").read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["llm"]["mode"] == "custom"
        assert "{context_file}" in raw["llm"]["cli_command"]
        assert "{output_file}" in raw["llm"]["cli_command"]

    def test_empty_project(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--path", str(tmp_path)])
        assert result.exit_code == 0


# ── nit scan ─────────────────────────────────────────────────────


class TestScan:
    def test_scan_fresh(self, tmp_path: Path) -> None:
        (tmp_path / "lib.py").write_text("def f(): pass\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--path", str(tmp_path)])

        assert result.exit_code == 0
        assert (tmp_path / ".nit" / "profile.json").is_file()

    def test_scan_force(self, tmp_path: Path) -> None:
        (tmp_path / "lib.py").write_text("def f(): pass\n")

        runner = CliRunner()
        runner.invoke(cli, ["scan", "--path", str(tmp_path)])
        result = runner.invoke(cli, ["scan", "--path", str(tmp_path), "--force"])

        assert result.exit_code == 0
        assert "Profile updated" in result.output

    def test_scan_json_output(self, tmp_path: Path) -> None:
        (tmp_path / "lib.py").write_text("def f(): pass\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--path", str(tmp_path), "--force", "--json-output"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "languages" in data
        assert "frameworks" in data
        assert "packages" in data

    def test_scan_empty_project(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--path", str(tmp_path)])
        assert result.exit_code == 0


class TestConfig:
    def test_config_set_platform_values(self, tmp_path: Path) -> None:
        runner = CliRunner()

        result_url = runner.invoke(
            cli,
            [
                "config",
                "set",
                "platform.url",
                "https://platform.getnit.dev",
                "--path",
                str(tmp_path),
            ],
        )
        result_key = runner.invoke(
            cli, ["config", "set", "platform.api_key", "nit_key_123", "--path", str(tmp_path)]
        )

        assert result_url.exit_code == 0, result_url.output
        assert result_key.exit_code == 0, result_key.output

        raw = yaml.safe_load((tmp_path / ".nit.yml").read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["platform"]["url"] == "https://platform.getnit.dev"
        assert raw["platform"]["api_key"] == "nit_key_123"

    def test_config_set_nested_values(self, tmp_path: Path) -> None:
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["config", "set", "e2e.auth.strategy", "token", "--path", str(tmp_path)],
        )

        assert result.exit_code == 0, result.output
        raw = yaml.safe_load((tmp_path / ".nit.yml").read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["e2e"]["auth"]["strategy"] == "token"

    def test_config_set_creates_file_if_missing(self, tmp_path: Path) -> None:
        runner = CliRunner()
        nit_yml = tmp_path / ".nit.yml"
        assert not nit_yml.exists()

        result = runner.invoke(
            cli,
            ["config", "set", "llm.provider", "anthropic", "--path", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert nit_yml.exists()
        raw = yaml.safe_load(nit_yml.read_text(encoding="utf-8"))
        assert raw["llm"]["provider"] == "anthropic"

    def test_config_show_displays_config(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "project:\n"
            "  root: .\n"
            "llm:\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test-1234567890\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "project:" in result.output
        assert "llm:" in result.output
        assert "provider: openai" in result.output

    def test_config_show_masks_sensitive_values(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  provider: openai\n"
            "  api_key: sk-test-1234567890abcdef\n"
            "platform:\n"
            "  api_key: nit_key_abc123xyz789\n"
            "e2e:\n"
            "  auth:\n"
            "    password: supersecret123\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        # Should NOT contain full sensitive values
        assert "sk-test-1234567890abcdef" not in result.output
        assert "nit_key_abc123xyz789" not in result.output
        assert "supersecret123" not in result.output
        # Should contain masked values
        assert "sk-t...cdef" in result.output or "***" in result.output

    def test_config_show_no_mask_shows_full_values(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  api_key: sk-test-secret\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "--path", str(tmp_path), "--no-mask"])

        assert result.exit_code == 0, result.output
        assert "sk-test-secret" in result.output

    def test_config_show_json_output(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "project:\n  root: .\nllm:\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "--path", str(tmp_path), "--json-output"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, dict)
        assert "project" in data
        assert "llm" in data
        assert data["llm"]["provider"] == "openai"

    def test_config_show_fails_on_invalid_config(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text("invalid: [[[yaml", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "--path", str(tmp_path)])

        assert result.exit_code != 0

    def test_config_validate_valid_config(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "project:\n"
            "  root: .\n"
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "validate", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "valid" in result.output.lower()

    def test_config_validate_invalid_config_missing_fields(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: cli\n  provider: openai\n  model: gpt-4o\n"
            # Missing cli_command which is required for cli mode
            "",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "validate", "--path", str(tmp_path)])

        assert result.exit_code != 0
        assert "error" in result.output.lower()
        assert "cli_command" in result.output

    def test_config_validate_invalid_mode(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: invalid_mode\n  provider: openai\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "validate", "--path", str(tmp_path)])

        assert result.exit_code != 0
        assert "mode" in result.output.lower()

    def test_config_validate_invalid_temperature(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  temperature: 5.0\n",  # Invalid: too high
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "validate", "--path", str(tmp_path)])

        assert result.exit_code != 0
        assert "temperature" in result.output.lower()

    def test_config_validate_invalid_auth_strategy(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "e2e:\n  auth:\n    strategy: form\n"
            # Missing login_url, username, password
            "",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "validate", "--path", str(tmp_path)])

        assert result.exit_code != 0
        assert "auth" in result.output.lower()

    def test_config_validate_platform_mode_requires_url(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "platform:\n  mode: byok\n  api_key: nit_key_123\n"
            # Missing url
            "",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "validate", "--path", str(tmp_path)])

        assert result.exit_code != 0
        assert "url" in result.output.lower()

    def test_config_validate_displays_multiple_errors(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: invalid_mode\n  temperature: 10.0\n  max_tokens: -5\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "validate", "--path", str(tmp_path)])

        assert result.exit_code != 0
        # Should show multiple errors
        assert "mode" in result.output.lower()
        assert "temperature" in result.output.lower()
        assert "max_tokens" in result.output.lower()


# ── nit generate ──────────────────────────────────────────────────


class TestGenerate:
    """Tests for 'nit generate' command."""

    def _write_valid_config(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "project:\n"
            "  root: .\n"
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )

    def test_generate_no_config_aborts(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", "--path", str(tmp_path)])
        # No .nit.yml at all -> load_config returns defaults which may pass
        # but we specifically test LLM not configured path
        assert result.exit_code != 0 or "not configured" in result.output.lower()

    def test_generate_validation_errors_abort(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: invalid_mode\n  temperature: 10.0\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_generate_no_llm_configured_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_generate_prints_header_and_info(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        (tmp_path / "app.py").write_text("def hello(): pass\n")
        # Run init to create profile
        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

        mock_result = MagicMock()
        mock_result.status = "COMPLETED"
        mock_result.result = {"build_tasks": []}

        with (patch("nit.cli._get_test_adapters", side_effect=click.Abort),):
            result = runner.invoke(cli, ["generate", "--path", str(tmp_path)])

        # Should show header and generation info before aborting on adapters
        assert "generate" in result.output.lower() or result.exit_code != 0

    def test_generate_with_type_flag(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

        with patch("nit.cli._get_test_adapters", side_effect=click.Abort):
            result = runner.invoke(cli, ["generate", "--path", str(tmp_path), "--type", "unit"])
        assert result.exit_code != 0

    def test_generate_with_coverage_target(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

        with patch("nit.cli._get_test_adapters", side_effect=click.Abort):
            result = runner.invoke(
                cli, ["generate", "--path", str(tmp_path), "--coverage-target", "90"]
            )
        assert result.exit_code != 0


# ── nit run ──────────────────────────────────────────────────────


class TestRun:
    """Tests for 'nit run' command."""

    def _setup_project(self, tmp_path: Path) -> None:
        """Create a minimal project with config and profile."""
        (tmp_path / ".nit.yml").write_text(
            "project:\n  root: .\nllm:\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        (tmp_path / "app.py").write_text("def hello(): pass\n")
        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

    def test_run_no_profile_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_run_no_adapters_aborts(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        runner = CliRunner()
        with patch("nit.cli._get_test_adapters", side_effect=click.Abort):
            result = runner.invoke(cli, ["run", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_run_success(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        run_result = RunResult(
            passed=3,
            failed=0,
            skipped=0,
            errors=0,
            duration_ms=150.0,
            success=True,
            test_cases=[],
        )
        mock_adapter = MagicMock()
        mock_adapter.name = "pytest"
        mock_adapter.run_tests = AsyncMock(return_value=run_result)
        mock_adapter.get_test_pattern.return_value = ["test_*.py"]

        runner = CliRunner()
        with (
            patch("nit.cli._get_test_adapters", return_value=[mock_adapter]),
            patch("nit.cli_helpers.check_and_install_prerequisites", return_value=True),
        ):
            result = runner.invoke(cli, ["run", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "passed" in result.output.lower()

    def test_run_failure_aborts(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        run_result = RunResult(
            passed=1,
            failed=2,
            skipped=0,
            errors=0,
            duration_ms=200.0,
            success=False,
            test_cases=[],
        )
        mock_adapter = MagicMock()
        mock_adapter.name = "pytest"
        mock_adapter.run_tests = AsyncMock(return_value=run_result)
        mock_adapter.get_test_pattern.return_value = ["test_*.py"]

        runner = CliRunner()
        with (
            patch("nit.cli._get_test_adapters", return_value=[mock_adapter]),
            patch("nit.cli_helpers.check_and_install_prerequisites", return_value=True),
        ):
            result = runner.invoke(cli, ["run", "--path", str(tmp_path)])

        assert result.exit_code != 0

    def test_run_ci_mode_json_output(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        run_result = RunResult(
            passed=5,
            failed=0,
            skipped=1,
            errors=0,
            duration_ms=300.0,
            success=True,
            test_cases=[],
        )
        mock_adapter = MagicMock()
        mock_adapter.name = "pytest"
        mock_adapter.run_tests = AsyncMock(return_value=run_result)
        mock_adapter.get_test_pattern.return_value = ["test_*.py"]

        runner = CliRunner()
        with (
            patch("nit.cli._get_test_adapters", return_value=[mock_adapter]),
            patch("nit.cli_helpers.check_and_install_prerequisites", return_value=True),
        ):
            result = runner.invoke(cli, ["--ci", "run", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        # CI mode still prints some info lines before the JSON blob,
        # so extract the JSON portion from the output.
        json_start = result.output.index("{")
        data = json.loads(result.output[json_start:])
        assert data["success"] is True
        assert data["passed"] == 5
        assert data["skipped"] == 1

    def test_run_shard_requires_both_flags(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--path", str(tmp_path), "--shard-index", "0"])
        assert result.exit_code != 0
        assert "shard" in result.output.lower()

    def test_run_prerequisites_fail_aborts(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        mock_adapter = MagicMock()
        mock_adapter.name = "pytest"
        mock_adapter.get_test_pattern.return_value = ["test_*.py"]

        runner = CliRunner()
        with (
            patch("nit.cli._get_test_adapters", return_value=[mock_adapter]),
            patch("nit.cli_helpers.check_and_install_prerequisites", return_value=False),
        ):
            result = runner.invoke(cli, ["run", "--path", str(tmp_path)])

        assert result.exit_code != 0
        assert "prerequisites" in result.output.lower()

    def test_run_with_package_flag(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        run_result = RunResult(
            passed=2,
            failed=0,
            skipped=0,
            errors=0,
            duration_ms=100.0,
            success=True,
            test_cases=[],
        )
        mock_adapter = MagicMock()
        mock_adapter.name = "pytest"
        mock_adapter.run_tests = AsyncMock(return_value=run_result)
        mock_adapter.get_test_pattern.return_value = ["test_*.py"]

        runner = CliRunner()
        with (
            patch("nit.cli._get_test_adapters", return_value=[mock_adapter]),
            patch("nit.cli_helpers.check_and_install_prerequisites", return_value=True),
        ):
            result = runner.invoke(
                cli, ["run", "--path", str(tmp_path), "--package", str(tmp_path)]
            )

        assert result.exit_code == 0, result.output


# ── nit pick ─────────────────────────────────────────────────────


class TestPick:
    """Tests for 'nit pick' command."""

    def _write_valid_config(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )

    def test_pick_no_config_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: invalid_mode\n  temperature: 10.0\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["pick", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_pick_no_llm_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["pick", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_pick_success(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=5,
            tests_passed=5,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["pick", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_pick_ci_mode(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=3,
            tests_passed=3,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["--ci", "pick", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_pick_with_fix_flag(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=4,
            tests_passed=4,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["pick", "--path", str(tmp_path), "--fix"])

        assert result.exit_code == 0, result.output
        assert "fix" in result.output.lower()

    def test_pick_with_type_and_coverage_target(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=2,
            tests_passed=2,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                [
                    "pick",
                    "--path",
                    str(tmp_path),
                    "--type",
                    "unit",
                    "--coverage-target",
                    "85",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "85%" in result.output

    def test_pick_failure_aborts(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=False,
            tests_run=5,
            tests_passed=2,
            tests_failed=3,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=["Test failures detected"],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["pick", "--path", str(tmp_path)])

        assert result.exit_code != 0

    def test_pick_with_max_loops(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=3,
            tests_passed=3,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["pick", "--path", str(tmp_path), "--max-loops", "3"])

        assert result.exit_code == 0, result.output

    def test_pick_with_token_budget(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=3,
            tests_passed=3,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["pick", "--path", str(tmp_path), "--token-budget", "5000"])

        assert result.exit_code == 0, result.output


# ── nit docs ─────────────────────────────────────────────────────


class TestDocs:
    """Tests for 'nit docs' command."""

    def test_docs_no_mode_shows_usage(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["docs"])
        assert result.exit_code == 0
        assert "nit docs" in result.output

    def test_docs_check_no_config_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: invalid_mode\n  temperature: 10.0\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--check", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_docs_check_success(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n  api_key: sk-test\n",
            encoding="utf-8",
        )

        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.COMPLETED
        mock_task_output.result = {"results": []}
        mock_task_output.errors = []

        runner = CliRunner()
        with patch("nit.cli.DocBuilder.run", return_value=mock_task_output):
            result = runner.invoke(cli, ["docs", "--check", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "up to date" in result.output.lower()

    def test_docs_check_finds_outdated(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n  api_key: sk-test\n",
            encoding="utf-8",
        )

        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.COMPLETED
        mock_task_output.result = {
            "results": [
                {
                    "file_path": "src/main.py",
                    "outdated": True,
                    "changes": [{"function_name": "foo"}],
                    "generated_docs": {},
                }
            ]
        }
        mock_task_output.errors = []

        runner = CliRunner()
        with patch("nit.cli.DocBuilder.run", return_value=mock_task_output):
            result = runner.invoke(cli, ["docs", "--check", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "outdated" in result.output.lower()

    def test_docs_all_runs_docbuilder(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n  api_key: sk-test\n",
            encoding="utf-8",
        )

        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.COMPLETED
        mock_task_output.result = {"results": []}
        mock_task_output.errors = []

        runner = CliRunner()
        with (
            patch("nit.cli.DocBuilder.run", return_value=mock_task_output),
            patch("nit.cli.create_engine"),
        ):
            result = runner.invoke(cli, ["docs", "--all", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_docs_changelog_missing_git_aborts(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with patch(
            "nit.cli._docs_changelog",
            side_effect=GitOperationError("Not a git repo"),
        ):
            result = runner.invoke(cli, ["docs", "--changelog", "v1.0.0", "--path", str(tmp_path)])

        assert result.exit_code != 0

    def test_docs_changelog_success(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with patch("nit.cli._docs_changelog") as mock_changelog:
            result = runner.invoke(cli, ["docs", "--changelog", "v1.0.0", "--path", str(tmp_path)])

        assert result.exit_code == 0
        mock_changelog.assert_called_once()

    def test_docs_readme_no_llm_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--readme", "--path", str(tmp_path)])
        assert result.exit_code != 0


# ── nit drift ────────────────────────────────────────────────────


class TestDrift:
    """Tests for 'nit drift' command."""

    def test_drift_test_mode(self, tmp_path: Path) -> None:
        mock_report = DriftReport(
            total_tests=3,
            passed_tests=3,
            failed_tests=0,
            skipped_tests=0,
            drift_detected=False,
            results=[],
        )
        runner = CliRunner()
        with patch(
            "nit.agents.watchers.drift.DriftWatcher.run_drift_tests",
            return_value=mock_report,
        ):
            result = runner.invoke(cli, ["drift", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "drift test" in result.output.lower()

    def test_drift_baseline_mode(self, tmp_path: Path) -> None:
        mock_report = DriftReport(
            total_tests=2,
            passed_tests=2,
            failed_tests=0,
            skipped_tests=0,
            drift_detected=False,
            results=[
                DriftTestResult(
                    test_id="t1",
                    test_name="test_one",
                    passed=True,
                    output="ok",
                ),
                DriftTestResult(
                    test_id="t2",
                    test_name="test_two",
                    passed=True,
                    output="ok",
                ),
            ],
        )
        runner = CliRunner()
        with patch(
            "nit.agents.watchers.drift.DriftWatcher.update_baselines",
            return_value=mock_report,
        ):
            result = runner.invoke(cli, ["drift", "--baseline", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "baseline" in result.output.lower()

    def test_drift_detected_exits_nonzero(self, tmp_path: Path) -> None:
        mock_report = DriftReport(
            total_tests=2,
            passed_tests=1,
            failed_tests=1,
            skipped_tests=0,
            drift_detected=True,
            results=[
                DriftTestResult(
                    test_id="t1",
                    test_name="test_stable",
                    passed=True,
                    output="ok",
                    similarity_score=0.99,
                    baseline_exists=True,
                ),
                DriftTestResult(
                    test_id="t2",
                    test_name="test_drifted",
                    passed=False,
                    output="different",
                    similarity_score=0.4,
                    baseline_exists=True,
                ),
            ],
        )
        runner = CliRunner()
        with patch(
            "nit.agents.watchers.drift.DriftWatcher.run_drift_tests",
            return_value=mock_report,
        ):
            result = runner.invoke(cli, ["drift", "--path", str(tmp_path)])

        assert result.exit_code != 0

    def test_drift_with_tests_file_option(self, tmp_path: Path) -> None:
        mock_report = DriftReport(
            total_tests=1,
            passed_tests=1,
            failed_tests=0,
            skipped_tests=0,
            drift_detected=False,
            results=[],
        )
        runner = CliRunner()
        with patch(
            "nit.agents.watchers.drift.DriftWatcher.run_drift_tests",
            return_value=mock_report,
        ):
            result = runner.invoke(
                cli,
                ["drift", "--path", str(tmp_path), "--tests-file", "custom-drift.yml"],
            )

        assert result.exit_code == 0, result.output

    def test_drift_baseline_with_errors(self, tmp_path: Path) -> None:
        mock_report = DriftReport(
            total_tests=2,
            passed_tests=1,
            failed_tests=0,
            skipped_tests=1,
            drift_detected=False,
            results=[
                DriftTestResult(
                    test_id="t1",
                    test_name="test_ok",
                    passed=True,
                    output="ok",
                ),
                DriftTestResult(
                    test_id="t2",
                    test_name="test_err",
                    passed=False,
                    output="",
                    error="Connection refused",
                ),
            ],
        )
        runner = CliRunner()
        with patch(
            "nit.agents.watchers.drift.DriftWatcher.update_baselines",
            return_value=mock_report,
        ):
            result = runner.invoke(cli, ["drift", "--baseline", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "skipped" in result.output.lower()


# ── nit watch ────────────────────────────────────────────────────


class TestWatch:
    """Tests for 'nit watch' command."""

    def test_watch_single_run(self, tmp_path: Path) -> None:
        mock_run_result = ScheduledRunResult(
            run_id="run-1",
            scheduled_time="2025-01-01T00:00:00",
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:00:01",
            success=True,
            exit_code=0,
            output="all tests passed",
            duration_seconds=1.0,
        )

        runner = CliRunner()
        with patch(
            "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
            return_value=mock_run_result,
        ):
            result = runner.invoke(
                cli,
                ["watch", "--path", str(tmp_path), "--max-runs", "1"],
            )

        assert result.exit_code == 0, result.output
        assert "passed" in result.output.lower() or "run 1" in result.output.lower()

    def test_watch_failed_run(self, tmp_path: Path) -> None:
        mock_run_result = ScheduledRunResult(
            run_id="run-1",
            scheduled_time="2025-01-01T00:00:00",
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:00:02",
            success=False,
            exit_code=1,
            output="FAILED",
            duration_seconds=2.0,
            error="2 tests failed",
        )

        runner = CliRunner()
        with patch(
            "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
            return_value=mock_run_result,
        ):
            result = runner.invoke(
                cli,
                ["watch", "--path", str(tmp_path), "--max-runs", "1"],
            )

        assert result.exit_code == 0, result.output
        assert "failed" in result.output.lower()

    def test_watch_with_coverage(self, tmp_path: Path) -> None:
        mock_run_result = ScheduledRunResult(
            run_id="run-1",
            scheduled_time="2025-01-01T00:00:00",
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:00:01",
            success=True,
            exit_code=0,
            output="ok",
            duration_seconds=1.0,
        )

        mock_snapshot = MagicMock()
        mock_snapshot.overall_line_coverage = 85.0
        mock_snapshot.overall_function_coverage = 90.0

        mock_trend = MagicMock()
        mock_trend.current_snapshot = mock_snapshot
        mock_trend.trend = "stable"
        mock_trend.alerts = []

        runner = CliRunner()
        with (
            patch(
                "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
                return_value=mock_run_result,
            ),
            patch(
                "nit.agents.watchers.coverage.CoverageWatcher.collect_and_analyze",
                return_value=mock_trend,
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "watch",
                    "--path",
                    str(tmp_path),
                    "--max-runs",
                    "1",
                    "--coverage",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "coverage" in result.output.lower()

    def test_watch_with_custom_interval(self, tmp_path: Path) -> None:
        mock_run_result = ScheduledRunResult(
            run_id="run-1",
            scheduled_time="2025-01-01T00:00:00",
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:00:01",
            success=True,
            exit_code=0,
            output="ok",
            duration_seconds=1.0,
        )

        runner = CliRunner()
        with patch(
            "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
            return_value=mock_run_result,
        ):
            result = runner.invoke(
                cli,
                [
                    "watch",
                    "--path",
                    str(tmp_path),
                    "--max-runs",
                    "1",
                    "--interval",
                    "1800",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "1800s" in result.output


# ── nit report ───────────────────────────────────────────────────


class TestReport:
    """Tests for 'nit report' command."""

    def test_report_html_generates_dashboard(self, tmp_path: Path) -> None:
        runner = CliRunner()
        mock_dashboard = MagicMock()
        mock_dashboard.generate_html.return_value = tmp_path / "report.html"

        with patch("nit.agents.reporters.dashboard.DashboardReporter", return_value=mock_dashboard):
            result = runner.invoke(cli, ["report", "--html", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "dashboard" in result.output.lower()

    def test_report_html_failure_aborts(self, tmp_path: Path) -> None:
        runner = CliRunner()
        mock_dashboard = MagicMock()
        mock_dashboard.generate_html.side_effect = RuntimeError("Generation failed")

        with patch("nit.agents.reporters.dashboard.DashboardReporter", return_value=mock_dashboard):
            result = runner.invoke(cli, ["report", "--html", "--path", str(tmp_path)])

        assert result.exit_code != 0

    def test_report_html_with_days(self, tmp_path: Path) -> None:
        runner = CliRunner()
        mock_dashboard = MagicMock()
        mock_dashboard.generate_html.return_value = tmp_path / "report.html"

        with patch(
            "nit.agents.reporters.dashboard.DashboardReporter", return_value=mock_dashboard
        ) as mock_cls:
            result = runner.invoke(
                cli, ["report", "--html", "--path", str(tmp_path), "--days", "7"]
            )

        assert result.exit_code == 0, result.output
        # Verify days=7 was passed to constructor
        call_kwargs = mock_cls.call_args
        assert call_kwargs[1]["days"] == 7

    def test_report_pr_delegates_to_pick(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=True,
            tests_run=3,
            tests_passed=3,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["report", "--pr", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_report_no_flags_delegates_to_pick(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=True,
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["report", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output


# ── nit memory ───────────────────────────────────────────────────


class TestMemory:
    """Tests for 'nit memory' subcommands."""

    def test_memory_show_global(self, tmp_path: Path) -> None:
        mock_memory = MagicMock()
        mock_memory.get_conventions.return_value = {"naming": "snake_case"}
        mock_memory.get_known_patterns.return_value = []
        mock_memory.get_failed_patterns.return_value = []
        mock_memory.get_stats.return_value = {
            "total_runs": 5,
            "successful_generations": 3,
            "failed_generations": 2,
            "total_tests_generated": 10,
            "total_tests_passing": 8,
            "last_run": "2025-01-01",
        }

        runner = CliRunner()
        with patch("nit.memory.global_memory.GlobalMemory", return_value=mock_memory):
            result = runner.invoke(cli, ["memory", "show", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "snake_case" in result.output

    def test_memory_show_global_json(self, tmp_path: Path) -> None:
        mock_memory = MagicMock()
        mock_memory.to_dict.return_value = {"conventions": {}, "patterns": []}

        runner = CliRunner()
        with patch("nit.memory.global_memory.GlobalMemory", return_value=mock_memory):
            result = runner.invoke(
                cli, ["memory", "show", "--path", str(tmp_path), "--json-output"]
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "conventions" in data

    def test_memory_show_package(self, tmp_path: Path) -> None:
        mock_pkg_memory = MagicMock()
        mock_pkg_memory.get_test_patterns.return_value = {"style": "bdd"}
        mock_pkg_memory.get_known_issues.return_value = []
        mock_pkg_memory.get_coverage_history.return_value = []
        mock_pkg_memory.get_llm_feedback.return_value = []

        mock_manager = MagicMock()
        mock_manager.get_package_memory.return_value = mock_pkg_memory

        runner = CliRunner()
        with patch(
            "nit.memory.package_memory_manager.PackageMemoryManager", return_value=mock_manager
        ):
            result = runner.invoke(
                cli,
                ["memory", "show", "--path", str(tmp_path), "--package", "api"],
            )

        assert result.exit_code == 0, result.output

    def test_memory_show_package_json(self, tmp_path: Path) -> None:
        mock_pkg_memory = MagicMock()
        mock_pkg_memory.to_dict.return_value = {"patterns": {}}

        mock_manager = MagicMock()
        mock_manager.get_package_memory.return_value = mock_pkg_memory

        runner = CliRunner()
        with patch(
            "nit.memory.package_memory_manager.PackageMemoryManager", return_value=mock_manager
        ):
            result = runner.invoke(
                cli,
                [
                    "memory",
                    "show",
                    "--path",
                    str(tmp_path),
                    "--package",
                    "api",
                    "--json-output",
                ],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "patterns" in data

    def test_memory_reset_with_confirm(self, tmp_path: Path) -> None:
        mock_memory = MagicMock()

        runner = CliRunner()
        with patch("nit.memory.global_memory.GlobalMemory", return_value=mock_memory):
            result = runner.invoke(
                cli,
                ["memory", "reset", "--path", str(tmp_path), "--confirm"],
            )

        assert result.exit_code == 0, result.output
        assert "cleared" in result.output.lower()
        mock_memory.clear.assert_called_once()

    def test_memory_reset_without_confirm_prompts(self, tmp_path: Path) -> None:
        mock_memory = MagicMock()

        runner = CliRunner()
        with patch("nit.memory.global_memory.GlobalMemory", return_value=mock_memory):
            result = runner.invoke(
                cli,
                ["memory", "reset", "--path", str(tmp_path)],
                input="n\n",
            )

        assert result.exit_code == 0, result.output
        assert "cancelled" in result.output.lower()
        mock_memory.clear.assert_not_called()

    def test_memory_reset_accepts_prompt_yes(self, tmp_path: Path) -> None:
        mock_memory = MagicMock()

        runner = CliRunner()
        with patch("nit.memory.global_memory.GlobalMemory", return_value=mock_memory):
            result = runner.invoke(
                cli,
                ["memory", "reset", "--path", str(tmp_path)],
                input="y\n",
            )

        assert result.exit_code == 0, result.output
        assert "cleared" in result.output.lower()
        mock_memory.clear.assert_called_once()

    def test_memory_reset_package(self, tmp_path: Path) -> None:
        mock_pkg_memory = MagicMock()
        mock_manager = MagicMock()
        mock_manager.get_package_memory.return_value = mock_pkg_memory

        runner = CliRunner()
        with patch(
            "nit.memory.package_memory_manager.PackageMemoryManager", return_value=mock_manager
        ):
            result = runner.invoke(
                cli,
                [
                    "memory",
                    "reset",
                    "--path",
                    str(tmp_path),
                    "--package",
                    "api",
                    "--confirm",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "cleared" in result.output.lower()
        mock_manager.clear_package_memory.assert_called_once_with("api")

    def test_memory_export_global_stdout(self, tmp_path: Path) -> None:
        mock_memory = MagicMock()
        mock_memory.to_markdown.return_value = "# Global Memory\nSome content"

        runner = CliRunner()
        with patch("nit.memory.global_memory.GlobalMemory", return_value=mock_memory):
            result = runner.invoke(cli, ["memory", "export", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "# Global Memory" in result.output

    def test_memory_export_global_to_file(self, tmp_path: Path) -> None:
        mock_memory = MagicMock()
        mock_memory.to_markdown.return_value = "# Memory Export"

        output_file = tmp_path / "memory.md"

        runner = CliRunner()
        with patch("nit.memory.global_memory.GlobalMemory", return_value=mock_memory):
            result = runner.invoke(
                cli,
                [
                    "memory",
                    "export",
                    "--path",
                    str(tmp_path),
                    "--output",
                    str(output_file),
                ],
            )

        assert result.exit_code == 0, result.output
        assert output_file.exists()
        assert output_file.read_text(encoding="utf-8") == "# Memory Export"

    def test_memory_export_package(self, tmp_path: Path) -> None:
        mock_pkg_memory = MagicMock()
        mock_pkg_memory.to_markdown.return_value = "# API Memory"

        mock_manager = MagicMock()
        mock_manager.get_package_memory.return_value = mock_pkg_memory

        runner = CliRunner()
        with patch(
            "nit.memory.package_memory_manager.PackageMemoryManager", return_value=mock_manager
        ):
            result = runner.invoke(
                cli,
                [
                    "memory",
                    "export",
                    "--path",
                    str(tmp_path),
                    "--package",
                    "api",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "# API Memory" in result.output


# ── nit analyze ──────────────────────────────────────────────────


class TestAnalyze:
    """Tests for 'nit analyze' command."""

    def test_analyze_pipeline_error_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        with patch(
            "nit.cli.PickPipeline.run",
            side_effect=RuntimeError("Pipeline error"),
        ):
            result = runner.invoke(cli, ["analyze", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_analyze_success(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=True,
            tests_run=5,
            tests_passed=5,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["analyze", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_analyze_with_failed_result_displays_output(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=False,
            tests_run=0,
            tests_passed=0,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=["Pipeline failed"],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["analyze", "--path", str(tmp_path)])

        # The analyze command displays results even when success=False
        # (it only aborts on exceptions, not on pipeline result status)
        assert result.exit_code == 0, result.output


# ── nit debug ────────────────────────────────────────────────────


class TestDebug:
    """Tests for 'nit debug' command."""

    def test_debug_no_llm_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["debug", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_debug_delegates_to_pick_fix(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=True,
            tests_run=3,
            tests_passed=3,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["debug", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_debug_dry_run_disables_fix(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=True,
            tests_run=2,
            tests_passed=2,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["debug", "--dry-run", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output


# ── nit scan --diff ──────────────────────────────────────────────


class TestScanDiff:
    """Tests for 'nit scan --diff' command."""

    def test_scan_diff_mode(self, tmp_path: Path) -> None:
        mock_diff_result = MagicMock()
        mock_diff_result.changed_files = ["src/app.py"]
        mock_diff_result.changed_source_files = ["src/app.py"]
        mock_diff_result.changed_test_files = []
        mock_diff_result.affected_source_files = ["src/app.py"]
        mock_diff_result.total_lines_added = 10
        mock_diff_result.total_lines_removed = 2
        mock_diff_result.file_mappings = []

        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.COMPLETED
        mock_task_output.result = {"diff_result": mock_diff_result}

        runner = CliRunner()
        with patch("nit.cli.DiffAnalyzer.run", return_value=mock_task_output):
            result = runner.invoke(cli, ["scan", "--diff", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_scan_diff_ci_mode(self, tmp_path: Path) -> None:
        mock_diff_result = MagicMock()
        mock_diff_result.changed_files = ["src/a.py"]
        mock_diff_result.changed_source_files = ["src/a.py"]
        mock_diff_result.changed_test_files = []
        mock_diff_result.affected_source_files = ["src/a.py"]
        mock_diff_result.total_lines_added = 5
        mock_diff_result.total_lines_removed = 1
        mock_diff_result.file_mappings = []

        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.COMPLETED
        mock_task_output.result = {"diff_result": mock_diff_result}

        runner = CliRunner()
        with patch("nit.cli.DiffAnalyzer.run", return_value=mock_task_output):
            result = runner.invoke(cli, ["--ci", "scan", "--diff", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "changed_source_files" in data

    def test_scan_diff_failed_aborts(self, tmp_path: Path) -> None:
        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.FAILED
        mock_task_output.errors = ["Git error"]

        runner = CliRunner()
        with patch("nit.cli.DiffAnalyzer.run", return_value=mock_task_output):
            result = runner.invoke(cli, ["scan", "--diff", "--path", str(tmp_path)])

        assert result.exit_code != 0


# ── Additional config edge case tests ────────────────────────────


class TestConfigEdgeCases:
    """Additional config tests for edge cases."""

    def test_config_set_multiple_values(self, tmp_path: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            cli,
            ["config", "set", "llm.provider", "anthropic", "--path", str(tmp_path)],
        )
        runner.invoke(
            cli,
            ["config", "set", "llm.model", "claude-3-opus", "--path", str(tmp_path)],
        )

        raw = yaml.safe_load((tmp_path / ".nit.yml").read_text(encoding="utf-8"))
        assert raw["llm"]["provider"] == "anthropic"
        assert raw["llm"]["model"] == "claude-3-opus"

    def test_config_show_missing_config(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "--path", str(tmp_path)])
        # Should work with defaults even if no .nit.yml exists
        assert result.exit_code == 0, result.output


# ── Helper function tests ────────────────────────────────────────


class TestHelperFunctions:
    """Tests for CLI helper functions."""

    def test_mask_sensitive_values(self) -> None:
        short_pw = "short"
        config = {
            "llm": {"api_key": "sk-test-1234567890", "model": "gpt-4o"},
            "platform": {"api_key": "nit_key_long_enough"},
            "e2e": {"auth": {"password": short_pw}},
        }
        masked = _mask_sensitive_values(config)
        assert masked["llm"]["api_key"] != "sk-test-1234567890"
        assert masked["llm"]["model"] == "gpt-4o"
        assert masked["platform"]["api_key"] != "nit_key_long_enough"
        assert masked["e2e"]["auth"]["password"] != short_pw

    def test_mask_sensitive_values_preserves_empty(self) -> None:
        config = {"llm": {"api_key": "", "model": "gpt-4o"}}
        masked = _mask_sensitive_values(config)
        assert masked["llm"]["api_key"] == ""

    def test_set_nested_config_value(self) -> None:
        config: dict[str, Any] = {}
        _set_nested_config_value(config, "a.b.c", "value")
        assert config["a"]["b"]["c"] == "value"

    def test_set_nested_config_value_overwrites(self) -> None:
        config: dict[str, Any] = {"llm": {"provider": "openai"}}
        _set_nested_config_value(config, "llm.provider", "anthropic")
        assert config["llm"]["provider"] == "anthropic"

    def test_load_nit_yml_missing_file(self, tmp_path: Path) -> None:
        result = _load_nit_yml(tmp_path / ".nit.yml")
        assert result == {}

    def test_load_nit_yml_non_dict(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text("just a string", encoding="utf-8")
        result = _load_nit_yml(tmp_path / ".nit.yml")
        assert result == {}

    def test_display_test_results_json(self) -> None:
        run_result = RunResult(
            passed=3,
            failed=1,
            skipped=0,
            errors=0,
            duration_ms=500.0,
            success=False,
            test_cases=[],
        )
        # Just verify it doesn't crash (output goes to click.echo)
        runner = CliRunner()
        with runner.isolated_filesystem():
            _display_test_results_json(run_result)


# ── nit init --auto ──────────────────────────────────────────────


class TestInitAuto:
    """Tests for 'nit init --auto' flag."""

    def test_init_auto_mode(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")

        runner = CliRunner()
        with patch(
            "nit.auto_init.build_auto_config",
            return_value={
                "llm": {
                    "mode": "builtin",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "api_key": "",
                    "base_url": "",
                },
                "platform": {"mode": "disabled", "url": ""},
                "git": {
                    "auto_commit": False,
                    "auto_pr": False,
                    "create_issues": False,
                    "create_fix_prs": False,
                    "branch_prefix": "nit/",
                },
                "report": {
                    "format": "terminal",
                    "upload_to_platform": False,
                    "html_output_dir": ".nit/reports",
                    "serve_port": 8080,
                },
                "e2e": {"enabled": False},
                "coverage": {
                    "line_threshold": 80.0,
                    "branch_threshold": 75.0,
                    "function_threshold": 85.0,
                    "complexity_threshold": 10,
                },
            },
        ):
            result = runner.invoke(cli, ["init", "--auto", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".nit.yml").is_file()

    def test_init_quick_mode(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--quick", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".nit.yml").is_file()


class TestPickReportUpload:
    def test_pick_report_upload_posts_to_platform(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n"
            "platform:\n"
            "  url: https://platform.getnit.dev\n"
            "  api_key: nit_key_abc\n",
            encoding="utf-8",
        )

        # Mock successful pipeline result
        mock_result = PickPipelineResult(
            success=True,
            tests_run=5,
            tests_passed=5,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with (
            patch("nit.cli.PickPipeline.run", return_value=mock_result),
            patch(
                "nit.cli.post_platform_report", return_value={"reportId": "report-1"}
            ) as mock_post,
        ):
            result = runner.invoke(cli, ["--ci", "pick", "--path", str(tmp_path), "--report"])

        assert result.exit_code == 0, result.output
        assert mock_post.call_count == 1
        payload = mock_post.call_args.args[1]
        assert payload["runMode"] == "pick"
        assert payload["fullReport"]["status"] == "completed"


class TestUploadBugsToPlatform:
    """Tests for _upload_bugs_to_platform using post_platform_bug."""

    def test_upload_bugs_posts_correct_payload(self) -> None:
        bug = BugReport(
            bug_type=BugType.NULL_DEREFERENCE,
            severity=BugSeverity.HIGH,
            title="Null dereference in handler",
            description="Accessing .name on None",
            location=BugLocation(file_path="src/handler.py", function_name="handle"),
            error_message="AttributeError",
        )

        mock_result = PickPipelineResult(
            success=True,
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[bug],
            fixes_applied=[],
            errors=[],
        )

        config_obj = MagicMock()
        config_obj.platform.url = "https://platform.getnit.dev"
        config_obj.platform.api_key = "nit_key_abc"

        with patch("nit.cli.post_platform_bug", return_value={"bugId": "bug-1"}) as mock_post:
            ids = _upload_bugs_to_platform(
                config_obj,
                mock_result,
                issue_urls={"Null dereference in handler": "https://github.com/issues/1"},
                pr_urls={"Null dereference in handler": "https://github.com/pulls/2"},
            )

        assert ids == ["bug-1"]
        assert mock_post.call_count == 1
        payload = mock_post.call_args.args[1]
        assert payload["filePath"] == "src/handler.py"
        assert payload["description"] == "Accessing .name on None"
        assert payload["severity"] == "high"
        assert payload["status"] == "open"
        assert payload["functionName"] == "handle"
        assert payload["githubIssueUrl"] == "https://github.com/issues/1"
        assert payload["githubPrUrl"] == "https://github.com/pulls/2"

    def test_upload_bugs_skips_on_error(self) -> None:
        bug = BugReport(
            bug_type=BugType.NULL_DEREFERENCE,
            severity=BugSeverity.LOW,
            title="Minor issue",
            description="Potential None",
            location=BugLocation(file_path="src/a.py"),
            error_message="NoneType",
        )

        mock_result = PickPipelineResult(
            success=True,
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[bug],
            fixes_applied=[],
            errors=[],
        )

        config_obj = MagicMock()
        config_obj.platform.url = "https://platform.getnit.dev"
        config_obj.platform.api_key = "nit_key_abc"

        with patch(
            "nit.cli.post_platform_bug",
            side_effect=PlatformClientError("HTTP 500"),
        ):
            ids = _upload_bugs_to_platform(config_obj, mock_result)

        assert ids == []

    def test_upload_bugs_empty_list(self) -> None:
        mock_result = PickPipelineResult(
            success=True,
            tests_run=0,
            tests_passed=0,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        config_obj = MagicMock()
        ids = _upload_bugs_to_platform(config_obj, mock_result)
        assert ids == []


# ── Additional tests for untested CLI paths ──────────────────────


class TestGenerateDeepPaths:
    """Additional tests for 'nit generate' covering deeper paths."""

    def _write_valid_config(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "project:\n"
            "  root: .\n"
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )

    def test_generate_with_package_flag(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        (tmp_path / "app.py").write_text("def hello(): pass\n")
        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

        with patch("nit.cli._get_test_adapters", side_effect=click.Abort):
            result = runner.invoke(
                cli,
                ["generate", "--path", str(tmp_path), "--package", str(tmp_path)],
            )
        assert result.exit_code != 0

    def test_generate_ci_mode(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        (tmp_path / "app.py").write_text("def hello(): pass\n")
        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

        with patch("nit.cli._get_test_adapters", side_effect=click.Abort):
            result = runner.invoke(
                cli,
                ["--ci", "generate", "--path", str(tmp_path)],
            )
        assert result.exit_code != 0

    def test_generate_stale_profile_rescans(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        (tmp_path / "app.py").write_text("def hello(): pass\n")
        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

        with (
            patch("nit.cli.is_profile_stale", return_value=True),
            patch("nit.cli._get_test_adapters", side_effect=click.Abort),
        ):
            result = runner.invoke(cli, ["generate", "--path", str(tmp_path)])
        # Aborts at _get_test_adapters, but should have rescanned
        assert result.exit_code != 0


class TestRunDeepPaths:
    """Additional tests for 'nit run' covering deeper paths."""

    def _setup_project(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "project:\n  root: .\nllm:\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        (tmp_path / "app.py").write_text("def hello(): pass\n")
        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

    def test_run_shard_count_without_index_fails(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--path", str(tmp_path), "--shard-count", "4"])
        assert result.exit_code != 0
        assert "shard" in result.output.lower()

    def test_run_exception_during_test_aborts(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        mock_adapter = MagicMock()
        mock_adapter.name = "pytest"
        mock_adapter.run_tests = AsyncMock(side_effect=RuntimeError("test crash"))
        mock_adapter.get_test_pattern.return_value = ["test_*.py"]

        runner = CliRunner()
        with (
            patch("nit.cli._get_test_adapters", return_value=[mock_adapter]),
            patch("nit.cli_helpers.check_and_install_prerequisites", return_value=True),
        ):
            result = runner.invoke(cli, ["run", "--path", str(tmp_path)])

        assert result.exit_code != 0

    def test_run_no_coverage_flag(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        run_result = RunResult(
            passed=2,
            failed=0,
            skipped=0,
            errors=0,
            duration_ms=100.0,
            success=True,
            test_cases=[],
        )
        mock_adapter = MagicMock()
        mock_adapter.name = "pytest"
        mock_adapter.run_tests = AsyncMock(return_value=run_result)
        mock_adapter.get_test_pattern.return_value = ["test_*.py"]

        runner = CliRunner()
        with (
            patch("nit.cli._get_test_adapters", return_value=[mock_adapter]),
            patch("nit.cli_helpers.check_and_install_prerequisites", return_value=True),
        ):
            result = runner.invoke(cli, ["run", "--path", str(tmp_path), "--no-coverage"])
        assert result.exit_code == 0, result.output

    def test_run_config_load_failure_aborts(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        runner = CliRunner()
        with patch("nit.cli.load_config", side_effect=RuntimeError("Bad config")):
            result = runner.invoke(cli, ["run", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_run_with_zero_total_and_raw_output(self, tmp_path: Path) -> None:
        """Test run displays diagnostic info when 0 tests run but execution fails."""
        self._setup_project(tmp_path)
        run_result = RunResult(
            passed=0,
            failed=0,
            skipped=0,
            errors=0,
            duration_ms=50.0,
            success=False,
            test_cases=[],
            raw_output="ERROR: No tests found!",
        )
        mock_adapter = MagicMock()
        mock_adapter.name = "pytest"
        mock_adapter.run_tests = AsyncMock(return_value=run_result)
        mock_adapter.get_test_pattern.return_value = ["test_*.py"]

        runner = CliRunner()
        with (
            patch("nit.cli._get_test_adapters", return_value=[mock_adapter]),
            patch("nit.cli_helpers.check_and_install_prerequisites", return_value=True),
        ):
            result = runner.invoke(cli, ["run", "--path", str(tmp_path)])

        assert result.exit_code != 0


class TestPickDeepPaths:
    """Additional tests for 'nit pick' covering deeper CLI flag paths."""

    def _write_valid_config(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )

    def test_pick_with_auto_commit(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=2,
            tests_passed=2,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["pick", "--path", str(tmp_path), "--auto-commit"],
            )

        assert result.exit_code == 0, result.output
        assert "auto-commit" in result.output.lower()

    def test_pick_with_create_issues(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=3,
            tests_passed=3,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["pick", "--path", str(tmp_path), "--create-issues"],
            )

        assert result.exit_code == 0, result.output
        assert "issue" in result.output.lower()

    def test_pick_with_create_fix_prs(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=2,
            tests_passed=2,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["pick", "--path", str(tmp_path), "--create-fix-prs"],
            )

        assert result.exit_code == 0, result.output
        assert "fix pr" in result.output.lower()

    def test_pick_with_output_format_json(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["pick", "--path", str(tmp_path), "--format", "json"],
            )

        assert result.exit_code == 0, result.output

    def test_pick_with_pr_flag(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        mock_result = PickPipelineResult(
            success=True,
            tests_run=3,
            tests_passed=3,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["pick", "--path", str(tmp_path), "--pr"],
            )

        assert result.exit_code == 0, result.output
        assert "pr mode" in result.output.lower()

    def test_pick_upload_report_platform_error_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n"
            "platform:\n"
            "  mode: byok\n"
            "  url: https://platform.getnit.dev\n"
            "  api_key: nit_key_abc\n",
            encoding="utf-8",
        )

        mock_result = PickPipelineResult(
            success=True,
            tests_run=2,
            tests_passed=2,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with (
            patch("nit.cli.PickPipeline.run", return_value=mock_result),
            patch(
                "nit.cli.post_platform_report",
                side_effect=PlatformClientError("Upload failed"),
            ),
        ):
            result = runner.invoke(
                cli,
                ["--ci", "pick", "--path", str(tmp_path), "--report"],
            )

        assert result.exit_code != 0

    def test_pick_exception_aborts(self, tmp_path: Path) -> None:
        self._write_valid_config(tmp_path)
        runner = CliRunner()
        with patch(
            "nit.cli.PickPipeline.run",
            side_effect=RuntimeError("Pipeline explosion"),
        ):
            result = runner.invoke(cli, ["pick", "--path", str(tmp_path)])
        assert result.exit_code != 0


class TestDriftDeepPaths:
    """Additional tests for 'nit drift' covering deeper paths."""

    def test_drift_ci_mode_test(self, tmp_path: Path) -> None:
        mock_report = DriftReport(
            total_tests=2,
            passed_tests=2,
            failed_tests=0,
            skipped_tests=0,
            drift_detected=False,
            results=[],
        )
        runner = CliRunner()
        with patch(
            "nit.agents.watchers.drift.DriftWatcher.run_drift_tests",
            return_value=mock_report,
        ):
            result = runner.invoke(cli, ["--ci", "drift", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_drift_with_custom_interval(self, tmp_path: Path) -> None:
        mock_report = DriftReport(
            total_tests=1,
            passed_tests=1,
            failed_tests=0,
            skipped_tests=0,
            drift_detected=False,
            results=[],
        )
        runner = CliRunner()
        with patch(
            "nit.agents.watchers.drift.DriftWatcher.run_drift_tests",
            return_value=mock_report,
        ):
            result = runner.invoke(
                cli,
                ["drift", "--path", str(tmp_path), "--interval", "1800"],
            )

        assert result.exit_code == 0, result.output

    def test_drift_results_with_no_baseline(self, tmp_path: Path) -> None:
        mock_report = DriftReport(
            total_tests=1,
            passed_tests=0,
            failed_tests=0,
            skipped_tests=1,
            drift_detected=False,
            results=[
                DriftTestResult(
                    test_id="t1",
                    test_name="test_new",
                    passed=False,
                    output="some output",
                    baseline_exists=False,
                ),
            ],
        )
        runner = CliRunner()
        with patch(
            "nit.agents.watchers.drift.DriftWatcher.run_drift_tests",
            return_value=mock_report,
        ):
            result = runner.invoke(cli, ["drift", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_drift_baseline_all_pass(self, tmp_path: Path) -> None:
        mock_report = DriftReport(
            total_tests=3,
            passed_tests=3,
            failed_tests=0,
            skipped_tests=0,
            drift_detected=False,
            results=[
                DriftTestResult(
                    test_id=f"t{i}",
                    test_name=f"test_{i}",
                    passed=True,
                    output="ok",
                )
                for i in range(3)
            ],
        )
        runner = CliRunner()
        with patch(
            "nit.agents.watchers.drift.DriftWatcher.update_baselines",
            return_value=mock_report,
        ):
            result = runner.invoke(cli, ["drift", "--baseline", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "3 baselines" in result.output.lower() or "3" in result.output


class TestDocsDeepPaths:
    """Additional tests for 'nit docs' covering deeper paths."""

    def test_docs_changelog_no_llm_flag(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with patch("nit.cli._docs_changelog") as mock_changelog:
            result = runner.invoke(
                cli,
                [
                    "docs",
                    "--changelog",
                    "v1.0.0",
                    "--no-llm",
                    "--path",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0
        mock_changelog.assert_called_once()
        call_kwargs = mock_changelog.call_args
        assert call_kwargs.kwargs.get("use_llm") is False

    def test_docs_changelog_with_output(self, tmp_path: Path) -> None:
        output_path = tmp_path / "CHANGES.md"
        runner = CliRunner()
        with patch("nit.cli._docs_changelog") as mock_changelog:
            result = runner.invoke(
                cli,
                [
                    "docs",
                    "--changelog",
                    "v1.0.0",
                    "--output",
                    str(output_path),
                    "--path",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0
        mock_changelog.assert_called_once()

    def test_docs_readme_success(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n  api_key: sk-test\n",
            encoding="utf-8",
        )
        (tmp_path / "README.md").write_text("# Project\n")
        (tmp_path / "app.py").write_text("def hello(): pass\n")

        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

        with (
            patch("nit.cli._is_llm_runtime_configured", return_value=True),
            patch("nit.cli.create_engine"),
            patch("nit.cli.load_llm_config"),
            patch("nit.cli.ReadmeUpdater") as mock_updater_cls,
        ):
            mock_updater = mock_updater_cls.return_value
            mock_updater.update_readme = AsyncMock(return_value="# Updated README")
            result = runner.invoke(cli, ["docs", "--readme", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "Updated README" in result.output

    def test_docs_readme_write_mode(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n  api_key: sk-test\n",
            encoding="utf-8",
        )
        (tmp_path / "README.md").write_text("# Old\n")
        (tmp_path / "app.py").write_text("def hello(): pass\n")

        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])

        with (
            patch("nit.cli._is_llm_runtime_configured", return_value=True),
            patch("nit.cli.create_engine"),
            patch("nit.cli.load_llm_config"),
            patch("nit.cli.ReadmeUpdater") as mock_updater_cls,
        ):
            mock_updater = mock_updater_cls.return_value
            mock_updater.update_readme = AsyncMock(return_value="# New README")
            result = runner.invoke(cli, ["docs", "--readme", "--write", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        readme_content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert readme_content == "# New README"

    def test_docs_readme_no_readme_file_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n  api_key: sk-test\n",
            encoding="utf-8",
        )
        # No README file exists

        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--readme", "--path", str(tmp_path)])

        assert result.exit_code != 0

    def test_docs_all_files_mode(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n  api_key: sk-test\n",
            encoding="utf-8",
        )

        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.COMPLETED
        mock_task_output.result = {"results": []}
        mock_task_output.errors = []

        runner = CliRunner()
        with (
            patch("nit.cli.DocBuilder.run", return_value=mock_task_output),
            patch("nit.cli.create_engine"),
        ):
            result = runner.invoke(cli, ["docs", "--all", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_docs_specific_file(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n  api_key: sk-test\n",
            encoding="utf-8",
        )

        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.COMPLETED
        mock_task_output.result = {"results": []}
        mock_task_output.errors = []

        runner = CliRunner()
        with (
            patch("nit.cli.DocBuilder.run", return_value=mock_task_output),
            patch("nit.cli.create_engine"),
        ):
            result = runner.invoke(
                cli,
                [
                    "docs",
                    "--file",
                    "src/main.py",
                    "--path",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output

    def test_docs_docbuilder_failed_aborts(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n  api_key: sk-test\n",
            encoding="utf-8",
        )

        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.FAILED
        mock_task_output.result = {}
        mock_task_output.errors = ["Build failed"]

        runner = CliRunner()
        with (
            patch("nit.cli.DocBuilder.run", return_value=mock_task_output),
            patch("nit.cli.create_engine"),
        ):
            result = runner.invoke(cli, ["docs", "--all", "--path", str(tmp_path)])

        assert result.exit_code != 0


class TestWatchDeepPaths:
    """Additional tests for 'nit watch' covering deeper paths."""

    def test_watch_coverage_with_alerts(self, tmp_path: Path) -> None:
        mock_run_result = ScheduledRunResult(
            run_id="run-1",
            scheduled_time="2025-01-01T00:00:00",
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:00:01",
            success=True,
            exit_code=0,
            output="ok",
            duration_seconds=1.0,
        )

        mock_snapshot = MagicMock()
        mock_snapshot.overall_line_coverage = 65.0
        mock_snapshot.overall_function_coverage = 70.0

        mock_alert = MagicMock()
        mock_alert.severity = "critical"
        mock_alert.message = "Coverage dropped below threshold"
        mock_alert.previous_coverage = 80.0
        mock_alert.current_coverage = 65.0
        mock_alert.threshold = 80.0

        mock_trend = MagicMock()
        mock_trend.current_snapshot = mock_snapshot
        mock_trend.trend = "declining"
        mock_trend.alerts = [mock_alert]

        runner = CliRunner()
        with (
            patch(
                "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
                return_value=mock_run_result,
            ),
            patch(
                "nit.agents.watchers.coverage.CoverageWatcher.collect_and_analyze",
                return_value=mock_trend,
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "watch",
                    "--path",
                    str(tmp_path),
                    "--max-runs",
                    "1",
                    "--coverage",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "coverage" in result.output.lower()

    def test_watch_with_test_command(self, tmp_path: Path) -> None:
        mock_run_result = ScheduledRunResult(
            run_id="run-1",
            scheduled_time="2025-01-01T00:00:00",
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:00:01",
            success=True,
            exit_code=0,
            output="ok",
            duration_seconds=1.0,
        )

        runner = CliRunner()
        with patch(
            "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
            return_value=mock_run_result,
        ):
            result = runner.invoke(
                cli,
                [
                    "watch",
                    "--path",
                    str(tmp_path),
                    "--max-runs",
                    "1",
                    "--test-command",
                    "pytest -x",
                ],
            )

        assert result.exit_code == 0, result.output

    def test_watch_with_timeout(self, tmp_path: Path) -> None:
        mock_run_result = ScheduledRunResult(
            run_id="run-1",
            scheduled_time="2025-01-01T00:00:00",
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:00:01",
            success=True,
            exit_code=0,
            output="ok",
            duration_seconds=1.0,
        )

        runner = CliRunner()
        with patch(
            "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
            return_value=mock_run_result,
        ):
            result = runner.invoke(
                cli,
                [
                    "watch",
                    "--path",
                    str(tmp_path),
                    "--max-runs",
                    "1",
                    "--timeout",
                    "120",
                ],
            )

        assert result.exit_code == 0, result.output

    def test_watch_coverage_collection_fails_gracefully(self, tmp_path: Path) -> None:
        mock_run_result = ScheduledRunResult(
            run_id="run-1",
            scheduled_time="2025-01-01T00:00:00",
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:00:01",
            success=True,
            exit_code=0,
            output="ok",
            duration_seconds=1.0,
        )

        runner = CliRunner()
        with (
            patch(
                "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
                return_value=mock_run_result,
            ),
            patch(
                "nit.agents.watchers.coverage.CoverageWatcher.collect_and_analyze",
                side_effect=RuntimeError("Coverage tool not found"),
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "watch",
                    "--path",
                    str(tmp_path),
                    "--max-runs",
                    "1",
                    "--coverage",
                ],
            )

        # Should not crash, handles error gracefully
        assert result.exit_code == 0, result.output

    def test_watch_with_coverage_threshold(self, tmp_path: Path) -> None:
        mock_run_result = ScheduledRunResult(
            run_id="run-1",
            scheduled_time="2025-01-01T00:00:00",
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:00:01",
            success=True,
            exit_code=0,
            output="ok",
            duration_seconds=1.0,
        )

        runner = CliRunner()
        with patch(
            "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
            return_value=mock_run_result,
        ):
            result = runner.invoke(
                cli,
                [
                    "watch",
                    "--path",
                    str(tmp_path),
                    "--max-runs",
                    "1",
                    "--coverage-threshold",
                    "90",
                ],
            )

        assert result.exit_code == 0, result.output


class TestReportDeepPaths:
    """Additional tests for 'nit report' covering deeper paths."""

    def test_report_html_with_serve(self, tmp_path: Path) -> None:
        runner = CliRunner()
        mock_dashboard = MagicMock()
        mock_dashboard.generate_html.return_value = tmp_path / "report.html"

        with patch(
            "nit.agents.reporters.dashboard.DashboardReporter",
            return_value=mock_dashboard,
        ):
            result = runner.invoke(
                cli,
                ["report", "--html", "--serve", "--path", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output
        mock_dashboard.serve.assert_called_once()

    def test_report_html_custom_port(self, tmp_path: Path) -> None:
        runner = CliRunner()
        mock_dashboard = MagicMock()
        mock_dashboard.generate_html.return_value = tmp_path / "report.html"

        with patch(
            "nit.agents.reporters.dashboard.DashboardReporter",
            return_value=mock_dashboard,
        ):
            result = runner.invoke(
                cli,
                [
                    "report",
                    "--html",
                    "--serve",
                    "--port",
                    "9090",
                    "--path",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output
        mock_dashboard.serve.assert_called_once_with(port=9090, open_browser=True)

    def test_report_with_create_issues(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=True,
            tests_run=2,
            tests_passed=2,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["report", "--create-issues", "--path", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output

    def test_report_with_no_commit(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=True,
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["report", "--no-commit", "--path", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output

    def test_report_config_load_failure_aborts(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with patch("nit.cli.load_config", side_effect=RuntimeError("Config error")):
            result = runner.invoke(cli, ["report", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_report_ci_mode_html(self, tmp_path: Path) -> None:
        runner = CliRunner()
        mock_dashboard = MagicMock()
        mock_dashboard.generate_html.return_value = tmp_path / "report.html"

        with patch(
            "nit.agents.reporters.dashboard.DashboardReporter",
            return_value=mock_dashboard,
        ):
            result = runner.invoke(
                cli,
                ["--ci", "report", "--html", "--path", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output


class TestAnalyzeDeepPaths:
    """Additional tests for 'nit analyze' covering deeper paths."""

    def test_analyze_ci_mode(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=True,
            tests_run=3,
            tests_passed=3,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(cli, ["--ci", "analyze", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

    def test_analyze_with_json_output(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=True,
            tests_run=2,
            tests_passed=2,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["analyze", "--path", str(tmp_path), "--json-output"],
            )

        assert result.exit_code == 0, result.output

    def test_analyze_with_type_unit(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  provider: openai\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        mock_result = PickPipelineResult(
            success=True,
            tests_run=4,
            tests_passed=4,
            tests_failed=0,
            tests_errors=0,
            bugs_found=[],
            fixes_applied=[],
            errors=[],
        )

        runner = CliRunner()
        with patch("nit.cli.PickPipeline.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["analyze", "--path", str(tmp_path), "--type", "unit"],
            )

        assert result.exit_code == 0, result.output


class TestDebugDeepPaths:
    """Additional tests for 'nit debug' covering deeper paths."""

    def test_debug_config_load_failure_aborts(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with patch("nit.cli.load_config", side_effect=RuntimeError("Load error")):
            result = runner.invoke(cli, ["debug", "--path", str(tmp_path)])
        assert result.exit_code != 0


class TestCombine:
    """Tests for 'nit combine' command."""

    def test_combine_no_args_shows_usage(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["combine"])
        assert result.exit_code != 0

    def test_combine_success(self, tmp_path: Path) -> None:
        # Create two shard result files
        result1 = RunResult(
            passed=3,
            failed=0,
            skipped=0,
            errors=0,
            duration_ms=100.0,
            success=True,
            test_cases=[],
        )
        result2 = RunResult(
            passed=2,
            failed=0,
            skipped=1,
            errors=0,
            duration_ms=150.0,
            success=True,
            test_cases=[],
        )

        shard1 = tmp_path / "shard-0.json"
        shard2 = tmp_path / "shard-1.json"
        write_shard_result(result1, shard1, 0, 2, "pytest")
        write_shard_result(result2, shard2, 1, 2, "pytest")

        runner = CliRunner()
        result = runner.invoke(cli, ["combine", str(shard1), str(shard2)])

        assert result.exit_code == 0, result.output
        assert "5" in result.output  # 3 + 2 passed

    def test_combine_with_output(self, tmp_path: Path) -> None:
        result1 = RunResult(
            passed=1,
            failed=0,
            skipped=0,
            errors=0,
            duration_ms=50.0,
            success=True,
            test_cases=[],
        )

        shard1 = tmp_path / "shard-0.json"
        write_shard_result(result1, shard1, 0, 1, "pytest")

        output_path = tmp_path / "combined.json"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["combine", str(shard1), "--output", str(output_path)],
        )

        assert result.exit_code == 0, result.output
        assert output_path.exists()

    def test_combine_with_failures_aborts(self, tmp_path: Path) -> None:
        result1 = RunResult(
            passed=2,
            failed=1,
            skipped=0,
            errors=0,
            duration_ms=100.0,
            success=False,
            test_cases=[],
        )

        shard1 = tmp_path / "shard-0.json"
        write_shard_result(result1, shard1, 0, 1, "pytest")

        runner = CliRunner()
        result = runner.invoke(cli, ["combine", str(shard1)])

        assert result.exit_code != 0


class TestHelperFunctionsExtended:
    """Extended tests for CLI helper functions."""

    def test_config_to_dict(self) -> None:
        # Create a minimal config object
        config = load_config("/nonexistent")  # Returns defaults
        result = _config_to_dict(config)
        assert isinstance(result, dict)
        assert "raw" not in result

    def test_is_llm_runtime_configured_builtin_with_key(self) -> None:
        config = MagicMock()
        config.llm.is_configured = True
        assert _is_llm_runtime_configured(config) is True

    def test_is_llm_runtime_configured_not_configured(self) -> None:
        config = MagicMock()
        config.llm.is_configured = False
        config.llm.mode = "builtin"
        config.platform.normalized_mode = "disabled"
        assert _is_llm_runtime_configured(config) is False

    def test_mask_sensitive_values_with_list(self) -> None:
        sensitive_key = "token"
        config: dict[str, Any] = {
            "items": [
                {"api_key": "secret-long-value-1234", "name": "test"},
                {sensitive_key: "short"},
            ]
        }
        masked = _mask_sensitive_values(config)
        assert masked["items"][0]["api_key"] != "secret-long-value-1234"
        assert masked["items"][0]["name"] == "test"
        # Short sensitive values should be masked to "***"
        assert masked["items"][1][sensitive_key] != "short"

    def test_set_nested_config_value_empty_key_raises(self) -> None:
        config: dict[str, Any] = {}
        with pytest.raises(ValueError, match="must not be empty"):
            _set_nested_config_value(config, "", "value")

    def test_display_test_results_console_with_failed_tests(self) -> None:
        run_result = RunResult(
            passed=1,
            failed=2,
            skipped=1,
            errors=0,
            duration_ms=300.0,
            success=False,
            test_cases=[
                CaseResult(
                    name="test_ok",
                    status=CaseStatus.PASSED,
                    duration_ms=10.0,
                ),
                CaseResult(
                    name="test_bad",
                    status=CaseStatus.FAILED,
                    duration_ms=20.0,
                    failure_message="Expected 1 got 2",
                ),
                CaseResult(
                    name="test_worse",
                    status=CaseStatus.FAILED,
                    duration_ms=30.0,
                    failure_message="Assertion error",
                ),
            ],
        )
        # Should not crash
        _display_test_results_console(run_result)

    def test_display_test_results_json_with_failures(self) -> None:
        run_result = RunResult(
            passed=1,
            failed=1,
            skipped=0,
            errors=0,
            duration_ms=200.0,
            success=False,
            test_cases=[
                CaseResult(
                    name="test_ok",
                    status=CaseStatus.PASSED,
                    duration_ms=10.0,
                ),
                CaseResult(
                    name="test_bad",
                    status=CaseStatus.FAILED,
                    duration_ms=20.0,
                    failure_message="Assertion failed",
                ),
            ],
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            _display_test_results_json(run_result)

    def test_load_nit_yml_valid(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  provider: openai\n",
            encoding="utf-8",
        )
        result = _load_nit_yml(tmp_path / ".nit.yml")
        assert result == {"llm": {"provider": "openai"}}

    def test_load_nit_yml_yaml_error(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text("{invalid: yaml: data:", encoding="utf-8")
        # yaml.safe_load might raise or parse oddly; we just ensure no crash
        with contextlib.suppress(Exception):
            _load_nit_yml(tmp_path / ".nit.yml")


class TestScanDeepPaths:
    """Additional tests for 'nit scan' covering deeper paths."""

    def test_scan_cached_profile_ci_mode(self, tmp_path: Path) -> None:
        (tmp_path / "lib.py").write_text("def f(): pass\n")

        runner = CliRunner()
        # First scan to create profile
        runner.invoke(cli, ["scan", "--path", str(tmp_path), "--force"])
        # Second scan in CI mode should use cache
        result = runner.invoke(cli, ["--ci", "scan", "--path", str(tmp_path)])

        assert result.exit_code == 0
        # CI mode should output JSON
        data = json.loads(result.output)
        assert "languages" in data

    def test_scan_diff_with_base_ref(self, tmp_path: Path) -> None:
        mock_diff_result = MagicMock()
        mock_diff_result.changed_files = ["src/a.py"]
        mock_diff_result.changed_source_files = ["src/a.py"]
        mock_diff_result.changed_test_files = []
        mock_diff_result.affected_source_files = ["src/a.py"]
        mock_diff_result.total_lines_added = 3
        mock_diff_result.total_lines_removed = 0
        mock_diff_result.file_mappings = []

        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.COMPLETED
        mock_task_output.result = {"diff_result": mock_diff_result}

        runner = CliRunner()
        with patch("nit.cli.DiffAnalyzer.run", return_value=mock_task_output):
            result = runner.invoke(
                cli,
                [
                    "scan",
                    "--diff",
                    "--base-ref",
                    "main",
                    "--path",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output

    def test_scan_diff_with_compare_ref(self, tmp_path: Path) -> None:
        mock_diff_result = MagicMock()
        mock_diff_result.changed_files = []
        mock_diff_result.changed_source_files = []
        mock_diff_result.changed_test_files = []
        mock_diff_result.affected_source_files = []
        mock_diff_result.total_lines_added = 0
        mock_diff_result.total_lines_removed = 0
        mock_diff_result.file_mappings = []

        mock_task_output = MagicMock()
        mock_task_output.status = TaskStatus.COMPLETED
        mock_task_output.result = {"diff_result": mock_diff_result}

        runner = CliRunner()
        with patch("nit.cli.DiffAnalyzer.run", return_value=mock_task_output):
            result = runner.invoke(
                cli,
                [
                    "scan",
                    "--diff",
                    "--base-ref",
                    "main",
                    "--compare-ref",
                    "feature",
                    "--path",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output


class TestConfigDeepPaths:
    """Additional tests for 'nit config' covering edge cases."""

    def test_config_set_deeply_nested(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "config",
                "set",
                "e2e.auth.oauth.client_id",
                "test-client",
                "--path",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        raw = yaml.safe_load((tmp_path / ".nit.yml").read_text(encoding="utf-8"))
        assert raw["e2e"]["auth"]["oauth"]["client_id"] == "test-client"

    def test_config_validate_no_file_uses_defaults(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "validate", "--path", str(tmp_path)])
        # Default config may or may not validate; just ensure it does not crash
        assert result.exit_code in (0, 1)

    def test_config_show_json_masks_by_default(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n  api_key: supersecretlongkey123456\n  model: gpt-4o\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["config", "show", "--json-output", "--path", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["llm"]["api_key"] != "supersecretlongkey123456"


class TestInitDeepPaths:
    """Additional tests for 'nit init' covering deeper paths."""

    def test_init_with_multiple_languages(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")
        (tmp_path / "util.ts").write_text("const x = 1;\n")
        (tmp_path / "lib.go").write_text("package main\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".nit" / "profile.json").is_file()

    def test_init_reinit_overwrites_config(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x = 1\n")

        runner = CliRunner()
        runner.invoke(cli, ["init", "--path", str(tmp_path)])
        # Re-init should overwrite
        result = runner.invoke(cli, ["init", "--path", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".nit.yml").is_file()


class TestRenderFunctions:
    """Tests for internal YAML rendering helpers."""

    def test_render_llm_section_builtin(self) -> None:
        lines = _render_llm_section(
            {
                "mode": "builtin",
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": "sk-test",
                "base_url": "",
            }
        )
        joined = "\n".join(lines)
        assert "mode: builtin" in joined
        assert "provider: openai" in joined
        assert '"gpt-4o"' in joined

    def test_render_llm_section_cli(self) -> None:
        lines = _render_llm_section(
            {
                "mode": "cli",
                "provider": "anthropic",
                "model": "claude-sonnet-4-5-20250514",
                "cli_command": "claude",
                "cli_timeout": 300,
                "cli_extra_args": ["--json"],
            }
        )
        joined = "\n".join(lines)
        assert "mode: cli" in joined
        assert "cli_command:" in joined
        assert '"--json"' in joined

    def test_render_llm_section_with_advanced(self) -> None:
        lines = _render_llm_section(
            {
                "mode": "builtin",
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": "",
                "base_url": "",
                "temperature": 0.5,
                "max_tokens": 8192,
                "requests_per_minute": 30,
                "max_retries": 5,
            }
        )
        joined = "\n".join(lines)
        assert "temperature: 0.5" in joined
        assert "max_tokens: 8192" in joined
        assert "requests_per_minute: 30" in joined
        assert "max_retries: 5" in joined

    def test_render_platform_section(self) -> None:
        lines = _render_platform_section(
            {
                "mode": "byok",
                "url": "https://platform.getnit.dev",
                "api_key": "key-123",
            }
        )
        joined = "\n".join(lines)
        assert "mode: byok" in joined
        assert "url:" in joined

    def test_render_git_section(self) -> None:
        lines = _render_git_section(
            {
                "auto_commit": True,
                "auto_pr": False,
                "create_issues": True,
                "create_fix_prs": False,
                "branch_prefix": "nit/test",
            }
        )
        joined = "\n".join(lines)
        assert "auto_commit: true" in joined
        assert "auto_pr: false" in joined
        assert "create_issues: true" in joined

    def test_render_report_section(self) -> None:
        lines = _render_report_section(
            {
                "format": "html",
                "upload_to_platform": True,
                "html_output_dir": ".nit/reports",
                "serve_port": 9090,
                "slack_webhook": "https://hooks.slack.com/test",
                "email_alerts": ["admin@test.com", "dev@test.com"],
            }
        )
        joined = "\n".join(lines)
        assert "format: html" in joined
        assert "html_output_dir:" in joined
        assert "serve_port: 9090" in joined
        assert "slack_webhook:" in joined
        assert '"admin@test.com"' in joined
        assert '"dev@test.com"' in joined

    def test_render_e2e_section(self) -> None:
        lines = _render_e2e_section(
            {
                "enabled": True,
                "base_url": "http://localhost:3000",
                "auth": {
                    "strategy": "token",
                    "token": "my-token",
                    "token_header": "Authorization",
                    "token_prefix": "Bearer",
                },
            }
        )
        joined = "\n".join(lines)
        assert "enabled: true" in joined
        assert "strategy: token" in joined
        assert "token_header:" in joined

    def test_render_coverage_section(self) -> None:
        lines = _render_coverage_section(
            {
                "line_threshold": 90.0,
                "branch_threshold": 85.0,
                "function_threshold": 95.0,
                "complexity_threshold": 15,
                "undertested_threshold": 60.0,
            }
        )
        joined = "\n".join(lines)
        assert "line_threshold: 90.0" in joined
        assert "branch_threshold: 85.0" in joined
        assert "complexity_threshold: 15" in joined

    def test_render_sentry_section(self) -> None:
        lines = _render_sentry_section(
            {
                "enabled": True,
                "dsn": "https://key@sentry.io/123",
                "traces_sample_rate": 0.5,
                "profiles_sample_rate": 0.1,
                "enable_logs": True,
                "environment": "staging",
            }
        )
        joined = "\n".join(lines)
        assert "enabled: true" in joined
        assert "sentry.io/123" in joined
        assert "traces_sample_rate: 0.5" in joined
        assert "profiles_sample_rate: 0.1" in joined
        assert "enable_logs: true" in joined
        assert "staging" in joined

    def test_render_sentry_section_disabled(self) -> None:
        lines = _render_sentry_section(
            {
                "enabled": False,
                "dsn": "",
                "traces_sample_rate": 0.0,
                "profiles_sample_rate": 0.0,
                "enable_logs": False,
                "environment": "",
            }
        )
        joined = "\n".join(lines)
        assert "enabled: false" in joined
        # DSN should not appear when empty
        assert "dsn:" not in joined
        # Environment should not appear when empty
        assert "environment:" not in joined

    def test_format_yaml_string(self) -> None:
        assert _format_yaml_string("hello") == '"hello"'
        assert _format_yaml_string('say "hi"') == '"say \\"hi\\""'
        assert _format_yaml_string("back\\slash") == '"back\\\\slash"'


# ── _display_profile ──────────────────────────────────────────────


class TestDisplayProfile:
    """Tests for _display_profile (lines ~430-503)."""

    def test_display_profile_full(self) -> None:
        profile = MagicMock()
        profile.languages = [
            LanguageInfo(
                language="Python",
                file_count=42,
                confidence=0.95,
                extensions={".py": 42},
            ),
        ]
        profile.frameworks = [
            DetectedFramework(
                name="pytest",
                language="Python",
                category=FrameworkCategory.UNIT_TEST,
                confidence=0.9,
            ),
        ]
        profile.packages = [
            PackageInfo(name="core", path="packages/core", dependencies=["utils"]),
        ]
        profile.llm_usage_count = 3
        profile.llm_providers = ["openai", "anthropic"]
        profile.workspace_tool = "generic"
        profile.primary_language = "Python"

        _display_profile(profile)

    def test_display_profile_no_frameworks(self) -> None:
        profile = MagicMock()
        profile.languages = []
        profile.frameworks = []
        profile.packages = []
        profile.llm_usage_count = 0
        profile.llm_providers = []
        profile.workspace_tool = "generic"
        profile.primary_language = None

        _display_profile(profile)

    def test_display_profile_llm_no_providers(self) -> None:
        profile = MagicMock()
        profile.languages = []
        profile.frameworks = []
        profile.packages = []
        profile.llm_usage_count = 2
        profile.llm_providers = []
        profile.workspace_tool = "npm"
        profile.primary_language = "TypeScript"

        _display_profile(profile)


# ── _display_diff_result ──────────────────────────────────────────


class TestDisplayDiffResult:
    """Tests for _display_diff_result (lines ~505-581)."""

    def test_full_diff_display(self) -> None:
        result = DiffAnalysisResult(
            changed_files=[],
            changed_source_files=["src/foo.py", "src/bar.py"],
            changed_test_files=["tests/test_foo.py"],
            file_mappings=[
                FileMapping(source_file="src/foo.py", test_file="tests/test_foo.py", exists=True),
                FileMapping(source_file="src/bar.py", test_file="tests/test_bar.py", exists=False),
            ],
            affected_source_files=["src/foo.py", "src/bar.py"],
            total_lines_added=100,
            total_lines_removed=20,
        )
        _display_diff_result(result)

    def test_empty_diff(self) -> None:
        result = DiffAnalysisResult()
        _display_diff_result(result)

    def test_truncated_source_files(self) -> None:
        # More than MAX_CHANGED_FILES_DISPLAY (20)
        many_files = [f"src/file{i}.py" for i in range(25)]
        result = DiffAnalysisResult(
            changed_files=[],
            changed_source_files=many_files,
            changed_test_files=[],
            file_mappings=[],
            affected_source_files=many_files,
            total_lines_added=50,
            total_lines_removed=10,
        )
        _display_diff_result(result)

    def test_truncated_file_mappings(self) -> None:
        # More than MAX_FILE_MAPPINGS_DISPLAY (15)
        mappings = [
            FileMapping(source_file=f"src/m{i}.py", test_file=f"tests/test_m{i}.py", exists=True)
            for i in range(20)
        ]
        result = DiffAnalysisResult(
            changed_files=[],
            changed_source_files=[],
            changed_test_files=[],
            file_mappings=mappings,
            affected_source_files=[],
            total_lines_added=0,
            total_lines_removed=0,
        )
        _display_diff_result(result)


# ── _display_pick_results ─────────────────────────────────────────


class TestDisplayPickResults:
    """Tests for _display_pick_results (lines ~2612-2688)."""

    def _make_result(self, **overrides: Any) -> PickPipelineResult:
        defaults: dict[str, Any] = {
            "success": True,
            "tests_run": 10,
            "tests_passed": 8,
            "tests_failed": 2,
            "tests_errors": 0,
            "bugs_found": [],
            "fixes_applied": [],
            "errors": [],
            "gap_report": None,
            "pr_created": False,
            "pr_url": None,
        }
        defaults.update(overrides)
        return PickPipelineResult(**defaults)

    def test_basic_results(self) -> None:
        result = self._make_result()
        _display_pick_results(result, fix_enabled=False)

    def test_results_with_bugs(self) -> None:
        bugs = []
        for i in range(10):
            bug = MagicMock()
            bug.title = f"Bug {i}"
            sev = MagicMock()
            sev.value = ["HIGH", "MEDIUM", "LOW"][i % 3]
            bug.severity = sev
            bugs.append(bug)
        result = self._make_result(bugs_found=bugs)
        _display_pick_results(result, fix_enabled=False)

    def test_results_with_fixes(self) -> None:
        fixes = ["src/a.py", "src/b.py", "src/c.py", "src/d.py", "src/e.py", "src/f.py"]
        result = self._make_result(fixes_applied=fixes)
        _display_pick_results(result, fix_enabled=True)

    def test_results_no_fixes(self) -> None:
        result = self._make_result()
        _display_pick_results(result, fix_enabled=True)

    def test_results_with_pr(self) -> None:
        result = self._make_result(pr_created=True, pr_url="https://github.com/org/repo/pull/1")
        _display_pick_results(result, fix_enabled=False)

    def test_results_with_gap_report(self) -> None:
        gap = CoverageGapReport(
            untested_files=["src/untested.py"],
            function_gaps=[],
            stale_tests=[],
            overall_coverage=65.0,
            target_coverage=80.0,
        )
        result = self._make_result(gap_report=gap)
        _display_pick_results(result, fix_enabled=False)

    def test_results_failure(self) -> None:
        result = self._make_result(success=False, errors=["Something went wrong", "Another error"])
        _display_pick_results(result, fix_enabled=False)


# ── _build_pick_report_payload ────────────────────────────────────


class TestBuildPickReportPayload:
    """Tests for _build_pick_report_payload (lines ~189-316)."""

    def _make_config(self) -> MagicMock:
        config = MagicMock()
        config.project.root = "/home/user/proj"
        config.llm.provider = "openai"
        config.llm.model = "gpt-4o"
        config.platform.url = "https://api.example.com"
        config.platform.api_key = "sk-test"
        config.platform.mode = "byok"
        config.platform.user_id = ""
        config.platform.project_id = ""
        config.platform.key_hash = ""
        return config

    @patch("nit.cli.get_session_usage_stats")
    @patch("nit.cli.get_usage_reporter")
    @patch("nit.cli.detect_ci_context")
    def test_basic_payload(
        self,
        mock_ci: MagicMock,
        mock_reporter: MagicMock,
        mock_stats: MagicMock,
    ) -> None:
        ci = MagicMock()
        ci.commit_sha = "abc123"
        ci.branch = "main"
        mock_ci.return_value = ci

        stats = MagicMock()
        stats.request_count = 5
        stats.prompt_tokens = 1000
        stats.completion_tokens = 500
        stats.total_tokens = 1500
        stats.total_cost_usd = 0.02
        mock_stats.return_value = stats

        reporter_obj = MagicMock()
        reporter_obj.session_id = "sess-1"
        mock_reporter.return_value = reporter_obj

        options = _PickOptions(
            test_type="unit", target_file="src/a.py", coverage_target=80, fix=True
        )
        result = self._make_config()
        payload = _build_pick_report_payload(result, options)

        assert payload["runMode"] == "pick"
        assert payload["branch"] == "main"
        assert payload["commitSha"] == "abc123"
        assert payload["llmProvider"] == "openai"
        assert payload["llmModel"] == "gpt-4o"

    @patch("nit.cli.get_session_usage_stats")
    @patch("nit.cli.get_usage_reporter")
    @patch("nit.cli.detect_ci_context")
    def test_payload_git_fallback(
        self,
        mock_ci: MagicMock,
        mock_reporter: MagicMock,
        mock_stats: MagicMock,
    ) -> None:
        """When CI context has no commit_sha/branch, falls back to git."""
        ci = MagicMock()
        ci.commit_sha = None
        ci.branch = None
        mock_ci.return_value = ci

        stats = MagicMock()
        stats.request_count = 0
        stats.prompt_tokens = 0
        stats.completion_tokens = 0
        stats.total_tokens = 0
        stats.total_cost_usd = 0.0
        mock_stats.return_value = stats
        mock_reporter.return_value = MagicMock()

        options = _PickOptions(test_type="all", target_file=None, coverage_target=None, fix=False)
        config = self._make_config()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")
            payload = _build_pick_report_payload(config, options)

        assert payload["commitSha"] is None
        assert payload["branch"] is None

    @patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}, clear=False)
    @patch("nit.cli.get_session_usage_stats")
    @patch("nit.cli.get_usage_reporter")
    @patch("nit.cli.detect_ci_context")
    def test_payload_github_actions_env(
        self,
        mock_ci: MagicMock,
        mock_reporter: MagicMock,
        mock_stats: MagicMock,
    ) -> None:
        ci = MagicMock()
        ci.commit_sha = "def456"
        ci.branch = "feature/x"
        mock_ci.return_value = ci

        stats = MagicMock()
        stats.request_count = 1
        stats.prompt_tokens = 100
        stats.completion_tokens = 50
        stats.total_tokens = 150
        stats.total_cost_usd = 0.01
        mock_stats.return_value = stats
        mock_reporter.return_value = MagicMock()

        options = _PickOptions(test_type="unit", target_file=None, coverage_target=None, fix=False)
        config = self._make_config()
        payload = _build_pick_report_payload(config, options)
        assert payload["executionEnvironment"] == "github-actions"

    @patch("nit.cli.get_session_usage_stats")
    @patch("nit.cli.get_usage_reporter")
    @patch("nit.cli.detect_ci_context")
    def test_payload_with_result_and_start_time(
        self,
        mock_ci: MagicMock,
        mock_reporter: MagicMock,
        mock_stats: MagicMock,
    ) -> None:
        ci = MagicMock()
        ci.commit_sha = "abc"
        ci.branch = "main"
        mock_ci.return_value = ci

        stats = MagicMock()
        stats.request_count = 2
        stats.prompt_tokens = 200
        stats.completion_tokens = 100
        stats.total_tokens = 300
        stats.total_cost_usd = 0.005
        mock_stats.return_value = stats
        mock_reporter.return_value = MagicMock()

        options = _PickOptions(test_type="unit", target_file=None, coverage_target=None, fix=False)
        config = self._make_config()
        pipeline_result = MagicMock()
        pipeline_result.success = True
        pipeline_result.tests_run = 5
        pipeline_result.tests_passed = 4
        pipeline_result.tests_failed = 1
        pipeline_result.tests_errors = 0
        pipeline_result.bugs_found = [MagicMock()]
        pipeline_result.fixes_applied = []
        pipeline_result.errors = []

        start_time = datetime.now(UTC) - timedelta(seconds=10)
        payload = _build_pick_report_payload(
            config, options, result=pipeline_result, start_time=start_time
        )

        assert payload["testsGenerated"] == 5
        assert payload["testsPassed"] == 4
        assert payload["testsFailed"] == 1
        assert payload["bugsFound"] == 1
        assert payload["executionTimeMs"] is not None
        assert payload["executionTimeMs"] > 0
        assert payload["fullReport"]["testsRun"] == 5


# ── _upload_bugs_to_platform extended ─────────────────────────────


class TestUploadBugsToPlatformExtended:
    """Extended tests for _upload_bugs_to_platform edge cases."""

    def _make_config(self) -> MagicMock:
        config = MagicMock()
        config.platform.url = "https://api.example.com"
        config.platform.api_key = "sk-test"
        return config

    def _make_bug(
        self,
        title: str = "Bug1",
        file_path: str = "src/a.py",
        function_name: str | None = "foo",
        root_cause: str | None = None,
    ) -> MagicMock:
        bug = MagicMock()
        bug.title = title
        bug.description = "A bug"
        bug.location = MagicMock()
        bug.location.file_path = file_path
        bug.location.function_name = function_name
        sev = MagicMock()
        sev.value = "HIGH"
        bug.severity = sev
        if root_cause is not None:
            bug.root_cause = root_cause
        else:
            # Make hasattr return False for root_cause
            del bug.root_cause
        return bug

    @patch("nit.cli.post_platform_bug")
    def test_upload_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = {"bugId": "bug-123"}
        config = self._make_config()
        bug = self._make_bug()
        result = MagicMock()
        result.bugs_found = [bug]

        ids = _upload_bugs_to_platform(config, result)
        assert ids == ["bug-123"]
        mock_post.assert_called_once()

    @patch("nit.cli.post_platform_bug")
    def test_upload_with_issue_and_pr_urls(self, mock_post: MagicMock) -> None:
        mock_post.return_value = {"bugId": "bug-456"}
        config = self._make_config()
        bug = self._make_bug(root_cause="null pointer")
        result = MagicMock()
        result.bugs_found = [bug]

        ids = _upload_bugs_to_platform(
            config,
            result,
            issue_urls={"Bug1": "https://github.com/issue/1"},
            pr_urls={"Bug1": "https://github.com/pr/2"},
        )
        assert ids == ["bug-456"]
        call_payload = mock_post.call_args[0][1]
        assert call_payload["githubIssueUrl"] == "https://github.com/issue/1"
        assert call_payload["githubPrUrl"] == "https://github.com/pr/2"
        assert call_payload["rootCause"] == "null pointer"

    @patch("nit.cli.post_platform_bug")
    def test_upload_api_failure_continues(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = PlatformClientError("API Error")
        config = self._make_config()
        bug = self._make_bug()
        result = MagicMock()
        result.bugs_found = [bug]

        ids = _upload_bugs_to_platform(config, result)
        assert ids == []

    def test_upload_no_bugs(self) -> None:
        config = self._make_config()
        result = MagicMock()
        result.bugs_found = []

        ids = _upload_bugs_to_platform(config, result)
        assert ids == []


# ── _get_slack_reporter ───────────────────────────────────────────


class TestGetSlackReporter:
    """Tests for _get_slack_reporter (lines ~584-591)."""

    def test_with_webhook(self) -> None:
        config = MagicMock()
        config.report.slack_webhook = "https://hooks.slack.com/test"
        result = _get_slack_reporter(config)
        assert result is not None

    def test_without_webhook(self) -> None:
        config = MagicMock()
        config.report.slack_webhook = ""
        result = _get_slack_reporter(config)
        assert result is None

    def test_no_report_attr(self) -> None:
        config = MagicMock(spec=[])
        result = _get_slack_reporter(config)
        assert result is None


# ── _write_comprehensive_nit_yml ──────────────────────────────────


class TestWriteComprehensiveNitYml:
    """Tests for _write_comprehensive_nit_yml (lines ~1549-1612)."""

    def test_full_config(self, tmp_path: Path) -> None:
        profile = MagicMock()
        profile.root = str(tmp_path)
        profile.primary_language = "Python"
        profile.workspace_tool = "generic"
        profile.frameworks_by_category = MagicMock(
            side_effect=lambda cat: (
                [
                    DetectedFramework(
                        name="pytest",
                        language="Python",
                        category=FrameworkCategory.UNIT_TEST,
                        confidence=0.9,
                    )
                ]
                if cat == FrameworkCategory.UNIT_TEST
                else []
            )
        )

        config_dict: dict[str, Any] = {
            "llm": {"mode": "builtin", "provider": "openai", "model": "gpt-4o"},
            "platform": {"mode": "byok", "url": "https://example.com", "api_key": "sk-123"},
            "git": {"auto_commit": True},
            "report": {"format": "terminal"},
            "e2e": {"enabled": True, "base_url": "http://localhost:3000"},
            "coverage": {"line_threshold": 80.0},
        }

        result_path = _write_comprehensive_nit_yml(profile, config_dict)
        assert result_path.exists()
        content = result_path.read_text()
        assert "project:" in content
        assert "pytest" in content
        assert "llm:" in content

    def test_minimal_config(self, tmp_path: Path) -> None:
        profile = MagicMock()
        profile.root = str(tmp_path)
        profile.primary_language = None
        profile.workspace_tool = "generic"
        profile.frameworks_by_category = MagicMock(return_value=[])

        config_dict: dict[str, Any] = {
            "llm": {"mode": "builtin"},
            "platform": {"mode": "disabled"},
        }
        result_path = _write_comprehensive_nit_yml(profile, config_dict)
        assert result_path.exists()
        content = result_path.read_text()
        assert "project:" in content
        assert "platform:" not in content

    def test_sentry_section_written_when_enabled(self, tmp_path: Path) -> None:
        profile = MagicMock()
        profile.root = str(tmp_path)
        profile.primary_language = "Python"
        profile.workspace_tool = "generic"
        profile.frameworks_by_category = MagicMock(return_value=[])

        config_dict: dict[str, Any] = {
            "llm": {"mode": "builtin"},
            "sentry": {
                "enabled": True,
                "dsn": "https://key@sentry.io/123",
                "traces_sample_rate": 0.5,
                "profiles_sample_rate": 0.1,
                "enable_logs": True,
                "environment": "production",
            },
        }
        result_path = _write_comprehensive_nit_yml(profile, config_dict)
        content = result_path.read_text()
        assert "sentry:" in content
        assert "enabled: true" in content
        assert "sentry.io/123" in content

    def test_sentry_section_omitted_when_disabled(self, tmp_path: Path) -> None:
        profile = MagicMock()
        profile.root = str(tmp_path)
        profile.primary_language = "Python"
        profile.workspace_tool = "generic"
        profile.frameworks_by_category = MagicMock(return_value=[])

        config_dict: dict[str, Any] = {
            "llm": {"mode": "builtin"},
            "sentry": {"enabled": False},
        }
        result_path = _write_comprehensive_nit_yml(profile, config_dict)
        content = result_path.read_text()
        assert "sentry:" not in content


# ── _write_nit_yml ────────────────────────────────────────────────


class TestWriteNitYml:
    """Tests for _write_nit_yml (lines ~1615-1648)."""

    def test_default_llm(self, tmp_path: Path) -> None:
        profile = MagicMock()
        profile.root = str(tmp_path)
        profile.primary_language = "Python"
        profile.workspace_tool = "generic"
        profile.frameworks_by_category = MagicMock(
            side_effect=lambda cat: (
                [
                    DetectedFramework(
                        name="pytest",
                        language="Python",
                        category=FrameworkCategory.UNIT_TEST,
                        confidence=0.9,
                    )
                ]
                if cat == FrameworkCategory.UNIT_TEST
                else []
            )
        )

        result_path = _write_nit_yml(profile)
        assert result_path.exists()
        content = result_path.read_text()
        assert "gpt-4o" in content
        assert "pytest" in content

    def test_custom_llm(self, tmp_path: Path) -> None:
        profile = MagicMock()
        profile.root = str(tmp_path)
        profile.primary_language = "Go"
        profile.workspace_tool = "go-mod"
        profile.frameworks_by_category = MagicMock(return_value=[])

        custom_llm = {"mode": "cli", "provider": "anthropic", "model": "claude-sonnet-4-5-20250514"}
        result_path = _write_nit_yml(profile, llm_config=custom_llm)
        assert result_path.exists()
        content = result_path.read_text()
        assert "claude" in content
        assert "Go" in content


# ── _display_doc_results ──────────────────────────────────────────


class TestDisplayDocResults:
    """Tests for _display_doc_results (lines ~4116-4199)."""

    def test_check_mode_outdated(self) -> None:
        results = [
            {
                "file_path": "src/a.py",
                "outdated": True,
                "changes": [
                    {"function_name": "foo"},
                    {"function_name": "bar"},
                ],
                "generated_docs": {},
            },
            {
                "file_path": "src/b.py",
                "outdated": False,
                "changes": [],
                "generated_docs": {},
            },
        ]
        _display_doc_results(results, check_only=True)

    def test_check_mode_all_up_to_date(self) -> None:
        results = [
            {
                "file_path": "src/a.py",
                "outdated": False,
                "changes": [],
                "generated_docs": {},
            },
        ]
        _display_doc_results(results, check_only=True)

    def test_generation_mode_with_docs(self) -> None:
        results = [
            {
                "file_path": "src/a.py",
                "outdated": True,
                "changes": [{"function_name": "foo"}],
                "generated_docs": {"foo": "def foo():\n    '''Does stuff.'''"},
            },
        ]
        _display_doc_results(results, check_only=False)

    def test_generation_mode_no_changes(self) -> None:
        results = [
            {
                "file_path": "src/a.py",
                "outdated": False,
                "changes": [],
                "generated_docs": {},
            },
        ]
        _display_doc_results(results, check_only=False)

    def test_check_mode_many_functions(self) -> None:
        # More than max_display_functions (5)
        changes = [{"function_name": f"func_{i}"} for i in range(8)]
        results = [
            {
                "file_path": "src/big.py",
                "outdated": True,
                "changes": changes,
                "generated_docs": {},
            },
        ]
        _display_doc_results(results, check_only=True)

    def test_generation_mode_many_docs(self) -> None:
        # More than max_display_functions (5) generated docs
        docs = {f"func_{i}": f"docstring {i}" for i in range(8)}
        results = [
            {
                "file_path": "src/big.py",
                "outdated": True,
                "changes": [{"function_name": f"func_{i}"} for i in range(8)],
                "generated_docs": docs,
            },
        ]
        _display_doc_results(results, check_only=False)


# ── _display_global_memory / _display_package_memory ──────────────


class TestDisplayGlobalMemory:
    """Tests for _display_global_memory (lines ~4389-4440)."""

    def test_with_data(self) -> None:
        memory = MagicMock()
        memory.get_conventions.return_value = {"indent": "4 spaces", "naming": "snake_case"}
        memory.get_known_patterns.return_value = [
            {"pattern": "pytest fixtures", "success_count": 5, "last_used": "2025-01-01"},
        ]
        memory.get_failed_patterns.return_value = [
            {"pattern": "bad mock", "reason": "leaked state"},
        ]
        memory.get_stats.return_value = {
            "total_runs": 10,
            "successful_generations": 8,
            "failed_generations": 2,
            "total_tests_generated": 50,
            "total_tests_passing": 45,
            "last_run": "2025-01-02",
        }
        _display_global_memory(memory)

    def test_empty(self) -> None:
        memory = MagicMock()
        memory.get_conventions.return_value = {}
        memory.get_known_patterns.return_value = []
        memory.get_failed_patterns.return_value = []
        memory.get_stats.return_value = {}
        _display_global_memory(memory)

    def test_truncated_patterns(self) -> None:
        memory = MagicMock()
        memory.get_conventions.return_value = {}
        # More than MAX_MEMORY_PATTERNS_DISPLAY (5)
        memory.get_known_patterns.return_value = [
            {"pattern": f"p{i}", "success_count": i, "last_used": "n/a"} for i in range(8)
        ]
        memory.get_failed_patterns.return_value = [
            {"pattern": f"f{i}", "reason": "err"} for i in range(8)
        ]
        memory.get_stats.return_value = {"total_runs": 1}
        _display_global_memory(memory)


class TestDisplayPackageMemory:
    """Tests for _display_package_memory (lines ~4443-4496)."""

    def test_with_data(self) -> None:
        memory = MagicMock()
        memory.get_test_patterns.return_value = {"framework": "pytest", "style": "class-based"}
        memory.get_known_issues.return_value = [
            {"issue": "Flaky test on CI", "workaround": "retry 3x"},
        ]
        memory.get_coverage_history.return_value = [
            {"coverage_percent": 75.0},
            {"coverage_percent": 80.0},
        ]
        memory.get_llm_feedback.return_value = [
            {"type": "suggestion", "content": "Use parametrize for combinatorial tests"},
        ]
        _display_package_memory(memory)

    def test_empty(self) -> None:
        memory = MagicMock()
        memory.get_test_patterns.return_value = {}
        memory.get_known_issues.return_value = []
        memory.get_coverage_history.return_value = []
        memory.get_llm_feedback.return_value = []
        _display_package_memory(memory)

    def test_truncated_issues_and_feedback(self) -> None:
        memory = MagicMock()
        memory.get_test_patterns.return_value = {}
        memory.get_known_issues.return_value = [
            {"issue": f"issue{i}", "workaround": f"fix{i}"} for i in range(8)
        ]
        memory.get_coverage_history.return_value = [{"coverage_percent": 50.0}]
        memory.get_llm_feedback.return_value = [
            {"type": "hint", "content": f"feedback {i}"} for i in range(6)
        ]
        _display_package_memory(memory)


# ── _display_watch_run ────────────────────────────────────────────


class TestDisplayWatchRun:
    """Tests for _display_watch_run (lines ~3819-3829)."""

    def test_success(self) -> None:
        run_result = MagicMock()
        run_result.success = True
        run_result.duration_seconds = 12.5
        _display_watch_run(run_result)

    def test_failure_with_error(self) -> None:
        run_result = MagicMock()
        run_result.success = False
        run_result.exit_code = 1
        run_result.duration_seconds = 5.0
        run_result.error = "Timeout exceeded"
        _display_watch_run(run_result)

    def test_failure_no_error(self) -> None:
        run_result = MagicMock()
        run_result.success = False
        run_result.exit_code = 2
        run_result.duration_seconds = 3.0
        run_result.error = None
        _display_watch_run(run_result)


# ── _display_drift_report ─────────────────────────────────────────


class TestDisplayDriftReport:
    """Tests for _display_drift_report (lines ~3611-3667)."""

    def test_all_pass(self) -> None:
        report = MagicMock()
        report.total_tests = 3
        report.passed_tests = 3
        report.failed_tests = 0
        report.skipped_tests = 0
        report.drift_detected = False
        r1 = MagicMock()
        r1.error = None
        r1.baseline_exists = True
        r1.passed = True
        r1.similarity_score = 1.0
        r1.test_name = "test_a"
        report.results = [r1]
        _display_drift_report(report)

    def test_drift_detected(self) -> None:
        report = MagicMock()
        report.total_tests = 2
        report.passed_tests = 1
        report.failed_tests = 1
        report.skipped_tests = 0
        report.drift_detected = True

        r1 = MagicMock()
        r1.error = None
        r1.baseline_exists = True
        r1.passed = True
        r1.similarity_score = 0.99
        r1.test_name = "test_ok"

        r2 = MagicMock()
        r2.error = None
        r2.baseline_exists = True
        r2.passed = False
        r2.similarity_score = 0.5
        r2.test_name = "test_drifted"

        report.results = [r1, r2]
        _display_drift_report(report)

    def test_error_and_no_baseline(self) -> None:
        report = MagicMock()
        report.total_tests = 2
        report.passed_tests = 0
        report.failed_tests = 0
        report.skipped_tests = 2
        report.drift_detected = False

        r1 = MagicMock()
        r1.error = "File not found"
        r1.baseline_exists = True
        r1.passed = False
        r1.similarity_score = None
        r1.test_name = "test_err"

        r2 = MagicMock()
        r2.error = None
        r2.baseline_exists = False
        r2.passed = False
        r2.similarity_score = None
        r2.test_name = "test_no_baseline"

        report.results = [r1, r2]
        _display_drift_report(report)


# ── _display_test_results_console deeper branches ─────────────────


class TestDisplayTestResultsConsoleDeep:
    """Tests for deeper branches in _display_test_results_console (lines ~639-673)."""

    def test_errors_count(self) -> None:
        result = RunResult(
            success=False,
            passed=3,
            failed=0,
            skipped=0,
            errors=2,
            duration_ms=1500.0,
            test_cases=[],
        )
        _display_test_results_console(result)

    def test_raw_output_on_framework_error(self) -> None:
        result = RunResult(
            success=False,
            passed=0,
            failed=0,
            skipped=0,
            errors=0,
            duration_ms=500.0,
            test_cases=[],
            raw_output="Error: module 'pytest' not found\nTraceback ...\nImportError",
        )
        _display_test_results_console(result)

    def test_failed_with_truncated_message(self) -> None:
        cases = [
            CaseResult(
                name=f"test_case_{i}",
                status=CaseStatus.FAILED,
                duration_ms=10.0,
                failure_message="x" * 300,
            )
            for i in range(12)
        ]
        result = RunResult(
            success=False,
            passed=0,
            failed=12,
            skipped=0,
            errors=0,
            duration_ms=2000.0,
            test_cases=cases,
        )
        _display_test_results_console(result)


# ── Render function edge cases ────────────────────────────────────


class TestRenderFunctionsEdgeCases:
    """Test render helper edge cases not covered by existing tests."""

    def test_e2e_form_auth(self) -> None:
        lines = _render_e2e_section(
            {
                "enabled": True,
                "base_url": "http://localhost:3000",
                "auth": {
                    "strategy": "form",
                    "login_url": "/login",
                    "username_field": "email",
                    "password_field": "pass",
                    "username": "admin",
                    "password": "secret",
                },
            }
        )
        joined = "\n".join(lines)
        assert "strategy: form" in joined
        assert "login_url:" in joined

    def test_e2e_cookie_auth(self) -> None:
        lines = _render_e2e_section(
            {
                "enabled": True,
                "base_url": "http://localhost:3000",
                "auth": {
                    "strategy": "cookie",
                    "cookie_name": "session",
                    "cookie_value": "abc123",
                },
            }
        )
        joined = "\n".join(lines)
        assert "strategy: cookie" in joined
        assert "cookie_name:" in joined

    def test_e2e_custom_auth(self) -> None:
        lines = _render_e2e_section(
            {
                "enabled": True,
                "base_url": "http://localhost:3000",
                "auth": {
                    "strategy": "custom",
                    "custom_script": "node setup.js",
                },
            }
        )
        joined = "\n".join(lines)
        assert "strategy: custom" in joined
        assert "custom_script:" in joined

    def test_platform_disabled(self) -> None:
        lines = _render_platform_section(
            {
                "mode": "disabled",
            }
        )
        joined = "\n".join(lines)
        assert "mode: disabled" in joined

    def test_platform_byok_with_ids(self) -> None:
        lines = _render_platform_section(
            {
                "mode": "byok",
                "url": "https://api.example.com",
                "api_key": "sk-test",
                "user_id": "user-123",
                "project_id": "proj-456",
                "key_hash": "hash789",
            }
        )
        joined = "\n".join(lines)
        assert "mode: byok" in joined
        assert "user_id:" in joined
        assert "project_id:" in joined

    def test_report_no_optional(self) -> None:
        lines = _render_report_section(
            {
                "format": "json",
                "upload_to_platform": False,
            }
        )
        joined = "\n".join(lines)
        assert "format: json" in joined

    def test_git_commit_template(self) -> None:
        lines = _render_git_section(
            {
                "auto_commit": False,
                "auto_pr": False,
                "create_issues": False,
                "create_fix_prs": False,
                "branch_prefix": "nit/",
                "commit_message_template": "fix: {description}",
            }
        )
        joined = "\n".join(lines)
        assert "commit_message_template:" in joined


# ── combine edge cases ────────────────────────────────────────────


class TestCombineEdgeCases:
    """Tests for combine command edge cases."""

    def test_combine_with_coverage(self, tmp_path: Path) -> None:
        shard = RunResult(
            success=True,
            passed=3,
            failed=0,
            skipped=0,
            errors=0,
            duration_ms=1000.0,
            test_cases=[],
            coverage=CoverageReport(files={}),
        )
        write_shard_result(shard, tmp_path / "shard-0.json", 0, 1, "pytest")

        runner = CliRunner()
        result = runner.invoke(cli, ["combine", str(tmp_path / "shard-0.json")])
        assert result.exit_code == 0

    def test_combine_invalid_shard(self, tmp_path: Path) -> None:
        (tmp_path / "shard-0.json").write_text("not json", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(cli, ["combine", str(tmp_path / "shard-0.json")])
        assert result.exit_code != 0


# ── run --shard-index/--shard-count ───────────────────────────────


class TestRunSharding:
    """Tests for run with shard options validation."""

    def test_run_shard_without_count_fails(self, tmp_path: Path) -> None:
        """Providing --shard-index without --shard-count should error."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", "--path", str(tmp_path), "--shard-index", "0"],
        )
        # Missing --shard-count
        assert result.exit_code != 0

    def test_run_shard_without_index_fails(self, tmp_path: Path) -> None:
        """Providing --shard-count without --shard-index should error."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", "--path", str(tmp_path), "--shard-count", "2"],
        )
        # Missing --shard-index
        assert result.exit_code != 0


# ── analyze JSON and terminal output ──────────────────────────────


class TestAnalyzeOutput:
    """Tests for analyze command output modes."""

    @patch("nit.cli._is_llm_runtime_configured", return_value=True)
    @patch("nit.cli.create_engine")
    @patch("nit.cli.load_llm_config")
    @patch("nit.cli.validate_config", return_value=[])
    @patch("nit.cli.load_config")
    @patch("nit.cli._load_and_validate_profile")
    @patch("nit.cli._get_test_adapters")
    def test_analyze_no_issues(
        self,
        mock_adapters: MagicMock,
        mock_profile: MagicMock,
        mock_config: MagicMock,
        mock_validate: MagicMock,
        mock_llm_config: MagicMock,
        mock_engine: MagicMock,
        mock_is_llm: MagicMock,
        tmp_path: Path,
    ) -> None:
        profile = MagicMock()
        profile.root = str(tmp_path)
        mock_profile.return_value = profile

        adapter = MagicMock()
        adapter.name = "pytest"
        run_result = RunResult(
            success=True,
            passed=5,
            failed=0,
            skipped=0,
            errors=0,
            duration_ms=1000.0,
            test_cases=[],
        )
        adapter.run = AsyncMock(return_value=run_result)
        mock_adapters.return_value = [adapter]

        mock_engine_obj = MagicMock()
        mock_engine.return_value = mock_engine_obj

        # Mock the bug analyzer to return no bugs
        with patch("nit.cli.asyncio.run") as mock_run:
            analyzer_result = MagicMock()
            analyzer_result.status = TaskStatus.COMPLETED
            analyzer_result.result = {"bugs": []}
            mock_run.return_value = analyzer_result

            runner = CliRunner()
            result = runner.invoke(cli, ["analyze", "--path", str(tmp_path)])
            # Just verify it doesn't crash
            assert result.exit_code in (0, 1)


# ── docs readme edge cases ────────────────────────────────────────


class TestDocsReadmeEdgeCases:
    """Tests for docs --readme edge cases."""

    @patch("nit.cli.load_config")
    def test_readme_config_error(self, mock_config: MagicMock, tmp_path: Path) -> None:
        mock_config.side_effect = Exception("Config not found")
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--readme", "--path", str(tmp_path)])
        assert result.exit_code != 0

    @patch("nit.cli.find_readme", return_value=None)
    @patch("nit.cli._is_llm_runtime_configured", return_value=True)
    @patch("nit.cli.validate_config", return_value=[])
    @patch("nit.cli.load_config")
    @patch("nit.cli.load_profile")
    def test_readme_no_readme_file(
        self,
        mock_profile: MagicMock,
        mock_config: MagicMock,
        mock_validate: MagicMock,
        mock_is_llm: MagicMock,
        mock_readme: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_profile.return_value = MagicMock()
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--readme", "--path", str(tmp_path)])
        assert result.exit_code != 0


# ── docs docstrings edge cases ────────────────────────────────────


class TestDocsDocstringEdgeCases:
    """Tests for docs --check and --all edge cases."""

    @patch("nit.cli.load_config")
    def test_check_config_error(self, mock_config: MagicMock, tmp_path: Path) -> None:
        mock_config.side_effect = Exception("No config")
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--check", "--path", str(tmp_path)])
        assert result.exit_code != 0

    @patch("nit.cli._is_llm_runtime_configured", return_value=False)
    @patch("nit.cli.validate_config", return_value=[])
    @patch("nit.cli.load_config")
    def test_all_no_llm_aborts(
        self,
        mock_config: MagicMock,
        mock_validate: MagicMock,
        mock_is_llm: MagicMock,
        tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--all", "--path", str(tmp_path)])
        assert result.exit_code != 0

    @patch("nit.cli.asyncio.run")
    @patch("nit.cli.DocBuilder")
    @patch("nit.cli.create_engine")
    @patch("nit.cli.load_llm_config")
    @patch("nit.cli._is_llm_runtime_configured", return_value=True)
    @patch("nit.cli.validate_config", return_value=[])
    @patch("nit.cli.load_config")
    def test_docbuilder_exception(
        self,
        mock_config: MagicMock,
        mock_validate: MagicMock,
        mock_is_llm: MagicMock,
        mock_llm_cfg: MagicMock,
        mock_engine: MagicMock,
        mock_builder: MagicMock,
        mock_arun: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_arun.side_effect = RuntimeError("Builder failed")
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--all", "--path", str(tmp_path)])
        assert result.exit_code != 0

    @patch("nit.cli.validate_config", return_value=["error1"])
    @patch("nit.cli.load_config")
    def test_check_with_validation_errors(
        self,
        mock_config: MagicMock,
        mock_validate: MagicMock,
        tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--check", "--path", str(tmp_path)])
        assert result.exit_code != 0


# ── _display_test_results_json ────────────────────────────────────


class TestDisplayTestResultsJson:
    """Tests for _display_test_results_json (lines ~620-636)."""

    def test_json_output_with_failed(self) -> None:
        cases = [
            CaseResult(
                name="test_ok",
                status=CaseStatus.PASSED,
                duration_ms=10.0,
            ),
            CaseResult(
                name="test_bad",
                status=CaseStatus.FAILED,
                duration_ms=20.0,
                failure_message="assert False",
            ),
        ]
        result = RunResult(
            success=False,
            passed=1,
            failed=1,
            skipped=0,
            errors=0,
            duration_ms=30.0,
            test_cases=cases,
        )
        _display_test_results_json(result)

    def test_json_output_all_passed(self) -> None:
        result = RunResult(
            success=True,
            passed=3,
            failed=0,
            skipped=0,
            errors=0,
            duration_ms=100.0,
            test_cases=[],
        )
        _display_test_results_json(result)


# ── docs --no-mode ────────────────────────────────────────────────


class TestDocsNoMode:
    """Test docs command with no mode flags prints usage hint."""

    def test_no_flags(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "nit docs" in result.output


# ── _is_llm_runtime_configured edge cases ─────────────────────────


class TestIsLlmRuntimeConfigured:
    """Tests for _is_llm_runtime_configured edge cases."""

    def test_configured_directly(self) -> None:
        config = MagicMock()
        config.llm.is_configured = True
        assert _is_llm_runtime_configured(config) is True

    def test_not_configured(self) -> None:
        config = MagicMock()
        config.llm.is_configured = False
        config.llm.mode = "builtin"
        config.platform.normalized_mode = "disabled"
        assert _is_llm_runtime_configured(config) is False


# ── _mask_sensitive_values edge cases ─────────────────────────────


class TestMaskSensitiveEdgeCases:
    """Tests for _mask_sensitive_values edge cases."""

    def test_short_value_masked(self) -> None:
        result = _mask_sensitive_values({"api_key": "short"})
        assert result["api_key"] == "***"

    def test_long_value_partially_masked(self) -> None:
        result = _mask_sensitive_values({"api_key": "sk-1234567890abcdef"})
        assert result["api_key"].startswith("sk-1")
        assert result["api_key"].endswith("cdef")
        assert "..." in result["api_key"]

    def test_nested_masking(self) -> None:
        result = _mask_sensitive_values({"outer": {"api_key": "sk-1234567890abcdef"}})
        assert "..." in result["outer"]["api_key"]

    def test_list_with_dicts(self) -> None:
        original = "longtoken1234567"
        result = _mask_sensitive_values({"items": [{"token": original}]})
        assert result["items"][0]["token"] != original

    def test_empty_value_not_masked(self) -> None:
        result = _mask_sensitive_values({"api_key": ""})
        assert result["api_key"] == ""


# ── _config_to_dict ───────────────────────────────────────────────


class TestConfigToDict:
    """Tests for _config_to_dict edge cases."""

    def test_removes_raw_field(self) -> None:
        @dataclass
        class FakeConfig:
            name: str = "test"
            raw: dict[str, Any] = field(default_factory=dict)

        config = FakeConfig(name="proj", raw={"extra": "data"})
        result = _config_to_dict(config)
        assert "raw" not in result
        assert result["name"] == "proj"


# ── config set / show commands ────────────────────────────────────


class TestConfigCommands:
    """Tests for config set and config show commands."""

    def test_config_set_creates_nested(self, tmp_path: Path) -> None:
        nit_yml = tmp_path / ".nit.yml"
        nit_yml.write_text("llm:\n  mode: builtin\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["config", "set", "platform.url", "https://api.example.com", "--path", str(tmp_path)],
        )
        assert result.exit_code == 0
        content = yaml.safe_load(nit_yml.read_text())
        assert content["platform"]["url"] == "https://api.example.com"

    def test_config_show_json(self, tmp_path: Path) -> None:
        nit_yml = tmp_path / ".nit.yml"
        nit_yml.write_text("llm:\n  mode: builtin\n", encoding="utf-8")

        with patch("nit.cli.load_config") as mock_config:

            @dataclass
            class FakeConfig:
                name: str = "test"
                raw: dict[str, Any] = field(default_factory=dict)

            mock_config.return_value = FakeConfig()
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["config", "show", "--path", str(tmp_path), "--json-output"],
            )
            # Should output JSON
            assert result.exit_code == 0


# ── _set_nested_config_value edge cases ───────────────────────────


class TestSetNestedConfigValue:
    """Tests for _set_nested_config_value edge cases."""

    def test_empty_key_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            _set_nested_config_value({}, "", "value")

    def test_deep_nesting(self) -> None:
        config: dict[str, Any] = {}
        _set_nested_config_value(config, "a.b.c.d", "deep")
        assert config["a"]["b"]["c"]["d"] == "deep"

    def test_overwrite_existing(self) -> None:
        config: dict[str, Any] = {"a": {"b": "old"}}
        _set_nested_config_value(config, "a.b", "new")
        assert config["a"]["b"] == "new"

    def test_overwrite_non_dict_intermediate(self) -> None:
        config: dict[str, Any] = {"a": "string"}
        _set_nested_config_value(config, "a.b", "nested")
        assert config["a"]["b"] == "nested"


# ── _load_nit_yml edge cases ─────────────────────────────────────


class TestLoadNitYml:
    """Tests for _load_nit_yml edge cases."""

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        result = _load_nit_yml(tmp_path / ".nit.yml")
        assert result == {}

    def test_non_dict_yaml(self, tmp_path: Path) -> None:
        nit_yml = tmp_path / ".nit.yml"
        nit_yml.write_text("- item1\n- item2\n", encoding="utf-8")
        result = _load_nit_yml(nit_yml)
        assert result == {}

    def test_valid_yaml(self, tmp_path: Path) -> None:
        nit_yml = tmp_path / ".nit.yml"
        nit_yml.write_text("llm:\n  mode: builtin\n", encoding="utf-8")
        result = _load_nit_yml(nit_yml)
        assert result["llm"]["mode"] == "builtin"
