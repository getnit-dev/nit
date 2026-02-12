"""pytest adapter — detection, test generation prompts, execution, and validation.

Implements ``TestFrameworkAdapter`` for projects using pytest as their
unit test runner (Python).
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.adapters.coverage.coverage_py_adapter import CoveragePyAdapter
from nit.llm.prompts.pytest_prompt import PytestTemplate
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)
from nit.utils.prerequisites import detect_python_environment, get_command_path

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_CONFTEST = "conftest.py"
_PYTEST_INI = "pytest.ini"
_SETUP_CFG = "setup.cfg"
_PYPROJECT = "pyproject.toml"

_TEST_PATTERNS = [
    "**/test_*.py",
    "**/*_test.py",
]

_DEFAULT_TIMEOUT = 120.0

_PYTHON_LANGUAGE = "python"


# ── Adapter ──────────────────────────────────────────────────────


class PytestAdapter(TestFrameworkAdapter):
    """pytest test framework adapter.

    Provides detection of pytest projects, pytest-specific prompt
    templates for LLM-based test generation, subprocess-based test
    execution with JSON report parsing, and tree-sitter validation
    of generated Python test code.
    """

    # ── Identity ─────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "pytest"

    @property
    def language(self) -> str:
        return "python"

    # ── Detection (1.11.1) ───────────────────────────────────────

    def detect(self, project_path: Path) -> bool:
        """Return ``True`` when the project uses pytest.

        Checks for:
        * A ``conftest.py`` file in the project root.
        * A ``[tool.pytest.ini_options]`` section in ``pyproject.toml``.
        * A ``pytest.ini`` configuration file.
        * A ``[tool:pytest]`` section in ``setup.cfg``.
        * ``pytest`` listed as a dependency in ``pyproject.toml``.
        """
        if _has_conftest(project_path):
            return True
        if _has_pytest_ini(project_path):
            return True
        if _has_pyproject_pytest_config(project_path):
            return True
        if _has_setup_cfg_pytest(project_path):
            return True
        return _has_pytest_dependency(project_path)

    # ── Test file patterns (1.11.1) ──────────────────────────────

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    # ── Prompt template (1.11.2) ─────────────────────────────────

    def get_prompt_template(self) -> PytestTemplate:
        return PytestTemplate()

    # ── Test execution (1.11.3) ──────────────────────────────────

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        collect_coverage: bool = True,
    ) -> RunResult:
        """Execute pytest via subprocess and parse JSON report output.

        Runs ``pytest --json-report --json-report-file=-`` inside
        *project_path*.  If *test_files* is provided, only those files
        are executed. Optionally collects coverage using CoveragePyAdapter.
        """
        # Use robust environment detection to find pytest
        pytest_cmd = "pytest"
        env = detect_python_environment(project_path)
        pytest_path = get_command_path("pytest", env)
        if pytest_path:
            pytest_cmd = str(pytest_path)

        # Use a temp file for JSON report since --json-report-file=- doesn't work reliably
        json_report_file = None
        try:
            _json_report_fd, json_report_path = tempfile.mkstemp(suffix=".json", prefix="pytest_")
            json_report_file = Path(json_report_path)

            cmd = [
                pytest_cmd,
                "--json-report",
                f"--json-report-file={json_report_path}",
                "-q",
            ]
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
                logger.warning("pytest run timed out after %.1fs", timeout)
                return RunResult(
                    raw_output="pytest run timed out",
                    success=False,
                )
            except FileNotFoundError:
                logger.error("pytest not found — is it installed?")
                return RunResult(
                    raw_output="pytest not found",
                    success=False,
                )

            raw_stdout = stdout_bytes.decode("utf-8", errors="replace")
            raw_stderr = stderr_bytes.decode("utf-8", errors="replace")
            raw_output = raw_stdout + ("\n" + raw_stderr if raw_stderr else "")

            # Read JSON report from temp file
            json_content = ""
            if json_report_file and json_report_file.exists():
                json_content = json_report_file.read_text(encoding="utf-8")

            result = _parse_pytest_json(json_content, raw_output)

            # Collect coverage if requested
            if collect_coverage:
                try:
                    coverage_adapter = CoveragePyAdapter()
                    coverage_report = await coverage_adapter.run_coverage(
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

        finally:
            # Clean up temp file
            if json_report_file and json_report_file.exists():
                json_report_file.unlink()

    # ── Validation (1.11.4) ──────────────────────────────────────

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse *test_code* with tree-sitter Python and report syntax errors."""
        return _validate_python(test_code)

    def get_required_packages(self) -> list[str]:
        """Return required packages for pytest."""
        return ["pytest", "pytest-json-report"]

    def get_required_commands(self) -> list[str]:
        """Return required commands for pytest."""
        return ["python"]


# ── Detection helpers ────────────────────────────────────────────


def _has_conftest(project_path: Path) -> bool:
    """Check for ``conftest.py`` in *project_path*."""
    return (project_path / _CONFTEST).is_file()


def _has_pytest_ini(project_path: Path) -> bool:
    """Check for ``pytest.ini`` in *project_path*."""
    return (project_path / _PYTEST_INI).is_file()


def _has_pyproject_pytest_config(project_path: Path) -> bool:
    """Check ``pyproject.toml`` for ``[tool.pytest.ini_options]``."""
    pyproject = project_path / _PYPROJECT
    if not pyproject.is_file():
        return False
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return "[tool.pytest" in content


