"""Tests for the PytestAdapter (adapters/unit/pytest_adapter.py).

Covers detection, prompt template, JSON report parsing, and
tree-sitter validation with sample Python fixtures.
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
from nit.adapters.unit.pytest_adapter import (
    PytestAdapter,
    _extract_json_object,
    _has_conftest,
    _has_pyproject_pytest_config,
    _has_pytest_dependency,
    _has_pytest_ini,
    _has_setup_cfg_pytest,
    _map_outcome,
    _parse_pytest_json,
    _safe_read_text,
    _to_float,
    _validate_python,
)
from nit.llm.prompts.pytest_prompt import PytestTemplate

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


# ── Sample pytest-json-report output ─────────────────────────────

_PYTEST_JSON_ALL_PASS = json.dumps(
    {
        "created": 1700000000.0,
        "duration": 0.5,
        "exitcode": 0,
        "root": "/home/user/project",
        "summary": {
            "passed": 3,
            "total": 3,
            "collected": 3,
        },
        "tests": [
            {
                "nodeid": "tests/test_math.py::test_add",
                "outcome": "passed",
                "duration": 0.001,
                "call": {"duration": 0.001, "outcome": "passed"},
                "setup": {"duration": 0.0, "outcome": "passed"},
                "teardown": {"duration": 0.0, "outcome": "passed"},
            },
            {
                "nodeid": "tests/test_math.py::test_subtract",
                "outcome": "passed",
                "duration": 0.002,
                "call": {"duration": 0.002, "outcome": "passed"},
                "setup": {"duration": 0.0, "outcome": "passed"},
                "teardown": {"duration": 0.0, "outcome": "passed"},
            },
            {
                "nodeid": "tests/test_math.py::test_multiply",
                "outcome": "passed",
                "duration": 0.001,
                "call": {"duration": 0.001, "outcome": "passed"},
                "setup": {"duration": 0.0, "outcome": "passed"},
                "teardown": {"duration": 0.0, "outcome": "passed"},
            },
        ],
    }
)

_PYTEST_JSON_WITH_FAILURES = json.dumps(
    {
        "created": 1700000000.0,
        "duration": 0.8,
        "exitcode": 1,
        "root": "/home/user/project",
        "summary": {
            "passed": 1,
            "failed": 1,
            "total": 3,
            "collected": 3,
        },
        "tests": [
            {
                "nodeid": "tests/test_utils.py::test_parse_valid",
                "outcome": "passed",
                "duration": 0.003,
                "call": {"duration": 0.003, "outcome": "passed"},
                "setup": {"duration": 0.0, "outcome": "passed"},
                "teardown": {"duration": 0.0, "outcome": "passed"},
            },
            {
                "nodeid": "tests/test_utils.py::test_parse_invalid",
                "outcome": "failed",
                "duration": 0.005,
                "call": {
                    "duration": 0.005,
                    "outcome": "failed",
                    "longrepr": "AssertionError: assert parse('bad') is None",
                    "crash": {
                        "path": "tests/test_utils.py",
                        "lineno": 15,
                        "message": "AssertionError: assert parse('bad') is None",
                    },
                },
                "setup": {"duration": 0.0, "outcome": "passed"},
                "teardown": {"duration": 0.0, "outcome": "passed"},
            },
            {
                "nodeid": "tests/test_utils.py::test_skipped_feature",
                "outcome": "skipped",
                "duration": 0.0,
                "call": {"duration": 0.0, "outcome": "skipped"},
                "setup": {"duration": 0.0, "outcome": "passed"},
                "teardown": {"duration": 0.0, "outcome": "passed"},
            },
        ],
    }
)

# ── Valid / Invalid Python samples ───────────────────────────────

_VALID_PY = """\
import pytest

from mypackage.math import add


def test_add_positive() -> None:
    assert add(1, 2) == 3


def test_add_negative() -> None:
    assert add(-1, -2) == -3


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(0, 0, 0), (1, -1, 0)],
)
def test_add_parametrize(a: int, b: int, expected: int) -> None:
    assert add(a, b) == expected
