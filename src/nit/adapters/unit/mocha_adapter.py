"""Mocha adapter — detection, test generation prompts, execution, and validation.

Implements ``TestFrameworkAdapter`` for projects using Mocha as their
unit test runner (JavaScript).
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
from nit.llm.prompts.mocha_prompt import MochaTemplate
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_CONFIG_PREFIXES = (".mocharc.",)

_DEP_NAME = "mocha"

_TEST_PATTERNS = [
    "**/*.test.js",
    "**/*.test.mjs",
    "**/*.spec.js",
    "**/*.spec.mjs",
    "test/**/*.js",
    "test/**/*.mjs",
]

_DEFAULT_TIMEOUT = 120.0

_JS_LANGUAGE = "javascript"


# ── Adapter ──────────────────────────────────────────────────────


class MochaAdapter(TestFrameworkAdapter):
    """Mocha test framework adapter.

    Provides detection of Mocha projects, Mocha-specific prompt templates
    for LLM-based test generation, subprocess-based test execution with
    JSON reporter parsing, and tree-sitter validation of generated test code.
    """

    # ── Identity ─────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "mocha"

    @property
    def language(self) -> str:
        return "javascript"

    # ── Detection ─────────────────────────────────────────────────

    def detect(self, project_path: Path) -> bool:
        """Return ``True`` when the project uses Mocha.

        Checks for:
        * A ``.mocharc.*`` config file.
        * ``mocha`` in ``package.json`` dependencies or devDependencies.
        """
        if _has_config_file(project_path):
            return True
        return _has_mocha_dependency(project_path)

    # ── Test file patterns ────────────────────────────────────────

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    # ── Prompt template ───────────────────────────────────────────

    def get_prompt_template(self) -> MochaTemplate:
        return MochaTemplate()

    # ── Test execution ────────────────────────────────────────────

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> RunResult:
        """Execute Mocha via subprocess and parse JSON reporter output.

        Runs ``npx mocha --reporter json`` inside *project_path*.
        If *test_files* is provided, only those files are executed.
        """
        cmd = ["npx", "mocha", "--reporter", "json"]
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
            logger.warning("Mocha run timed out after %.1fs", timeout)
            return RunResult(
                raw_output="Mocha run timed out",
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

        return _parse_mocha_json(raw_stdout, raw_output)

    # ── Validation ────────────────────────────────────────────────

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse *test_code* with tree-sitter JavaScript and report syntax errors."""
        return _validate_javascript(test_code)

    def get_required_packages(self) -> list[str]:
        return ["mocha"]

    def get_required_commands(self) -> list[str]:
        return ["node", "npx"]


# ── Detection helpers ────────────────────────────────────────────


def _has_config_file(project_path: Path) -> bool:
    """Check for .mocharc.* in *project_path*."""
    for child in _safe_iterdir(project_path):
        for prefix in _CONFIG_PREFIXES:
            if child.name.startswith(prefix):
                return True
    return False


def _has_mocha_dependency(project_path: Path) -> bool:
    """Check ``package.json`` for ``mocha`` in dependencies or devDependencies."""
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


def _parse_mocha_json(stdout: str, raw_output: str) -> RunResult:
    """Parse Mocha JSON reporter output into a ``RunResult``.

    Mocha's JSON reporter outputs:
    ``{ stats: {...}, tests: [...], failures: [...], passes: [...] }``
    """
    json_obj = _extract_json_object(stdout)
    if json_obj is None:
        logger.debug("Could not extract JSON from Mocha output")
        return RunResult(raw_output=raw_output, success=False)

    stats_raw = json_obj.get("stats", {})
    stats: dict[str, object] = stats_raw if isinstance(stats_raw, dict) else {}

    passed = _to_int(stats.get("passes", 0))
    failed = _to_int(stats.get("failures", 0))
    skipped = _to_int(stats.get("pending", 0))
    duration_ms = _to_float(stats.get("duration", 0))

    test_cases: list[CaseResult] = []

    # Parse individual tests from the "tests" array
    raw_tests = json_obj.get("tests", [])
    tests_list: list[dict[str, object]] = raw_tests if isinstance(raw_tests, list) else []
    for test_obj in tests_list:
        test: dict[str, object] = test_obj if isinstance(test_obj, dict) else {}
        tc_name = str(test.get("fullTitle") or test.get("title", "unknown"))
        tc_duration = _to_float(test.get("duration", 0))

        err = test.get("err", {})
        err_dict: dict[str, object] = err if isinstance(err, dict) else {}
        failure_message = str(err_dict.get("message", "")) if err_dict else ""

        # Determine status from the test's own err field
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

    return RunResult(
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=0,
        duration_ms=duration_ms,
        test_cases=test_cases,
        raw_output=raw_output,
        success=failed == 0 and (passed + skipped) > 0,
    )


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


def _validate_javascript(code: str) -> ValidationResult:
    """Parse *code* with tree-sitter JavaScript and report syntax errors."""
    source = code.encode("utf-8")
    tree = parse_code(source, _JS_LANGUAGE)
    root = tree.root_node

    if not has_parse_errors(root):
        return ValidationResult(valid=True)

    error_ranges = collect_error_ranges(root)
    error_messages = [f"Syntax error at line {start}-{end}" for start, end in error_ranges]
    return ValidationResult(valid=False, errors=error_messages)
