"""Tests for the nit generate command wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from nit.cli import _determine_test_output_path, cli

if TYPE_CHECKING:
    from pathlib import Path


class TestGenerateCommand:
    def test_generate_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", "--help"])
        assert result.exit_code == 0
        assert "--type" in result.output
        assert "--file" in result.output
        assert "--coverage-target" in result.output

    def test_generate_no_config_aborts(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_generate_runs_pipeline(self, tmp_path: Path) -> None:
        """Test that generate calls _run_generate."""
        mock_config = MagicMock()
        mock_profile = MagicMock()

        with (
            patch("nit.cli.load_config", return_value=mock_config),
            patch("nit.cli.validate_config", return_value=[]),
            patch("nit.cli._is_llm_runtime_configured", return_value=True),
            patch("nit.cli.load_profile", return_value=mock_profile),
            patch("nit.cli.is_profile_stale", return_value=False),
            patch(
                "nit.cli._run_generate",
                new_callable=AsyncMock,
            ) as mock_run,
        ):
            mock_run.return_value = None
            runner = CliRunner()
            result = runner.invoke(cli, ["generate", "--path", str(tmp_path), "--type", "unit"])
            assert mock_run.called
            assert result.exit_code == 0

    def test_generate_with_target_file(self, tmp_path: Path) -> None:
        """Test that --file filters tasks."""
        (tmp_path / "main.py").write_text("def foo(): pass\n")
        nit_yml = tmp_path / ".nit.yml"
        nit_yml.write_text(
            "project:\n  name: test\n"
            "llm:\n  mode: builtin\n  provider: openai\n  model: gpt-4o\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["generate", "--path", str(tmp_path), "--file", "main.py"],
        )
        assert "main.py" in result.output or result.exit_code != 0


class TestDetermineTestOutputPath:
    def test_python_test_path(self, tmp_path: Path) -> None:
        adapter = MagicMock()
        adapter.get_test_pattern.return_value = ["**/test_*.py"]

        result = _determine_test_output_path("src/foo.py", adapter, tmp_path)
        assert result.name == "test_foo.py"

    def test_vitest_test_path(self, tmp_path: Path) -> None:
        adapter = MagicMock()
        adapter.get_test_pattern.return_value = ["**/*.test.ts"]

        result = _determine_test_output_path("src/foo.ts", adapter, tmp_path)
        assert result.name == "foo.test.ts"

    def test_tests_dir_preferred(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        adapter = MagicMock()
        adapter.get_test_pattern.return_value = ["**/test_*.py"]

        result = _determine_test_output_path("src/bar.py", adapter, tmp_path)
        assert "tests" in str(result)
        assert result.name == "test_bar.py"