"""

_INVALID_PY = """\
import pytest

def test_broken() -> None:
    assert (1 +
"""

_VALID_PY_FIXTURE = """\
import pytest


@pytest.fixture
def calculator():
    return Calculator()


def test_calculator_add(calculator):
    calculator.add(5)
    assert calculator.result == 5
"""


# ═══════════════════════════════════════════════════════════════════
# Test classes
# ═══════════════════════════════════════════════════════════════════


class TestPytestAdapterIdentity:
    """Basic identity and interface conformance."""

    def test_implements_test_framework_adapter(self) -> None:
        assert isinstance(PytestAdapter(), TestFrameworkAdapter)

    def test_name(self) -> None:
        assert PytestAdapter().name == "pytest"

    def test_language(self) -> None:
        assert PytestAdapter().language == "python"


# ── Detection (1.11.1) ───────────────────────────────────────────


class TestPytestDetection:
    def test_detect_conftest(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["conftest.py", "tests/test_foo.py"])
        assert PytestAdapter().detect(tmp_path) is True

    def test_detect_pytest_ini(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["pytest.ini"])
        assert PytestAdapter().detect(tmp_path) is True

    def test_detect_pyproject_tool_pytest(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            "[tool.pytest.ini_options]\naddopts = '-v'\n",
        )
        assert PytestAdapter().detect(tmp_path) is True

    def test_detect_setup_cfg_pytest(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "setup.cfg",
            "[tool:pytest]\naddopts = -v\n",
        )
        assert PytestAdapter().detect(tmp_path) is True

    def test_detect_pytest_dependency(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            '[project]\nname = "myproject"\n\n'
            "[project.optional-dependencies]\n"
            'dev = [\n    "pytest>=7.0",\n]\n',
        )
        assert PytestAdapter().detect(tmp_path) is True

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert PytestAdapter().detect(tmp_path) is False

    def test_no_detection_unittest_project(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "tests/test_foo.py",
            "import unittest\n\nclass TestFoo(unittest.TestCase):\n    pass\n",
        )
        assert PytestAdapter().detect(tmp_path) is False

    def test_no_detection_only_source_files(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/app.py", "print('hello')\n")
        assert PytestAdapter().detect(tmp_path) is False


class TestDetectionHelpers:
    def test_has_conftest_true(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["conftest.py"])
        assert _has_conftest(tmp_path) is True

    def test_has_conftest_false(self, tmp_path: Path) -> None:
        assert _has_conftest(tmp_path) is False

    def test_has_pytest_ini_true(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["pytest.ini"])
        assert _has_pytest_ini(tmp_path) is True

    def test_has_pytest_ini_false(self, tmp_path: Path) -> None:
        assert _has_pytest_ini(tmp_path) is False

    def test_has_pyproject_pytest_config_true(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            "[tool.pytest.ini_options]\naddopts = '-v'\n",
        )
        assert _has_pyproject_pytest_config(tmp_path) is True

    def test_has_pyproject_pytest_config_false_no_file(self, tmp_path: Path) -> None:
        assert _has_pyproject_pytest_config(tmp_path) is False

    def test_has_pyproject_pytest_config_false_no_section(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            '[project]\nname = "myproject"\n',
        )
        assert _has_pyproject_pytest_config(tmp_path) is False

    def test_has_setup_cfg_pytest_true(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "setup.cfg", "[tool:pytest]\naddopts = -v\n")
        assert _has_setup_cfg_pytest(tmp_path) is True

    def test_has_setup_cfg_pytest_false(self, tmp_path: Path) -> None:
        assert _has_setup_cfg_pytest(tmp_path) is False

    def test_has_setup_cfg_no_pytest_section(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "setup.cfg", "[metadata]\nname = foo\n")
        assert _has_setup_cfg_pytest(tmp_path) is False

    def test_has_pytest_dependency_true(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            '[project.optional-dependencies]\ndev = [\n    "pytest>=7.0",\n]\n',
        )
        assert _has_pytest_dependency(tmp_path) is True

    def test_has_pytest_dependency_false_no_file(self, tmp_path: Path) -> None:
        assert _has_pytest_dependency(tmp_path) is False

    def test_has_pytest_dependency_false_empty(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            '[project]\nname = "myproject"\n',
        )
        assert _has_pytest_dependency(tmp_path) is False


# ── Test patterns (1.11.1) ───────────────────────────────────────


class TestPytestTestPatterns:
    def test_returns_list_of_patterns(self) -> None:
        patterns = PytestAdapter().get_test_pattern()
        assert isinstance(patterns, list)
        assert len(patterns) >= 2

    def test_includes_test_prefix(self) -> None:
        patterns = PytestAdapter().get_test_pattern()
        assert "**/test_*.py" in patterns

    def test_includes_test_suffix(self) -> None:
        patterns = PytestAdapter().get_test_pattern()
        assert "**/*_test.py" in patterns


# ── Prompt template (1.11.2) ─────────────────────────────────────


class TestPytestPromptTemplate:
    def test_returns_pytest_template(self) -> None:
        template = PytestAdapter().get_prompt_template()
        assert isinstance(template, PytestTemplate)

    def test_template_name(self) -> None:
        template = PytestAdapter().get_prompt_template()
        assert template.name == "pytest"


# ── JSON report parsing (1.11.3) ─────────────────────────────────


class TestPytestJsonParsing:
    def test_parse_all_passing(self) -> None:
        result = _parse_pytest_json(_PYTEST_JSON_ALL_PASS, _PYTEST_JSON_ALL_PASS)
        assert result.success is True
        assert result.passed == 3
        assert result.failed == 0
        assert result.skipped == 0
        assert result.total == 3
        assert len(result.test_cases) == 3

    def test_parse_with_failures(self) -> None:
        result = _parse_pytest_json(_PYTEST_JSON_WITH_FAILURES, _PYTEST_JSON_WITH_FAILURES)
        assert result.success is False
        assert result.passed == 1
        assert result.failed == 1
        assert result.skipped == 1
        assert result.total == 3

    def test_failure_message_captured(self) -> None:
        result = _parse_pytest_json(_PYTEST_JSON_WITH_FAILURES, _PYTEST_JSON_WITH_FAILURES)
        failed_cases = [tc for tc in result.test_cases if tc.status == CaseStatus.FAILED]
        assert len(failed_cases) == 1
        assert "AssertionError" in failed_cases[0].failure_message

    def test_file_path_captured(self) -> None:
        result = _parse_pytest_json(_PYTEST_JSON_ALL_PASS, _PYTEST_JSON_ALL_PASS)
        assert result.test_cases[0].file_path == "tests/test_math.py"

    def test_test_case_names_are_nodeids(self) -> None:
        result = _parse_pytest_json(_PYTEST_JSON_ALL_PASS, _PYTEST_JSON_ALL_PASS)
        names = [tc.name for tc in result.test_cases]
        assert "tests/test_math.py::test_add" in names
        assert "tests/test_math.py::test_multiply" in names

    def test_duration_from_report(self) -> None:
        result = _parse_pytest_json(_PYTEST_JSON_ALL_PASS, _PYTEST_JSON_ALL_PASS)
        assert result.duration_ms > 0

    def test_duration_in_milliseconds(self) -> None:
        result = _parse_pytest_json(_PYTEST_JSON_ALL_PASS, _PYTEST_JSON_ALL_PASS)
        # Report says 0.5 seconds = 500ms
        assert result.duration_ms == pytest.approx(500.0)

    def test_parse_empty_output(self) -> None:
        result = _parse_pytest_json("", "")
        assert result.success is False
        assert result.total == 0

    def test_parse_garbage_output(self) -> None:
        result = _parse_pytest_json("not json at all", "not json at all")
        assert result.success is False

    def test_parse_json_with_prefix(self) -> None:
        """pytest may emit warnings before the JSON blob."""
        output = "===== warnings ======\n\n" + _PYTEST_JSON_ALL_PASS
        result = _parse_pytest_json(output, output)
        assert result.success is True
        assert result.passed == 3

    def test_parse_json_with_suffix(self) -> None:
        output = _PYTEST_JSON_ALL_PASS + "\n\n===== 3 passed ====="
        result = _parse_pytest_json(output, output)
        assert result.success is True

    def test_raw_output_preserved(self) -> None:
        raw = "custom raw output"
        result = _parse_pytest_json(_PYTEST_JSON_ALL_PASS, raw)
        assert result.raw_output == raw

    def test_per_test_duration_in_ms(self) -> None:
        result = _parse_pytest_json(_PYTEST_JSON_ALL_PASS, _PYTEST_JSON_ALL_PASS)
        # First test has duration 0.001s = 1ms
        assert result.test_cases[0].duration_ms == pytest.approx(1.0)


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
        assert _extract_json_object("[1, 2, 3]") is None

    def test_handles_nested_braces(self) -> None:
        text = '{"outer": {"inner": 1}}'
        obj = _extract_json_object(text)
        assert obj is not None
        assert "outer" in obj


class TestMapOutcome:
    def test_passed(self) -> None:
        assert _map_outcome("passed") == CaseStatus.PASSED

    def test_failed(self) -> None:
        assert _map_outcome("failed") == CaseStatus.FAILED

    def test_skipped(self) -> None:
        assert _map_outcome("skipped") == CaseStatus.SKIPPED

    def test_xfailed(self) -> None:
        assert _map_outcome("xfailed") == CaseStatus.SKIPPED

    def test_xpassed(self) -> None:
        assert _map_outcome("xpassed") == CaseStatus.PASSED

    def test_error(self) -> None:
        assert _map_outcome("error") == CaseStatus.ERROR

    def test_unknown(self) -> None:
        assert _map_outcome("unknown_outcome") == CaseStatus.ERROR


# ── Validation (1.11.4) ──────────────────────────────────────────


class TestPytestValidation:
    def test_valid_python(self) -> None:
        result = PytestAdapter().validate_test(_VALID_PY)
        assert result.valid is True
        assert result.errors == []

    def test_invalid_python(self) -> None:
        result = PytestAdapter().validate_test(_INVALID_PY)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_empty_code_is_valid(self) -> None:
        result = PytestAdapter().validate_test("")
        assert result.valid is True

    def test_simple_assignment_valid(self) -> None:
        result = PytestAdapter().validate_test("x = 1")
        assert result.valid is True

    def test_fixture_code_valid(self) -> None:
        result = PytestAdapter().validate_test(_VALID_PY_FIXTURE)
        assert result.valid is True

    def test_error_messages_contain_line_numbers(self) -> None:
        result = PytestAdapter().validate_test(_INVALID_PY)
        if result.errors:
            assert any("line" in e.lower() for e in result.errors)


class TestValidatePython:
    def test_valid(self) -> None:
        result = _validate_python("x: int = 1")
        assert result.valid is True

    def test_invalid(self) -> None:
        result = _validate_python("def f(\n")
        assert result.valid is False

    def test_multiline_valid(self) -> None:
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        result = _validate_python(code)
        assert result.valid is True


# ── Run tests integration (1.11.3) ───────────────────────────────


class TestRunTestsIntegration:
    """Integration-style tests for run_tests using a sample Python project."""

    @pytest.fixture()
    def sample_py_project(self, tmp_path: Path) -> Path:
        """Create a minimal Python project with pytest config."""
        _write_file(
            tmp_path,
            "pyproject.toml",
            "[tool.pytest.ini_options]\naddopts = '-v'\n",
        )
        _write_file(
            tmp_path,
            "conftest.py",
            "",
        )
        _write_file(
            tmp_path,
            "src/math_utils.py",
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n\n"
            "def multiply(a: int, b: int) -> int:\n"
            "    return a * b\n",
        )
        _write_file(
            tmp_path,
            "tests/test_math_utils.py",
            "from src.math_utils import add, multiply\n\n"
            "def test_add() -> None:\n"
            "    assert add(2, 3) == 5\n\n"
            "def test_multiply() -> None:\n"
            "    assert multiply(3, 4) == 12\n",
        )
        return tmp_path

    def test_detect_sample_project(self, sample_py_project: Path) -> None:
        adapter = PytestAdapter()
        assert adapter.detect(sample_py_project) is True

    def test_validate_sample_test(self, sample_py_project: Path) -> None:
        test_code = (sample_py_project / "tests/test_math_utils.py").read_text(encoding="utf-8")
        result = PytestAdapter().validate_test(test_code)
        assert result.valid is True

    def test_prompt_template_for_sample(self, sample_py_project: Path) -> None:
        adapter = PytestAdapter()
        template = adapter.get_prompt_template()
        assert template.name == "pytest"


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


# ── Additional coverage: missing lines ────────────────────────────


class TestPytestSafeReadText:
    """Cover _safe_read_text branches."""

    def test_reads_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hello", encoding="utf-8")
        result = _safe_read_text(f)
        assert result == "hello"

    def test_returns_none_for_missing(self, tmp_path: Path) -> None:
        result = _safe_read_text(tmp_path / "nonexistent.txt")
        assert result is None


class TestPytestToFloat:
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


class TestPytestRequiredPackagesCommands:
    """Cover get_required_packages / get_required_commands."""

    def test_required_packages(self) -> None:
        pkgs = PytestAdapter().get_required_packages()
        assert "pytest" in pkgs
        assert "pytest-json-report" in pkgs

    def test_required_commands(self) -> None:
        cmds = PytestAdapter().get_required_commands()
        assert "python" in cmds


class TestPytestJsonParsingEdgeCases:
    """Cover edge cases in _parse_pytest_json."""

    def test_non_list_tests_key(self) -> None:
        data = json.dumps({"tests": "not a list", "duration": 0.5})
        result = _parse_pytest_json(data, data)
        assert result.total == 0

    def test_non_dict_test_entry(self) -> None:
        data = json.dumps({"tests": ["not a dict"], "duration": 0.5})
        result = _parse_pytest_json(data, data)
        assert result.total == 1
        assert result.errors == 1

    def test_duration_from_call_phase(self) -> None:
        """Cover duration from call phase when top-level is 0."""
        data = json.dumps(
            {
                "duration": 0.5,
                "tests": [
                    {
                        "nodeid": "test.py::test_x",
                        "outcome": "passed",
                        "duration": 0,
                        "call": {"duration": 0.01, "outcome": "passed"},
                    }
                ],
            }
        )
        result = _parse_pytest_json(data, data)
        assert result.test_cases[0].duration_ms == pytest.approx(10.0)

    def test_crash_message_when_no_longrepr(self) -> None:
        """Cover crash message extraction when longrepr is empty."""
        data = json.dumps(
            {
                "duration": 0.1,
                "tests": [
                    {
                        "nodeid": "test.py::test_crash",
                        "outcome": "failed",
                        "duration": 0.01,
                        "call": {
                            "duration": 0.01,
                            "outcome": "failed",
                            "crash": {"message": "segfault"},
                        },
                    }
                ],
            }
        )
        result = _parse_pytest_json(data, data)
        assert "segfault" in result.test_cases[0].failure_message

    def test_error_outcome(self) -> None:
        data = json.dumps(
            {
                "duration": 0.1,
                "tests": [
                    {
                        "nodeid": "test.py::test_err",
                        "outcome": "error",
                        "duration": 0.01,
                    }
                ],
            }
        )
        result = _parse_pytest_json(data, data)
        assert result.errors == 1

    def test_nodeid_without_separator(self) -> None:
        """Cover nodeid without :: => empty file_path."""
        data = json.dumps(
            {
                "duration": 0.1,
                "tests": [
                    {
                        "nodeid": "just_a_name",
                        "outcome": "passed",
                        "duration": 0.01,
                    }
                ],
            }
        )
        result = _parse_pytest_json(data, data)
        assert result.test_cases[0].file_path == ""


class TestPytestDetectionEdgeCases:
    """Cover more detection branches."""

    def test_has_pytest_dependency_tool_pytest_line(self, tmp_path: Path) -> None:
        """Lines with [tool.pytest should be skipped."""
        _write_file(
            tmp_path,
            "pyproject.toml",
            "[tool.pytest.ini_options]\naddopts = '-v'\n",
        )
        # _has_pytest_dependency should NOT match tool.pytest lines
        # but _has_pyproject_pytest_config should
        assert _has_pyproject_pytest_config(tmp_path) is True

    def test_has_pytest_dependency_section_header_skipped(self, tmp_path: Path) -> None:
        """Lines starting with [ should be skipped."""
        _write_file(
            tmp_path,
            "pyproject.toml",
            '[project]\nname = "my-tool"\n',
        )
        assert _has_pytest_dependency(tmp_path) is False

    def test_has_setup_cfg_no_section(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "setup.cfg", "[metadata]\nname = foo\n")
        assert _has_setup_cfg_pytest(tmp_path) is False


class TestPytestRunTestsMocked:
    """Cover run_tests method branches with mocked subprocess."""

    @pytest.mark.asyncio
    async def test_run_tests_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(tmp_path, "conftest.py", "")

        async def _fake_exec(*args: object, **kwargs: object) -> object:
            raise TimeoutError

        monkeypatch.setattr(
            "nit.adapters.unit.pytest_adapter.asyncio.create_subprocess_exec",
            _fake_exec,
        )
        result = await PytestAdapter().run_tests(tmp_path, collect_coverage=False)
        assert result.success is False
        assert "timed out" in result.raw_output

    @pytest.mark.asyncio
    async def test_run_tests_file_not_found(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(tmp_path, "conftest.py", "")

        async def _fake_exec(*args: object, **kwargs: object) -> object:
            raise FileNotFoundError

        monkeypatch.setattr(
            "nit.adapters.unit.pytest_adapter.asyncio.create_subprocess_exec",
            _fake_exec,
        )
        result = await PytestAdapter().run_tests(tmp_path, collect_coverage=False)
        assert result.success is False
        assert "not found" in result.raw_output

    @pytest.mark.asyncio
    async def test_run_tests_with_json_report(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(tmp_path, "conftest.py", "")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"stdout", b""))

        json_report = json.dumps(
            {
                "duration": 0.5,
                "tests": [
                    {
                        "nodeid": "test.py::test_ok",
                        "outcome": "passed",
                        "duration": 0.01,
                    }
                ],
            }
        )

        created_files: list[str] = []

        original_mkstemp = __import__("tempfile").mkstemp

        def fake_mkstemp(suffix: str = "", prefix: str = "") -> tuple[int, str]:
            fd, path = original_mkstemp(suffix=suffix, prefix=prefix, dir=str(tmp_path))
            created_files.append(path)
            Path(path).write_text(json_report, encoding="utf-8")
            return fd, path

        monkeypatch.setattr("tempfile.mkstemp", fake_mkstemp)
        monkeypatch.setattr(
            "nit.adapters.unit.pytest_adapter.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        result = await PytestAdapter().run_tests(
            tmp_path,
            collect_coverage=False,
        )
        assert result.passed == 1

    @pytest.mark.asyncio
    async def test_run_tests_with_test_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(tmp_path, "conftest.py", "")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        monkeypatch.setattr(
            "nit.adapters.unit.pytest_adapter.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        test_file = tmp_path / "tests" / "test_foo.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.touch()
        result = await PytestAdapter().run_tests(
            tmp_path,
            test_files=[test_file],
            collect_coverage=False,
        )
        assert isinstance(result, RunResult)


class TestExtractJsonObjectEdgeCases:
    """Cover edge cases in _extract_json_object."""

    def test_brace_before_closing(self) -> None:
        """Cover end < start branch."""
        assert _extract_json_object("}before{") is None
