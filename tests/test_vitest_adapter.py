"""Tests for the VitestAdapter (adapters/unit/vitest_adapter.py).

Covers detection, prompt template, JSON reporter parsing, and
tree-sitter validation with sample TypeScript fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.adapters.base import (
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.adapters.unit.vitest_adapter import (
    VitestAdapter,
    _extract_json_object,
    _has_config_file,
    _has_vitest_dependency,
    _looks_like_tsx,
    _map_status,
    _parse_vitest_json,
    _read_vitest_config,
    _safe_iterdir,
    _to_float,
    _validate_typescript,
)
from nit.llm.prompts.vitest import VitestTemplate

# ── Helpers ──────────────────────────────────────────────────────


def _make_files(root: Path, rel_paths: list[str]) -> None:
    """Create empty files (with parent directories) under *root*."""
    for rel in rel_paths:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()


def _write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file under *root*."""
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def _write_package_json(root: Path, data: dict[str, object]) -> None:
    """Write a ``package.json`` at *root*."""
    (root / "package.json").write_text(json.dumps(data), encoding="utf-8")


# ── Sample Vitest JSON reporter output ───────────────────────────

_VITEST_JSON_ALL_PASS = json.dumps(
    {
        "numTotalTestSuites": 1,
        "numPassedTestSuites": 1,
        "numFailedTestSuites": 0,
        "numPendingTestSuites": 0,
        "numTotalTests": 3,
        "numPassedTests": 3,
        "numFailedTests": 0,
        "numPendingTests": 0,
        "numTodoTests": 0,
        "testResults": [
            {
                "name": "src/math.test.ts",
                "duration": 42,
                "assertionResults": [
                    {
                        "fullName": "add > should return the sum",
                        "title": "should return the sum",
                        "status": "passed",
                        "duration": 2,
                        "failureMessages": [],
                    },
                    {
                        "fullName": "add > should handle negatives",
                        "title": "should handle negatives",
                        "status": "passed",
                        "duration": 1,
                        "failureMessages": [],
                    },
                    {
                        "fullName": "multiply > should multiply",
                        "title": "should multiply",
                        "status": "passed",
                        "duration": 1,
                        "failureMessages": [],
                    },
                ],
            },
        ],
    }
)

_VITEST_JSON_WITH_FAILURES = json.dumps(
    {
        "numTotalTests": 3,
        "numPassedTests": 1,
        "numFailedTests": 1,
        "numPendingTests": 1,
        "testResults": [
            {
                "name": "src/utils.test.ts",
                "duration": 100,
                "assertionResults": [
                    {
                        "fullName": "parse > should parse valid input",
                        "title": "should parse valid input",
                        "status": "passed",
                        "duration": 5,
                        "failureMessages": [],
                    },
                    {
                        "fullName": "parse > should reject invalid input",
                        "title": "should reject invalid input",
                        "status": "failed",
                        "duration": 3,
                        "failureMessages": ["AssertionError: expected true to be false"],
                    },
                    {
                        "fullName": "parse > pending test",
                        "title": "pending test",
                        "status": "pending",
                        "duration": 0,
                        "failureMessages": [],
                    },
                ],
            },
        ],
    }
)

# ── Valid / Invalid TypeScript samples ───────────────────────────

_VALID_TS = """\
import { describe, it, expect } from 'vitest';
import { add } from '../math';

describe('add', () => {
  it('should add two numbers', () => {
    expect(add(1, 2)).toBe(3);
  });
});
"""

_INVALID_TS = """\
import { describe, it, expect } from 'vitest';

describe('broken', () => {
  it('syntax error', () => {
    expect(1 + )).toBe(3);
  });
});
"""

_VALID_TSX = """\
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { Button } from './Button';

describe('Button', () => {
  it('renders', () => {
    const { getByText } = render(<Button label="click" />);
    expect(getByText('click')).toBeTruthy();
  });
});
"""


# ═══════════════════════════════════════════════════════════════════
# Test classes
# ═══════════════════════════════════════════════════════════════════


class TestVitestAdapterIdentity:
    """Basic identity and interface conformance."""

    def test_implements_test_framework_adapter(self) -> None:
        assert isinstance(VitestAdapter(), TestFrameworkAdapter)

    def test_name(self) -> None:
        assert VitestAdapter().name == "vitest"

    def test_language(self) -> None:
        assert VitestAdapter().language == "typescript"


