"""Template adapter for documentation frameworks.

This is a template for creating new documentation framework adapters.
Copy this file and replace all instances of "Template" and "template"
with your framework name.

See docs/CONTRIBUTING_ADAPTERS.md for a complete guide.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nit.adapters.base import DocFrameworkAdapter, ValidationResult

if TYPE_CHECKING:
    from nit.llm.prompts.base import PromptTemplate


class TemplateDocAdapter(DocFrameworkAdapter):
    """Adapter for Template documentation framework.

    Replace this docstring with a description of your framework.
    Include: What is it? What output does it generate? When is it used?
    """

    @property
    def name(self) -> str:
        """Framework identifier.

        This should be a unique, lowercase name used for registration.
        Examples: "sphinx", "typedoc", "doxygen"
        """
        return "templatedoc"

    @property
    def language(self) -> str:
        """Primary programming language.

        Valid values: "python", "typescript", "javascript", "cpp", "go",
        "rust", "java", "kotlin", "csharp"
        """
        return "python"

    def detect(self, project_path: Path) -> bool:
        """Detect if Template documentation framework is present.

        Implement multiple detection strategies for robustness:
        1. Check for framework-specific config files
        2. Check for framework dependencies
        3. Check for characteristic directory structures

        Args:
            project_path: Root directory of the project to scan.

        Returns:
            True if Template framework is detected, False otherwise.
        """
        # Strategy 1: Check for config file
        config_file = project_path / "docs" / "template.conf"
        if config_file.exists():
            return True

        # Strategy 2: Check for dependency
        if self._has_dependency(project_path):
            return True

        # Strategy 3: Check for characteristic directory structure
        docs_dir = project_path / "docs"
        if docs_dir.exists() and (docs_dir / "source").exists():
            return True

        return False

    def _has_dependency(self, project_path: Path) -> bool:
        """Check if Template is listed as a dependency.

        Implement this based on your language's package management.
        """
        # Example for Python (pyproject.toml):
        pyproject = project_path / "pyproject.toml"
        if pyproject.exists():
            import tomllib

            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                    deps = data.get("project", {}).get("dependencies", [])
                    optional_deps = data.get("project", {}).get("optional-dependencies", {})
                    all_deps = deps + [dep for group in optional_deps.values() for dep in group]
                    return any("templatedoc" in dep.lower() for dep in all_deps)
            except Exception:
                pass

        return False

    def get_doc_pattern(self) -> list[str]:
        """Return glob patterns for locating documentation source files.

        Returns:
            List of glob patterns (e.g., ["docs/**/*.rst", "docs/**/*.md"]).
        """
        return [
            "docs/**/*.rst",  # reStructuredText
            "docs/**/*.md",  # Markdown
            "*.md",  # Root-level markdown files
        ]

    def get_prompt_template(self) -> PromptTemplate:
        """Return the LLM prompt template for generating documentation.

        This template guides the LLM to generate docs in your framework's
        style and conventions.

        Returns:
            A PromptTemplate instance for this framework.
        """
        # Import your framework-specific prompt template
        from nit.llm.prompts.doc_generation import DocGenerationPrompt

        return DocGenerationPrompt()

    async def build_docs(
        self,
        project_path: Path,
        *,
        timeout: float = 120.0,
    ) -> bool:
        """Build documentation and return success status.

        This method runs the doc build tool and returns whether it succeeded.

        Args:
            project_path: Root of the project containing the documentation.
            timeout: Maximum seconds to wait for doc build.

        Returns:
            True if documentation built successfully, False otherwise.
        """
        from nit.utils.subprocess_runner import run_command

        # Build the command
        # Adjust this for your framework's CLI
        cmd = ["templatedoc", "build", "docs/", "docs/_build/"]

        # Execute the build
        result = await run_command(
            cmd,
            cwd=project_path,
            timeout=timeout,
        )

        # Check if build succeeded
        # Exit code 0 usually means success
        return result.returncode == 0

    def validate_doc(self, doc_code: str) -> ValidationResult:
        """Validate that generated documentation code is correct.

        This performs static validation without building the full docs.

        Args:
            doc_code: The generated documentation code to validate.

        Returns:
            ValidationResult with validity status, errors, and warnings.
        """
        # For reStructuredText: basic checks
        if ".rst" in self.get_doc_pattern()[0]:
            # Check for common RST errors
            errors = []

            # Check for mismatched header underlines
            lines = doc_code.split("\n")
            for i, line in enumerate(lines[:-1]):
                next_line = lines[i + 1]
                if next_line and all(c in "=-~^'\"" for c in next_line):
                    # This is a header underline
                    if len(line) != len(next_line):
                        errors.append(f"Line {i + 2}: Header underline length doesn't match title")

            if errors:
                return ValidationResult(valid=False, errors=errors)

        # For Markdown: basic checks
        elif ".md" in self.get_doc_pattern()[0]:
            # Check for common Markdown errors
            errors = []

            # Check for unbalanced code blocks
            code_block_count = doc_code.count("```")
            if code_block_count % 2 != 0:
                errors.append("Unbalanced code blocks (``` markers)")

            if errors:
                return ValidationResult(valid=False, errors=errors)

        # If no errors found
        return ValidationResult(valid=True)
