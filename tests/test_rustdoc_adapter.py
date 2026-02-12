"""Tests for RustDocAdapter (adapters/docs/rustdoc_adapter.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.base import DocFrameworkAdapter, ValidationResult
from nit.adapters.docs.rustdoc_adapter import RustDocAdapter
from nit.llm.prompts.doc_generation import DocGenerationTemplate


def _write_file(root: Path, rel: str, content: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


@pytest.fixture
def adapter() -> RustDocAdapter:
    return RustDocAdapter()


@pytest.fixture
def project_with_cargo(tmp_path: Path) -> Path:
    _write_file(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "foo"\nversion = "0.1.0"\n',
    )
    return tmp_path


def test_is_doc_framework_adapter(adapter: RustDocAdapter) -> None:
    assert isinstance(adapter, DocFrameworkAdapter)


def test_name(adapter: RustDocAdapter) -> None:
    assert adapter.name == "rustdoc"


def test_language(adapter: RustDocAdapter) -> None:
    assert adapter.language == "rust"


def test_detect_via_cargo_toml(adapter: RustDocAdapter, project_with_cargo: Path) -> None:
    assert adapter.detect(project_with_cargo) is True


def test_detect_empty(tmp_path: Path, adapter: RustDocAdapter) -> None:
    assert adapter.detect(tmp_path) is False


def test_get_doc_pattern(adapter: RustDocAdapter) -> None:
    patterns = adapter.get_doc_pattern()
    assert "**/*.rs" in patterns
    assert any("target" in p for p in patterns)


def test_get_prompt_template(adapter: RustDocAdapter) -> None:
    template = adapter.get_prompt_template()
    assert isinstance(template, DocGenerationTemplate)
    assert template.name == "doc_generation_rustdoc"


@pytest.mark.asyncio
async def test_build_docs_success(adapter: RustDocAdapter, project_with_cargo: Path) -> None:
    with patch(
        "nit.adapters.docs.rustdoc_adapter._run_command",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")
        result = await adapter.build_docs(project_with_cargo)
        assert result is True
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["cargo", "doc", "--no-deps"]


@pytest.mark.asyncio
async def test_build_docs_failure(adapter: RustDocAdapter, project_with_cargo: Path) -> None:
    with patch(
        "nit.adapters.docs.rustdoc_adapter._run_command",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = MagicMock(success=False, stderr="error")
        result = await adapter.build_docs(project_with_cargo)
        assert result is False


def test_validate_doc_triple_slash(adapter: RustDocAdapter) -> None:
    doc = "/// Adds two numbers.\n///\n/// # Arguments\n/// * `a` - First.\n/// * `b` - Second."
    result = adapter.validate_doc(doc)
    assert isinstance(result, ValidationResult)
    assert result.valid is True


def test_validate_doc_inner(adapter: RustDocAdapter) -> None:
    doc = "//! Module-level docs."
    result = adapter.validate_doc(doc)
    assert result.valid is True


def test_validate_doc_invalid_prefix(adapter: RustDocAdapter) -> None:
    result = adapter.validate_doc("Not a doc comment.")
    assert result.valid is False


def test_validate_doc_empty(adapter: RustDocAdapter) -> None:
    result = adapter.validate_doc("")
    assert result.valid is False
