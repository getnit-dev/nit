"""Tests for nit init --auto auto-detection."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import httpx
import yaml
from click.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

from nit.auto_init import (
    _detect_anthropic_api_key,
    _detect_claude_cli,
    _detect_claude_project_dir,
    _detect_codex_cli,
    _detect_e2e_base_url,
    _detect_llm,
    _detect_nit_llm_api_key,
    _detect_ollama_host_env,
    _detect_ollama_running,
    _detect_openai_api_key,
    _detect_platform,
    _detect_sentry,
    _extract_port_from_script,
    _pick_best_ollama_model,
    build_auto_config,
)
from nit.cli import cli


def _mock_httpx_response(data: dict[str, object]) -> httpx.Response:
    """Build a fake httpx.Response with JSON body."""
    return httpx.Response(200, json=data)


# ── LLM env var detectors ────────────────────────────────────────


class TestLLMEnvDetection:
    def test_anthropic_key_present(self) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            config, source = _detect_anthropic_api_key()
        assert config["provider"] == "anthropic"
        assert config["mode"] == "builtin"
        assert config["api_key"] == "${ANTHROPIC_API_KEY}"
        assert "ANTHROPIC_API_KEY" in source

    def test_anthropic_key_absent(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config, source = _detect_anthropic_api_key()
        assert config == {}
        assert source == ""

    def test_openai_key_present(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            config, _source = _detect_openai_api_key()
        assert config["provider"] == "openai"
        assert config["model"] == "gpt-4o"
        assert config["api_key"] == "${OPENAI_API_KEY}"

    def test_openai_key_absent(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config, _source = _detect_openai_api_key()
        assert config == {}

    def test_nit_llm_key_present(self) -> None:
        with patch.dict("os.environ", {"NIT_LLM_API_KEY": "sk-nit"}):
            config, _source = _detect_nit_llm_api_key()
        assert config["api_key"] == "${NIT_LLM_API_KEY}"
        assert config["mode"] == "builtin"

    def test_nit_llm_key_absent(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config, _source = _detect_nit_llm_api_key()
        assert config == {}


# ── CLI detectors ────────────────────────────────────────────────


class TestCLIDetection:
    def test_claude_project_dir_present(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        config, source = _detect_claude_project_dir(tmp_path)
        assert config["mode"] == "cli"
        assert config["cli_command"] == "claude"
        assert ".claude/" in source

    def test_claude_project_dir_absent(self, tmp_path: Path) -> None:
        config, _source = _detect_claude_project_dir(tmp_path)
        assert config == {}

    def test_claude_on_path(self) -> None:
        with patch("nit.auto_init.shutil.which", return_value="/usr/bin/claude"):
            config, _source = _detect_claude_cli()
        assert config["mode"] == "cli"
        assert config["provider"] == "anthropic"

    def test_claude_not_on_path(self) -> None:
        with patch("nit.auto_init.shutil.which", return_value=None):
            config, _source = _detect_claude_cli()
        assert config == {}

    def test_codex_on_path(self) -> None:
        with patch("nit.auto_init.shutil.which", return_value="/usr/bin/codex"):
            config, _source = _detect_codex_cli()
        assert config["cli_command"] == "codex"
        assert config["provider"] == "openai"

    def test_codex_not_on_path(self) -> None:
        with patch("nit.auto_init.shutil.which", return_value=None):
            config, _source = _detect_codex_cli()
        assert config == {}


# ── Ollama detection ─────────────────────────────────────────────


class TestOllamaDetection:
    def test_ollama_running_with_models(self) -> None:
        resp = _mock_httpx_response(
            {
                "models": [
                    {"name": "llama3.1:latest"},
                    {"name": "mistral:latest"},
                ]
            }
        )

        with patch("nit.auto_init.httpx.get", return_value=resp):
            config, source = _detect_ollama_running()

        assert config["mode"] == "ollama"
        assert "llama3.1" in config["model"]
        assert "2 model(s)" in source

    def test_ollama_not_running(self) -> None:
        with patch(
            "nit.auto_init.httpx.get",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            config, _source = _detect_ollama_running()
        assert config == {}

    def test_ollama_running_no_models(self) -> None:
        resp = _mock_httpx_response({"models": []})

        with patch("nit.auto_init.httpx.get", return_value=resp):
            config, _source = _detect_ollama_running()
        assert config == {}

    def test_ollama_host_env_present(self) -> None:
        with patch.dict("os.environ", {"OLLAMA_HOST": "http://gpu-server:11434"}):
            config, _source = _detect_ollama_host_env()
        assert config["mode"] == "ollama"
        assert config["model"] == "llama3.1"
        assert config["base_url"] == "http://gpu-server:11434"

    def test_ollama_host_env_absent(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config, _source = _detect_ollama_host_env()
        assert config == {}


# ── Ollama model picker ──────────────────────────────────────────


class TestOllamaModelPicker:
    def test_prefers_llama31(self) -> None:
        assert _pick_best_ollama_model(["mistral:latest", "llama3.1:8b"]) == "llama3.1:8b"

    def test_prefers_llama3_over_mistral(self) -> None:
        assert _pick_best_ollama_model(["mistral:latest", "llama3:8b"]) == "llama3:8b"

    def test_falls_back_to_first(self) -> None:
        assert _pick_best_ollama_model(["phi3:latest"]) == "phi3:latest"

    def test_empty_returns_default(self) -> None:
        assert _pick_best_ollama_model([]) == "llama3.1"


# ── LLM priority order ──────────────────────────────────────────


class TestLLMPriorityOrder:
    def test_anthropic_wins_over_openai(self, tmp_path: Path) -> None:
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_API_KEY": "sk-ant", "OPENAI_API_KEY": "sk-oai"},
        ):
            config, _source = _detect_llm(tmp_path)
        assert config["provider"] == "anthropic"

    def test_openai_wins_over_cli(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-oai"}, clear=True),
            patch("nit.auto_init.shutil.which", return_value="/usr/bin/claude"),
        ):
            config, _source = _detect_llm(tmp_path)
        assert config["mode"] == "builtin"
        assert config["provider"] == "openai"

    def test_fallback_when_nothing_found(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("nit.auto_init.shutil.which", return_value=None),
            patch(
                "nit.auto_init.httpx.get",
                side_effect=httpx.ConnectError("fail"),
            ),
        ):
            config, source = _detect_llm(tmp_path)
        assert config["mode"] == "builtin"
        assert "none" in source


# ── Platform detection ───────────────────────────────────────────


class TestPlatformDetection:
    def test_platform_key_with_url(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "NIT_PLATFORM_API_KEY": "pk-test",
                "NIT_PLATFORM_URL": "https://platform.getnit.dev",
            },
        ):
            config, _source = _detect_platform()
        assert config["mode"] == "platform"
        assert config["api_key"] == "${NIT_PLATFORM_API_KEY}"

    def test_platform_key_without_url(self) -> None:
        with patch.dict("os.environ", {"NIT_PLATFORM_API_KEY": "pk-test"}, clear=True):
            config, _source = _detect_platform()
        assert config["mode"] == "byok"

    def test_no_platform(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config, _source = _detect_platform()
        assert config["mode"] == "disabled"


# ── E2E base URL detection ───────────────────────────────────────


class TestE2EDetection:
    def test_vite_in_dev_script(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
        config, source = _detect_e2e_base_url(tmp_path)
        assert config["enabled"] is True
        assert config["base_url"] == "http://localhost:5173"
        assert "Vite" in source

    def test_next_in_dev_script(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "next dev"}}))
        config, source = _detect_e2e_base_url(tmp_path)
        assert config["base_url"] == "http://localhost:3000"
        assert "Next.js" in source

    def test_explicit_port_in_script(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite --port 4000"}}))
        config, source = _detect_e2e_base_url(tmp_path)
        assert config["base_url"] == "http://localhost:4000"
        assert "port 4000" in source

    def test_no_package_json(self, tmp_path: Path) -> None:
        config, _source = _detect_e2e_base_url(tmp_path)
        assert config["enabled"] is False

    def test_no_dev_script(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}))
        config, _source = _detect_e2e_base_url(tmp_path)
        assert config["enabled"] is False


# ── Port extraction ──────────────────────────────────────────────


class TestPortExtraction:
    def test_port_with_equals(self) -> None:
        assert _extract_port_from_script("vite --port=3001") == 3001

    def test_port_with_space(self) -> None:
        assert _extract_port_from_script("vite --port 4000") == 4000

    def test_short_flag(self) -> None:
        assert _extract_port_from_script("vite -p 5555") == 5555

    def test_no_port(self) -> None:
        assert _extract_port_from_script("vite dev") is None


# ── Sentry detection ─────────────────────────────────────────────


class TestSentryDetection:
    def test_dsn_present(self) -> None:
        with patch.dict(
            "os.environ",
            {"NIT_SENTRY_DSN": "https://key@sentry.io/123", "NIT_SENTRY_ENABLED": "true"},
            clear=True,
        ):
            config, source = _detect_sentry()
        assert config["enabled"] is True
        assert config["dsn"] == "${NIT_SENTRY_DSN}"
        assert "NIT_SENTRY_DSN" in source

    def test_dsn_present_with_rates(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "NIT_SENTRY_DSN": "https://key@sentry.io/123",
                "NIT_SENTRY_TRACES_SAMPLE_RATE": "0.5",
                "NIT_SENTRY_PROFILES_SAMPLE_RATE": "0.1",
                "NIT_SENTRY_ENABLE_LOGS": "yes",
            },
            clear=True,
        ):
            config, _source = _detect_sentry()
        assert config["traces_sample_rate"] == 0.5
        assert config["profiles_sample_rate"] == 0.1
        assert config["enable_logs"] is True

    def test_dsn_absent(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config, source = _detect_sentry()
        assert config["enabled"] is False
        assert config["dsn"] == ""
        assert "disabled" in source


# ── build_auto_config integration ────────────────────────────────


class TestBuildAutoConfig:
    def test_returns_all_sections(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            config = build_auto_config(tmp_path)

        assert "llm" in config
        assert "platform" in config
        assert "git" in config
        assert "report" in config
        assert "e2e" in config
        assert "coverage" in config
        assert "sentry" in config

    def test_sane_defaults(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            config = build_auto_config(tmp_path)

        assert config["git"]["auto_commit"] is False
        assert config["git"]["auto_pr"] is False
        assert config["git"]["branch_prefix"] == "nit/"
        assert config["coverage"]["line_threshold"] == 80.0
        assert config["coverage"]["branch_threshold"] == 75.0
        assert config["coverage"]["function_threshold"] == 85.0
        assert config["report"]["format"] == "terminal"

    def test_upload_enabled_when_platform_configured(self, tmp_path: Path) -> None:
        with patch.dict(
            "os.environ",
            {"NIT_PLATFORM_API_KEY": "pk-test", "NIT_PLATFORM_URL": "https://x"},
            clear=True,
        ):
            config = build_auto_config(tmp_path)
        assert config["report"]["upload_to_platform"] is True

    def test_upload_disabled_when_no_platform(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config = build_auto_config(tmp_path)
        assert config["report"]["upload_to_platform"] is False


# ── CLI integration ──────────────────────────────────────────────


class TestAutoInitCLI:
    def test_auto_flag_creates_config(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("x = 1\n")
        runner = CliRunner()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            result = runner.invoke(cli, ["init", "--auto", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".nit.yml").is_file()
        raw = yaml.safe_load((tmp_path / ".nit.yml").read_text(encoding="utf-8"))
        assert raw["llm"]["provider"] == "anthropic"
        assert raw["llm"]["api_key"] == "${ANTHROPIC_API_KEY}"

    def test_auto_flag_with_no_keys(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("x = 1\n")
        runner = CliRunner()
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("nit.auto_init.shutil.which", return_value=None),
            patch(
                "nit.auto_init.httpx.get",
                side_effect=httpx.ConnectError("fail"),
            ),
        ):
            result = runner.invoke(cli, ["init", "--auto", "--path", str(tmp_path)])

        assert result.exit_code == 0, result.output
        raw = yaml.safe_load((tmp_path / ".nit.yml").read_text(encoding="utf-8"))
        assert raw["llm"]["mode"] == "builtin"
        assert raw["llm"]["provider"] == "openai"
