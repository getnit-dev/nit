"""Tests for the nit CLI commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import yaml
from click.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

from nit.cli import cli


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
            result = runner.invoke(cli, ["init", "--path", str(tmp_path)], input="2\n")

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
            result = runner.invoke(cli, ["init", "--path", str(tmp_path)], input="5\n")

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
            ["config", "set", "platform.url", "https://api.getnit.dev", "--path", str(tmp_path)],
        )
        result_key = runner.invoke(
            cli, ["config", "set", "platform.api_key", "nit_key_123", "--path", str(tmp_path)]
        )

        assert result_url.exit_code == 0, result_url.output
        assert result_key.exit_code == 0, result_key.output

        raw = yaml.safe_load((tmp_path / ".nit.yml").read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["platform"]["url"] == "https://api.getnit.dev"
        assert raw["platform"]["api_key"] == "nit_key_123"


class TestHuntReportUpload:
    def test_hunt_report_upload_posts_to_platform(self, tmp_path: Path) -> None:
        (tmp_path / ".nit.yml").write_text(
            "llm:\n"
            "  mode: builtin\n"
            "  provider: openai\n"
            "  model: gpt-4o\n"
            "  api_key: sk-test\n"
            "platform:\n"
            "  url: https://api.getnit.dev\n"
            "  api_key: nit_key_abc\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch(
            "nit.cli.post_platform_report", return_value={"reportId": "report-1"}
        ) as mock_post:
            result = runner.invoke(cli, ["--ci", "hunt", "--path", str(tmp_path), "--report"])

        assert result.exit_code == 0, result.output
        assert mock_post.call_count == 1
        payload = mock_post.call_args.args[1]
        assert payload["runMode"] == "hunt"
        assert payload["fullReport"]["status"] == "pipeline_not_implemented"
