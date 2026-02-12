"""Tests for the DoxygenAdapter (adapters/docs/doxygen_adapter.py).

Covers detection (Doxyfile, Doxyfile.in, CMake find_package(Doxygen)),
doc pattern, prompt template, doc build, and Doxygen comment validation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.base import DocFrameworkAdapter, ValidationResult
from nit.adapters.docs.doxygen_adapter import DoxygenAdapter
from nit.llm.prompts.doc_generation import DocGenerationTemplate


def _write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file under *root*."""
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


# ── Sample Doxygen Comments ───────────────────────────────────────


_VALID_DOXYGEN_FUNCTION = """
/**
 * @brief Calculates the sum of two numbers.
 *
 * @param a First number.
 * @param b Second number.
 * @return The sum of a and b.
 */
"""

_VALID_DOXYGEN_CLASS = """
/**
 * @brief Represents a user account.
 *
 * @details This class handles user authentication and profile management.
 */
"""

_INVALID_DOXYGEN_NO_START = """
 * Missing opening /**
 * @param x A parameter.
 * @return Something.
 */
"""

_INVALID_DOXYGEN_NO_END = """
/**
 * @brief Missing closing
 * @param x A parameter.
"""

_DOXYGEN_WITH_UNKNOWN_TAG = """
/**
 * @brief Some function.
 *
 * @param x Description.
 * @return A value.
 * @customTag Non-standard tag.
 */
"""


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> DoxygenAdapter:
    """Create a DoxygenAdapter instance."""
    return DoxygenAdapter()


