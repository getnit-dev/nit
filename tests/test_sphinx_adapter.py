"""Tests for the SphinxAdapter (adapters/docs/sphinx_adapter.py).

Covers detection (docs/conf.py, conf.py, setup.cfg, deps), doc pattern,
prompt template, RST page generation, doc build, and docstring validation.
"""

from __future__ import annotations

import configparser
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.base import DocFrameworkAdapter, ValidationResult
from nit.adapters.docs.sphinx_adapter import (
    SphinxAdapter,
    _CommandResult,
    _has_build_sphinx_in_setup_cfg,
    _has_sphinx_in_pyproject,
    _has_sphinx_in_requirements,
    _run_command,
)
from nit.llm.prompts.doc_generation import DocGenerationTemplate

# ── Helpers ──────────────────────────────────────────────────────


def _write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file under *root*."""
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def _write_setup_cfg(root: Path, sections: dict[str, dict[str, str]]) -> None:
    """Write a setup.cfg with given sections."""
    parser = configparser.ConfigParser()
    for section, options in sections.items():
        parser[section] = options
    with (root / "setup.cfg").open("w", encoding="utf-8") as f:
        parser.write(f)


# ── Sample docstrings ────────────────────────────────────────────


_GOOGLE_STYLE_DOC = '''
"""Brief description.

Extended description if needed.

Args:
    param1: Description of param1.
    param2: Description of param2.

Returns:
    Description of return value.

Raises:
    ValueError: When something is wrong.
"""
'''

_NUMPY_STYLE_DOC = '''
"""Brief description.

Extended description.

Parameters
----------
param1 : str
    Description.
param2 : int, optional
    Optional param.

Returns
-------
bool
    Return description.
