"""Cypress adapter — detection, test generation prompts, execution, and validation.

Implements ``TestFrameworkAdapter`` for projects using Cypress as their
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
from nit.llm.prompts.cypress_prompt import CypressTemplate
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_CONFIG_PREFIXES = ("cypress.config.",)
_LEGACY_CONFIG = "cypress.json"

_DEP_NAME = "cypress"

_TEST_PATTERNS = [
    "cypress/e2e/**/*.cy.ts",
    "cypress/e2e/**/*.cy.js",
    "cypress/e2e/**/*.cy.tsx",
    "cypress/e2e/**/*.cy.jsx",
    "cypress/integration/**/*.spec.ts",
    "cypress/integration/**/*.spec.js",
]

_DEFAULT_TIMEOUT = 300.0  # E2E tests can take longer

# Tree-sitter languages used for syntax validation.
_TS_LANGUAGE = "typescript"
_TSX_LANGUAGE = "tsx"
_JS_LANGUAGE = "javascript"


# ── Adapter ──────────────────────────────────────────────────────


class CypressAdapter(TestFrameworkAdapter):
    """Cypress E2E test framework adapter.

    Provides detection of Cypress projects, Cypress-specific prompt
    templates for LLM-based E2E test generation, subprocess-based test
    execution with JSON reporter parsing, and tree-sitter validation
    of generated test code.
    """

    # ── Identity ─────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "cypress"

    @property
    def language(self) -> str:
        return "javascript"

    # ── Detection ─────────────────────────────────────────────────

    def detect(self, project_path: Path) -> bool:
        """Return ``True`` when the project uses Cypress.

        Checks for:
        * A ``cypress.config.*`` or ``cypress.json`` config file.
        * ``cypress`` in ``package.json`` ``devDependencies`` or ``dependencies``.
        """
        if _has_config_file(project_path):
            return True
        return _has_cypress_dependency(project_path)

    # ── Test file patterns ────────────────────────────────────────

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    # ── Prompt template ───────────────────────────────────────────

    def get_prompt_template(self) -> PromptTemplate:
        return CypressTemplate()

    # ── Test execution ────────────────────────────────────────────

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> RunResult:
        """Execute Cypress via subprocess and parse JSON reporter output.

        Runs ``npx cypress run --reporter json`` inside *project_path*.
        If *test_files* is provided, only those spec files are executed.
        """
        cmd = ["npx", "cypress", "run", "--reporter", "json"]
        if test_files:
            specs = ",".join(str(f) for f in test_files)
            cmd.extend(["--spec", specs])

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
            logger.warning("Cypress run timed out after %.1fs", timeout)
            return RunResult(
                raw_output="Cypress run timed out",
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

        return _parse_cypress_json(raw_stdout, raw_output)

    # ── Validation ────────────────────────────────────────────────

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse *test_code* with tree-sitter and report syntax errors."""
        return _validate_js_or_ts(test_code)

    def get_required_packages(self) -> list[str]:
        return ["cypress"]

    def get_required_commands(self) -> list[str]:
        return ["node", "npx"]


# ── Detection helpers ────────────────────────────────────────────


def _has_config_file(project_path: Path) -> bool:
    """Check for cypress.config.* or cypress.json in *project_path*."""
    # Check legacy config
    if (project_path / _LEGACY_CONFIG).is_file():
        return True

    for child in _safe_iterdir(project_path):
        for prefix in _CONFIG_PREFIXES:
            if child.name.startswith(prefix):
                return True
    return False


def _has_cypress_dependency(project_path: Path) -> bool:
    """Check ``package.json`` for ``cypress`` dependency."""
    pkg_path = project_path / "package.json"
    if not pkg_path.is_file():
        return False
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    for section in ("devDependencies", "dependencies"):
        deps = data.get(section)
        if isinstance(deps, dict) and _DEP_NAME in deps:
            return True
    return False


def _safe_iterdir(path: Path) -> list[Path]:
    """List directory children, returning empty list on errors."""
    try:
        return list(path.iterdir())
    except OSError:
        return []


# ── JSON reporter parsing ────────────────────────────────────────


