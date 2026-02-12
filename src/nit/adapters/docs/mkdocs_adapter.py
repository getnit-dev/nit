"""MkDocs adapter for Markdown documentation generation.

This adapter (task 4.5.4):
1. Detects MkDocs presence (mkdocs.yml)
2. Generates Markdown pages for MkDocs sites
3. Builds documentation using `mkdocs build`
4. Validates Markdown syntax (basic checks)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.adapters.base import DocFrameworkAdapter, ValidationResult
from nit.llm.prompts.doc_generation import DocGenerationContext, DocGenerationTemplate

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
    """Run a command and return the result."""
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


class MkDocsAdapter(DocFrameworkAdapter):
    """Adapter for MkDocs documentation (Markdown sites).

    MkDocs builds static sites from Markdown files;
    commonly used with Python projects and docs/.
    """

    @property
    def name(self) -> str:
        """Framework identifier."""
        return "mkdocs"

    @property
    def language(self) -> str:
        """Primary language (Markdown)."""
        return "markdown"

    def detect(self, project_path: Path) -> bool:
        """Return True if MkDocs is present (mkdocs.yml)."""
        if (project_path / "mkdocs.yml").exists():
            logger.info("Detected MkDocs via mkdocs.yml")
            return True
        if (project_path / "mkdocs.yaml").exists():
            logger.info("Detected MkDocs via mkdocs.yaml")
            return True
        return False

    def get_doc_pattern(self) -> list[str]:
        """Return glob patterns for MkDocs doc source files."""
        return ["docs/**/*.md", "**/*.md", "!**/node_modules/**", "!**/site/**"]

    def get_prompt_template(self) -> PromptTemplate:
        """Return the prompt template for generating MkDocs Markdown."""
        context = DocGenerationContext(
            changes=[],
            doc_framework="mkdocs",
            language="markdown",
            source_path="",
            source_code="",
        )
        return DocGenerationTemplate(context)

    async def build_docs(
        self,
        project_path: Path,
        *,
        timeout: float = 120.0,
    ) -> bool:
        """Build documentation using mkdocs build."""
        logger.info("Building MkDocs documentation in %s", project_path)
        result = await _run_command(
            ["mkdocs", "build"],
            cwd=project_path,
            timeout=timeout,
        )
        if result.success:
            logger.info("MkDocs build succeeded")
            return True
        logger.error("MkDocs build failed: %s", result.stderr)
        return False

    def validate_doc(self, doc_code: str) -> ValidationResult:
        """Validate that the doc is non-empty (Markdown is permissive)."""
        errors: list[str] = []
        warnings: list[str] = []
        if not doc_code.strip():
            errors.append("Markdown content cannot be empty")
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
