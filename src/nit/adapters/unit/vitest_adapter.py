"""Vitest adapter — detection, test generation prompts, execution, and validation.

Implements ``TestFrameworkAdapter`` for projects using Vitest as their
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
from nit.llm.prompts.vitest import VitestTemplate
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_CONFIG_GLOBS = ("vitest.config.*", "vitest.workspace.*")

_DEV_DEP_NAME = "vitest"

_TEST_PATTERNS = [
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/*.spec.ts",
    "**/*.spec.tsx",
]

_DEFAULT_TIMEOUT = 120.0

# Tree-sitter languages used for syntax validation.
_TS_LANGUAGE = "typescript"
_TSX_LANGUAGE = "tsx"


# ── Adapter ──────────────────────────────────────────────────────


class VitestAdapter(TestFrameworkAdapter):
    """Vitest test framework adapter.

    Provides detection of Vitest projects, Vitest-specific prompt
    templates for LLM-based test generation, subprocess-based test
    execution with JSON reporter parsing, and tree-sitter validation
    of generated TypeScript test code.
    """

    # ── Identity ─────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "vitest"

    @property
    def language(self) -> str:
        return "typescript"

    # ── Detection (1.10.1) ───────────────────────────────────────

    def detect(self, project_path: Path) -> bool:
        """Return ``True`` when the project uses Vitest.

        Checks for:
        * A ``vitest.config.*`` or ``vitest.workspace.*`` config file.
        * ``vitest`` in ``package.json`` ``devDependencies`` or ``dependencies``.
        """
        if _has_config_file(project_path):
            return True
        return _has_vitest_dependency(project_path)

    # ── Test file patterns (1.10.1) ──────────────────────────────

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    # ── Prompt template (1.10.2) ─────────────────────────────────

    def get_prompt_template(self) -> VitestTemplate:
        return VitestTemplate()

    # ── Test execution (1.10.3) ──────────────────────────────────

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        collect_coverage: bool = True,
    ) -> RunResult:
        """Execute Vitest via subprocess and parse JSON reporter output.

        Runs ``npx vitest run --reporter=json`` inside *project_path*.
        If *test_files* is provided, only those files are executed.
        Optionally collects coverage using IstanbulAdapter.
        """
        cmd = ["npx", "vitest", "run", "--reporter=json"]
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
            logger.warning("Vitest run timed out after %.1fs", timeout)
            return RunResult(
                raw_output="Vitest run timed out",
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

        result = _parse_vitest_json(raw_stdout, raw_output)

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
            except Exception as e:
                logger.warning("Failed to collect coverage: %s", e)
                # Don't fail the test run if coverage collection fails

        return result

    # ── Validation (1.10.4) ──────────────────────────────────────

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse *test_code* with tree-sitter TypeScript and report syntax errors."""
        return _validate_typescript(test_code)

    def get_required_packages(self) -> list[str]:
        """Return required packages for Vitest, including environment dependencies."""
        return ["vitest"]

    def get_required_commands(self) -> list[str]:
        """Return required commands for Vitest."""
        return ["node", "npx"]

    def get_environment_packages(self, project_path: Path) -> list[str]:
        """Detect additional packages needed based on vitest config.

        Parses vitest.config.* files to detect test environment and
        returns additional required packages.

        Args:
            project_path: Root of the project.

        Returns:
            List of environment-specific packages (e.g., ["jsdom"]).
        """
        config_content = _read_vitest_config(project_path)
        if not config_content:
            return []

        packages = []

        # Check for test environment setting
        if "environment:" in config_content or 'environment"' in config_content:
            if "'jsdom'" in config_content or '"jsdom"' in config_content:
                packages.append("jsdom")
            elif "'happy-dom'" in config_content or '"happy-dom"' in config_content:
                packages.append("happy-dom")

        # Check for coverage provider
        if "provider:" in config_content or 'provider"' in config_content:
            if "'v8'" in config_content or '"v8"' in config_content:
                packages.append("@vitest/coverage-v8")
            elif "'istanbul'" in config_content or '"istanbul"' in config_content:
                packages.append("@vitest/coverage-istanbul")

        # Check for UI mode
        if "'@vitest/ui'" in config_content or '"@vitest/ui"' in config_content:
            packages.append("@vitest/ui")

        return packages


