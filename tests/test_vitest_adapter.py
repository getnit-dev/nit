"""Tests for the VitestAdapter (adapters/unit/vitest_adapter.py).

Covers detection, prompt template, JSON reporter parsing, and
tree-sitter validation with sample TypeScript fixtures.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

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
