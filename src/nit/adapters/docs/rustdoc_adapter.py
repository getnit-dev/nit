"""RustDoc adapter for Rust documentation generation.

This adapter (task 4.5.3):
1. Detects Cargo project (Cargo.toml)
2. Generates Rust doc comments (/// with markdown)
3. Builds documentation using `cargo doc`
4. Validates Rust doc comment syntax
"""

from __future__ import annotations

import asyncio
import logging
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


class RustDocAdapter(DocFrameworkAdapter):
    """Adapter for Rust documentation (rustdoc).

    Rust uses /// or //! doc comments with markdown;
    cargo doc builds HTML documentation.
    """

    @property
    def name(self) -> str:
        """Framework identifier."""
        return "rustdoc"

    @property
    def language(self) -> str:
        """Primary language."""
        return "rust"

    def detect(self, project_path: Path) -> bool:
        """Return True if this is a Cargo project (Cargo.toml)."""
        if (project_path / "Cargo.toml").exists():
            logger.info("Detected Rust via Cargo.toml")
            return True
        return False

    def get_doc_pattern(self) -> list[str]:
        """Return glob patterns for Rust source files."""
        return ["**/*.rs", "!**/target/**"]

    def get_prompt_template(self) -> PromptTemplate:
        """Return the prompt template for generating Rust doc comments."""
        context = DocGenerationContext(
            changes=[],
            doc_framework="rustdoc",
            language="rust",
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
        """Build documentation using cargo doc."""
        logger.info("Building RustDoc documentation in %s", project_path)
        result = await _run_command(
            ["cargo", "doc", "--no-deps"],
            cwd=project_path,
            timeout=timeout,
        )
        if result.success:
            logger.info("RustDoc build succeeded")
            return True
        logger.error("RustDoc build failed: %s", result.stderr)
        return False

    def validate_doc(self, doc_code: str) -> ValidationResult:
        """Validate that the doc is valid Rust doc comment (/// or //!)."""
        errors: list[str] = []
        warnings: list[str] = []
        lines = [line.strip() for line in doc_code.strip().splitlines() if line.strip()]
        if not lines:
            errors.append("Rust doc comment cannot be empty")
        for line in lines:
            if not line.startswith(("///", "//!")):
                errors.append("Rust doc comment lines must start with /// or //!")
                break
        test_code = f"{doc_code}\nfn test() {{}}"
        try:
            source = test_code.encode("utf-8")
            tree = parse_code(source, "rust")
            if has_parse_errors(tree.root_node):
                errors.append("Rust doc comment contains syntax errors")
        except Exception as e:
            errors.append(f"Failed to parse: {e}")
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
