"""Tests for doc adapter _run_command and _CommandResult across all adapters.

Each doc adapter duplicates _run_command / _CommandResult for subprocess execution.
This module tests all of them to ensure consistent behaviour and coverage.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if sys.platform == "win32":
    # Avoid ProactorEventLoop cleanup errors on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from nit.adapters.docs import doxygen_adapter as doxygen
from nit.adapters.docs import godoc_adapter as godoc
from nit.adapters.docs import jsdoc_adapter as jsdoc
from nit.adapters.docs import mkdocs_adapter as mkdocs
from nit.adapters.docs import rustdoc_adapter as rustdoc
from nit.adapters.docs import sphinx_adapter as sphinx
from nit.adapters.docs import typedoc_adapter as typedoc

# ── _CommandResult Tests ────────────────────────────────────────

# Each adapter has its own _CommandResult — test them all.

_CMD_RESULT_CLASSES: list[type[Any]] = [
    doxygen._CommandResult,
    godoc._CommandResult,
    jsdoc._CommandResult,
    mkdocs._CommandResult,
    rustdoc._CommandResult,
    sphinx._CommandResult,
    typedoc._CommandResult,
]


@pytest.mark.parametrize("cls", _CMD_RESULT_CLASSES, ids=lambda c: c.__module__.split(".")[-1])
class TestCommandResult:
    def test_success_when_returncode_zero(self, cls: type[Any]) -> None:
        result = cls(returncode=0, stdout="ok", stderr="")
        assert result.success is True

    def test_failure_when_returncode_nonzero(self, cls: type[Any]) -> None:
        result = cls(returncode=1, stdout="", stderr="error")
        assert result.success is False

    def test_failure_when_timed_out(self, cls: type[Any]) -> None:
        result = cls(returncode=0, stdout="", stderr="", timed_out=True)
        assert result.success is False

    def test_failure_when_not_found(self, cls: type[Any]) -> None:
        result = cls(returncode=0, stdout="", stderr="", not_found=True)
        assert result.success is False


# ── _run_command Tests ──────────────────────────────────────────

_RUN_COMMAND_FUNCS = [
    ("doxygen_adapter", doxygen._run_command),
    ("godoc_adapter", godoc._run_command),
    ("jsdoc_adapter", jsdoc._run_command),
    ("mkdocs_adapter", mkdocs._run_command),
    ("rustdoc_adapter", rustdoc._run_command),
    ("sphinx_adapter", sphinx._run_command),
    ("typedoc_adapter", typedoc._run_command),
]


def _make_mock_proc(
    returncode: int = 0,
    stdout: bytes = b"output",
    stderr: bytes = b"",
) -> MagicMock:
    """Create a mock subprocess."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


@pytest.mark.parametrize(
    "name,run_cmd", _RUN_COMMAND_FUNCS, ids=lambda x: x if isinstance(x, str) else ""
)
class TestRunCommand:
    def test_success(self, name: str, run_cmd: Any, tmp_path: Path) -> None:
        proc = _make_mock_proc(returncode=0, stdout=b"hello", stderr=b"")
        module_path = f"nit.adapters.docs.{name}.asyncio.create_subprocess_exec"

        with patch(module_path, new=AsyncMock(return_value=proc)):
            result = asyncio.run(run_cmd(["echo", "hi"], cwd=tmp_path, timeout=10.0))
        assert result.success is True
        assert result.stdout == "hello"
        assert result.returncode == 0

    def test_timeout(self, name: str, run_cmd: Any, tmp_path: Path) -> None:
        module_path = f"nit.adapters.docs.{name}.asyncio"

        mock_proc = _make_mock_proc()

        async def _raise_timeout(*args: Any, **kwargs: Any) -> None:
            raise TimeoutError

        with (
            patch(
                f"{module_path}.create_subprocess_exec",
                new=AsyncMock(return_value=mock_proc),
            ),
            patch(f"{module_path}.wait_for", side_effect=_raise_timeout),
        ):
            result = asyncio.run(run_cmd(["slow"], cwd=tmp_path, timeout=0.001))
        assert result.success is False
        assert result.timed_out is True
        assert "timed out" in result.stderr

    def test_file_not_found(self, name: str, run_cmd: Any, tmp_path: Path) -> None:
        module_path = f"nit.adapters.docs.{name}.asyncio.create_subprocess_exec"

        with patch(module_path, new=AsyncMock(side_effect=FileNotFoundError)):
            result = asyncio.run(run_cmd(["nonexistent"], cwd=tmp_path, timeout=10.0))
        assert result.success is False
        assert result.not_found is True
        assert result.returncode == 127

    def test_returncode_none_defaults_to_one(self, name: str, run_cmd: Any, tmp_path: Path) -> None:
        proc = _make_mock_proc(returncode=0)
        proc.returncode = None
        module_path = f"nit.adapters.docs.{name}.asyncio.create_subprocess_exec"

        with patch(module_path, new=AsyncMock(return_value=proc)):
            result = asyncio.run(run_cmd(["cmd"], cwd=tmp_path, timeout=10.0))
        assert result.returncode == 1


# ── Sphinx-specific helper tests ────────────────────────────────


class TestSphinxHelpers:
    def test_has_sphinx_in_requirements(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("sphinx>=4.0\n")
        assert sphinx._has_sphinx_in_requirements(tmp_path) is True

    def test_has_sphinx_in_requirements_false(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("pytest\nblack\n")
        assert sphinx._has_sphinx_in_requirements(tmp_path) is False

    def test_has_sphinx_in_requirements_no_file(self, tmp_path: Path) -> None:
        assert sphinx._has_sphinx_in_requirements(tmp_path) is False

    def test_has_sphinx_in_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["sphinx"]\n')
        assert sphinx._has_sphinx_in_pyproject(tmp_path) is True

    def test_has_sphinx_in_pyproject_false(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
        assert sphinx._has_sphinx_in_pyproject(tmp_path) is False

    def test_has_sphinx_in_pyproject_no_file(self, tmp_path: Path) -> None:
        assert sphinx._has_sphinx_in_pyproject(tmp_path) is False

    def test_has_build_sphinx_in_setup_cfg(self, tmp_path: Path) -> None:
        (tmp_path / "setup.cfg").write_text("[build_sphinx]\nsource-dir = docs\n")
        assert sphinx._has_build_sphinx_in_setup_cfg(tmp_path) is True

    def test_has_build_sphinx_in_setup_cfg_false(self, tmp_path: Path) -> None:
        (tmp_path / "setup.cfg").write_text("[metadata]\nname = foo\n")
        assert sphinx._has_build_sphinx_in_setup_cfg(tmp_path) is False

    def test_has_build_sphinx_in_setup_cfg_no_file(self, tmp_path: Path) -> None:
        assert sphinx._has_build_sphinx_in_setup_cfg(tmp_path) is False


# ── Doxygen-specific helper tests ───────────────────────────────


class TestDoxygenHelpers:
    def test_cmake_uses_doxygen_found(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text("find_package(Doxygen)\n")
        assert doxygen._cmake_uses_doxygen(tmp_path) is True

    def test_cmake_uses_doxygen_not_found(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text("find_package(GTest)\n")
        assert doxygen._cmake_uses_doxygen(tmp_path) is False

    def test_cmake_uses_doxygen_no_cmake(self, tmp_path: Path) -> None:
        assert doxygen._cmake_uses_doxygen(tmp_path) is False
