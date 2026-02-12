"""Sphinx adapter for Python documentation generation.

This adapter (task 4.3):
1. Detects Sphinx presence (docs/conf.py, conf.py, sphinx dep, setup.cfg [build_sphinx])
2. Generates Python docstrings (Google/NumPy style) for undocumented functions/classes
3. Generates RST pages for new modules
4. Builds documentation using sphinx-build
5. Validates docstring syntax (Google/NumPy style)
"""

from __future__ import annotations

import asyncio
import configparser
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.adapters.base import DocFrameworkAdapter, ValidationResult
from nit.llm.prompts.doc_generation import DocGenerationContext, DocGenerationTemplate
from nit.parsing.treesitter import has_parse_errors, parse_code

if TYPE_CHECKING:
    from pathlib import Path

    from nit.llm.prompts.base import PromptTemplate

logger = logging.getLogger(__name__)


@dataclass
class _CommandResult:
    """Result of a subprocess command execution."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    not_found: bool = False

    @property
    def success(self) -> bool:
        """Return True if the command succeeded."""
        return self.returncode == 0 and not self.timed_out and not self.not_found


async def _run_command(cmd: list[str], *, cwd: Path, timeout: float) -> _CommandResult:
    """Run a command and return the result.

    Args:
        cmd: Command and arguments to run.
        cwd: Working directory for the command.
        timeout: Maximum time in seconds to wait for the command.

    Returns:
        _CommandResult with stdout, stderr, and return code.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        return _CommandResult(
            returncode=1,
            stdout="",
            stderr=f"Command timed out after {timeout:.1f}s",
            timed_out=True,
        )
    except FileNotFoundError:
        return _CommandResult(
            returncode=127,
            stdout="",
            stderr=f"Command not found: {cmd[0]}",
            not_found=True,
        )

    return _CommandResult(
        returncode=proc.returncode if proc.returncode is not None else 1,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
    )


def _has_sphinx_in_requirements(project_path: Path) -> bool:
    """Return True if sphinx appears in requirements.txt or similar."""
    for name in ("requirements.txt", "requirements-docs.txt", "requirements-dev.txt"):
        path = project_path / name
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                if "sphinx" in text.lower():
                    return True
            except OSError:
                pass
    return False


def _has_sphinx_in_pyproject(project_path: Path) -> bool:
    """Return True if sphinx is in pyproject.toml dependencies."""
    path = project_path / "pyproject.toml"
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
        # Simple heuristic: [project] dependencies or [project.optional-dependencies]
        if "sphinx" in text.lower():
            return True
    except OSError:
        pass
    return False


def _has_build_sphinx_in_setup_cfg(project_path: Path) -> bool:
    """Return True if setup.cfg contains [build_sphinx] section."""
    path = project_path / "setup.cfg"
    if not path.exists():
        return False
    try:
        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        return "build_sphinx" in parser or "tool:build_sphinx" in parser
    except configparser.Error:
        return False


