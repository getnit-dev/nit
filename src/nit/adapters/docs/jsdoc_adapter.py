"""JSDoc adapter for JavaScript documentation generation.

This adapter (task 4.5.1):
1. Detects JSDoc presence (jsdoc.json, "jsdoc" in package.json)
2. Generates JSDoc comments for undocumented JavaScript functions/classes
3. Builds documentation using `npx jsdoc`
4. Validates JSDoc comment syntax
"""

from __future__ import annotations

import asyncio
import json
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


class JSDocAdapter(DocFrameworkAdapter):
    """Adapter for JSDoc documentation generation.

    JSDoc is the standard documentation format for JavaScript projects,
    using block comments with @param, @returns, etc.
    """

    @property
    def name(self) -> str:
        """Framework identifier."""
        return "jsdoc"

    @property
    def language(self) -> str:
        """Primary language."""
        return "javascript"

    def detect(self, project_path: Path) -> bool:
        """Return True if JSDoc is present in the project.

        Detection: jsdoc.json config or "jsdoc" in package.json devDependencies.
        """
        if (project_path / "jsdoc.json").exists():
            logger.info("Detected JSDoc via jsdoc.json")
            return True
        package_json = project_path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
                dev_deps = data.get("devDependencies", {})
                if "jsdoc" in dev_deps:
                    logger.info("Detected JSDoc via package.json devDependencies")
                    return True
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to parse package.json: %s", e)
        return False

    def get_doc_pattern(self) -> list[str]:
        """Return glob patterns for JavaScript source files."""
        return [
            "**/*.js",
            "**/*.jsx",
            "!**/*.test.js",
            "!**/*.test.jsx",
            "!**/*.spec.js",
            "!**/*.spec.jsx",
            "!**/node_modules/**",
            "!**/dist/**",
            "!**/build/**",
        ]

    def get_prompt_template(self) -> PromptTemplate:
        """Return the prompt template for generating JSDoc comments."""
        context = DocGenerationContext(
            changes=[],
            doc_framework="jsdoc",
            language="javascript",
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
        """Build documentation using JSDoc.

        Executes `npx jsdoc` to generate HTML from JSDoc comments.
        """
        logger.info("Building JSDoc documentation in %s", project_path)
        config = project_path / "jsdoc.json"
        cmd = ["npx", "jsdoc"]
        if config.exists():
            cmd.extend(["-c", "jsdoc.json"])
        else:
            cmd.extend(["-d", "out", "src"])
        result = await _run_command(cmd, cwd=project_path, timeout=timeout)
        if result.success:
            logger.info("JSDoc build succeeded")
            return True
        logger.error("JSDoc build failed: %s", result.stderr)
        return False

    def validate_doc(self, doc_code: str) -> ValidationResult:
        """Validate that the doc block is valid JSDoc (/** ... */)."""
        errors: list[str] = []
        warnings: list[str] = []
        stripped = doc_code.strip()
        if not stripped.startswith("/**"):
            errors.append("JSDoc comments must start with /**")
        if not stripped.endswith("*/"):
            errors.append("JSDoc comments must end with */")
        test_code = f"{doc_code}\nfunction test() {{}}"
        try:
            source = test_code.encode("utf-8")
            tree = parse_code(source, "javascript")
            if has_parse_errors(tree.root_node):
                errors.append("JSDoc comment contains syntax errors")
        except Exception as e:
            errors.append(f"Failed to parse: {e}")
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
