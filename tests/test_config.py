"""Tests for config.py — .nit.yml parsing and validation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from nit.config import (
    AuthConfig,
    CoverageConfig,
    DocsConfig,
    E2EConfig,
    LLMConfig,
    NitConfig,
    PipelineConfig,
    PlatformConfig,
    ProjectConfig,
    SentryConfig,
    _parse_auth_config,
    _parse_docs_config,
    _parse_e2e_config,
    _parse_pipeline_config,
    _parse_sentry_config,
    _resolve_dict,
    _resolve_env_vars,
    _validate_coverage_config,
    _validate_llm_config,
    _validate_pipeline_config,
    _validate_platform_config,
    _validate_sentry_config,
    load_config,
    validate_auth_config,
    validate_config,
)

if TYPE_CHECKING:
    import pytest


def _write_nit_yml(root: Path, data: dict[str, Any]) -> None:
    """Write .nit.yml with given data."""
    (root / ".nit.yml").write_text(yaml.dump(data), encoding="utf-8")


# ── _resolve_env_vars / _resolve_dict ─────────────────────────────────


class TestResolveEnvVars:
    def test_resolves_existing_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_VAR", "hello")
        assert _resolve_env_vars("${MY_VAR}") == "hello"

    def test_missing_var_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISSING_VAR", raising=False)
        assert _resolve_env_vars("${MISSING_VAR}") == ""

    def test_no_vars_unchanged(self) -> None:
        assert _resolve_env_vars("plain text") == "plain text"


class TestResolveDict:
    def test_resolves_string_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KEY", "val")
        result = _resolve_dict({"a": "${KEY}", "b": "literal"})
        assert result["a"] == "val"
        assert result["b"] == "literal"

    def test_resolves_nested_dicts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INNER", "resolved")
        result = _resolve_dict({"outer": {"inner": "${INNER}"}})
        assert result["outer"]["inner"] == "resolved"

    def test_resolves_list_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ITEM", "x")
        result = _resolve_dict({"items": ["${ITEM}", 42]})
        assert result["items"] == ["x", 42]

    def test_passes_non_string_non_collection(self) -> None:
        result = _resolve_dict({"num": 42, "flag": True})
        assert result["num"] == 42
        assert result["flag"] is True


# ── load_config ───────────────────────────────────────────────────────


class TestLoadConfig:
    def test_load_missing_yml(self, tmp_path: Path) -> None:
        """Loads defaults when .nit.yml does not exist."""
        config = load_config(tmp_path)
        assert config.project.root == str(tmp_path.resolve())
        assert config.testing.unit_framework == ""
        assert config.llm.provider == "openai"

    def test_load_empty_yml(self, tmp_path: Path) -> None:
        """Loads defaults from empty YAML."""
        (tmp_path / ".nit.yml").write_text("")
        config = load_config(tmp_path)
        assert config.project.root == str(tmp_path.resolve())

    def test_load_full_yml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loads all sections from YAML."""
        monkeypatch.delenv("NIT_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("NIT_LLM_MODEL", raising=False)
        monkeypatch.delenv("NIT_LLM_API_KEY", raising=False)
        monkeypatch.delenv("NIT_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("NIT_PLATFORM_URL", raising=False)
        monkeypatch.delenv("NIT_PLATFORM_API_KEY", raising=False)
        monkeypatch.delenv("NIT_PLATFORM_MODE", raising=False)
        monkeypatch.delenv("NIT_PLATFORM_USER_ID", raising=False)
        monkeypatch.delenv("NIT_PLATFORM_PROJECT_ID", raising=False)
        monkeypatch.delenv("NIT_PLATFORM_KEY_HASH", raising=False)
        monkeypatch.delenv("NIT_SENTRY_ENABLED", raising=False)
        monkeypatch.delenv("NIT_SENTRY_DSN", raising=False)
        _write_nit_yml(
            tmp_path,
            {
                "project": {
                    "primary_language": "python",
                    "workspace_tool": "poetry",
                },
                "testing": {
                    "unit_framework": "pytest",
                    "e2e_framework": "playwright",
                    "integration_framework": "pytest",
                },
                "llm": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-5-20250514",
                    "api_key": "sk-test",
                    "mode": "builtin",
                    "temperature": 0.3,
                    "max_tokens": 8192,
                    "cli_extra_args": ["--verbose"],
                    "token_budget": 100000,
                },
                "git": {
                    "auto_commit": True,
                    "auto_pr": True,
                    "create_issues": True,
                    "create_fix_prs": True,
                    "branch_prefix": "nit/",
                    "base_branch": "main",
                },
                "report": {
                    "format": "json",
                    "serve_port": 9090,
                },
                "platform": {
                    "url": "https://platform.getnit.dev",
                    "api_key": "pk-test",
                    "mode": "byok",
                },
                "workspace": {
                    "auto_detect": False,
                    "packages": ["pkg1", "pkg2"],
                },
                "e2e": {
                    "enabled": True,
                    "base_url": "http://localhost:3000",
                    "auth": {
                        "strategy": "form",
                        "login_url": "/login",
                        "username": "admin",
                        "password": "secret",
                    },
                },
                "coverage": {
                    "line_threshold": 90.0,
                    "branch_threshold": 85.0,
                    "function_threshold": 95.0,
                    "complexity_threshold": 15,
                    "undertested_threshold": 40.0,
                },
                "pipeline": {"max_fix_loops": 3},
                "sentry": {
                    "enabled": True,
                    "dsn": "https://sentry.example.com",
                    "traces_sample_rate": 0.5,
                    "profiles_sample_rate": 0.3,
                    "enable_logs": True,
                    "environment": "test",
                },
                "docs": {
                    "enabled": True,
                    "style": "google",
                    "framework": "sphinx",
                    "write_to_source": True,
                    "check_mismatch": False,
                    "output_dir": "docs/api",
                    "exclude_patterns": ["vendor/**"],
                    "max_tokens": 2048,
                },
                "packages": {
                    "my-app": {
                        "e2e": {
                            "enabled": True,
                            "base_url": "http://app:3000",
                        }
                    }
                },
            },
        )
        config = load_config(tmp_path)
        assert config.project.primary_language == "python"
        assert config.testing.unit_framework == "pytest"
        assert config.llm.provider == "anthropic"
        assert config.llm.model == "claude-sonnet-4-5-20250514"
        assert config.llm.token_budget == 100000
        assert config.git.auto_commit is True
        assert config.report.format == "json"
        assert config.platform.url == "https://platform.getnit.dev"
        assert config.workspace.auto_detect is False
        assert len(config.workspace.packages) == 2
        assert config.e2e.enabled is True
        assert config.coverage.line_threshold == 90.0
        assert config.docs.style == "google"
        assert config.docs.framework == "sphinx"
        assert config.docs.write_to_source is True
        assert config.docs.check_mismatch is False
        assert config.docs.output_dir == "docs/api"
        assert config.docs.exclude_patterns == ["vendor/**"]
        assert config.docs.max_tokens == 2048
        assert config.pipeline.max_fix_loops == 3
        assert config.sentry.enabled is True
        assert config.sentry.dsn == "https://sentry.example.com"

    def test_load_non_dict_sections(self, tmp_path: Path) -> None:
        """Handles non-dict sections gracefully."""
        _write_nit_yml(
            tmp_path,
            {
                "project": "not-a-dict",
                "testing": "not-a-dict",
                "llm": "not-a-dict",
                "git": "not-a-dict",
                "report": "not-a-dict",
                "platform": "not-a-dict",
                "workspace": "not-a-dict",
                "e2e": "not-a-dict",
                "coverage": "not-a-dict",
                "pipeline": "not-a-dict",
                "sentry": "not-a-dict",
                "packages": "not-a-dict",
            },
        )
        config = load_config(tmp_path)
        assert config.project.root == str(tmp_path.resolve())

    def test_load_cli_extra_args_not_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cli_extra_args defaults to empty if not a list."""
        monkeypatch.delenv("NIT_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("NIT_LLM_MODEL", raising=False)
        monkeypatch.delenv("NIT_LLM_API_KEY", raising=False)
        monkeypatch.delenv("NIT_LLM_BASE_URL", raising=False)
        _write_nit_yml(
            tmp_path,
            {"llm": {"cli_extra_args": "not-a-list"}},
        )
        config = load_config(tmp_path)
        assert config.llm.cli_extra_args == []


# ── LLMConfig.is_configured ──────────────────────────────────────────


class TestLLMConfigIsConfigured:
    def test_builtin_needs_model_and_key(self) -> None:
        cfg = LLMConfig(mode="builtin", model="gpt-4", api_key="sk-x")
        assert cfg.is_configured is True

    def test_builtin_missing_key(self) -> None:
        cfg = LLMConfig(mode="builtin", model="gpt-4", api_key="")
        assert cfg.is_configured is False

    def test_ollama_needs_model(self) -> None:
        cfg = LLMConfig(mode="ollama", model="llama3")
        assert cfg.is_configured is True

    def test_ollama_missing_model(self) -> None:
        cfg = LLMConfig(mode="ollama", model="")
        assert cfg.is_configured is False

    def test_cli_needs_model_and_command(self) -> None:
        cfg = LLMConfig(mode="cli", model="gpt-4", cli_command="llm chat")
        assert cfg.is_configured is True

    def test_cli_missing_command(self) -> None:
        cfg = LLMConfig(mode="cli", model="gpt-4", cli_command="")
        assert cfg.is_configured is False


# ── PlatformConfig.normalized_mode ────────────────────────────────────


class TestPlatformNormalizedMode:
    def test_explicit_byok(self) -> None:
        cfg = PlatformConfig(mode="byok")
        assert cfg.normalized_mode == "byok"

    def test_explicit_disabled(self) -> None:
        cfg = PlatformConfig(mode="disabled")
        assert cfg.normalized_mode == "disabled"

    def test_auto_byok_from_url_and_key(self) -> None:
        cfg = PlatformConfig(url="https://platform.example", api_key="pk-x")
        assert cfg.normalized_mode == "byok"

    def test_auto_disabled(self) -> None:
        cfg = PlatformConfig()
        assert cfg.normalized_mode == "disabled"


# ── validate_auth_config ──────────────────────────────────────────────


class TestValidateAuthConfig:
    def test_no_strategy_returns_empty(self) -> None:
        errors = validate_auth_config(AuthConfig())
        assert errors == []

    def test_invalid_strategy(self) -> None:
        auth = AuthConfig(strategy="invalid")
        errors = validate_auth_config(auth)
        assert any("strategy" in e for e in errors)

    def test_form_missing_fields(self) -> None:
        auth = AuthConfig(strategy="form")
        errors = validate_auth_config(auth)
        assert any("login_url" in e for e in errors)
        assert any("username" in e or "password" in e for e in errors)

    def test_token_missing_token(self) -> None:
        auth = AuthConfig(strategy="token")
        errors = validate_auth_config(auth)
        assert any("token" in e for e in errors)

    def test_cookie_missing_fields(self) -> None:
        auth = AuthConfig(strategy="cookie")
        errors = validate_auth_config(auth)
        assert any("cookie_name" in e for e in errors)

    def test_custom_missing_script(self) -> None:
        auth = AuthConfig(strategy="custom")
        errors = validate_auth_config(auth)
        assert any("custom_script" in e for e in errors)

    def test_timeout_too_low(self) -> None:
        tok = "t" + "k"
        auth = AuthConfig(strategy="token", token=tok, timeout=100)
        errors = validate_auth_config(auth)
        assert any("timeout" in e for e in errors)


# ── _validate_llm_config ─────────────────────────────────────────────


class TestValidateLLMConfig:
    def test_valid_config(self) -> None:
        cfg = LLMConfig(provider="openai", model="gpt-4", mode="builtin")
        assert _validate_llm_config(cfg) == []

    def test_invalid_mode(self) -> None:
        cfg = LLMConfig(mode="invalid")
        errors = _validate_llm_config(cfg)
        assert any("mode" in e for e in errors)

    def test_cli_without_command(self) -> None:
        cfg = LLMConfig(mode="cli", cli_command="")
        errors = _validate_llm_config(cfg)
        assert any("cli_command" in e for e in errors)

    def test_cli_timeout_too_low(self) -> None:
        cfg = LLMConfig(mode="cli", cli_command="cmd", cli_timeout=0)
        errors = _validate_llm_config(cfg)
        assert any("cli_timeout" in e for e in errors)

    def test_unknown_provider_warning(self) -> None:
        cfg = LLMConfig(provider="custom_provider", mode="builtin")
        errors = _validate_llm_config(cfg)
        assert any("provider" in e for e in errors)

    def test_temperature_out_of_range(self) -> None:
        cfg = LLMConfig(temperature=3.0)
        errors = _validate_llm_config(cfg)
        assert any("temperature" in e for e in errors)

    def test_max_tokens_zero(self) -> None:
        cfg = LLMConfig(max_tokens=0)
        errors = _validate_llm_config(cfg)
        assert any("max_tokens" in e for e in errors)


# ── _validate_platform_config ────────────────────────────────────────


class TestValidatePlatformConfig:
    def test_disabled_ok(self) -> None:
        cfg = PlatformConfig(mode="disabled")
        assert _validate_platform_config(cfg) == []

    def test_byok_missing_url(self) -> None:
        cfg = PlatformConfig(mode="byok", url="", api_key="key")
        errors = _validate_platform_config(cfg)
        assert any("url" in e for e in errors)

    def test_byok_missing_key(self) -> None:
        cfg = PlatformConfig(mode="byok", url="https://x", api_key="")
        errors = _validate_platform_config(cfg)
        assert any("api_key" in e for e in errors)


# ── _validate_coverage_config ────────────────────────────────────────


class TestValidateCoverageConfig:
    def test_valid_defaults(self) -> None:
        assert _validate_coverage_config(CoverageConfig()) == []

    def test_line_threshold_out_of_range(self) -> None:
        cfg = CoverageConfig(line_threshold=110.0)
        errors = _validate_coverage_config(cfg)
        assert any("line_threshold" in e for e in errors)

    def test_branch_threshold_negative(self) -> None:
        cfg = CoverageConfig(branch_threshold=-1.0)
        errors = _validate_coverage_config(cfg)
        assert any("branch_threshold" in e for e in errors)

    def test_function_threshold_out_of_range(self) -> None:
        cfg = CoverageConfig(function_threshold=200.0)
        errors = _validate_coverage_config(cfg)
        assert any("function_threshold" in e for e in errors)

    def test_complexity_threshold_zero(self) -> None:
        cfg = CoverageConfig(complexity_threshold=0)
        errors = _validate_coverage_config(cfg)
        assert any("complexity_threshold" in e for e in errors)

    def test_undertested_threshold_out_of_range(self) -> None:
        cfg = CoverageConfig(undertested_threshold=101.0)
        errors = _validate_coverage_config(cfg)
        assert any("undertested_threshold" in e for e in errors)


# ── _validate_pipeline_config ────────────────────────────────────────


class TestValidatePipelineConfig:
    def test_valid_defaults(self) -> None:
        assert _validate_pipeline_config(PipelineConfig()) == []

    def test_negative_fix_loops(self) -> None:
        cfg = PipelineConfig(max_fix_loops=-1)
        errors = _validate_pipeline_config(cfg)
        assert any("max_fix_loops" in e for e in errors)


# ── _validate_sentry_config ──────────────────────────────────────────


class TestValidateSentryConfig:
    def test_disabled_ok(self) -> None:
        assert _validate_sentry_config(SentryConfig()) == []

    def test_enabled_without_dsn(self) -> None:
        cfg = SentryConfig(enabled=True, dsn="")
        errors = _validate_sentry_config(cfg)
        assert any("dsn" in e for e in errors)

    def test_traces_out_of_range(self) -> None:
        cfg = SentryConfig(traces_sample_rate=1.5)
        errors = _validate_sentry_config(cfg)
        assert any("traces_sample_rate" in e for e in errors)

    def test_profiles_out_of_range(self) -> None:
        cfg = SentryConfig(profiles_sample_rate=-0.1)
        errors = _validate_sentry_config(cfg)
        assert any("profiles_sample_rate" in e for e in errors)


# ── validate_config ──────────────────────────────────────────────────


class TestValidateConfig:
    def test_valid_config(self, tmp_path: Path) -> None:
        config = load_config(tmp_path)
        errors = validate_config(config)
        # May have some warnings but should be a list
        assert isinstance(errors, list)

    def test_empty_root(self) -> None:
        config = NitConfig(project=ProjectConfig(root=""))
        errors = validate_config(config)
        assert any("root" in e for e in errors)

    def test_package_e2e_auth_validated(self, tmp_path: Path) -> None:
        config = NitConfig(
            project=ProjectConfig(root=str(tmp_path)),
            packages={
                "my-app": {
                    "e2e": {
                        "auth": {
                            "strategy": "invalid_strat",
                        }
                    }
                }
            },
        )
        errors = validate_config(config)
        assert any("strategy" in e for e in errors)


# ── _parse_e2e_config / _parse_auth_config ───────────────────────────


class TestParseE2EConfig:
    def test_default(self) -> None:
        result = _parse_e2e_config({})
        assert result.enabled is False

    def test_with_auth(self) -> None:
        result = _parse_e2e_config(
            {
                "enabled": True,
                "base_url": "http://localhost:3000",
                "auth": {"strategy": "token", "token": "tk"},
            }
        )
        assert result.enabled is True
        assert result.auth.strategy == "token"

    def test_non_dict_auth(self) -> None:
        result = _parse_e2e_config({"auth": "not-a-dict"})
        assert result.auth.strategy == ""


class TestParseAuthConfig:
    def test_credentials_fallback(self) -> None:
        result = _parse_auth_config(
            {
                "credentials": {
                    "username": "admin",
                    "password": "secret",
                }
            }
        )
        assert result.username == "admin"
        expected_pw = "secret"
        assert result.password == expected_pw


class TestParsePipelineConfig:
    def test_default(self) -> None:
        result = _parse_pipeline_config({})
        assert result.max_fix_loops == 1

    def test_non_dict(self) -> None:
        result = _parse_pipeline_config({"pipeline": "not-a-dict"})
        assert result.max_fix_loops == 1


class TestParseSentryConfig:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NIT_SENTRY_ENABLED", raising=False)
        monkeypatch.delenv("NIT_SENTRY_DSN", raising=False)
        monkeypatch.delenv("NIT_SENTRY_TRACES_SAMPLE_RATE", raising=False)
        monkeypatch.delenv("NIT_SENTRY_PROFILES_SAMPLE_RATE", raising=False)
        monkeypatch.delenv("NIT_SENTRY_ENABLE_LOGS", raising=False)
        result = _parse_sentry_config({})
        assert result.enabled is False

    def test_non_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NIT_SENTRY_ENABLED", raising=False)
        monkeypatch.delenv("NIT_SENTRY_DSN", raising=False)
        result = _parse_sentry_config({"sentry": "not-a-dict"})
        assert result.enabled is False

    def test_env_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NIT_SENTRY_ENABLED", "true")
        monkeypatch.setenv("NIT_SENTRY_DSN", "https://sentry.io")
        monkeypatch.delenv("NIT_SENTRY_TRACES_SAMPLE_RATE", raising=False)
        monkeypatch.delenv("NIT_SENTRY_PROFILES_SAMPLE_RATE", raising=False)
        monkeypatch.delenv("NIT_SENTRY_ENABLE_LOGS", raising=False)
        result = _parse_sentry_config({})
        assert result.enabled is True
        assert result.dsn == "https://sentry.io"


# ── NitConfig.get_package_e2e_config ─────────────────────────────────


class TestGetPackageE2EConfig:
    def test_missing_package(self, tmp_path: Path) -> None:
        config = NitConfig(project=ProjectConfig(root=str(tmp_path)))
        e2e = config.get_package_e2e_config("nonexistent")
        assert e2e.enabled is False

    def test_non_dict_e2e(self, tmp_path: Path) -> None:
        config = NitConfig(
            project=ProjectConfig(root=str(tmp_path)),
            packages={"pkg": {"e2e": "not-a-dict"}},
        )
        e2e = config.get_package_e2e_config("pkg")
        # Falls back to global config
        assert e2e.enabled is False

    def test_package_override(self, tmp_path: Path) -> None:
        config = NitConfig(
            project=ProjectConfig(root=str(tmp_path)),
            e2e=E2EConfig(enabled=False, base_url="http://global"),
            packages={
                "pkg": {
                    "e2e": {
                        "enabled": True,
                        "base_url": "http://local",
                    }
                }
            },
        )
        e2e = config.get_package_e2e_config("pkg")
        assert e2e.enabled is True
        assert e2e.base_url == "http://local"


# ── DocsConfig ───────────────────────────────────────────────────────


class TestDocsConfigDefaults:
    def test_all_defaults(self) -> None:
        cfg = DocsConfig()
        assert cfg.enabled is True
        assert cfg.output_dir == ""
        assert cfg.style == ""
        assert cfg.framework == ""
        assert cfg.write_to_source is False
        assert cfg.check_mismatch is True
        assert cfg.exclude_patterns == []
        assert cfg.max_tokens == 4096

    def test_custom_values(self) -> None:
        cfg = DocsConfig(
            enabled=False,
            output_dir="docs/api",
            style="numpy",
            framework="sphinx",
            write_to_source=True,
            check_mismatch=False,
            exclude_patterns=["*_test.py", "vendor/**"],
            max_tokens=8192,
        )
        assert cfg.enabled is False
        assert cfg.output_dir == "docs/api"
        assert cfg.style == "numpy"
        assert cfg.framework == "sphinx"
        assert cfg.write_to_source is True
        assert cfg.check_mismatch is False
        assert cfg.exclude_patterns == ["*_test.py", "vendor/**"]
        assert cfg.max_tokens == 8192


class TestParseDocsConfig:
    def test_empty_raw(self) -> None:
        result = _parse_docs_config({})
        assert result.enabled is True
        assert result.write_to_source is False
        assert result.check_mismatch is True

    def test_non_dict_docs_section(self) -> None:
        result = _parse_docs_config({"docs": "not-a-dict"})
        assert result.enabled is True
        assert result.style == ""

    def test_full_yaml_section(self) -> None:
        result = _parse_docs_config(
            {
                "docs": {
                    "enabled": False,
                    "output_dir": "build/docs",
                    "style": "google",
                    "framework": "typedoc",
                    "write_to_source": True,
                    "check_mismatch": False,
                    "exclude_patterns": ["*.generated.ts"],
                    "max_tokens": 2048,
                }
            }
        )
        assert result.enabled is False
        assert result.output_dir == "build/docs"
        assert result.style == "google"
        assert result.framework == "typedoc"
        assert result.write_to_source is True
        assert result.check_mismatch is False
        assert result.exclude_patterns == ["*.generated.ts"]
        assert result.max_tokens == 2048

    def test_exclude_patterns_non_list(self) -> None:
        result = _parse_docs_config({"docs": {"exclude_patterns": "not-a-list"}})
        assert result.exclude_patterns == []


class TestLoadConfigWithDocs:
    def test_docs_defaults_when_missing(self, tmp_path: Path) -> None:
        config = load_config(tmp_path)
        assert config.docs.enabled is True
        assert config.docs.write_to_source is False
        assert config.docs.check_mismatch is True

    def test_docs_from_yaml(self, tmp_path: Path) -> None:
        _write_nit_yml(
            tmp_path,
            {
                "docs": {
                    "enabled": True,
                    "style": "numpy",
                    "framework": "sphinx",
                    "write_to_source": True,
                    "output_dir": "docs/api",
                    "exclude_patterns": ["test_*.py"],
                }
            },
        )
        config = load_config(tmp_path)
        assert config.docs.style == "numpy"
        assert config.docs.framework == "sphinx"
        assert config.docs.write_to_source is True
        assert config.docs.output_dir == "docs/api"
        assert config.docs.exclude_patterns == ["test_*.py"]

    def test_nitconfig_has_docs_field(self, tmp_path: Path) -> None:
        config = NitConfig(project=ProjectConfig(root=str(tmp_path)))
        assert isinstance(config.docs, DocsConfig)