def _has_setup_cfg_pytest(project_path: Path) -> bool:
    """Check ``setup.cfg`` for ``[tool:pytest]``."""
    setup_cfg = project_path / _SETUP_CFG
    if not setup_cfg.is_file():
        return False
    try:
        content = setup_cfg.read_text(encoding="utf-8")
    except OSError:
        return False
    return "[tool:pytest]" in content


def _has_pytest_dependency(project_path: Path) -> bool:
    """Check ``pyproject.toml`` for pytest in dependencies.

    Looks in ``[project.optional-dependencies]`` (all groups) and
    ``[project.dependencies]``.
    """
    pyproject = project_path / _PYPROJECT
    if not pyproject.is_file():
        return False
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    # Simple heuristic: look for 'pytest' as a dependency string.
    # This avoids importing a TOML parser; the word 'pytest' in
    # pyproject.toml deps is distinctive enough to avoid false positives.
    for line in content.splitlines():
        stripped = line.strip().strip('"').strip("'")
        # Skip section headers and tool.pytest config (already checked)
        if stripped.startswith("["):
            continue
        if "pytest" in stripped.lower() and "tool.pytest" not in stripped:
            return True
    return False


def _safe_read_text(path: Path) -> str | None:
    """Read file contents, returning ``None`` on errors."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# ── JSON report parsing ──────────────────────────────────────────


def _parse_pytest_json(stdout: str, raw_output: str) -> RunResult:
    """Parse pytest-json-report output into a ``RunResult``.

    The ``pytest-json-report`` plugin (with ``--json-report-file=-``)
    writes a JSON object to stdout.  The report contains a ``tests``
    array with individual test outcomes and a ``summary`` object.
    """
    json_obj = _extract_json_object(stdout)
    if json_obj is None:
        logger.debug("Could not extract JSON from pytest output")
        return RunResult(raw_output=raw_output, success=False)

    passed = 0
    failed = 0
    skipped = 0
    errors = 0
    duration_ms = 0.0
    test_cases: list[CaseResult] = []

    # Use summary for top-level counts if available, but always parse
    # individual tests for detailed results.
    raw_tests = json_obj.get("tests", [])
    tests: list[dict[str, object]] = raw_tests if isinstance(raw_tests, list) else []

    # Total duration from the report root (in seconds).
    report_duration = _to_float(json_obj.get("duration", 0))
    duration_ms = report_duration * 1000.0

    for test_obj in tests:
        test: dict[str, object] = test_obj if isinstance(test_obj, dict) else {}
        outcome = str(test.get("outcome", "error"))
        tc_status = _map_outcome(outcome)

        nodeid = str(test.get("nodeid", "unknown"))

        # Duration may be at test level or inside the "call" phase.
        tc_duration_s = _to_float(test.get("duration", 0))
        if tc_duration_s == 0:
            call_phase = test.get("call")
            if isinstance(call_phase, dict):
                tc_duration_s = _to_float(call_phase.get("duration", 0))
        tc_duration_ms = tc_duration_s * 1000.0

        # Extract failure message from the call phase.
        failure_message = ""
        call_phase = test.get("call")
        if isinstance(call_phase, dict):
            longrepr = call_phase.get("longrepr", "")
            if isinstance(longrepr, str):
                failure_message = longrepr
            crash = call_phase.get("crash")
            if isinstance(crash, dict) and not failure_message:
                failure_message = str(crash.get("message", ""))

        # Extract file path from nodeid (format: "path/to/test.py::test_name").
        file_path = nodeid.split("::", maxsplit=1)[0] if "::" in nodeid else ""

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
                name=nodeid,
                status=tc_status,
                duration_ms=tc_duration_ms,
                failure_message=failure_message,
                file_path=file_path,
            ),
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

    pytest-json-report with ``--json-report-file=-`` writes JSON to
    stdout, but other pytest output (warnings, progress) may appear
    before or after.  We locate the first ``{`` and attempt to parse.
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


def _map_outcome(outcome: str) -> CaseStatus:
    """Map a pytest-json-report outcome string to ``CaseStatus``."""
    mapping: dict[str, CaseStatus] = {
        "passed": CaseStatus.PASSED,
        "failed": CaseStatus.FAILED,
        "skipped": CaseStatus.SKIPPED,
        "xfailed": CaseStatus.SKIPPED,
        "xpassed": CaseStatus.PASSED,
        "error": CaseStatus.ERROR,
    }
    return mapping.get(outcome, CaseStatus.ERROR)


def _to_float(value: object) -> float:
    """Coerce *value* to ``float``, defaulting to ``0.0``."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# ── Validation helpers ───────────────────────────────────────────


def _validate_python(code: str) -> ValidationResult:
    """Parse *code* as Python with tree-sitter and report syntax errors."""
    source = code.encode("utf-8")
    tree = parse_code(source, _PYTHON_LANGUAGE)
    root = tree.root_node

    if not has_parse_errors(root):
        return ValidationResult(valid=True)

    error_ranges = collect_error_ranges(root)
    error_messages = [f"Syntax error at line {start}-{end}" for start, end in error_ranges]
    return ValidationResult(valid=False, errors=error_messages)
