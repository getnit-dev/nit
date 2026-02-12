"""TypeDoc adapter for TypeScript documentation generation.

This adapter (task 4.2):
1. Detects TypeDoc presence (typedoc.json, "typedoc" in package.json)
2. Generates TSDoc comments for undocumented exported functions/classes/interfaces
3. Builds documentation using `npx typedoc`
4. Validates TSDoc comment syntax
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
    """Run a command and return the result.

    Args:
        cmd: Command and arguments to run.
        cwd: Working directory for the command.
        timeout: Maximum time in seconds to wait for the command.

    Returns:
        CommandResult with stdout, stderr, and return code.
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


class TypeDocAdapter(DocFrameworkAdapter):
    """Adapter for TypeDoc documentation generation.

    TypeDoc is the standard documentation generator for TypeScript projects,
    using TSDoc-style comments (similar to JSDoc but with TypeScript support).
    """

    @property
    def name(self) -> str:
        """Framework identifier."""
        return "typedoc"

    @property
    def language(self) -> str:
        """Primary language."""
        return "typescript"

    def detect(self, project_path: Path) -> bool:
        """Return True if TypeDoc is present in the project.

        Detection signals (task 4.2.1):
        1. typedoc.json config file exists
        2. "typedoc" in package.json devDependencies

        Args:
            project_path: Root of the project.

        Returns:
            True if TypeDoc is detected, False otherwise.
        """
        # Check for typedoc.json
        if (project_path / "typedoc.json").exists():
            logger.info("Detected TypeDoc via typedoc.json")
            return True

        # Check package.json devDependencies
        package_json = project_path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
                dev_deps = data.get("devDependencies", {})
                if "typedoc" in dev_deps:
                    logger.info("Detected TypeDoc via package.json devDependencies")
                    return True
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to parse package.json: %s", e)

        return False

    def get_doc_pattern(self) -> list[str]:
        """Return glob patterns for TypeScript source files.

        Returns:
            List of glob patterns matching TypeScript files.
        """
        return [
            "**/*.ts",
            "**/*.tsx",
            "!**/*.test.ts",
            "!**/*.test.tsx",
            "!**/*.spec.ts",
            "!**/*.spec.tsx",
            "!**/node_modules/**",
            "!**/dist/**",
            "!**/build/**",
        ]

    def get_prompt_template(self) -> PromptTemplate:
        """Return the prompt template for generating TSDoc comments.

        Returns:
            A DocGenerationTemplate configured for TypeDoc/TSDoc.
        """
        # This will be called by DocBuilder with a DocGenerationContext
        # For now, return a placeholder that will be properly configured later
        context = DocGenerationContext(
            changes=[],
            doc_framework="typedoc",
            language="typescript",
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
        """Build documentation using TypeDoc (task 4.2.1).

        Executes `npx typedoc` to generate HTML documentation from TSDoc comments.

        Args:
            project_path: Root of the project containing the documentation.
            timeout: Maximum seconds to wait for doc build.

        Returns:
            True if the documentation built successfully, False otherwise.
        """
        logger.info("Building TypeDoc documentation in %s", project_path)

        # Check if typedoc.json exists (otherwise TypeDoc will use defaults)
        config_exists = (project_path / "typedoc.json").exists()
        if not config_exists:
            logger.warning("No typedoc.json found, TypeDoc will use default configuration")

        # Run TypeDoc
        cmd = ["npx", "typedoc"]

        # If no config file, specify some defaults
        if not config_exists:
            cmd.extend(["--out", "docs", "--entryPointStrategy", "expand", "src"])

        result = await _run_command(
            cmd,
            cwd=project_path,
            timeout=timeout,
        )

        if result.success:
            logger.info("TypeDoc build succeeded")
            return True

        logger.error("TypeDoc build failed: %s", result.stderr)
        return False

    def validate_doc(self, doc_code: str) -> ValidationResult:
        """Validate that TSDoc comment is syntactically correct (task 4.2.1).

        Uses tree-sitter TypeScript parser to check comment syntax.

        Args:
            doc_code: TSDoc comment block to validate.

        Returns:
            ValidationResult with validity status and any errors.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Basic TSDoc syntax checks
        if not doc_code.strip().startswith("/**"):
            errors.append("TSDoc comments must start with /**")

        if not doc_code.strip().endswith("*/"):
            errors.append("TSDoc comments must end with */")

        # Check for common TSDoc tags
        valid_tags = {
            "@param",
            "@returns",
            "@throws",
            "@example",
            "@deprecated",
            "@see",
            "@since",
            "@remarks",
            "@typeParam",
            "@defaultValue",
            "@public",
            "@private",
            "@internal",
            "@packageDocumentation",
        }

        lines = doc_code.split("\n")
        for line in lines:
            stripped = line.strip()
            # Remove leading * from doc comment lines
            if stripped.startswith("*"):
                stripped = stripped[1:].strip()
            if stripped.startswith("@"):
                # Extract tag name (just the @tagname part, not the rest)
                tag = stripped.split()[0] if stripped.split() else ""
                if tag and tag not in valid_tags:
                    warnings.append(f"Unknown or non-standard TSDoc tag: {tag}")

        # Try to parse with tree-sitter (create a minimal valid TypeScript code)
        test_code = f"""
{doc_code}
function test(): void {{}}
"""

        try:
            source = test_code.encode("utf-8")
            tree = parse_code(source, "typescript")
            root = tree.root_node
            if has_parse_errors(root):
                errors.append("TSDoc comment contains syntax errors")
        except Exception as e:
            errors.append(f"Failed to parse: {e}")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
