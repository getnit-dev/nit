"""Tests for MkDocsAdapter (adapters/docs/mkdocs_adapter.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.base import DocFrameworkAdapter
from nit.adapters.docs.mkdocs_adapter import MkDocsAdapter
from nit.llm.prompts.doc_generation import DocGenerationTemplate


def _write_file(root: Path, rel: str, content: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


@pytest.fixture
def adapter() -> MkDocsAdapter:
    return MkDocsAdapter()


@pytest.fixture
def project_with_mkdocs_yml(tmp_path: Path) -> Path:
    _write_file(
        tmp_path,
        "mkdocs.yml",
        "site_name: Test\nnav:\n  - Home: index.md\n",
    )
    return tmp_path


@pytest.fixture
def project_with_mkdocs_yaml(tmp_path: Path) -> Path:
    _write_file(
        tmp_path,
        "mkdocs.yaml",
        "site_name: Test\n",
    )
    return tmp_path


def test_is_doc_framework_adapter(adapter: MkDocsAdapter) -> None:
    assert isinstance(adapter, DocFrameworkAdapter)


def test_name(adapter: MkDocsAdapter) -> None:
    assert adapter.name == "mkdocs"


def test_language(adapter: MkDocsAdapter) -> None:
    assert adapter.language == "markdown"


def test_detect_via_mkdocs_yml(adapter: MkDocsAdapter, project_with_mkdocs_yml: Path) -> None:
    assert adapter.detect(project_with_mkdocs_yml) is True


def test_detect_via_mkdocs_yaml(adapter: MkDocsAdapter, project_with_mkdocs_yaml: Path) -> None:
    assert adapter.detect(project_with_mkdocs_yaml) is True


def test_detect_empty(tmp_path: Path, adapter: MkDocsAdapter) -> None:
    assert adapter.detect(tmp_path) is False


def test_get_doc_pattern(adapter: MkDocsAdapter) -> None:
    patterns = adapter.get_doc_pattern()
    assert "docs/**/*.md" in patterns
    assert "**/*.md" in patterns


def test_get_prompt_template(adapter: MkDocsAdapter) -> None:
    template = adapter.get_prompt_template()
    assert isinstance(template, DocGenerationTemplate)
    assert template.name == "doc_generation_mkdocs"


@pytest.mark.asyncio
async def test_build_docs_success(adapter: MkDocsAdapter, project_with_mkdocs_yml: Path) -> None:
    with patch(
        "nit.adapters.docs.mkdocs_adapter._run_command",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")
        result = await adapter.build_docs(project_with_mkdocs_yml)
        assert result is True
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["mkdocs", "build"]


@pytest.mark.asyncio
async def test_build_docs_failure(adapter: MkDocsAdapter, project_with_mkdocs_yml: Path) -> None:
    with patch(
        "nit.adapters.docs.mkdocs_adapter._run_command",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = MagicMock(success=False, stderr="Config error")
        result = await adapter.build_docs(project_with_mkdocs_yml)
        assert result is False


def test_validate_doc_valid(adapter: MkDocsAdapter) -> None:
    doc = "# Title\n\nSome **markdown** content."
    result = adapter.validate_doc(doc)
    assert result.valid is True


def test_validate_doc_empty(adapter: MkDocsAdapter) -> None:
    result = adapter.validate_doc("")
    assert result.valid is False
    assert any("empty" in e.lower() for e in result.errors)