# ── Detection (1.10.1) ───────────────────────────────────────────


class TestVitestDetection:
    def test_detect_vitest_config_ts(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["vitest.config.ts", "src/index.ts"])
        assert VitestAdapter().detect(tmp_path) is True

    def test_detect_vitest_config_js(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["vitest.config.js"])
        assert VitestAdapter().detect(tmp_path) is True

    def test_detect_vitest_config_mts(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["vitest.config.mts"])
        assert VitestAdapter().detect(tmp_path) is True

    def test_detect_vitest_workspace(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["vitest.workspace.ts"])
        assert VitestAdapter().detect(tmp_path) is True

    def test_detect_vitest_devdep(self, tmp_path: Path) -> None:
        _write_package_json(tmp_path, {"devDependencies": {"vitest": "^1.0.0"}})
        assert VitestAdapter().detect(tmp_path) is True

    def test_detect_vitest_dep(self, tmp_path: Path) -> None:
        _write_package_json(tmp_path, {"dependencies": {"vitest": "^1.0.0"}})
        assert VitestAdapter().detect(tmp_path) is True

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert VitestAdapter().detect(tmp_path) is False

    def test_no_detection_jest_project(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["jest.config.js"])
        _write_package_json(tmp_path, {"devDependencies": {"jest": "^29.0.0"}})
        assert VitestAdapter().detect(tmp_path) is False

    def test_no_detection_invalid_package_json(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "package.json", "NOT JSON")
        assert VitestAdapter().detect(tmp_path) is False

    def test_no_detection_no_vitest_in_deps(self, tmp_path: Path) -> None:
        _write_package_json(tmp_path, {"devDependencies": {"jest": "^29.0"}})
        assert VitestAdapter().detect(tmp_path) is False


class TestDetectionHelpers:
    def test_has_config_file_true(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["vitest.config.ts"])
        assert _has_config_file(tmp_path) is True

    def test_has_config_file_false(self, tmp_path: Path) -> None:
        assert _has_config_file(tmp_path) is False

    def test_has_vitest_dependency_true(self, tmp_path: Path) -> None:
        _write_package_json(tmp_path, {"devDependencies": {"vitest": "^1.0.0"}})
        assert _has_vitest_dependency(tmp_path) is True

    def test_has_vitest_dependency_false_no_file(self, tmp_path: Path) -> None:
        assert _has_vitest_dependency(tmp_path) is False

    def test_has_vitest_dependency_false_empty_deps(self, tmp_path: Path) -> None:
        _write_package_json(tmp_path, {})
        assert _has_vitest_dependency(tmp_path) is False


# ── Test patterns (1.10.1) ───────────────────────────────────────


class TestVitestTestPatterns:
    def test_returns_list_of_patterns(self) -> None:
        patterns = VitestAdapter().get_test_pattern()
        assert isinstance(patterns, list)
        assert len(patterns) >= 2

    def test_includes_test_ts(self) -> None:
        patterns = VitestAdapter().get_test_pattern()
        assert "**/*.test.ts" in patterns

    def test_includes_test_tsx(self) -> None:
        patterns = VitestAdapter().get_test_pattern()
        assert "**/*.test.tsx" in patterns

    def test_includes_spec_ts(self) -> None:
        patterns = VitestAdapter().get_test_pattern()
        assert "**/*.spec.ts" in patterns


# ── Prompt template (1.10.2) ─────────────────────────────────────


class TestVitestPromptTemplate:
    def test_returns_vitest_template(self) -> None:
        template = VitestAdapter().get_prompt_template()
        assert isinstance(template, VitestTemplate)

    def test_template_name(self) -> None:
        template = VitestAdapter().get_prompt_template()
        assert template.name == "vitest"


# ── JSON reporter parsing (1.10.3) ───────────────────────────────