"""
'''

_SIMPLE_DOC = '''"""One-line summary."""'''

_INVALID_NO_START = "One line without triple quotes."

_INVALID_NO_END = '''"""Missing closing quotes'''

_EMPTY = ""


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> SphinxAdapter:
    """Create a SphinxAdapter instance."""
    return SphinxAdapter()


@pytest.fixture
def project_with_docs_conf(tmp_path: Path) -> Path:
    """Create a project with docs/conf.py."""
    _write_file(tmp_path, "docs/conf.py", "# Sphinx config\n")
    return tmp_path


@pytest.fixture
def project_with_root_conf(tmp_path: Path) -> Path:
    """Create a project with conf.py at root."""
    _write_file(tmp_path, "conf.py", "# Sphinx config\n")
    return tmp_path


@pytest.fixture
def project_with_setup_cfg_sphinx(tmp_path: Path) -> Path:
    """Create a project with setup.cfg [build_sphinx]."""
    _write_setup_cfg(tmp_path, {"build_sphinx": {"source-dir": "docs", "build-dir": "docs/_build"}})
    return tmp_path


@pytest.fixture
def project_with_requirements_sphinx(tmp_path: Path) -> Path:
    """Create a project with sphinx in requirements.txt and docs/."""
    (tmp_path / "docs").mkdir(exist_ok=True)
    _write_file(tmp_path, "requirements.txt", "sphinx>=5.0\n")
    _write_file(tmp_path, "docs/conf.py", "# Sphinx\n")
    return tmp_path


@pytest.fixture
def project_with_pyproject_sphinx(tmp_path: Path) -> Path:
    """Create a project with sphinx in pyproject.toml and docs/conf.py."""
    _write_file(
        tmp_path,
        "pyproject.toml",
        "[project]\nname = 'p'\ndependencies = ['sphinx>=5']\n",
    )
    _write_file(tmp_path, "docs/conf.py", "# Sphinx\n")
    return tmp_path


@pytest.fixture
def project_no_sphinx(tmp_path: Path) -> Path:
    """Create a project without Sphinx."""
    _write_file(tmp_path, "README.md", "No Sphinx here.")
    return tmp_path


# ── Tests ───────────────────────────────────────────────────────


def test_adapter_is_doc_framework_adapter(adapter: SphinxAdapter) -> None:
    """SphinxAdapter implements DocFrameworkAdapter."""
    assert isinstance(adapter, DocFrameworkAdapter)


def test_adapter_name(adapter: SphinxAdapter) -> None:
    """Adapter name is 'sphinx'."""
    assert adapter.name == "sphinx"


def test_adapter_language(adapter: SphinxAdapter) -> None:
    """Adapter language is 'python'."""
    assert adapter.language == "python"


def test_detect_via_docs_conf(adapter: SphinxAdapter, project_with_docs_conf: Path) -> None:
    """Detection succeeds when docs/conf.py exists."""
    assert adapter.detect(project_with_docs_conf) is True


def test_detect_via_root_conf(adapter: SphinxAdapter, project_with_root_conf: Path) -> None:
    """Detection succeeds when conf.py exists at root."""
    assert adapter.detect(project_with_root_conf) is True


def test_detect_via_setup_cfg(adapter: SphinxAdapter, project_with_setup_cfg_sphinx: Path) -> None:
    """Detection succeeds when setup.cfg has [build_sphinx]."""
    assert adapter.detect(project_with_setup_cfg_sphinx) is True


def test_detect_via_requirements(
    adapter: SphinxAdapter, project_with_requirements_sphinx: Path
) -> None:
    """Detection succeeds when docs/ exists and requirements.txt has sphinx."""
    assert adapter.detect(project_with_requirements_sphinx) is True


def test_detect_via_pyproject(adapter: SphinxAdapter, project_with_pyproject_sphinx: Path) -> None:
    """Detection succeeds when pyproject.toml has sphinx and docs/conf.py."""
    assert adapter.detect(project_with_pyproject_sphinx) is True


def test_detect_fails_no_sphinx(adapter: SphinxAdapter, project_no_sphinx: Path) -> None:
    """Detection fails when Sphinx is not present."""
    assert adapter.detect(project_no_sphinx) is False


def test_detect_empty_project(adapter: SphinxAdapter, tmp_path: Path) -> None:
    """Detection fails in an empty project."""
    assert adapter.detect(tmp_path) is False


def test_get_doc_pattern(adapter: SphinxAdapter) -> None:
    """get_doc_pattern returns Python file patterns and excludes tests."""
    patterns = adapter.get_doc_pattern()
    assert "**/*.py" in patterns
    assert any("test" in p for p in patterns if p.startswith("!"))
    assert any("tests" in p or "test/" in p for p in patterns if p.startswith("!"))


def test_get_prompt_template(adapter: SphinxAdapter) -> None:
    """get_prompt_template returns a DocGenerationTemplate for sphinx."""
    template = adapter.get_prompt_template()
    assert isinstance(template, DocGenerationTemplate)
    assert template.name == "doc_generation_sphinx"


def test_generate_module_rst_default(adapter: SphinxAdapter) -> None:
    """generate_module_rst produces RST with automodule and :members:."""
    rst = adapter.generate_module_rst("mypackage.utils")
    assert "mypackage.utils" in rst
    assert "automodule" in rst
    assert ":members:" in rst
    assert ":undoc-members:" in rst
    assert ":show-inheritance:" in rst


def test_generate_module_rst_with_members(adapter: SphinxAdapter) -> None:
    """generate_module_rst can list specific members."""
    rst = adapter.generate_module_rst("mypackage.utils", members=["foo", "bar"])
    assert "mypackage.utils" in rst
    assert "foo" in rst
    assert "bar" in rst
    assert ":members: foo, bar" in rst or "foo, bar" in rst


@pytest.mark.asyncio
async def test_build_docs_with_docs_conf(
    adapter: SphinxAdapter, project_with_docs_conf: Path
) -> None:
    """build_docs runs sphinx-build with docs/ as source when docs/conf.py exists."""
    with patch("nit.adapters.docs.sphinx_adapter._run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")

        result = await adapter.build_docs(project_with_docs_conf)

        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args
        cmd = args[0][0]
        assert cmd[0] == "sphinx-build"
        assert "-b" in cmd
        assert "html" in cmd
        assert any("docs" in str(arg) for arg in cmd)
        assert args[1]["cwd"] == project_with_docs_conf


@pytest.mark.asyncio
async def test_build_docs_with_root_conf(
    adapter: SphinxAdapter, project_with_root_conf: Path
) -> None:
    """build_docs uses current dir as source when conf.py is at root."""
    with patch("nit.adapters.docs.sphinx_adapter._run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")

        result = await adapter.build_docs(project_with_root_conf)

        assert result is True
        args = mock_run.call_args
        cmd = args[0][0]
        assert "sphinx-build" in cmd


@pytest.mark.asyncio
async def test_build_docs_no_conf_fails(adapter: SphinxAdapter, tmp_path: Path) -> None:
    """build_docs returns False when no conf.py exists."""
    result = await adapter.build_docs(tmp_path)
    assert result is False


@pytest.mark.asyncio
async def test_build_docs_failure(adapter: SphinxAdapter, project_with_docs_conf: Path) -> None:
    """build_docs returns False on sphinx-build failure."""
    with patch("nit.adapters.docs.sphinx_adapter._run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = MagicMock(success=False, stdout="", stderr="Sphinx error.")

        result = await adapter.build_docs(project_with_docs_conf)

        assert result is False


@pytest.mark.asyncio
async def test_build_docs_timeout(adapter: SphinxAdapter, project_with_docs_conf: Path) -> None:
    """build_docs respects timeout parameter."""
    with patch("nit.adapters.docs.sphinx_adapter._run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = MagicMock(success=True, stdout="", stderr="")

        await adapter.build_docs(project_with_docs_conf, timeout=60.0)

        args = mock_run.call_args
        assert args[1]["timeout"] == 60.0


def test_validate_doc_google_style(adapter: SphinxAdapter) -> None:
    """validate_doc accepts Google-style docstring."""
    result = adapter.validate_doc(_GOOGLE_STYLE_DOC)
    assert isinstance(result, ValidationResult)
    assert result.valid is True
    assert len(result.errors) == 0


def test_validate_doc_numpy_style(adapter: SphinxAdapter) -> None:
    """validate_doc accepts NumPy-style docstring."""
    result = adapter.validate_doc(_NUMPY_STYLE_DOC)
    assert result.valid is True
    assert len(result.errors) == 0


def test_validate_doc_simple(adapter: SphinxAdapter) -> None:
    """validate_doc accepts simple one-line docstring."""
    result = adapter.validate_doc(_SIMPLE_DOC)
    assert result.valid is True


def test_validate_doc_missing_start(adapter: SphinxAdapter) -> None:
    """validate_doc rejects text without triple-quote start."""
    result = adapter.validate_doc(_INVALID_NO_START)
    assert result.valid is False
    assert any("triple" in e.lower() or "start" in e.lower() for e in result.errors)


def test_validate_doc_missing_end(adapter: SphinxAdapter) -> None:
    """validate_doc rejects docstring without closing quotes."""
    result = adapter.validate_doc(_INVALID_NO_END)
    assert result.valid is False
    assert any("end" in e.lower() or "triple" in e.lower() for e in result.errors)


def test_validate_doc_empty(adapter: SphinxAdapter) -> None:
    """validate_doc rejects empty string."""
    result = adapter.validate_doc(_EMPTY)
    assert result.valid is False
    assert len(result.errors) > 0


def test_validate_doc_no_sections_warning(adapter: SphinxAdapter) -> None:
    """validate_doc may warn when no Args/Returns sections in multiline doc."""
    doc = '''"""A multiline docstring with no standard sections."""'''
    result = adapter.validate_doc(doc)
    # Single line may not trigger section warning
    assert result.valid is True


# ── Coverage gap tests: _run_command, helper functions, edge cases ─────


@pytest.mark.asyncio
async def test_run_command_success(tmp_path: Path) -> None:
    """_run_command returns success on good command."""
    result = await _run_command(
        [sys.executable, "-c", "print('hello')"], cwd=tmp_path, timeout=10.0
    )
    assert result.success is True
    assert "hello" in result.stdout
    assert result.timed_out is False
    assert result.not_found is False


@pytest.mark.asyncio
async def test_run_command_timeout(tmp_path: Path) -> None:
    """_run_command returns timed_out on timeout."""
    result = await _run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        timeout=0.01,
    )
    assert result.timed_out is True
    assert result.success is False


@pytest.mark.asyncio
async def test_run_command_not_found(tmp_path: Path) -> None:
    """_run_command returns not_found when command does not exist."""
    result = await _run_command(
        ["nonexistent_command_12345"],
        cwd=tmp_path,
        timeout=5.0,
    )
    assert result.not_found is True
    assert result.success is False
    assert result.returncode == 127


def test_command_result_success_property() -> None:
    """_CommandResult.success returns correct value."""
    ok = _CommandResult(returncode=0, stdout="", stderr="")
    assert ok.success is True

    fail = _CommandResult(returncode=1, stdout="", stderr="err")
    assert fail.success is False

    timeout = _CommandResult(returncode=1, stdout="", stderr="", timed_out=True)
    assert timeout.success is False

    notfound = _CommandResult(returncode=127, stdout="", stderr="", not_found=True)
    assert notfound.success is False


def test_has_sphinx_in_requirements_dev(tmp_path: Path) -> None:
    """Detects sphinx in requirements-dev.txt."""
    _write_file(tmp_path, "requirements-dev.txt", "pytest\nsphinx>=5.0\nblack\n")
    assert _has_sphinx_in_requirements(tmp_path) is True


def test_has_sphinx_in_requirements_docs(tmp_path: Path) -> None:
    """Detects sphinx in requirements-docs.txt."""
    _write_file(tmp_path, "requirements-docs.txt", "sphinx-rtd-theme\n")
    assert _has_sphinx_in_requirements(tmp_path) is True


def test_has_sphinx_in_requirements_missing(tmp_path: Path) -> None:
    """Returns False when no requirements file found."""
    assert _has_sphinx_in_requirements(tmp_path) is False


def test_has_sphinx_in_requirements_no_sphinx(tmp_path: Path) -> None:
    """Returns False when requirements has no sphinx."""
    _write_file(tmp_path, "requirements.txt", "pytest\nblack\n")
    assert _has_sphinx_in_requirements(tmp_path) is False


def test_has_sphinx_in_pyproject_missing(tmp_path: Path) -> None:
    """Returns False when no pyproject.toml exists."""
    assert _has_sphinx_in_pyproject(tmp_path) is False


def test_has_sphinx_in_pyproject_no_sphinx(tmp_path: Path) -> None:
    """Returns False when pyproject.toml has no sphinx."""
    _write_file(
        tmp_path,
        "pyproject.toml",
        "[project]\nname = 'foo'\ndependencies = ['pytest']\n",
    )
    assert _has_sphinx_in_pyproject(tmp_path) is False


def test_has_build_sphinx_in_setup_cfg_missing(tmp_path: Path) -> None:
    """Returns False when no setup.cfg exists."""
    assert _has_build_sphinx_in_setup_cfg(tmp_path) is False


def test_has_build_sphinx_in_setup_cfg_no_section(tmp_path: Path) -> None:
    """Returns False when setup.cfg has no [build_sphinx] section."""
    _write_setup_cfg(tmp_path, {"metadata": {"name": "foo"}})
    assert _has_build_sphinx_in_setup_cfg(tmp_path) is False


def test_detect_via_pyproject_without_confpy(adapter: SphinxAdapter, tmp_path: Path) -> None:
    """Detects Sphinx via pyproject.toml even without conf.py."""
    _write_file(
        tmp_path,
        "pyproject.toml",
        "[project]\nname='p'\ndependencies=['sphinx>=5']\n",
    )
    assert adapter.detect(tmp_path) is True


def test_detect_via_requirements_without_docs_conf(adapter: SphinxAdapter, tmp_path: Path) -> None:
    """Returns False when sphinx in requirements but no docs/ dir."""
    _write_file(tmp_path, "requirements.txt", "sphinx>=5.0\n")
    assert adapter.detect(tmp_path) is False


def test_validate_doc_multiline_no_sections_warns(
    adapter: SphinxAdapter,
) -> None:
    """validate_doc warns when multiline doc has no standard sections."""
    doc = '''"""This is a multiline docstring.

It has multiple lines but no Args/Returns/Raises sections.

Just regular prose explanation of the thing.
"""'''
    result = adapter.validate_doc(doc)
    assert result.valid is True
    assert len(result.warnings) > 0
    assert any("section" in w.lower() for w in result.warnings)
