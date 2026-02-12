"""Tests for JSDocAdapter (adapters/docs/jsdoc_adapter.py)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.base import DocFrameworkAdapter, ValidationResult
from nit.adapters.docs.jsdoc_adapter import JSDocAdapter
from nit.llm.prompts.doc_generation import DocGenerationTemplate


def _write_file(root: Path, rel: str, content: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def _write_package_json(root: Path, data: dict[str, object]) -> None:
    (root / "package.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def adapter() -> JSDocAdapter:
    return JSDocAdapter()


@pytest.fixture
def project_with_jsdoc_json(tmp_path: Path) -> Path:
    _write_file(tmp_path, "jsdoc.json", '{"source": {"include": ["src"]}}')
    return tmp_path


@pytest.fixture
def project_with_package_dep(tmp_path: Path) -> Path:
    _write_package_json(
        tmp_path,
        {"name": "p", "devDependencies": {"jsdoc": "^4.0.0"}},
    )
    return tmp_path


@pytest.fixture
def project_no_jsdoc(tmp_path: Path) -> Path:
    _write_package_json(tmp_path, {"name": "p", "devDependencies": {"jest": "^29.0.0"}})
    return tmp_path


def test_is_doc_framework_adapter(adapter: JSDocAdapter) -> None:
    assert isinstance(adapter, DocFrameworkAdapter)


def test_name(adapter: JSDocAdapter) -> None:
    assert adapter.name == "jsdoc"


def test_language(adapter: JSDocAdapter) -> None:
    assert adapter.language == "javascript"


def test_detect_via_jsdoc_json(adapter: JSDocAdapter, project_with_jsdoc_json: Path) -> None:
    assert adapter.detect(project_with_jsdoc_json) is True


def test_detect_via_package_json(adapter: JSDocAdapter, project_with_package_dep: Path) -> None:
    assert adapter.detect(project_with_package_dep) is True


def test_detect_fails_no_jsdoc(adapter: JSDocAdapter, project_no_jsdoc: Path) -> None:
    assert adapter.detect(project_no_jsdoc) is False


def test_detect_empty(tmp_path: Path, adapter: JSDocAdapter) -> None:
    assert adapter.detect(tmp_path) is False


def test_get_doc_pattern(adapter: JSDocAdapter) -> None:
    patterns = adapter.get_doc_pattern()
    assert "**/*.js" in patterns
    assert "**/*.jsx" in patterns
    assert any("node_modules" in p for p in patterns)


def test_get_prompt_template(adapter: JSDocAdapter) -> None:
    template = adapter.get_prompt_template()
    assert isinstance(template, DocGenerationTemplate)
    assert template.name == "doc_generation_jsdoc"


@pytest.mark.asyncio
async def test_build_docs_success(adapter: JSDocAdapter, project_with_jsdoc_json: Path) -> None:
    with patch(
        "nit.adapters.docs.jsdoc_adapter._run_command",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")
        result = await adapter.build_docs(project_with_jsdoc_json)
        assert result is True
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][:2] == ["npx", "jsdoc"]


@pytest.mark.asyncio
async def test_build_docs_failure(adapter: JSDocAdapter, project_with_jsdoc_json: Path) -> None:
    with patch(
        "nit.adapters.docs.jsdoc_adapter._run_command",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = MagicMock(success=False, stderr="Error")
        result = await adapter.build_docs(project_with_jsdoc_json)
        assert result is False


def test_validate_doc_valid(adapter: JSDocAdapter) -> None:
    doc = (
        "/**\n * Sum of two numbers.\n * @param {number} a - First.\n"
        " * @param {number} b - Second.\n * @returns {number} Sum.\n */"
    )
    result = adapter.validate_doc(doc)
    assert isinstance(result, ValidationResult)
    assert result.valid is True


def test_validate_doc_no_start(adapter: JSDocAdapter) -> None:
    result = adapter.validate_doc(" * @param x\n */")
    assert result.valid is False
    assert any("start" in e.lower() for e in result.errors)


def test_validate_doc_no_end(adapter: JSDocAdapter) -> None:
    result = adapter.validate_doc("/**\n * Missing closing")
    assert result.valid is False
    assert any("end" in e.lower() for e in result.errors)


def test_validate_doc_empty(adapter: JSDocAdapter) -> None:
    result = adapter.validate_doc("")
    assert result.valid is False