class TestVitestJsonParsing:
    def test_parse_all_passing(self) -> None:
        result = _parse_vitest_json(_VITEST_JSON_ALL_PASS, _VITEST_JSON_ALL_PASS)
        assert result.success is True
        assert result.passed == 3
        assert result.failed == 0
        assert result.skipped == 0
        assert result.total == 3
        assert len(result.test_cases) == 3

    def test_parse_with_failures(self) -> None:
        result = _parse_vitest_json(_VITEST_JSON_WITH_FAILURES, _VITEST_JSON_WITH_FAILURES)
        assert result.success is False
        assert result.passed == 1
        assert result.failed == 1
        assert result.skipped == 1
        assert result.total == 3

    def test_failure_message_captured(self) -> None:
        result = _parse_vitest_json(_VITEST_JSON_WITH_FAILURES, _VITEST_JSON_WITH_FAILURES)
        failed_cases = [tc for tc in result.test_cases if tc.status == CaseStatus.FAILED]
        assert len(failed_cases) == 1
        assert "AssertionError" in failed_cases[0].failure_message

    def test_file_path_captured(self) -> None:
        result = _parse_vitest_json(_VITEST_JSON_ALL_PASS, _VITEST_JSON_ALL_PASS)
        assert result.test_cases[0].file_path == "src/math.test.ts"

    def test_test_case_names(self) -> None:
        result = _parse_vitest_json(_VITEST_JSON_ALL_PASS, _VITEST_JSON_ALL_PASS)
        names = [tc.name for tc in result.test_cases]
        assert "add > should return the sum" in names
        assert "multiply > should multiply" in names

    def test_duration_accumulated(self) -> None:
        result = _parse_vitest_json(_VITEST_JSON_ALL_PASS, _VITEST_JSON_ALL_PASS)
        assert result.duration_ms > 0

    def test_parse_empty_output(self) -> None:
        result = _parse_vitest_json("", "")
        assert result.success is False
        assert result.total == 0

    def test_parse_garbage_output(self) -> None:
        result = _parse_vitest_json("not json at all", "not json at all")
        assert result.success is False

    def test_parse_json_with_prefix(self) -> None:
        """Vitest may emit progress text before the JSON blob."""
        output = "Running tests...\n\n" + _VITEST_JSON_ALL_PASS
        result = _parse_vitest_json(output, output)
        assert result.success is True
        assert result.passed == 3

    def test_parse_json_with_suffix(self) -> None:
        output = _VITEST_JSON_ALL_PASS + "\n\nDone in 1.2s"
        result = _parse_vitest_json(output, output)
        assert result.success is True

    def test_raw_output_preserved(self) -> None:
        raw = "custom raw output"
        result = _parse_vitest_json(_VITEST_JSON_ALL_PASS, raw)
        assert result.raw_output == raw


class TestExtractJsonObject:
    def test_extracts_valid_json(self) -> None:
        text = 'prefix {"key": "value"} suffix'
        obj = _extract_json_object(text)
        assert obj is not None
        assert obj["key"] == "value"

    def test_returns_none_for_no_json(self) -> None:
        assert _extract_json_object("no json here") is None

    def test_returns_none_for_empty(self) -> None:
        assert _extract_json_object("") is None

    def test_returns_none_for_invalid_json(self) -> None:
        assert _extract_json_object("{invalid}") is None

    def test_returns_none_for_array(self) -> None:
        # We only want objects, not arrays
        assert _extract_json_object("[1, 2, 3]") is None

    def test_handles_nested_braces(self) -> None:
        text = '{"outer": {"inner": 1}}'
        obj = _extract_json_object(text)
        assert obj is not None
        assert "outer" in obj


class TestMapStatus:
    def test_passed(self) -> None:
        assert _map_status("passed") == CaseStatus.PASSED

    def test_failed(self) -> None:
        assert _map_status("failed") == CaseStatus.FAILED

    def test_skipped(self) -> None:
        assert _map_status("skipped") == CaseStatus.SKIPPED

    def test_pending(self) -> None:
        assert _map_status("pending") == CaseStatus.SKIPPED

    def test_todo(self) -> None:
        assert _map_status("todo") == CaseStatus.SKIPPED

    def test_unknown(self) -> None:
        assert _map_status("unknown_status") == CaseStatus.ERROR


# ── Validation (1.10.4) ──────────────────────────────────────────


class TestVitestValidation:
    def test_valid_typescript(self) -> None:
        result = VitestAdapter().validate_test(_VALID_TS)
        assert result.valid is True
        assert result.errors == []

    def test_invalid_typescript(self) -> None:
        result = VitestAdapter().validate_test(_INVALID_TS)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_empty_code_is_valid(self) -> None:
        result = VitestAdapter().validate_test("")
        assert result.valid is True

    def test_simple_assignment_valid(self) -> None:
        result = VitestAdapter().validate_test("const x = 1;")
        assert result.valid is True

    def test_tsx_detected_and_validated(self) -> None:
        result = VitestAdapter().validate_test(_VALID_TSX)
        assert result.valid is True

    def test_error_messages_contain_line_numbers(self) -> None:
        result = VitestAdapter().validate_test(_INVALID_TS)
        if result.errors:
            assert any("line" in e.lower() for e in result.errors)


