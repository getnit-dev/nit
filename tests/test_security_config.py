"""Tests for SecurityConfig parsing and validation (config.py).

Covers:
- Default values
- YAML parsing (_parse_security_config)
- Validation (_validate_security_config)
- Integration with NitConfig
"""

from __future__ import annotations

from nit.config import (
    SecurityConfig,
    _parse_security_config,
    _validate_security_config,
)

# ── Defaults ─────────────────────────────────────────────────────


class TestSecurityConfigDefaults:
    """SecurityConfig default values."""

    def test_enabled_by_default(self) -> None:
        cfg = SecurityConfig()
        assert cfg.enabled is True

    def test_llm_validation_by_default(self) -> None:
        cfg = SecurityConfig()
        assert cfg.llm_validation is True

    def test_default_confidence_threshold(self) -> None:
        cfg = SecurityConfig()
        assert cfg.confidence_threshold == 0.7

    def test_default_severity_threshold(self) -> None:
        cfg = SecurityConfig()
        assert cfg.severity_threshold == "medium"

    def test_default_exclude_patterns_empty(self) -> None:
        cfg = SecurityConfig()
        assert cfg.exclude_patterns == []


# ── Parsing ──────────────────────────────────────────────────────


class TestSecurityConfigParsing:
    """_parse_security_config from raw YAML dicts."""

    def test_parse_empty_dict(self) -> None:
        cfg = _parse_security_config({})
        assert cfg.enabled is True
        assert cfg.confidence_threshold == 0.7

    def test_parse_all_fields(self) -> None:
        raw = {
            "security": {
                "enabled": False,
                "llm_validation": False,
                "confidence_threshold": 0.5,
                "severity_threshold": "high",
                "exclude_patterns": ["tests/*", "vendor/*"],
            },
        }
        cfg = _parse_security_config(raw)
        assert cfg.enabled is False
        assert cfg.llm_validation is False
        assert cfg.confidence_threshold == 0.5
        assert cfg.severity_threshold == "high"
        assert cfg.exclude_patterns == ["tests/*", "vendor/*"]

    def test_parse_partial_fields(self) -> None:
        raw = {"security": {"enabled": False}}
        cfg = _parse_security_config(raw)
        assert cfg.enabled is False
        assert cfg.llm_validation is True  # default
        assert cfg.confidence_threshold == 0.7  # default

    def test_parse_invalid_security_type(self) -> None:
        raw = {"security": "not-a-dict"}
        cfg = _parse_security_config(raw)
        # Falls back to defaults
        assert cfg.enabled is True

    def test_parse_exclude_patterns_non_list(self) -> None:
        raw = {"security": {"exclude_patterns": "not-a-list"}}
        cfg = _parse_security_config(raw)
        assert cfg.exclude_patterns == []


# ── Validation ───────────────────────────────────────────────────


class TestSecurityConfigValidation:
    """_validate_security_config error checking."""

    def test_valid_config_no_errors(self) -> None:
        cfg = SecurityConfig()
        errors = _validate_security_config(cfg)
        assert len(errors) == 0

    def test_confidence_too_low(self) -> None:
        cfg = SecurityConfig(confidence_threshold=-0.1)
        errors = _validate_security_config(cfg)
        assert any("confidence" in e.lower() for e in errors)

    def test_confidence_too_high(self) -> None:
        cfg = SecurityConfig(confidence_threshold=1.5)
        errors = _validate_security_config(cfg)
        assert any("confidence" in e.lower() for e in errors)

    def test_invalid_severity_threshold(self) -> None:
        cfg = SecurityConfig(severity_threshold="invalid")
        errors = _validate_security_config(cfg)
        assert any("severity" in e.lower() for e in errors)

    def test_valid_severity_levels(self) -> None:
        for level in ("critical", "high", "medium", "low", "info"):
            cfg = SecurityConfig(severity_threshold=level)
            errors = _validate_security_config(cfg)
            assert len(errors) == 0, f"Unexpected error for severity {level}"

    def test_confidence_boundary_zero(self) -> None:
        cfg = SecurityConfig(confidence_threshold=0.0)
        errors = _validate_security_config(cfg)
        assert len(errors) == 0

    def test_confidence_boundary_one(self) -> None:
        cfg = SecurityConfig(confidence_threshold=1.0)
        errors = _validate_security_config(cfg)
        assert len(errors) == 0
