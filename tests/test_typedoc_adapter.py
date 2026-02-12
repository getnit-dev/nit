"""Tests for the TypeDocAdapter (adapters/docs/typedoc_adapter.py).

Covers detection, doc pattern, prompt template, doc building, and
TSDoc comment validation with sample TypeScript fixtures.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.base import DocFrameworkAdapter, ValidationResult
from nit.adapters.docs.typedoc_adapter import TypeDocAdapter
from nit.llm.prompts.doc_generation import DocGenerationTemplate

# ── Helpers ──────────────────────────────────────────────────────


def _write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file under *root*."""
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def _write_package_json(root: Path, data: dict[str, object]) -> None:
    """Write a ``package.json`` at *root*."""
    (root / "package.json").write_text(json.dumps(data), encoding="utf-8")


def _write_typedoc_json(root: Path, data: dict[str, object] | None = None) -> None:
    """Write a ``typedoc.json`` at *root*."""
    if data is None:
        data = {"entryPoints": ["src"], "out": "docs"}
    (root / "typedoc.json").write_text(json.dumps(data), encoding="utf-8")


# ── Sample TSDoc Comments ───────────────────────────────────────


_VALID_TSDOC_FUNCTION = """
/**
 * Calculates the sum of two numbers.
 *
 * @param a - The first number.
 * @param b - The second number.
 * @returns The sum of a and b.
 */
"""

_VALID_TSDOC_CLASS = """
/**
 * Represents a user account.
 *
 * @remarks
 * This class handles user authentication and profile management.
 *
 * @public
 */
"""

_INVALID_TSDOC_NO_START = """
 * Missing opening /**
 * @param x - A parameter.
 * @returns Something.
 */
"""

_INVALID_TSDOC_NO_END = """
/**
 * Missing closing
 * @param x - A parameter.
"""

_TSDOC_WITH_UNKNOWN_TAG = """
/**
 * Some function.
 *
 * @param x - A parameter.
 * @customTag This is not a standard TSDoc tag.
 * @returns A value.
 */
"""


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> TypeDocAdapter:
    """Create a TypeDocAdapter instance."""
    return TypeDocAdapter()


@pytest.fixture
def project_with_typedoc_json(tmp_path: Path) -> Path:
    """Create a project with typedoc.json."""
    _write_typedoc_json(tmp_path)
    return tmp_path


@pytest.fixture
def project_with_package_json_dep(tmp_path: Path) -> Path:
    """Create a project with typedoc in package.json devDependencies."""
    _write_package_json(
        tmp_path,
        {
            "name": "test-project",
            "devDependencies": {
                "typedoc": "^0.25.0",
                "typescript": "^5.0.0",
            },
        },
    )
    return tmp_path


@pytest.fixture
def project_with_both(tmp_path: Path) -> Path:
    """Create a project with both typedoc.json and package.json."""
    _write_typedoc_json(tmp_path)
    _write_package_json(
        tmp_path,
        {
            "name": "test-project",
            "devDependencies": {
                "typedoc": "^0.25.0",
            },
        },
    )
    return tmp_path


@pytest.fixture
def project_no_typedoc(tmp_path: Path) -> Path:
    """Create a project without TypeDoc."""
    _write_package_json(
        tmp_path,
        {
            "name": "test-project",
            "devDependencies": {
                "jest": "^29.0.0",
            },
        },
    )
    return tmp_path


# ── Tests ───────────────────────────────────────────────────────


def test_adapter_is_doc_framework_adapter(adapter: TypeDocAdapter) -> None:
    """TypeDocAdapter implements DocFrameworkAdapter."""
    assert isinstance(adapter, DocFrameworkAdapter)


def test_adapter_name(adapter: TypeDocAdapter) -> None:
    """Adapter name is 'typedoc'."""
    assert adapter.name == "typedoc"


def test_adapter_language(adapter: TypeDocAdapter) -> None:
    """Adapter language is 'typescript'."""
    assert adapter.language == "typescript"


def test_detect_via_typedoc_json(adapter: TypeDocAdapter, project_with_typedoc_json: Path) -> None:
    """Detection succeeds when typedoc.json exists."""
    assert adapter.detect(project_with_typedoc_json) is True


def test_detect_via_package_json(
    adapter: TypeDocAdapter, project_with_package_json_dep: Path
) -> None:
    """Detection succeeds when typedoc is in package.json devDependencies."""
    assert adapter.detect(project_with_package_json_dep) is True


def test_detect_with_both(adapter: TypeDocAdapter, project_with_both: Path) -> None:
    """Detection succeeds when both config file and dependency exist."""
    assert adapter.detect(project_with_both) is True


def test_detect_fails_no_typedoc(adapter: TypeDocAdapter, project_no_typedoc: Path) -> None:
    """Detection fails when TypeDoc is not present."""
    assert adapter.detect(project_no_typedoc) is False


def test_detect_empty_project(adapter: TypeDocAdapter, tmp_path: Path) -> None:
    """Detection fails in an empty project."""
    assert adapter.detect(tmp_path) is False


def test_detect_invalid_package_json(adapter: TypeDocAdapter, tmp_path: Path) -> None:
    """Detection handles invalid package.json gracefully."""
    _write_file(tmp_path, "package.json", "{ invalid json")
    assert adapter.detect(tmp_path) is False