class TestValidateTypescript:
    def test_valid(self) -> None:
        result = _validate_typescript("const x: number = 1;")
        assert result.valid is True

    def test_invalid(self) -> None:
        result = _validate_typescript("const x = ;")
        assert result.valid is False

    def test_multiline_valid(self) -> None:
        code = "function add(a: number, b: number): number {\n  return a + b;\n}\n"
        result = _validate_typescript(code)
        assert result.valid is True


class TestLooksLikeTsx:
    def test_jsx_closing_tag(self) -> None:
        assert _looks_like_tsx("<div></div>") is True

    def test_self_closing_tag(self) -> None:
        assert _looks_like_tsx("<Button />") is True

    def test_plain_typescript(self) -> None:
        assert _looks_like_tsx("const x = 1;") is False

    def test_jsx_keyword(self) -> None:
        assert _looks_like_tsx("// JSX component") is True


# ── Run tests integration (1.10.3) ──────────────────────────────


class TestRunTestsIntegration:
    """Integration-style tests for run_tests using a sample TS project fixture."""

    @pytest.fixture()
    def sample_ts_project(self, tmp_path: Path) -> Path:
        """Create a minimal TypeScript project with Vitest config."""
        _write_package_json(
            tmp_path,
            {
                "name": "sample-ts-project",
                "devDependencies": {"vitest": "^1.0.0", "typescript": "^5.0.0"},
                "scripts": {"test": "vitest run"},
            },
        )
        _write_file(
            tmp_path,
            "vitest.config.ts",
            'import { defineConfig } from "vitest/config";\n'
            "export default defineConfig({ test: { reporter: 'json' } });\n",
        )
        _write_file(
            tmp_path,
            "src/math.ts",
            "export function add(a: number, b: number): number {\n"
            "  return a + b;\n"
            "}\n"
            "export function multiply(a: number, b: number): number {\n"
            "  return a * b;\n"
            "}\n",
        )
        _write_file(
            tmp_path,
            "src/math.test.ts",
            "import { describe, it, expect } from 'vitest';\n"
            "import { add, multiply } from './math';\n\n"
            "describe('add', () => {\n"
            "  it('should return the sum', () => {\n"
            "    expect(add(2, 3)).toBe(5);\n"
            "  });\n"
            "});\n\n"
            "describe('multiply', () => {\n"
            "  it('should return the product', () => {\n"
            "    expect(multiply(3, 4)).toBe(12);\n"
            "  });\n"
            "});\n",
        )
        return tmp_path

    def test_detect_sample_project(self, sample_ts_project: Path) -> None:
        adapter = VitestAdapter()
        assert adapter.detect(sample_ts_project) is True

    def test_validate_sample_test(self, sample_ts_project: Path) -> None:
        test_code = (sample_ts_project / "src/math.test.ts").read_text(encoding="utf-8")
        result = VitestAdapter().validate_test(test_code)
        assert result.valid is True

    def test_prompt_template_for_sample(self, sample_ts_project: Path) -> None:
        adapter = VitestAdapter()
        template = adapter.get_prompt_template()
        assert template.name == "vitest"


# ── RunResult dataclass ─────────────────────────────────────────


class TestTestResult:
    def test_total_property(self) -> None:
        result = RunResult(passed=5, failed=2, skipped=1, errors=0)
        assert result.total == 8

    def test_default_values(self) -> None:
        result = RunResult()
        assert result.total == 0
        assert result.success is False
        assert result.raw_output == ""

    def test_success_flag(self) -> None:
        result = RunResult(passed=3, failed=0, errors=0, success=True)
        assert result.success is True


class TestValidationResult:
    def test_valid_result(self) -> None:
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_invalid_result(self) -> None:
        result = ValidationResult(valid=False, errors=["Syntax error at line 5-5"])
        assert result.valid is False
        assert len(result.errors) == 1


