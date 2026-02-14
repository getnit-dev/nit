"""Jest adapter — detection, test generation prompts, execution, and validation.

Implements ``TestFrameworkAdapter`` for projects using Jest as their
unit/component test runner (TypeScript / JavaScript).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.adapters.coverage.istanbul import IstanbulAdapter
from nit.llm.prompts.jest_prompt import JestTemplate
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_CONFIG_PREFIXES = ("jest.config.",)

_DEP_NAMES = ("jest", "@jest/core", "ts-jest")

_TEST_PATTERNS = [
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/*.test.js",
    "**/*.test.jsx",
    "**/*.spec.ts",
    "**/*.spec.tsx",
    "**/*.spec.js",
    "**/*.spec.jsx",
]

_DEFAULT_TIMEOUT = 120.0

# Tree-sitter languages used for syntax validation.
_TS_LANGUAGE = "typescript"
_TSX_LANGUAGE = "tsx"
_JS_LANGUAGE = "javascript"


# ── Adapter ──────────────────────────────────────────────────────


class JestAdapter(TestFrameworkAdapter):
    """Jest test framework adapter.

    Provides detection of Jest projects, Jest-specific prompt templates
    for LLM-based test generation, subprocess-based test execution with
    JSON reporter parsing, and tree-sitter validation of generated test code.
    """

    # ── Identity ─────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "jest"

    @property
    def language(self) -> str:
        return "javascript"

    # ── Detection ─────────────────────────────────────────────────

    def detect(self, project_path: Path) -> bool:
        """Return ``True`` when the project uses Jest.

        Checks for:
        * A ``jest.config.*`` config file.
        * ``jest``, ``@jest/core``, or ``ts-jest`` in ``package.json`` deps.
        * A top-level ``jest`` key in ``package.json``.
        """
        if _has_config_file(project_path):
            return True
        return _has_jest_dependency(project_path)

    # ── Test file patterns ────────────────────────────────────────

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    # ── Prompt template ───────────────────────────────────────────

    def get_prompt_template(self) -> JestTemplate:
        return JestTemplate()

    # ── Test execution ────────────────────────────────────────────

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        collect_coverage: bool = True,
    ) -> RunResult:
        """Execute Jest via subprocess and parse JSON output.

        Runs ``npx jest --json`` inside *project_path*.
        If *test_files* is provided, only those files are executed.
        Optionally collects coverage using IstanbulAdapter.
        """
        cmd = ["npx", "jest", "--json", "--no-coverage"]
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
            logger.warning("Jest run timed out after %.1fs", timeout)
            return RunResult(
                raw_output="Jest run timed out",
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

        result = _parse_jest_json(raw_stdout, raw_output)

        # Collect coverage if requested
        if collect_coverage:
            try:
                istanbul = IstanbulAdapter()
                coverage_report = await istanbul.run_coverage(
                    project_path, test_files=test_files, timeout=timeout
                )
                result.coverage = coverage_report
                logger.info(
                    "Coverage collected: %.1f%% line coverage",
                    coverage_report.overall_line_coverage,
                )
            except Exception as exc:
                logger.warning("Failed to collect coverage: %s", exc)

        return result

    # ── Validation ────────────────────────────────────────────────

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse *test_code* with tree-sitter and report syntax errors."""
        return _validate_js_or_ts(test_code)

    def get_required_packages(self) -> list[str]:
        return ["jest"]

    def get_required_commands(self) -> list[str]:
        return ["node", "npx"]


# ── Detection helpers ────────────────────────────────────────────


def _has_config_file(project_path: Path) -> bool:
    """Check for jest.config.* in *project_path*."""
    for child in _safe_iterdir(project_path):
        for prefix in _CONFIG_PREFIXES:
            if child.name.startswith(prefix):
                return True
    return False


def _has_jest_dependency(project_path: Path) -> bool:
    """Check ``package.json`` for Jest dependencies or top-level jest config."""
    pkg_path = project_path / "package.json"
    if not pkg_path.is_file():
        return False
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    # Check top-level "jest" key (inline config)
    if "jest" in data and isinstance(data["jest"], dict):
        return True

    # Check dependencies
    for section in ("devDependencies", "dependencies"):
        deps = data.get(section)
        if isinstance(deps, dict):
            for dep_name in _DEP_NAMES:
                if dep_name in deps:
                    return True
    return False