def test_get_doc_pattern(adapter: TypeDocAdapter) -> None:
    """get_doc_pattern returns TypeScript file patterns."""
    patterns = adapter.get_doc_pattern()
    assert "**/*.ts" in patterns
    assert "**/*.tsx" in patterns
    # Should exclude test files
    assert "!**/*.test.ts" in patterns or any("test" in p for p in patterns if p.startswith("!"))
    # Should exclude node_modules
    assert any("node_modules" in p for p in patterns if p.startswith("!"))


def test_get_prompt_template(adapter: TypeDocAdapter) -> None:
    """get_prompt_template returns a DocGenerationTemplate."""
    template = adapter.get_prompt_template()
    assert isinstance(template, DocGenerationTemplate)
    assert template.name == "doc_generation_typedoc"


@pytest.mark.asyncio
async def test_build_docs_with_config(
    adapter: TypeDocAdapter, project_with_typedoc_json: Path
) -> None:
    """build_docs executes npx typedoc when config exists."""
    with patch(
        "nit.adapters.docs.typedoc_adapter._run_command", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")

        result = await adapter.build_docs(project_with_typedoc_json)

        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args[0][0] == ["npx", "typedoc"]
        assert args[1]["cwd"] == project_with_typedoc_json


@pytest.mark.asyncio
async def test_build_docs_without_config(adapter: TypeDocAdapter, tmp_path: Path) -> None:
    """build_docs uses default args when no config file exists."""
    with patch(
        "nit.adapters.docs.typedoc_adapter._run_command", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")

        result = await adapter.build_docs(tmp_path)

        assert result is True
        args = mock_run.call_args
        cmd = args[0][0]
        assert cmd[0:2] == ["npx", "typedoc"]
        assert "--out" in cmd
        assert "docs" in cmd


@pytest.mark.asyncio
async def test_build_docs_failure(adapter: TypeDocAdapter, project_with_typedoc_json: Path) -> None:
    """build_docs returns False on failure."""
    with patch(
        "nit.adapters.docs.typedoc_adapter._run_command", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = MagicMock(success=False, stdout="", stderr="Error: No entry points")

        result = await adapter.build_docs(project_with_typedoc_json)

        assert result is False


@pytest.mark.asyncio
async def test_build_docs_timeout(adapter: TypeDocAdapter, project_with_typedoc_json: Path) -> None:
    """build_docs respects timeout parameter."""
    with patch(
        "nit.adapters.docs.typedoc_adapter._run_command", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")

        await adapter.build_docs(project_with_typedoc_json, timeout=60.0)

        args = mock_run.call_args
        assert args[1]["timeout"] == 60.0


def test_validate_doc_valid_function_comment(adapter: TypeDocAdapter) -> None:
    """validate_doc accepts valid TSDoc function comment."""
    result = adapter.validate_doc(_VALID_TSDOC_FUNCTION)
    assert isinstance(result, ValidationResult)
    assert result.valid is True
    assert len(result.errors) == 0


def test_validate_doc_valid_class_comment(adapter: TypeDocAdapter) -> None:
    """validate_doc accepts valid TSDoc class comment."""
    result = adapter.validate_doc(_VALID_TSDOC_CLASS)
    assert isinstance(result, ValidationResult)
    assert result.valid is True
    assert len(result.errors) == 0


def test_validate_doc_missing_start(adapter: TypeDocAdapter) -> None:
    """validate_doc rejects comment without /** opening."""
    result = adapter.validate_doc(_INVALID_TSDOC_NO_START)
    assert result.valid is False
    assert any("must start with" in e.lower() for e in result.errors)


def test_validate_doc_missing_end(adapter: TypeDocAdapter) -> None:
    """validate_doc rejects comment without */ closing."""
    result = adapter.validate_doc(_INVALID_TSDOC_NO_END)
    assert result.valid is False
    assert any("must end with" in e.lower() for e in result.errors)


def test_validate_doc_unknown_tag_warning(adapter: TypeDocAdapter) -> None:
    """validate_doc warns about unknown TSDoc tags."""
    result = adapter.validate_doc(_TSDOC_WITH_UNKNOWN_TAG)
    # Should still be valid (warnings, not errors)
    assert result.valid is True
    assert len(result.warnings) > 0
    assert any("customTag" in w for w in result.warnings)


def test_validate_doc_standard_tags(adapter: TypeDocAdapter) -> None:
    """validate_doc recognizes standard TSDoc tags."""
    doc = """
    /**
     * Test function.
     *
     * @param x - A parameter.
     * @returns A value.
     * @throws {Error} On failure.
     * @example
     * ```
     * test(5);
     * ```
     * @deprecated Use newTest instead.
     * @see newTest
     * @since 1.0.0
     * @remarks Some remarks.
     * @typeParam T - A type parameter.
     * @defaultValue 42
     * @public
     */
    """
    result = adapter.validate_doc(doc)
    assert result.valid is True
    # No warnings for standard tags
    assert len(result.warnings) == 0


def test_validate_doc_empty_string(adapter: TypeDocAdapter) -> None:
    """validate_doc handles empty string."""
    result = adapter.validate_doc("")
    assert result.valid is False
    assert len(result.errors) > 0


def test_validate_doc_multiline_formatting(adapter: TypeDocAdapter) -> None:
    """validate_doc accepts properly formatted multiline comments."""
    doc = """
    /**
     * A longer description that spans
     * multiple lines and includes proper
     * formatting.
     *
     * @param first - First parameter with
     *                long description.
     * @param second - Second parameter.
     * @returns A complex object with
     *          multiple properties.
     */
    """
    result = adapter.validate_doc(doc)
    assert result.valid is True