def _parse_cypress_json(stdout: str, raw_output: str) -> RunResult:
    """Parse Cypress JSON reporter output into ``RunResult``.

    Cypress uses Mocha's JSON reporter format internally with a
    structure of ``{ stats, tests, failures, passes, pending }``.
    """
    json_obj = _extract_json_object(stdout)
    if json_obj is None:
        logger.debug("Could not extract JSON from Cypress output")
        return RunResult(raw_output=raw_output, success=False)

    stats_raw = json_obj.get("stats", {})
    stats: dict[str, object] = stats_raw if isinstance(stats_raw, dict) else {}

    passed_count = _to_int(stats.get("passes", 0))
    failed_count = _to_int(stats.get("failures", 0))
    skipped_count = _to_int(stats.get("pending", 0))
    duration_ms = _to_float(stats.get("duration", 0))

    test_cases: list[CaseResult] = []

    # Parse individual tests
    raw_tests = json_obj.get("tests", [])
    tests_list: list[dict[str, object]] = raw_tests if isinstance(raw_tests, list) else []
    for test_obj in tests_list:
        test: dict[str, object] = test_obj if isinstance(test_obj, dict) else {}
        tc_name = str(test.get("fullTitle") or test.get("title", "unknown"))
        tc_duration = _to_float(test.get("duration", 0))

        err = test.get("err", {})
        err_dict: dict[str, object] = err if isinstance(err, dict) else {}
        failure_message = str(err_dict.get("message", "")) if err_dict else ""

        if test.get("pending"):
            tc_status = CaseStatus.SKIPPED
        elif err_dict and err_dict.get("message"):
            tc_status = CaseStatus.FAILED
        else:
            tc_status = CaseStatus.PASSED

        test_cases.append(
            CaseResult(
                name=tc_name,
                status=tc_status,
                duration_ms=tc_duration,
                failure_message=failure_message,
                file_path=str(test.get("file", "")),
            )
        )

    # Also walk nested suites if present (Cypress sometimes nests)
    raw_suites = json_obj.get("suites", [])
    if isinstance(raw_suites, list):
        for suite in raw_suites:
            if isinstance(suite, dict):
                _extract_suite_tests(cast("dict[str, Any]", suite), test_cases)

    # Recount from test_cases if we extracted more from suites
    if test_cases:
        actual_passed = sum(1 for tc in test_cases if tc.status == CaseStatus.PASSED)
        actual_failed = sum(1 for tc in test_cases if tc.status == CaseStatus.FAILED)
        actual_skipped = sum(1 for tc in test_cases if tc.status == CaseStatus.SKIPPED)
        actual_errors = sum(1 for tc in test_cases if tc.status == CaseStatus.ERROR)
        return RunResult(
            passed=actual_passed,
            failed=actual_failed,
            skipped=actual_skipped,
            errors=actual_errors,
            duration_ms=duration_ms,
            test_cases=test_cases,
            raw_output=raw_output,
            success=actual_failed == 0
            and actual_errors == 0
            and (actual_passed + actual_skipped) > 0,
        )

    return RunResult(
        passed=passed_count,
        failed=failed_count,
        skipped=skipped_count,
        errors=0,
        duration_ms=duration_ms,
        test_cases=test_cases,
        raw_output=raw_output,
        success=failed_count == 0 and (passed_count + skipped_count) > 0,
    )


def _extract_suite_tests(suite: dict[str, Any], test_cases: list[CaseResult]) -> None:
    """Recursively extract tests from nested Cypress suite structure."""
    tests = cast("list[dict[str, Any]]", suite.get("tests", []))
    for test in tests:
        status_str = cast("str", test.get("status", "unknown"))
        tc_status = _map_cypress_status(status_str)

        err = test.get("err", {})
        failure_msg = ""
        if isinstance(err, dict):
            failure_msg = err.get("message", "")

        test_cases.append(
            CaseResult(
                name=test.get("fullTitle", test.get("title", "unknown")),
                status=tc_status,
                duration_ms=test.get("duration", 0.0),
                failure_message=failure_msg,
                file_path=test.get("file", ""),
            )
        )

    nested_suites = cast("list[dict[str, Any]]", suite.get("suites", []))
    for nested in nested_suites:
        _extract_suite_tests(nested, test_cases)


def _map_cypress_status(status: str) -> CaseStatus:
    """Map a Cypress/Mocha status string to ``CaseStatus``."""
    mapping: dict[str, CaseStatus] = {
        "passed": CaseStatus.PASSED,
        "failed": CaseStatus.FAILED,
        "pending": CaseStatus.SKIPPED,
        "skipped": CaseStatus.SKIPPED,
    }
    return mapping.get(status.lower(), CaseStatus.ERROR)


def _extract_json_object(text: str) -> dict[str, object] | None:
    """Find and parse the first JSON object in *text*."""
    start = text.find("{")
    if start == -1:
        return None

    end = text.rfind("}")
    if end == -1 or end < start:
        return None

    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None

    if isinstance(obj, dict):
        return obj
    return None


def _to_float(value: object) -> float:
    """Coerce *value* to ``float``, defaulting to ``0.0``."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: object) -> int:
    """Coerce *value* to ``int``, defaulting to ``0``."""
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


# ── Validation helpers ───────────────────────────────────────────


def _validate_js_or_ts(code: str) -> ValidationResult:
    """Parse *code* with tree-sitter and report syntax errors.

    Detects language from content: TSX if JSX present, then TS if
    TypeScript-specific patterns, otherwise plain JavaScript.
    """
    source = code.encode("utf-8")
    language = _detect_language(code)

    tree = parse_code(source, language)
    root = tree.root_node

    if not has_parse_errors(root):
        return ValidationResult(valid=True)

    error_ranges = collect_error_ranges(root)
    error_messages = [f"Syntax error at line {start}-{end}" for start, end in error_ranges]
    return ValidationResult(valid=False, errors=error_messages)


def _detect_language(code: str) -> str:
    """Heuristic language detection from test code content."""
    if "</" in code or "/>" in code:
        return _TSX_LANGUAGE
    ts_markers = (": string", ": number", ": boolean", "interface ", "<T>", "as ")
    if any(marker in code for marker in ts_markers):
        return _TS_LANGUAGE
    return _JS_LANGUAGE
