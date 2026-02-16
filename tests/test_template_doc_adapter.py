"""Tests for template doc adapter (src/nit/adapters/docs/template_adapter.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.adapters.docs.template_adapter import TemplateDocAdapter


@pytest.fixture
def adapter() -> TemplateDocAdapter:
    return TemplateDocAdapter()


# ── Properties ──────────────────────────────────────────────────


def test_name(adapter: TemplateDocAdapter) -> None:
    assert adapter.name == "templatedoc"


def test_language(adapter: TemplateDocAdapter) -> None:
    assert adapter.language == "python"


# ── detect ──────────────────────────────────────────────────────


def test_detect_by_config_file(adapter: TemplateDocAdapter, tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "template.conf").write_text("config")
    assert adapter.detect(tmp_path) is True


def test_detect_by_directory_structure(adapter: TemplateDocAdapter, tmp_path: Path) -> None:
    (tmp_path / "docs" / "source").mkdir(parents=True)
    assert adapter.detect(tmp_path) is True


def test_detect_by_dependency(adapter: TemplateDocAdapter, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes(b'[project]\ndependencies = ["templatedoc>=1.0"]\n')
    assert adapter.detect(tmp_path) is True


def test_detect_false(adapter: TemplateDocAdapter, tmp_path: Path) -> None:
    assert adapter.detect(tmp_path) is False


# ── _has_dependency ─────────────────────────────────────────────


def test_has_dependency_true(adapter: TemplateDocAdapter, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes(b'[project]\ndependencies = ["templatedoc"]\n')
    assert adapter._has_dependency(tmp_path) is True


def test_has_dependency_in_optional(adapter: TemplateDocAdapter, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes(
        b'[project]\n[project.optional-dependencies]\ndocs = ["templatedoc"]\n'
    )
    assert adapter._has_dependency(tmp_path) is True


def test_has_dependency_false(adapter: TemplateDocAdapter, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes(b'[project]\ndependencies = ["sphinx"]\n')
    assert adapter._has_dependency(tmp_path) is False


def test_has_dependency_no_pyproject(adapter: TemplateDocAdapter, tmp_path: Path) -> None:
    assert adapter._has_dependency(tmp_path) is False


def test_has_dependency_invalid_toml(adapter: TemplateDocAdapter, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes(b"this is not valid toml {{{}}")
    assert adapter._has_dependency(tmp_path) is False


# ── get_doc_pattern ─────────────────────────────────────────────


def test_get_doc_pattern(adapter: TemplateDocAdapter) -> None:
    patterns = adapter.get_doc_pattern()
    assert isinstance(patterns, list)
    assert any("*.rst" in p for p in patterns)
    assert any("*.md" in p for p in patterns)


# ── get_prompt_template ─────────────────────────────────────────


def test_get_prompt_template_import_error(adapter: TemplateDocAdapter) -> None:
    # Template adapter references a non-existent DocGenerationPrompt class
    with pytest.raises(ImportError):
        adapter.get_prompt_template()


# ── validate_doc ────────────────────────────────────────────────


def test_validate_doc_valid_rst(adapter: TemplateDocAdapter) -> None:
    doc = "Title\n=====\n\nSome content.\n"
    result = adapter.validate_doc(doc)
    assert result.valid is True


def test_validate_doc_rst_mismatched_underline(adapter: TemplateDocAdapter) -> None:
    doc = "Title\n===\n"
    result = adapter.validate_doc(doc)
    assert result.valid is False
    assert any("underline" in e.lower() for e in result.errors)


def test_validate_doc_empty(adapter: TemplateDocAdapter) -> None:
    result = adapter.validate_doc("")
    assert result.valid is True
