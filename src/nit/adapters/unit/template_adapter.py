"""Template adapter for test frameworks.

This is a template for creating new test framework adapters.
Copy this file and replace all instances of "Template" and "template"
with your framework name.

See docs/CONTRIBUTING_ADAPTERS.md for a complete guide.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)

if TYPE_CHECKING:
    from nit.llm.prompts.base import PromptTemplate


class TemplateAdapter(TestFrameworkAdapter):
    """Adapter for Template testing framework.

    Replace this docstring with a description of your framework.
    Include: What is it? What languages does it support? When is it used?
    """

    @property
    def name(self) -> str:
        """Framework identifier.

        This should be a unique, lowercase name used for registration.
        Examples: "pytest", "vitest", "junit5"
        """
        return "template"

    @property
    def language(self) -> str:
        """Primary programming language.

        Valid values: "python", "typescript", "javascript", "cpp", "go",
        "rust", "java", "kotlin", "csharp"
        """
        return "python"

    def detect(self, project_path: Path) -> bool:
        """Detect if Template framework is present in the project.

        Implement multiple detection strategies for robustness:
        1. Check for framework-specific config files
        2. Check for framework dependencies in package manifests
        3. Check for characteristic import patterns in source files

        Args:
            project_path: Root directory of the project to scan.

        Returns:
            True if Template framework is detected, False otherwise.
        """
        # Strategy 1: Check for config file
        config_file = project_path / "template.config.json"
        if config_file.exists():
            return True

        # Strategy 2: Check for dependency
        # For Python projects: check pyproject.toml, requirements.txt
        # For JS/TS projects: check package.json
        # For Go projects: check go.mod
        # etc.
        if self._has_dependency(project_path):
            return True

        # Strategy 3: Check for characteristic file patterns
        # Look for test files that likely use this framework
        test_files = list(project_path.glob("**/*_test.py"))
        if test_files and self._contains_framework_import(test_files[0]):
            return True

        return False

    def _has_dependency(self, project_path: Path) -> bool:
        """Check if Template is listed as a dependency.

        Implement this based on your language's package management:
        - Python: Parse pyproject.toml, requirements.txt, setup.py
        - JavaScript/TypeScript: Parse package.json
        - Go: Parse go.mod
        - Rust: Parse Cargo.toml
        - Java: Parse pom.xml or build.gradle
        etc.
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
                    return any("template" in dep.lower() for dep in all_deps)
            except Exception:
                pass

        # Example for JavaScript (package.json):
        package_json = project_path / "package.json"
        if package_json.exists():
            import json

            try:
                with open(package_json) as f:
                    data = json.load(f)
                    deps = data.get("dependencies", {})
                    dev_deps = data.get("devDependencies", {})
                    return "template" in deps or "template" in dev_deps
            except Exception:
                pass

        return False

    def _contains_framework_import(self, file_path: Path) -> bool:
        """Check if a file imports the Template framework.

        This helps verify that files matching the test pattern actually
        use this framework (useful when multiple frameworks might be present).
        """
        try:
            content = file_path.read_text()
            # Adjust these patterns for your framework
            imports = [
                "import template",
                "from template import",
                "import { template }",
                "from 'template'",
            ]
            return any(pattern in content for pattern in imports)
        except Exception:
            return False

    def get_test_pattern(self) -> list[str]:
        """Return glob patterns for locating test files.

        These patterns are used to find existing tests and to suggest
        locations for generated tests.

        Returns:
            List of glob patterns (e.g., ["tests/**/*.py", "**/*_test.py"]).
        """
        return [
            "tests/**/*.py",  # tests/ directory
            "test/**/*.py",  # test/ directory
            "**/*_test.py",  # suffix pattern
            "**/test_*.py",  # prefix pattern
        ]

    def get_prompt_template(self) -> PromptTemplate:
        """Return the LLM prompt template for generating tests.

        This template guides the LLM to generate tests in your framework's
        style and conventions.

        Returns:
            A PromptTemplate instance for this framework.
        """
        # Option 1: Create a dedicated prompt template
        # from nit.llm.prompts.template_prompt import TemplatePrompt
        # return TemplatePrompt()

        # Option 2: Reuse a generic prompt for your language
        from nit.llm.prompts.generic_python import GenericPythonPrompt

        return GenericPythonPrompt()

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = 120.0,
    ) -> RunResult:
        """Execute Template tests and return structured results.

        This method runs the tests via subprocess and parses the output
        into a structured format.

        Args:
            project_path: Root of the project containing the tests.
            test_files: Specific test files to run. None runs all tests.
            timeout: Maximum seconds to wait for test execution.

        Returns:
            A RunResult with pass/fail counts and per-case details.
        """
        from nit.utils.subprocess_runner import run_command

        # Build the command
        # Adjust this for your framework's CLI
        cmd = ["template", "test", "--json"]  # Prefer JSON output if available

        # Add specific test files if provided
        if test_files:
            cmd.extend(str(f) for f in test_files)

        # Execute the tests
        result = await run_command(
            cmd,
            cwd=project_path,
            timeout=timeout,
        )

        # Parse the output
        # If your framework has JSON output, use that
        # Otherwise, parse text output
        return self._parse_test_results(result.stdout, result.stderr, result.returncode)

    def _parse_test_results(self, stdout: str, stderr: str, returncode: int) -> RunResult:
        """Parse test framework output into RunResult.

        Implement parsing logic based on your framework's output format.

        Args:
            stdout: Standard output from test execution.
            stderr: Standard error from test execution.
            returncode: Process exit code.

        Returns:
            Parsed RunResult with test counts and case details.
        """
        import json

        # Try parsing JSON output (if your framework supports it)
        try:
            data = json.loads(stdout)

            # Build test cases list
            test_cases = []
            for test in data.get("tests", []):
                test_cases.append(
                    CaseResult(
                        name=test["name"],
                        status=self._map_status(test["status"]),
                        duration_ms=test.get("duration", 0.0),
                        failure_message=test.get("error", ""),
                        file_path=test.get("file", ""),
                    )
                )

            return RunResult(
                passed=data.get("passed", 0),
                failed=data.get("failed", 0),
                skipped=data.get("skipped", 0),
                errors=data.get("errors", 0),
                duration_ms=data.get("duration", 0.0),
                test_cases=test_cases,
                raw_output=stdout,
                success=returncode == 0,
            )

        except json.JSONDecodeError:
            # Fallback: parse text output
            # Implement text parsing logic here
            # This is framework-specific
            return RunResult(
                raw_output=stdout,
                success=returncode == 0,
            )

    def _map_status(self, framework_status: str) -> CaseStatus:
        """Map framework-specific status to CaseStatus enum.

        Args:
            framework_status: Status string from your framework.

        Returns:
            Corresponding CaseStatus enum value.
        """
        # Adjust these mappings for your framework
        status_map = {
            "pass": CaseStatus.PASSED,
            "passed": CaseStatus.PASSED,
            "ok": CaseStatus.PASSED,
            "fail": CaseStatus.FAILED,
            "failed": CaseStatus.FAILED,
            "error": CaseStatus.ERROR,
            "skip": CaseStatus.SKIPPED,
            "skipped": CaseStatus.SKIPPED,
            "pending": CaseStatus.SKIPPED,
        }
        return status_map.get(framework_status.lower(), CaseStatus.ERROR)

    def validate_test(self, test_code: str) -> ValidationResult:
        """Validate that generated test code is syntactically correct.

        This performs static validation without executing the code.
        Use tree-sitter or language-specific parsers.

        Args:
            test_code: The generated test code to validate.

        Returns:
            ValidationResult with validity status, errors, and warnings.
        """
        # For Python: use compile()
        if self.language == "python":
            try:
                compile(test_code, "<string>", "exec")
                return ValidationResult(valid=True)
            except SyntaxError as e:
                return ValidationResult(
                    valid=False,
                    errors=[f"Syntax error at line {e.lineno}: {e.msg}"],
                )

        # For other languages: use tree-sitter
        from nit.parsing.treesitter import get_parser

        try:
            parser = get_parser(self.language)
            tree = parser.parse(bytes(test_code, "utf8"))

            if tree.root_node.has_error:
                return ValidationResult(
                    valid=False,
                    errors=["Syntax error in generated test code"],
                )

            return ValidationResult(valid=True)

        except Exception as e:
            return ValidationResult(
                valid=False,
                errors=[f"Failed to parse code: {e}"],
            )
