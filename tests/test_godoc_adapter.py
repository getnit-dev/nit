"""Tests for GoDocAdapter (adapters/docs/godoc_adapter.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.base import DocFrameworkAdapter
from nit.adapters.docs.godoc_adapter import GoDocAdapter
from nit.llm.prompts.doc_generation import DocGenerationTemplate


def _write_file(root: Path, rel: str, content: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


@pytest.fixture
def adapter() -> GoDocAdapter:
    return GoDocAdapter()


@pytest.fixture
def project_with_go_mod(tmp_path: Path) -> Path:
    _write_file(tmp_path, "go.mod", "module example.com/pkg\n\ngo 1.21\n")
    return tmp_path


@pytest.fixture
def project_with_go_files(tmp_path: Path) -> Path:
    _write_file(tmp_path, "main.go", "package main\n\nfunc main() {}\n")
    return tmp_path


def test_is_doc_framework_adapter(adapter: GoDocAdapter) -> None:
    assert isinstance(adapter, DocFrameworkAdapter)


def test_name(adapter: GoDocAdapter) -> None:
    assert adapter.name == "godoc"


def test_language(adapter: GoDocAdapter) -> None:
    assert adapter.language == "go"


def test_detect_via_go_mod(adapter: GoDocAdapter, project_with_go_mod: Path) -> None:
    assert adapter.detect(project_with_go_mod) is True


def test_detect_via_go_files(adapter: GoDocAdapter, project_with_go_files: Path) -> None:
    assert adapter.detect(project_with_go_files) is True


def test_detect_empty(tmp_path: Path, adapter: GoDocAdapter) -> None:
    assert adapter.detect(tmp_path) is False


def test_get_doc_pattern(adapter: GoDocAdapter) -> None:
    patterns = adapter.get_doc_pattern()
    assert "**/*.go" in patterns
    assert any("_test" in p or "test" in p for p in patterns)
    assert any("vendor" in p for p in patterns)


def test_get_prompt_template(adapter: GoDocAdapter) -> None:
    template = adapter.get_prompt_template()
    assert isinstance(template, DocGenerationTemplate)
    assert template.name == "doc_generation_godoc"


@pytest.mark.asyncio
async def test_build_docs_success(adapter: GoDocAdapter, project_with_go_mod: Path) -> None:
    with patch(
        "nit.adapters.docs.godoc_adapter._run_command",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")
        result = await adapter.build_docs(project_with_go_mod)
        assert result is True
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["go", "build", "./..."]


@pytest.mark.asyncio
async def test_build_docs_failure(adapter: GoDocAdapter, project_with_go_mod: Path) -> None:
    with patch(
        "nit.adapters.docs.godoc_adapter._run_command",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = MagicMock(success=False, stderr="build failed")
        result = await adapter.build_docs(project_with_go_mod)
        assert result is False


def test_validate_doc_line_comment(adapter: GoDocAdapter) -> None:
    doc = "// Add adds two integers.\n// Returns the sum."
    result = adapter.validate_doc(doc)
    assert result.valid is True


def test_validate_doc_block_comment(adapter: GoDocAdapter) -> None:
    doc = "/*\n * Add adds two integers.\n * Returns the sum.\n */"
    result = adapter.validate_doc(doc)
    assert result.valid is True


def test_validate_doc_invalid(adapter: GoDocAdapter) -> None:
    result = adapter.validate_doc("not a comment")
    assert result.valid is False


def test_validate_doc_empty(adapter: GoDocAdapter) -> None:
    result = adapter.validate_doc("")
    assert result.valid is False
