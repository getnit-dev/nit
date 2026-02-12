"""GoDoc adapter for Go documentation generation.

This adapter (task 4.5.2):
1. Detects Go module (go.mod, *.go files)
2. Generates Go doc comments (// Package ..., // FunctionName ...)
3. Verifies package builds (go build ./...)
4. Validates Go doc comment syntax
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


class GoDocAdapter(DocFrameworkAdapter):
    """Adapter for Go documentation (godoc-style comments).

    Go uses simple comment blocks above declarations;
    the Go toolchain serves them via `go doc` and pkg.go.dev.
    """

    @property
    def name(self) -> str:
        """Framework identifier."""
        return "godoc"

    @property
    def language(self) -> str:
        """Primary language."""
        return "go"

    def detect(self, project_path: Path) -> bool:
        """Return True if this is a Go module (go.mod or *.go present)."""
        if (project_path / "go.mod").exists():
            logger.info("Detected Go via go.mod")
            return True
        for p in project_path.rglob("*.go"):
            if p.is_file():
                logger.info("Detected Go via *.go files")
                return True
        return False

    def get_doc_pattern(self) -> list[str]:
        """Return glob patterns for Go source files."""
        return ["**/*.go", "!**/*_test.go", "!**/vendor/**"]

    def get_prompt_template(self) -> PromptTemplate:
        """Return the prompt template for generating Go doc comments."""
        context = DocGenerationContext(
            changes=[],
            doc_framework="godoc",
            language="go",
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
        """Verify Go package builds (documentation is in source; go doc reads it)."""
        logger.info("Verifying Go build in %s", project_path)
        result = await _run_command(
            ["go", "build", "./..."],
            cwd=project_path,
            timeout=timeout,
        )
        if result.success:
            logger.info("Go build succeeded")
            return True
        logger.error("Go build failed: %s", result.stderr)
        return False

    def validate_doc(self, doc_code: str) -> ValidationResult:
        """Validate that the doc is valid Go comment (// or /* */)."""
        errors: list[str] = []
        warnings: list[str] = []
        stripped = doc_code.strip()
        if not stripped:
            errors.append("Go doc comment cannot be empty")
        if stripped and not stripped.startswith(("//", "/*")):
            errors.append("Go doc comments must start with // or /*")
        if stripped.startswith("/*") and not stripped.rstrip().endswith("*/"):
            errors.append("Block comment must end with */")
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