def _safe_iterdir(path: Path) -> list[Path]:
    """List directory children, returning empty list on errors."""
    try:
        return list(path.iterdir())
    except OSError:
        return []


# ── JSON reporter parsing ────────────────────────────────────────


def _parse_jest_json(stdout: str, raw_output: str) -> RunResult:
    """Parse Jest ``--json`` output into a ``RunResult``.

    Jest's JSON output contains ``testResults`` array.  Each entry has
    ``assertionResults`` with individual test case outcomes.
    """
    json_obj = _extract_json_object(stdout)
    if json_obj is None:
        logger.debug("Could not extract JSON from Jest output")
        return RunResult(raw_output=raw_output, success=False)

    passed = 0
    failed = 0
    skipped = 0
    errors = 0
    duration_ms = 0.0
    test_cases: list[CaseResult] = []

    raw_suites = json_obj.get("testResults", [])
    suites: list[dict[str, object]] = raw_suites if isinstance(raw_suites, list) else []

    for suite_obj in suites:
        suite: dict[str, object] = suite_obj if isinstance(suite_obj, dict) else {}
        file_path = str(suite.get("name", ""))
        suite_duration = _to_float(suite.get("endTime", 0)) - _to_float(suite.get("startTime", 0))
        duration_ms += max(suite_duration, 0)

        raw_assertions = suite.get("assertionResults", [])
        assertions: list[dict[str, object]] = (
            raw_assertions if isinstance(raw_assertions, list) else []
        )
        for assertion_obj in assertions:
            assertion: dict[str, object] = assertion_obj if isinstance(assertion_obj, dict) else {}
            status_str = str(assertion.get("status", "failed"))
            tc_status = _map_status(status_str)
            tc_name = str(assertion.get("fullName") or assertion.get("title", "unknown"))
            raw_failure_msgs = assertion.get("failureMessages", [])
            failure_msgs: list[object] = (
                raw_failure_msgs if isinstance(raw_failure_msgs, list) else []
            )
            failure_message = "\n".join(str(m) for m in failure_msgs) if failure_msgs else ""
            tc_duration = _to_float(assertion.get("duration", 0))

            if tc_status == CaseStatus.PASSED:
                passed += 1
            elif tc_status == CaseStatus.FAILED:
                failed += 1
            elif tc_status == CaseStatus.SKIPPED:
                skipped += 1
            else:
                errors += 1

            test_cases.append(
                CaseResult(
                    name=tc_name,
                    status=tc_status,
                    duration_ms=tc_duration,
                    failure_message=failure_message,
                    file_path=file_path,
                )
            )

    return RunResult(
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        duration_ms=duration_ms,
        test_cases=test_cases,
        raw_output=raw_output,
        success=failed == 0 and errors == 0 and (passed + skipped) > 0,
    )


def _extract_json_object(text: str) -> dict[str, object] | None:
    """Find and parse the first JSON object in *text*.

    Jest may emit non-JSON warnings before the JSON body.
    """
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


def _map_status(status: str) -> CaseStatus:
    """Map a Jest status string to ``CaseStatus``."""
    mapping: dict[str, CaseStatus] = {
        "passed": CaseStatus.PASSED,
        "failed": CaseStatus.FAILED,
        "skipped": CaseStatus.SKIPPED,
        "pending": CaseStatus.SKIPPED,
        "todo": CaseStatus.SKIPPED,
        "disabled": CaseStatus.SKIPPED,
    }
    return mapping.get(status, CaseStatus.ERROR)


def _to_float(value: object) -> float:
    """Coerce *value* to ``float``, defaulting to ``0.0``."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


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
    if _looks_like_tsx(code):
        return _TSX_LANGUAGE
    if _looks_like_typescript(code):
        return _TS_LANGUAGE
    return _JS_LANGUAGE


def _looks_like_tsx(code: str) -> bool:
    """Heuristic: code contains JSX-like patterns."""
    return "</" in code or "/>" in code


def _looks_like_typescript(code: str) -> bool:
    """Heuristic: code contains TypeScript-specific syntax."""
    ts_markers = (": string", ": number", ": boolean", "interface ", "<T>", "as ")
    return any(marker in code for marker in ts_markers)