class TestVitestEnvironmentPackages:
    """Test environment package detection from vitest config."""

    def test_detects_jsdom_environment(self, tmp_path: Path) -> None:
        """Detect jsdom when environment is set to jsdom."""
        config = tmp_path / "vitest.config.ts"
        config.write_text("""
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
  },
});
""")
        adapter = VitestAdapter()
        packages = adapter.get_environment_packages(tmp_path)
        assert "jsdom" in packages

    def test_detects_happy_dom_environment(self, tmp_path: Path) -> None:
        """Detect happy-dom when environment is set to happy-dom."""
        config = tmp_path / "vitest.config.js"
        config.write_text("""
export default {
  test: {
    environment: "happy-dom",
  },
};
""")
        adapter = VitestAdapter()
        packages = adapter.get_environment_packages(tmp_path)
        assert "happy-dom" in packages

    def test_detects_coverage_provider(self, tmp_path: Path) -> None:
        """Detect coverage provider packages."""
        config = tmp_path / "vitest.config.ts"
        config.write_text("""
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    coverage: {
      provider: 'v8',
    },
  },
});
""")
        adapter = VitestAdapter()
        packages = adapter.get_environment_packages(tmp_path)
        assert "@vitest/coverage-v8" in packages

    def test_no_config_returns_empty(self, tmp_path: Path) -> None:
        """Return empty list when no config file exists."""
        adapter = VitestAdapter()
        packages = adapter.get_environment_packages(tmp_path)
        assert packages == []

    def test_detects_multiple_packages(self, tmp_path: Path) -> None:
        """Detect multiple environment packages from config."""
        config = tmp_path / "vitest.config.ts"
        config.write_text("""
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    coverage: {
      provider: 'istanbul',
    },
  },
});
""")
        adapter = VitestAdapter()
        packages = adapter.get_environment_packages(tmp_path)
        assert "jsdom" in packages
        assert "@vitest/coverage-istanbul" in packages


# ── Additional coverage: missing lines ────────────────────────────


class TestVitestToFloat:
    """Cover _to_float branches."""

    def test_float_value(self) -> None:
        assert _to_float(1.5) == 1.5

    def test_int_value(self) -> None:
        assert _to_float(42) == 42.0

    def test_string_value(self) -> None:
        assert _to_float("3.14") == pytest.approx(3.14)

    def test_invalid_returns_zero(self) -> None:
        assert _to_float("not a number") == 0.0
        assert _to_float(None) == 0.0