class SphinxAdapter(DocFrameworkAdapter):
    """Adapter for Sphinx documentation generation.

    Sphinx is the standard documentation generator for Python projects,
    using RST/MyST and docstrings in Google or NumPy style.
    """

    @property
    def name(self) -> str:
        """Framework identifier."""
        return "sphinx"

    @property
    def language(self) -> str:
        """Primary language."""
        return "python"

    def detect(self, project_path: Path) -> bool:
        """Return True if Sphinx is present in the project (task 4.3.1).

        Detection signals:
        1. docs/conf.py exists
        2. conf.py at project root exists
        3. sphinx in requirements.txt or pyproject.toml
        4. setup.cfg with [build_sphinx] section

        Args:
            project_path: Root of the project.

        Returns:
            True if Sphinx is detected, False otherwise.
        """
        found = False
        if (project_path / "docs" / "conf.py").exists():
            logger.info("Detected Sphinx via docs/conf.py")
            found = True
        elif (project_path / "conf.py").exists():
            logger.info("Detected Sphinx via conf.py")
            found = True
        elif _has_build_sphinx_in_setup_cfg(project_path):
            logger.info("Detected Sphinx via setup.cfg [build_sphinx]")
            found = True
        elif (project_path / "docs").is_dir() and _has_sphinx_in_requirements(project_path):
            logger.info("Detected Sphinx via docs/ + requirements.txt")
            found = True
        elif _has_sphinx_in_pyproject(project_path):
            if (project_path / "docs" / "conf.py").exists() or (project_path / "conf.py").exists():
                found = True
            else:
                logger.info("Detected Sphinx via pyproject.toml sphinx dependency")
                found = True
        return found

    def get_doc_pattern(self) -> list[str]:
        """Return glob patterns for Python source files (task 4.3.1).

        Returns:
            List of glob patterns matching Python files to document.
        """
        return [
            "**/*.py",
            "!**/test_*.py",
            "!**/*_test.py",
            "!**/tests/**",
            "!**/test/**",
            "!**/.venv/**",
            "!**/venv/**",
            "!**/build/**",
            "!**/dist/**",
        ]

    def get_prompt_template(self) -> PromptTemplate:
        """Return the prompt template for generating Google/NumPy-style docstrings (task 4.3.2).

        Returns:
            A DocGenerationTemplate configured for Sphinx (Python).
        """
        context = DocGenerationContext(
            changes=[],
            doc_framework="sphinx",
            language="python",
            source_path="",
            source_code="",
        )
        return DocGenerationTemplate(context)

    def generate_module_rst(self, module_name: str, members: list[str] | None = None) -> str:
        """Generate RST content for a module page (task 4.3.3).

        Produces a minimal RST page suitable for Sphinx autodoc, e.g. for
        inclusion in index.rst or as a new module doc page.

        Args:
            module_name: Dotted module name (e.g. 'mypackage.utils').
            members: Optional list of members to document. If None, uses automodule.

        Returns:
            RST string for the module.
        """
        lines = [
            f"{module_name}",
            "=" * len(module_name),
            "",
            f".. automodule:: {module_name}",
            "   :members:",
            "   :undoc-members:",
            "   :show-inheritance:",
            "",
        ]
        if members:
            lines = [
                f"{module_name}",
                "=" * len(module_name),
                "",
                f".. automodule:: {module_name}",
                "   :members: " + ", ".join(members),
                "   :undoc-members:",
                "   :show-inheritance:",
                "",
            ]
        return "\n".join(lines)

    async def build_docs(
        self,
        project_path: Path,
        *,
        timeout: float = 120.0,
    ) -> bool:
        """Build documentation using sphinx-build (task 4.3.1).

        Executes sphinx-build -b html to generate HTML documentation.
        Uses docs/ as source when docs/conf.py exists, else current dir when conf.py exists.

        Args:
            project_path: Root of the project containing the documentation.
            timeout: Maximum seconds to wait for doc build.

        Returns:
            True if the documentation built successfully, False otherwise.
        """
        logger.info("Building Sphinx documentation in %s", project_path)

        docs_conf = project_path / "docs" / "conf.py"
        root_conf = project_path / "conf.py"

        if docs_conf.exists():
            sourcedir = project_path / "docs"
            outputdir = project_path / "docs" / "_build"
        elif root_conf.exists():
            sourcedir = project_path
            outputdir = project_path / "_build"
        else:
            logger.error("No conf.py found (neither docs/conf.py nor conf.py)")
            return False

        cmd = [
            "sphinx-build",
            "-b",
            "html",
            str(sourcedir),
            str(outputdir),
        ]

        result = await _run_command(
            cmd,
            cwd=project_path,
            timeout=timeout,
        )

        if result.success:
            logger.info("Sphinx build succeeded")
            return True

        logger.error("Sphinx build failed: %s", result.stderr)
        return False

    def validate_doc(self, doc_code: str) -> ValidationResult:
        """Validate that a Python docstring is syntactically correct (task 4.3.2).

        Checks for triple-quoted string and optional Google/NumPy-style sections
        (Args, Parameters, Returns, Raises, Examples, Note, etc.).

        Args:
            doc_code: Docstring or Python code containing a docstring to validate.

        Returns:
            ValidationResult with validity status and any errors/warnings.
        """
        errors: list[str] = []
        warnings: list[str] = []

        stripped = doc_code.strip()

        # Must look like a docstring (triple quotes)
        triple_quotes = ('"""', "'''")
        if not stripped.startswith(triple_quotes):
            errors.append("Python docstrings must start with triple quotes (\"\"\" or ''').")
        if not stripped.endswith(triple_quotes):
            errors.append("Python docstrings must end with triple quotes")

        # If it's a raw docstring (triple-quoted), wrap in a function so Python can parse it
        if stripped.startswith(triple_quotes):
            indented = doc_code.strip().replace("\n", "\n    ")
            test_code = f"def _doc():\n    {indented}\n    pass\n"
        else:
            test_code = doc_code

        try:
            source = test_code.encode("utf-8")
            tree = parse_code(source, "python")
            root = tree.root_node
            if has_parse_errors(root):
                errors.append("Docstring contains syntax errors")
        except Exception as e:
            errors.append(f"Failed to parse as Python: {e}")

        # Optional: warn if common Google/NumPy sections are missing (for multi-line docstrings)
        if not errors and "\n" in stripped:
            section_pattern = re.compile(
                r"^\s*(Args?|Parameters?|Returns?|Raises?|Yields?|Examples?|"
                r"Note|Warning|See Also)\s*:",
                re.MULTILINE | re.IGNORECASE,
            )
            if not section_pattern.search(stripped):
                warnings.append(
                    "No standard Google/NumPy sections (Args, Returns, etc.) found; "
                    "consider adding them"
                )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
