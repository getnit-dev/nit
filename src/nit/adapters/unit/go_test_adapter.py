"""Go stdlib testing adapter — detection, execution, and validation.

Implements ``TestFrameworkAdapter`` for projects using Go's standard
testing package (``*_test.go``, ``go test ./...``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.adapters.coverage.go_cover_adapter import GoCoverAdapter
from nit.llm.prompts.go_test_prompt import GoTestTemplate
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_GO_MOD = "go.mod"
_TEST_PATTERNS = [
    "**/*_test.go",
]
_DEFAULT_TIMEOUT = 120.0
_GO_LANGUAGE = "go"


# ── Adapter ──────────────────────────────────────────────────────


class GoTestAdapter(TestFrameworkAdapter):
    """Go standard library testing adapter."""

    @property
    def name(self) -> str:
        return "gotest"

    @property
    def language(self) -> str:
        return "go"

    def detect(self, project_path: Path) -> bool:
        """Return True when the project has go.mod and *_test.go files."""
        if not (project_path / _GO_MOD).is_file():
            return False
        return any(path for pattern in _TEST_PATTERNS for path in project_path.glob(pattern))

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    def get_prompt_template(self) -> GoTestTemplate:
        return GoTestTemplate()

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        collect_coverage: bool = True,
    ) -> RunResult:
        """Execute tests via ``go test -json ./...`` and parse JSON stream.

        Optionally collects coverage using GoCoverAdapter.
        """
        cmd = ["go", "test", "-json", "./..."]
        if test_files:
            # Run tests for packages containing the given files (relative to project_path)
            pkgs: set[str] = set()
            for f in test_files:
                if f.suffix != ".go":
                    continue
                try:
                    rel = f.parent.relative_to(project_path)
                    pkgs.add("." if not rel.parts else f"./{rel}")
                except ValueError:
                    continue
            if pkgs:
                cmd = ["go", "test", "-json", *sorted(pkgs)]

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
            logger.warning("go test timed out after %.1fs", timeout)
            return RunResult(raw_output="go test timed out", success=False)
        except FileNotFoundError:
            logger.error("go not found — is Go installed?")
            return RunResult(raw_output="go not found", success=False)

        raw_stdout = stdout_bytes.decode("utf-8", errors="replace")
        raw_stderr = stderr_bytes.decode("utf-8", errors="replace")
        raw_output = raw_stdout + ("\n" + raw_stderr if raw_stderr else "")

        result = _parse_go_test_json(raw_stdout, raw_output, proc.returncode or 0)

        # Collect coverage if requested
        if collect_coverage:
            try:
                coverage_adapter = GoCoverAdapter()
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

        return result

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse *test_code* as Go with tree-sitter and report syntax errors."""
        source = test_code.encode("utf-8")
        tree = parse_code(source, _GO_LANGUAGE)
        root = tree.root_node

        if not has_parse_errors(root):
            return ValidationResult(valid=True)

        error_ranges = collect_error_ranges(root)
        errors = [f"Syntax error at line {start}-{end}" for start, end in error_ranges]
        return ValidationResult(valid=False, errors=errors)

    def get_required_packages(self) -> list[str]:
        """Return required packages for Go test."""
        return []  # Go test is built-in, no extra packages needed

    def get_required_commands(self) -> list[str]:
        """Return required commands for Go test."""
        return ["go"]


# ── Output parsing ──────────────────────────────────────────────


def _parse_go_test_json(stdout: str, raw_output: str, exit_code: int) -> RunResult:
    """Parse ``go test -json`` line-delimited JSON stream into RunResult.

    Each line is a JSON object with Action, Package, Test, Elapsed, etc.
    We aggregate by (Package, Test) and use the final pass/fail/skip event.
    """
    result = RunResult(raw_output=raw_output)
    # Map (Package, Test) -> last event for that test
    test_events: dict[tuple[str, str], dict[str, object]] = {}

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        action = event.get("Action")
        pkg = str(event.get("Package", ""))
        test_name = str(event.get("Test", ""))
        elapsed = _to_float(event.get("Elapsed", 0))

        if action in ("pass", "fail", "skip") and test_name:
            key = (pkg, test_name)
            test_events[key] = {
                "action": action,
                "package": pkg,
                "test": test_name,
                "elapsed": elapsed,
                "output": event.get("Output", ""),
            }

    for (pkg, test_name), ev in test_events.items():
        action = str(ev.get("action", "fail"))
        elapsed_ms = _to_float(ev.get("elapsed", 0)) * 1000.0
        output = str(ev.get("output", ""))

        if action == "pass":
            status = CaseStatus.PASSED
            result.passed += 1
        elif action == "skip":
            status = CaseStatus.SKIPPED
            result.skipped += 1
        else:
            status = CaseStatus.FAILED
            result.failed += 1

        full_name = f"{pkg}/{test_name}" if pkg else test_name
        result.test_cases.append(
            CaseResult(
                name=full_name,
                status=status,
                duration_ms=elapsed_ms,
                failure_message=output if status == CaseStatus.FAILED else "",
                file_path="",
            )
        )
        result.duration_ms += elapsed_ms

    result.success = result.failed == 0 and result.errors == 0 and exit_code == 0
    return result


def _to_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0
