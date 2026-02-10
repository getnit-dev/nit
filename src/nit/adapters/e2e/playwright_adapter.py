"""Playwright adapter — detection, test generation prompts, execution, and validation.

Implements ``TestFrameworkAdapter`` for projects using Playwright as their
E2E test runner (TypeScript / JavaScript).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

    from nit.llm.prompts.base import PromptTemplate

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.llm.prompts.e2e_test import E2ETestTemplate
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_CONFIG_GLOBS = ("playwright.config.*",)

_DEV_DEP_NAME = "@playwright/test"

_TEST_PATTERNS = [
    "**/*.spec.ts",
    "**/*.spec.tsx",
    "**/*.e2e.ts",
    "**/*.e2e.tsx",
    "tests/**/*.ts",
    "tests/**/*.tsx",
    "e2e/**/*.ts",
    "e2e/**/*.tsx",
]

_DEFAULT_TIMEOUT = 300.0  # E2E tests can take longer

# Tree-sitter languages used for syntax validation.
_TS_LANGUAGE = "typescript"
_TSX_LANGUAGE = "tsx"


# ── Adapter ──────────────────────────────────────────────────────


class PlaywrightAdapter(TestFrameworkAdapter):
    """Playwright E2E test framework adapter.

    Provides detection of Playwright projects, Playwright-specific prompt
    templates for LLM-based E2E test generation, subprocess-based test
    execution with JSON reporter parsing, and tree-sitter validation
    of generated TypeScript test code.
    """

    # ── Identity ─────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "playwright"

    @property
    def language(self) -> str:
        return "typescript"

    # ── Detection (2.6.1) ────────────────────────────────────────

    def detect(self, project_path: Path) -> bool:
        """Return ``True`` when the project uses Playwright.

        Checks for:
        * A ``playwright.config.*`` config file.
        * ``@playwright/test`` in ``package.json`` ``devDependencies`` or ``dependencies``.
        """
        if _has_config_file(project_path):
            return True
        return _has_playwright_dependency(project_path)

    # ── Test file patterns (2.6.1) ───────────────────────────────

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    # ── Prompt template (2.6.3) ──────────────────────────────────

    def get_prompt_template(self) -> PromptTemplate:
        return E2ETestTemplate()

    # ── Test execution (2.6.1) ───────────────────────────────────

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> RunResult:
        """Execute Playwright via subprocess and parse JSON reporter output.

        Runs ``npx playwright test --reporter=json`` inside *project_path*.
        If *test_files* is provided, only those files are executed.
        """
        cmd = ["npx", "playwright", "test", "--reporter=json"]
        if test_files:
            cmd.extend(str(f) for f in test_files)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning("Playwright run timed out after %.1fs", timeout)
            return RunResult(
                raw_output="Playwright run timed out",
                success=False,
            )
        except FileNotFoundError:
            logger.error("npx not found — is Node.js installed?")
            return RunResult(
                raw_output="npx not found",
                success=False,
            )

        raw_stdout = stdout_bytes.decode("utf-8", errors="replace")
        raw_stderr = stderr_bytes.decode("utf-8", errors="replace")
        raw_output = raw_stdout + ("\n" + raw_stderr if raw_stderr else "")

        return _parse_playwright_json(raw_stdout, raw_output)

    # ── Validation (2.6.1) ───────────────────────────────────────

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse *test_code* with tree-sitter TypeScript and report syntax errors."""
        return _validate_typescript(test_code)


# ── Detection helpers ────────────────────────────────────────────


def _has_config_file(project_path: Path) -> bool:
    """Check if any Playwright config file exists in *project_path*."""
    for pattern in _CONFIG_GLOBS:
        # Pattern is simple enough — just check exact matches and common extensions
        stem = pattern.rstrip("*")
        for ext in ("ts", "js", "mts", "mjs", "cts", "cjs"):
            if (project_path / f"{stem}{ext}").exists():
                return True
    return False


