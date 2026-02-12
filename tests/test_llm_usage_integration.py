"""Tests for LLM usage detector integration in CLI."""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING
from unittest.mock import patch

from click.testing import CliRunner
from rich.console import Console

from nit.cli import _build_profile, _display_profile, cli
from nit.models.profile import ProjectProfile

if TYPE_CHECKING:
    from pathlib import Path


class TestLLMUsageInProfile:
    def test_profile_has_llm_fields(self) -> None:
        profile = ProjectProfile(root="/test-project")
        assert profile.llm_usage_count == 0
        assert profile.llm_providers == []

    def test_to_dict_includes_llm_fields(self) -> None:
        profile = ProjectProfile(
            root="/test-project",
            llm_usage_count=3,
            llm_providers=["openai", "anthropic"],
        )
        d = profile.to_dict()
        assert d["llm_usage_count"] == 3
        assert d["llm_providers"] == ["openai", "anthropic"]

    def test_from_dict_reads_llm_fields(self) -> None:
        data: dict[str, object] = {
            "root": "/test-project",
            "llm_usage_count": 5,
            "llm_providers": ["openai"],
        }
        profile = ProjectProfile.from_dict(data)
        assert profile.llm_usage_count == 5
        assert profile.llm_providers == ["openai"]

    def test_from_dict_defaults_when_missing(self) -> None:
        data: dict[str, object] = {"root": "/test-project"}
        profile = ProjectProfile.from_dict(data)
        assert profile.llm_usage_count == 0
        assert profile.llm_providers == []


class TestBuildProfileLLMDetection:
    def test_build_profile_detects_llm_usage(self, tmp_path: Path) -> None:
        """Test that _build_profile runs LLMUsageDetector."""
        (tmp_path / "app.py").write_text("from openai import OpenAI\nclient = OpenAI()\n")

        profile = _build_profile(str(tmp_path))

        assert profile.llm_usage_count >= 1
        assert "openai" in profile.llm_providers

    def test_build_profile_no_llm_usage(self, tmp_path: Path) -> None:
        """Test that _build_profile handles no LLM usage gracefully."""
        (tmp_path / "app.py").write_text("x = 1\n")

        profile = _build_profile(str(tmp_path))
        assert profile.llm_usage_count == 0
        assert profile.llm_providers == []


class TestDisplayProfileLLM:
    def test_display_shows_llm_info(self, tmp_path: Path) -> None:
        """Test that _display_profile shows LLM integration info."""
        profile = ProjectProfile(
            root=str(tmp_path),
            llm_usage_count=3,
            llm_providers=["openai", "anthropic"],
        )

        output = StringIO()
        with patch("nit.cli.console", Console(file=output, force_terminal=False)):
            _display_profile(profile)

        text = output.getvalue()
        assert "LLM Integrations" in text
        assert "3 usage" in text
        assert "openai" in text

    def test_display_no_llm_info_when_zero(self, tmp_path: Path) -> None:
        """Test that _display_profile omits LLM info when count is 0."""
        profile = ProjectProfile(root=str(tmp_path))

        output = StringIO()
        with patch("nit.cli.console", Console(file=output, force_terminal=False)):
            _display_profile(profile)

        text = output.getvalue()
        assert "LLM Integrations" not in text


class TestInitDriftTestSkeleton:
    def test_init_generates_drift_tests_when_llm_found(self, tmp_path: Path) -> None:
        """Test that nit init generates drift-tests.yml when LLM usage is detected."""
        (tmp_path / "app.py").write_text(
            "from openai import OpenAI\n"
            "client = OpenAI()\n"
            "response = client.chat.completions.create(model='gpt-4')\n"
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output

        drift_tests = tmp_path / ".nit" / "drift-tests.yml"
        if drift_tests.exists():
            content = drift_tests.read_text()
            assert "tests:" in content
