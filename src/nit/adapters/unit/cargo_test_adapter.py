"""Rust cargo test adapter — detection, execution, and validation.

Implements ``TestFrameworkAdapter`` for projects using Rust's built-in
test harness (``#[test]``, ``cargo test``).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.adapters.coverage.tarpaulin import TarpaulinAdapter
from nit.llm.prompts.cargo_test_prompt import CargoTestTemplate
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_CARGO_TOML = "Cargo.toml"
_TEST_PATTERNS = [
    "**/tests/*.rs",
    "**/*.rs",
]
_DEFAULT_TIMEOUT = 120.0
_RUST_LANGUAGE = "rust"

# cargo test pretty: "test module::test_name ... ok" or "... FAILED" or "... ignored"
_TEST_LINE_REGEX = re.compile(r"^\s*test\s+(.+?)\s+\.\.\.\s+(ok|FAILED|ignored)\s*$")
_RESULT_REGEX = re.compile(
    r"test result:\s*(?:ok|FAILED)\.\s*"
    r"(?:(\d+)\s+passed)?;\s*"
    r"(?:(\d+)\s+failed)?;\s*"
    r"(?:(\d+)\s+ignored)?",
    re.IGNORECASE,
)


# ── Adapter ──────────────────────────────────────────────────────


class CargoTestAdapter(TestFrameworkAdapter):
    """Rust cargo test adapter."""

    @property
    def name(self) -> str:
        return "cargo_test"

    @property
    def language(self) -> str:
        return "rust"

    def detect(self, project_path: Path) -> bool:
        """Return True when the project has Cargo.toml and at least one .rs file."""
        if not (project_path / _CARGO_TOML).is_file():
            return False
        return any(path for pattern in _TEST_PATTERNS for path in project_path.glob(pattern))

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    def get_prompt_template(self) -> CargoTestTemplate:
        return CargoTestTemplate()

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        collect_coverage: bool = True,
    ) -> RunResult:
        """Execute tests via ``cargo test`` and parse pretty output.

        Optionally collects coverage using TarpaulinAdapter.
        """
        cmd = ["cargo", "test", "--no-fail-fast", "--", "--nocapture"]
        if test_files:
            # Filter by test name substrings from file paths
            names = []
            for f in test_files:
                if f.suffix != ".rs":
                    continue
                # Use file stem as a possible test name filter
                stem = f.stem
                if stem and stem not in {"lib", "main"}:
                    names.append(stem)
            if names:
                # cargo test <name> runs tests whose name contains <name>
                cmd = ["cargo", "test", "--no-fail-fast", *names, "--", "--nocapture"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning("cargo test timed out after %.1fs", timeout)
            return RunResult(raw_output="cargo test timed out", success=False)
        except FileNotFoundError:
            logger.error("cargo not found — is Rust installed?")
            return RunResult(raw_output="cargo not found", success=False)

        raw_output = stdout_bytes.decode("utf-8", errors="replace")
        result = _parse_cargo_test_output(raw_output, proc.returncode or 0)

        # Collect coverage if requested
        if collect_coverage:
            try:
                coverage_adapter = TarpaulinAdapter()
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
        """Parse *test_code* as Rust with tree-sitter and report syntax errors."""
        source = test_code.encode("utf-8")
        tree = parse_code(source, _RUST_LANGUAGE)
        root = tree.root_node

        if not has_parse_errors(root):
            return ValidationResult(valid=True)

        error_ranges = collect_error_ranges(root)
        errors = [f"Syntax error at line {start}-{end}" for start, end in error_ranges]
        return ValidationResult(valid=False, errors=errors)

    def get_required_packages(self) -> list[str]:
        """Return required packages for cargo test."""
        return []  # Rust test is built-in, no extra packages needed

    def get_required_commands(self) -> list[str]:
        """Return required commands for cargo test."""
        return ["cargo"]


# ── Output parsing ──────────────────────────────────────────────


def _parse_cargo_test_output(raw_output: str, exit_code: int) -> RunResult:
    """Parse cargo test pretty output into RunResult.

    Lines like:
      test foo::bar::test_baz ... ok
      test foo::bar::test_fail ... FAILED
      test foo::bar::test_ignored ... ignored
    Summary:
      test result: ok. 2 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out
    """
    result = RunResult(raw_output=raw_output)
    failures_block = False
    failure_messages: dict[str, str] = {}

    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Failure details: "---- module::test_name stdout ----"
        if stripped.startswith("---- ") and " stdout ----" in stripped:
            failures_block = True
            continue
        if failures_block and stripped.startswith("thread ") and "panicked at" in stripped:
            # Extract test name from previous "thread 'module::test_name' panicked at ..."
            continue

        match = _TEST_LINE_REGEX.match(line)
        if match:
            test_name = match.group(1).strip()
            outcome = match.group(2).strip().lower()
            if outcome == "ok":
                status = CaseStatus.PASSED
                result.passed += 1
            elif outcome == "ignored":
                status = CaseStatus.SKIPPED
                result.skipped += 1
            else:
                status = CaseStatus.FAILED
                result.failed += 1
                failure_messages[test_name] = ""

            result.test_cases.append(
                CaseResult(
                    name=test_name,
                    status=status,
                    duration_ms=0.0,
                    failure_message=failure_messages.get(test_name, ""),
                    file_path="",
                )
            )
            continue

        # Summary line
        res_match = _RESULT_REGEX.search(stripped)
        if res_match:
            # We already accumulated cases from test ... ok/FAILED/ignored lines
            break

    result.success = result.failed == 0 and result.errors == 0 and exit_code == 0
    return result