@pytest.fixture
def project_with_doxyfile(tmp_path: Path) -> Path:
    """Create a project with Doxyfile."""
    (tmp_path / "Doxyfile").write_text(
        "PROJECT_NAME = Test\nINPUT = .\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def project_with_doxyfile_in(tmp_path: Path) -> Path:
    """Create a project with Doxyfile.in."""
    (tmp_path / "Doxyfile.in").write_text(
        "@INCLUDE = config.in\nPROJECT_NAME = Test\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def project_with_cmake_doxygen(tmp_path: Path) -> Path:
    """Create a project with CMake find_package(Doxygen)."""
    _write_file(
        tmp_path,
        "CMakeLists.txt",
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(MyProject)\n"
        "find_package(Doxygen)\n"
        "if(DOXYGEN_FOUND)\n"
        "  doxygen_add_docs(docs ${CMAKE_SOURCE_DIR})\n"
        "endif()\n",
    )
    return tmp_path


@pytest.fixture
def project_with_cmake_no_doxygen(tmp_path: Path) -> Path:
    """Create a project with CMake but no Doxygen."""
    _write_file(
        tmp_path,
        "CMakeLists.txt",
        "cmake_minimum_required(VERSION 3.10)\nproject(MyProject)\n",
    )
    return tmp_path


@pytest.fixture
def project_no_doxygen(tmp_path: Path) -> Path:
    """Create a project without Doxygen."""
    _write_file(tmp_path, "main.cpp", "int main() { return 0; }\n")
    return tmp_path


# ── Tests ───────────────────────────────────────────────────────────


def test_adapter_is_doc_framework_adapter(adapter: DoxygenAdapter) -> None:
    """DoxygenAdapter implements DocFrameworkAdapter."""
    assert isinstance(adapter, DocFrameworkAdapter)


def test_adapter_name(adapter: DoxygenAdapter) -> None:
    """Adapter name is 'doxygen'."""
    assert adapter.name == "doxygen"


def test_adapter_language(adapter: DoxygenAdapter) -> None:
    """Adapter language is 'cpp'."""
    assert adapter.language == "cpp"


def test_detect_via_doxyfile(adapter: DoxygenAdapter, project_with_doxyfile: Path) -> None:
    """Detection succeeds when Doxyfile exists."""
    assert adapter.detect(project_with_doxyfile) is True


def test_detect_via_doxyfile_in(adapter: DoxygenAdapter, project_with_doxyfile_in: Path) -> None:
    """Detection succeeds when Doxyfile.in exists."""
    assert adapter.detect(project_with_doxyfile_in) is True


def test_detect_via_cmake(adapter: DoxygenAdapter, project_with_cmake_doxygen: Path) -> None:
    """Detection succeeds when CMakeLists.txt contains find_package(Doxygen)."""
    assert adapter.detect(project_with_cmake_doxygen) is True


def test_detect_fails_cmake_without_doxygen(
    adapter: DoxygenAdapter, project_with_cmake_no_doxygen: Path
) -> None:
    """Detection fails when CMake does not reference Doxygen."""
    assert adapter.detect(project_with_cmake_no_doxygen) is False


def test_detect_fails_no_doxygen(adapter: DoxygenAdapter, project_no_doxygen: Path) -> None:
    """Detection fails when Doxygen is not present."""
    assert adapter.detect(project_no_doxygen) is False


def test_detect_empty_project(adapter: DoxygenAdapter, tmp_path: Path) -> None:
    """Detection fails in an empty project."""
    assert adapter.detect(tmp_path) is False


def test_get_doc_pattern(adapter: DoxygenAdapter) -> None:
    """get_doc_pattern returns C/C++ file patterns."""
    patterns = adapter.get_doc_pattern()
    assert "**/*.h" in patterns
    assert "**/*.hpp" in patterns
    assert "**/*.cpp" in patterns
    assert "**/*.c" in patterns
    assert any("build" in p for p in patterns if p.startswith("!"))


def test_get_prompt_template(adapter: DoxygenAdapter) -> None:
    """get_prompt_template returns a DocGenerationTemplate for Doxygen."""
    template = adapter.get_prompt_template()
    assert isinstance(template, DocGenerationTemplate)
    assert template.name == "doc_generation_doxygen"


@pytest.mark.asyncio
async def test_build_docs_with_doxyfile(
    adapter: DoxygenAdapter, project_with_doxyfile: Path
) -> None:
    """build_docs runs doxygen with Doxyfile when present."""
    with patch(
        "nit.adapters.docs.doxygen_adapter._run_command", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")

        result = await adapter.build_docs(project_with_doxyfile)

        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args
        cmd = args[0][0]
        assert cmd[0] == "doxygen"
        assert str(project_with_doxyfile / "Doxyfile") in cmd
        assert args[1]["cwd"] == project_with_doxyfile


@pytest.mark.asyncio
async def test_build_docs_with_doxyfile_in(
    adapter: DoxygenAdapter, project_with_doxyfile_in: Path
) -> None:
    """build_docs runs doxygen with Doxyfile.in when present."""
    with patch(
        "nit.adapters.docs.doxygen_adapter._run_command", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")

        result = await adapter.build_docs(project_with_doxyfile_in)

        assert result is True
        args = mock_run.call_args
        cmd = args[0][0]
        assert cmd[0] == "doxygen"
        assert "Doxyfile.in" in cmd[1]


@pytest.mark.asyncio
async def test_build_docs_without_config(adapter: DoxygenAdapter, tmp_path: Path) -> None:
    """build_docs runs doxygen without config path when no Doxyfile exists."""
    with patch(
        "nit.adapters.docs.doxygen_adapter._run_command", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")

        result = await adapter.build_docs(tmp_path)

        assert result is True
        args = mock_run.call_args
        assert args[0][0] == ["doxygen"]


@pytest.mark.asyncio
async def test_build_docs_failure(adapter: DoxygenAdapter, project_with_doxyfile: Path) -> None:
    """build_docs returns False on failure."""
    with patch(
        "nit.adapters.docs.doxygen_adapter._run_command", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = MagicMock(success=False, stdout="", stderr="Error: invalid config")

        result = await adapter.build_docs(project_with_doxyfile)

        assert result is False


@pytest.mark.asyncio
async def test_build_docs_timeout(adapter: DoxygenAdapter, project_with_doxyfile: Path) -> None:
    """build_docs respects timeout parameter."""
    with patch(
        "nit.adapters.docs.doxygen_adapter._run_command", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")

        await adapter.build_docs(project_with_doxyfile, timeout=60.0)

        args = mock_run.call_args
        assert args[1]["timeout"] == 60.0


def test_validate_doc_valid_function_comment(adapter: DoxygenAdapter) -> None:
    """validate_doc accepts valid Doxygen function comment."""
    result = adapter.validate_doc(_VALID_DOXYGEN_FUNCTION)
    assert isinstance(result, ValidationResult)
    assert result.valid is True
    assert len(result.errors) == 0


def test_validate_doc_valid_class_comment(adapter: DoxygenAdapter) -> None:
    """validate_doc accepts valid Doxygen class comment."""
    result = adapter.validate_doc(_VALID_DOXYGEN_CLASS)
    assert result.valid is True
    assert len(result.errors) == 0


def test_validate_doc_missing_start(adapter: DoxygenAdapter) -> None:
    """validate_doc rejects comment without /** opening."""
    result = adapter.validate_doc(_INVALID_DOXYGEN_NO_START)
    assert result.valid is False
    assert any("must start with" in e.lower() for e in result.errors)


def test_validate_doc_missing_end(adapter: DoxygenAdapter) -> None:
    """validate_doc rejects comment without */ closing."""
    result = adapter.validate_doc(_INVALID_DOXYGEN_NO_END)
    assert result.valid is False
    assert any("must end with" in e.lower() for e in result.errors)


def test_validate_doc_unknown_tag_warning(adapter: DoxygenAdapter) -> None:
    """validate_doc warns about unknown Doxygen tags."""
    result = adapter.validate_doc(_DOXYGEN_WITH_UNKNOWN_TAG)
    assert result.valid is True
    assert len(result.warnings) > 0
    assert any("customTag" in w for w in result.warnings)


def test_validate_doc_standard_tags(adapter: DoxygenAdapter) -> None:
    """validate_doc recognizes standard Doxygen tags."""
    doc = """
/**
 * @brief Test function.
 *
 * @param x Description.
 * @return A value.
 * @see other_func
 * @note Internal use only.
 * @warning Deprecated.
 * @deprecated Use new_func.
 * @author Jane Doe
 * @date 2025-01-01
 * @version 1.0
 * @throws std::runtime_error On failure.
 * @pre x > 0
 * @post result >= 0
 */
"""
    result = adapter.validate_doc(doc)
    assert result.valid is True
    assert len(result.warnings) == 0


def test_validate_doc_empty_string(adapter: DoxygenAdapter) -> None:
    """validate_doc handles empty string."""
    result = adapter.validate_doc("")
    assert result.valid is False
    assert len(result.errors) > 0


def test_validate_doc_multiline_formatting(adapter: DoxygenAdapter) -> None:
    """validate_doc accepts properly formatted multiline comments."""
    doc = """
/**
 * @brief A longer description that spans
 *        multiple lines.
 *
 * @param first  First parameter.
 * @param second Second parameter.
 * @return A complex result.
 */
"""
    result = adapter.validate_doc(doc)
    assert result.valid is True