def _has_playwright_dependency(project_path: Path) -> bool:
    """Check ``package.json`` for ``@playwright/test`` dependency."""
    package_json = project_path / "package.json"
    if not package_json.exists():
        return False

    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
        dev_deps = data.get("devDependencies", {})
        deps = data.get("dependencies", {})
        return _DEV_DEP_NAME in dev_deps or _DEV_DEP_NAME in deps
    except json.JSONDecodeError, OSError:
        return False


# ── Parsing helpers ──────────────────────────────────────────────


def _parse_playwright_json(raw_stdout: str, fallback_output: str) -> RunResult:
    """Parse Playwright JSON reporter output into ``RunResult``.

    Playwright's JSON reporter format:
    {
      "suites": [
        {
          "title": "suite name",
          "tests": [
            {
              "title": "test name",
              "status": "passed" | "failed" | "skipped" | "timedOut",
              "duration": 123,
              "error": {...}
            }
          ]
        }
      ]
    }
    """
    try:
        data = json.loads(raw_stdout)
    except json.JSONDecodeError:
        logger.debug("Failed to parse Playwright JSON output, returning fallback")
        return RunResult(
            raw_output=fallback_output,
            success=False,
        )

    result = RunResult(raw_output=fallback_output)
    suites = data.get("suites", [])

    def _extract_tests(suite: dict[str, Any]) -> None:
        """Recursively extract tests from suite and nested suites."""
        # Process tests in this suite
        tests = cast("list[dict[str, Any]]", suite.get("tests", []))
        for test in tests:
            status_str = cast("str", test.get("status", "unknown"))
            status = _map_playwright_status(status_str)

            # Extract error message if present
            error = test.get("error", {})
            failure_msg = ""
            if isinstance(error, dict):
                failure_msg = error.get("message", "")
                if not failure_msg and "value" in error:
                    failure_msg = str(error.get("value", ""))

            test_case = CaseResult(
                name=test.get("title", "unknown"),
                status=status,
                duration_ms=test.get("duration", 0.0),
                failure_message=failure_msg,
                file_path=test.get("location", {}).get("file", ""),
            )

            result.test_cases.append(test_case)

            # Update counters
            if status == CaseStatus.PASSED:
                result.passed += 1
            elif status == CaseStatus.FAILED:
                result.failed += 1
            elif status == CaseStatus.SKIPPED:
                result.skipped += 1
            else:
                result.errors += 1

        # Process nested suites
        nested_suites = cast("list[dict[str, Any]]", suite.get("suites", []))
        for nested_suite in nested_suites:
            _extract_tests(nested_suite)

    for suite in suites:
        _extract_tests(suite)

    result.success = result.failed == 0 and result.errors == 0
    return result


def _map_playwright_status(status: str) -> CaseStatus:
    """Map Playwright test status to our ``CaseStatus`` enum."""
    mapping = {
        "passed": CaseStatus.PASSED,
        "failed": CaseStatus.FAILED,
        "skipped": CaseStatus.SKIPPED,
        "timedout": CaseStatus.ERROR,
        "interrupted": CaseStatus.ERROR,
    }
    return mapping.get(status.lower(), CaseStatus.ERROR)


# ── Validation helpers ───────────────────────────────────────────


def _validate_typescript(test_code: str) -> ValidationResult:
    """Parse TypeScript test code with tree-sitter and report syntax errors."""
    source = test_code.encode("utf-8")
    tree = parse_code(source, _TS_LANGUAGE)
    root = tree.root_node

    if not has_parse_errors(root):
        return ValidationResult(valid=True)

    error_ranges = collect_error_ranges(root)
    test_lines = test_code.splitlines()
    errors = [
        f"Syntax error at line {start_line}: {test_lines[start_line - 1] if start_line > 0 else ''}"
        for start_line, _ in error_ranges
        if 0 < start_line <= len(test_lines)
    ]

    return ValidationResult(
        valid=False,
        errors=errors if errors else ["Parse errors detected"],
    )