class TestVitestSafeIterdir:
    """Cover _safe_iterdir branches."""

    def test_existing_dir(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").touch()
        result = _safe_iterdir(tmp_path)
        assert len(result) >= 1

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        result = _safe_iterdir(tmp_path / "nope")
        assert result == []


class TestVitestReadConfig:
    """Cover _read_vitest_config."""

    def test_reads_existing_config(self, tmp_path: Path) -> None:
        config = tmp_path / "vitest.config.ts"
        config.write_text("export default {}", encoding="utf-8")
        result = _read_vitest_config(tmp_path)
        assert result is not None
        assert "export" in result

    def test_returns_none_when_no_config(self, tmp_path: Path) -> None:
        assert _read_vitest_config(tmp_path) is None


class TestVitestRequiredPackagesCommands:
    """Cover get_required_packages / get_required_commands."""

    def test_required_packages(self) -> None:
        pkgs = VitestAdapter().get_required_packages()
        assert "vitest" in pkgs

    def test_required_commands(self) -> None:
        cmds = VitestAdapter().get_required_commands()
        assert "node" in cmds
        assert "npx" in cmds


class TestVitestRunTestsMocked:
    """Cover run_tests branches with mocked subprocess."""

    @pytest.mark.asyncio
    async def test_run_tests_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make_files(tmp_path, ["vitest.config.ts"])

        async def _fake_exec(*args: object, **kwargs: object) -> object:
            raise TimeoutError

        monkeypatch.setattr(
            "nit.adapters.unit.vitest_adapter.asyncio.create_subprocess_exec",
            _fake_exec,
        )
        result = await VitestAdapter().run_tests(tmp_path, collect_coverage=False)
        assert result.success is False
        assert "timed out" in result.raw_output

    @pytest.mark.asyncio
    async def test_run_tests_file_not_found(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make_files(tmp_path, ["vitest.config.ts"])

        async def _fake_exec(*args: object, **kwargs: object) -> object:
            raise FileNotFoundError

        monkeypatch.setattr(
            "nit.adapters.unit.vitest_adapter.asyncio.create_subprocess_exec",
            _fake_exec,
        )
        result = await VitestAdapter().run_tests(tmp_path, collect_coverage=False)
        assert result.success is False
        assert "not found" in result.raw_output

    @pytest.mark.asyncio
    async def test_run_tests_success(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make_files(tmp_path, ["vitest.config.ts"])

        json_output = json.dumps(
            {
                "testResults": [
                    {
                        "name": "test.ts",
                        "duration": 10,
                        "assertionResults": [
                            {
                                "fullName": "test > works",
                                "status": "passed",
                                "duration": 5,
                                "failureMessages": [],
                            }
                        ],
                    }
                ],
            }
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(json_output.encode(), b""))

        monkeypatch.setattr(
            "nit.adapters.unit.vitest_adapter.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        result = await VitestAdapter().run_tests(tmp_path, collect_coverage=False)
        assert result.passed == 1
        assert result.success is True

    @pytest.mark.asyncio
    async def test_run_tests_with_test_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make_files(tmp_path, ["vitest.config.ts"])

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"{}", b""))

        monkeypatch.setattr(
            "nit.adapters.unit.vitest_adapter.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        test_file = Path("/src/math.test.ts")
        result = await VitestAdapter().run_tests(
            tmp_path,
            test_files=[test_file],
            collect_coverage=False,
        )
        assert isinstance(result.passed, int)

    @pytest.mark.asyncio
    async def test_run_tests_with_stderr(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make_files(tmp_path, ["vitest.config.ts"])

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error output"))

        monkeypatch.setattr(
            "nit.adapters.unit.vitest_adapter.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        result = await VitestAdapter().run_tests(tmp_path, collect_coverage=False)
        assert "error output" in result.raw_output


class TestVitestJsonParsingEdgeCases:
    """Cover more JSON parsing edge cases."""

    def test_non_list_test_results(self) -> None:
        data = json.dumps({"testResults": "not a list"})
        result = _parse_vitest_json(data, data)
        assert result.total == 0

    def test_non_dict_suite(self) -> None:
        data = json.dumps({"testResults": ["not a dict"]})
        result = _parse_vitest_json(data, data)
        assert result.total == 0

    def test_non_list_assertion_results(self) -> None:
        data = json.dumps(
            {"testResults": [{"name": "t", "duration": 1, "assertionResults": "bad"}]}
        )
        result = _parse_vitest_json(data, data)
        assert result.total == 0

    def test_non_dict_assertion(self) -> None:
        data = json.dumps(
            {"testResults": [{"name": "t", "duration": 1, "assertionResults": ["not a dict"]}]}
        )
        result = _parse_vitest_json(data, data)
        assert result.total == 1
        # Non-dict entry coerced to empty dict, status="failed" by default
        assert result.failed == 1

    def test_error_status_mapping(self) -> None:
        data = json.dumps(
            {
                "testResults": [
                    {
                        "name": "t",
                        "duration": 1,
                        "assertionResults": [
                            {
                                "fullName": "err",
                                "status": "unknown_status",
                                "duration": 0,
                                "failureMessages": [],
                            }
                        ],
                    }
                ]
            }
        )
        result = _parse_vitest_json(data, data)
        assert result.errors == 1

    def test_assertion_uses_title_when_no_fullname(self) -> None:
        data = json.dumps(
            {
                "testResults": [
                    {
                        "name": "t",
                        "duration": 1,
                        "assertionResults": [
                            {
                                "title": "my test",
                                "status": "passed",
                                "duration": 1,
                                "failureMessages": [],
                            }
                        ],
                    }
                ]
            }
        )
        result = _parse_vitest_json(data, data)
        assert result.test_cases[0].name == "my test"


class TestVitestExtractJsonEdge:
    """Cover edge cases for _extract_json_object."""

    def test_brace_mismatch(self) -> None:
        assert _extract_json_object("}before{") is None

    def test_non_dict_json(self) -> None:
        # Array parsed but we want dict only
        assert _extract_json_object("[1, 2]") is None


class TestVitestEnvironmentPackagesExtended:
    """Cover more environment package detection branches."""

    def test_ui_mode_detection(self, tmp_path: Path) -> None:
        config = tmp_path / "vitest.config.ts"
        config.write_text("""
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    ui: '@vitest/ui',
  },
});
""")
        adapter = VitestAdapter()
        packages = adapter.get_environment_packages(tmp_path)
        assert "@vitest/ui" in packages