# ── Detection helpers ────────────────────────────────────────────


def _has_config_file(project_path: Path) -> bool:
    """Check for vitest.config.* or vitest.workspace.* in *project_path*."""
    for child in _safe_iterdir(project_path):
        name = child.name
        for prefix in ("vitest.config.", "vitest.workspace."):
            if name.startswith(prefix):
                return True
    return False


def _read_vitest_config(project_path: Path) -> str | None:
    """Read vitest config file content if it exists.

    Args:
        project_path: Project root directory.

    Returns:
        Config file content as string, or None if not found.
    """
    for child in _safe_iterdir(project_path):
        name = child.name
        if name.startswith("vitest.config."):
            try:
                return child.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
    return None


def _has_vitest_dependency(project_path: Path) -> bool:
    """Check ``package.json`` for ``vitest`` in dependencies or devDependencies."""
    pkg_path = project_path / "package.json"
    if not pkg_path.is_file():
        return False
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    for section in ("devDependencies", "dependencies"):
        deps = data.get(section)
        if isinstance(deps, dict) and _DEV_DEP_NAME in deps:
            return True
    return False


def _safe_iterdir(path: Path) -> list[Path]:
    """List directory children, returning empty list on errors."""
    try:
        return list(path.iterdir())
    except OSError:
        return []


# ── JSON reporter parsing ────────────────────────────────────────


def _parse_vitest_json(stdout: str, raw_output: str) -> RunResult:
    """Parse Vitest JSON reporter output into a ``RunResult``.

    Vitest's JSON reporter outputs a JSON object with a ``testResults``
    array.  Each entry contains ``assertionResults`` with individual
    test case outcomes.
    """
    json_obj = _extract_json_object(stdout)
    if json_obj is None:
        logger.debug("Could not extract JSON from Vitest output")
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
        suite_duration = _to_float(suite.get("duration", 0))
        duration_ms += suite_duration

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

    Vitest may emit non-JSON text (progress bars, warnings) before the
    JSON body, so we locate the first ``{`` and attempt to parse from there.
    """
    start = text.find("{")
    if start == -1:
        return None

    # Walk backwards from the end to find the closing brace
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
    """Map a Vitest status string to ``CaseStatus``."""
    mapping: dict[str, CaseStatus] = {
        "passed": CaseStatus.PASSED,
        "failed": CaseStatus.FAILED,
        "skipped": CaseStatus.SKIPPED,
        "pending": CaseStatus.SKIPPED,
        "todo": CaseStatus.SKIPPED,
    }
    return mapping.get(status, CaseStatus.ERROR)


def _to_float(value: object) -> float:
    """Coerce *value* to ``float``, defaulting to ``0.0``."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# ── Validation helpers ───────────────────────────────────────────


def _validate_typescript(code: str) -> ValidationResult:
    """Parse *code* as TypeScript with tree-sitter and report syntax errors.

    Falls back to TSX if the code contains JSX-like patterns.
    """
    source = code.encode("utf-8")
    language = _TSX_LANGUAGE if _looks_like_tsx(code) else _TS_LANGUAGE

    tree = parse_code(source, language)
    root = tree.root_node

    if not has_parse_errors(root):
        return ValidationResult(valid=True)

    error_ranges = collect_error_ranges(root)
    error_messages = [f"Syntax error at line {start}-{end}" for start, end in error_ranges]
    return ValidationResult(valid=False, errors=error_messages)


def _looks_like_tsx(code: str) -> bool:
    """Heuristic: code contains JSX-like patterns."""
    return "</" in code or "/>" in code or "jsx" in code.lower()
