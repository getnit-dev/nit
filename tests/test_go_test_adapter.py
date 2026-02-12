"""Tests for GoTestAdapter (adapters/unit/go_test_adapter.py).

Covers detection, prompt template, go test -json parsing, and tree-sitter
validation with sample Go fixtures.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nit.adapters.base import CaseStatus, TestFrameworkAdapter
from nit.adapters.unit.go_test_adapter import (
    GoTestAdapter,
    _parse_go_test_json,
    _to_float,
)
from nit.llm.prompts.go_test_prompt import GoTestTemplate

# ── Helpers ──────────────────────────────────────────────────────


def _make_files(root: Path, rel_paths: list[str]) -> None:
    for rel in rel_paths:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()


def _write_file(root: Path, rel: str, content: str) -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


# ── Sample go test -json output ──────────────────────────────────

_GO_JSON_ALL_PASSED = """\
{"Time":"2024-01-15T10:00:00Z","Action":"run","Package":"mypkg","Test":"TestAdd"}
{"Time":"2024-01-15T10:00:00Z","Action":"pass","Package":"mypkg","Test":"TestAdd","Elapsed":0.001}
{"Time":"2024-01-15T10:00:00Z","Action":"run","Package":"mypkg","Test":"TestSub"}
{"Time":"2024-01-15T10:00:00Z","Action":"pass","Package":"mypkg","Test":"TestSub","Elapsed":0.002}
"""

# Fail line split to satisfy E501; JSON must contain "expected 1, got 0" for test assertion
_GO_JSON_FAIL_LINE = (
    '{"Time":"2024-01-15T10:00:00Z","Action":"fail","Package":"pkg","Test":"TestFail",'
    '"Elapsed":0.002,"Output":"expected 1, got 0\\n"}'
)
_GO_JSON_MIXED = (
    """\
{"Time":"2024-01-15T10:00:00Z","Action":"run","Package":"pkg","Test":"TestPass"}
{"Time":"2024-01-15T10:00:00Z","Action":"pass","Package":"pkg","Test":"TestPass","Elapsed":0.001}
{"Time":"2024-01-15T10:00:00Z","Action":"run","Package":"pkg","Test":"TestFail"}
"""
    + _GO_JSON_FAIL_LINE
    + """
{"Time":"2024-01-15T10:00:00Z","Action":"run","Package":"pkg","Test":"TestSkip"}
{"Time":"2024-01-15T10:00:00Z","Action":"skip","Package":"pkg","Test":"TestSkip","Elapsed":0}
"""
)

# ── Valid / invalid Go samples ──────────────────────────────────

_VALID_GO_TEST = """\
package mypkg

import "testing"

func TestAdd(t *testing.T) {
	if Add(2, 3) != 5 {
		t.Error("expected 5")
	}
}
"""

_INVALID_GO_TEST = """\
package mypkg

import "testing"

func TestBroken(t *testing.T) {
	if true {
"""


# ── Identity ─────────────────────────────────────────────────────


class TestGoTestAdapterIdentity:
    def test_implements_test_framework_adapter(self) -> None:
        assert isinstance(GoTestAdapter(), TestFrameworkAdapter)

    def test_name(self) -> None:
        assert GoTestAdapter().name == "gotest"

    def test_language(self) -> None:
        assert GoTestAdapter().language == "go"


# ── Detection ───────────────────────────────────────────────────


class TestGoTestDetection:
    def test_detect_go_mod_and_test_file(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "go.mod", "module example.com/mypkg\n")
        _write_file(tmp_path, "mypkg_test.go", _VALID_GO_TEST)
        assert GoTestAdapter().detect(tmp_path) is True

    def test_detect_go_mod_and_test_in_subdir(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "go.mod", "module example.com/mypkg\n")
        _write_file(tmp_path, "pkg/foo_test.go", _VALID_GO_TEST)
        assert GoTestAdapter().detect(tmp_path) is True

    def test_no_detection_without_go_mod(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "pkg/foo_test.go", _VALID_GO_TEST)
        assert GoTestAdapter().detect(tmp_path) is False

    def test_no_detection_without_test_files(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "go.mod", "module example.com/mypkg\n")
        _write_file(tmp_path, "main.go", "package main\nfunc main() {}\n")
        assert GoTestAdapter().detect(tmp_path) is False

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert GoTestAdapter().detect(tmp_path) is False


# ── Test patterns ───────────────────────────────────────────────


class TestGoTestPatterns:
    def test_returns_list_of_patterns(self) -> None:
        patterns = GoTestAdapter().get_test_pattern()
        assert isinstance(patterns, list)
        assert "**/*_test.go" in patterns


# ── Prompt template ──────────────────────────────────────────────


class TestGoTestPromptTemplate:
    def test_returns_go_template(self) -> None:
        template = GoTestAdapter().get_prompt_template()
        assert isinstance(template, GoTestTemplate)

    def test_template_name(self) -> None:
        template = GoTestAdapter().get_prompt_template()
        assert template.name == "gotest"


# ── JSON parsing ────────────────────────────────────────────────


class TestGoTestJsonParsing:
    def test_parse_all_passing(self) -> None:
        result = _parse_go_test_json(_GO_JSON_ALL_PASSED, _GO_JSON_ALL_PASSED, 0)
        assert result.success is True
        assert result.passed == 2
        assert result.failed == 0
        assert result.skipped == 0
        assert result.total == 2
        names = [c.name for c in result.test_cases]
        assert "mypkg/TestAdd" in names
        assert "mypkg/TestSub" in names

    def test_parse_mixed_outcomes(self) -> None:
        result = _parse_go_test_json(_GO_JSON_MIXED, _GO_JSON_MIXED, 1)
        assert result.success is False
        assert result.passed == 1
        assert result.failed == 1
        assert result.skipped == 1
        assert result.total == 3
        for c in result.test_cases:
            if c.name == "pkg/TestFail":
                assert c.status == CaseStatus.FAILED
                assert "expected 1, got 0" in c.failure_message
            elif c.name == "pkg/TestSkip":
                assert c.status == CaseStatus.SKIPPED
            elif c.name == "pkg/TestPass":
                assert c.status == CaseStatus.PASSED

    def test_parse_empty_output(self) -> None:
        result = _parse_go_test_json("", "", 0)
        assert result.passed == 0
        assert result.failed == 0
        assert result.total == 0


# ── Validation ───────────────────────────────────────────────────


class TestGoTestValidation:
    def test_valid_go_test_code(self) -> None:
        adapter = GoTestAdapter()
        result = adapter.validate_test(_VALID_GO_TEST)
        assert result.valid is True
        assert result.errors == []

    def test_invalid_go_test_code(self) -> None:
        adapter = GoTestAdapter()
        result = adapter.validate_test(_INVALID_GO_TEST)
        assert result.valid is False
        assert len(result.errors) >= 1


# ── run_tests (integration) ──────────────────────────────────────


class TestGoTestRunTests:
    @pytest.mark.asyncio
    async def test_run_tests_empty_dir_returns_failure(self, tmp_path: Path) -> None:
        adapter = GoTestAdapter()
        result = await adapter.run_tests(tmp_path, timeout=5.0)
        assert result.success is False


# ── Additional coverage tests ─────────────────────────────────────


class TestGoTestToFloat:
    """Tests for _to_float helper covering all branches."""

    def test_int(self) -> None:
        assert _to_float(3) == 3.0

    def test_float(self) -> None:
        assert _to_float(1.5) == 1.5

    def test_valid_string(self) -> None:
        assert _to_float("2.5") == 2.5

    def test_invalid_string(self) -> None:
        assert _to_float("abc") == 0.0

    def test_none(self) -> None:
        assert _to_float(None) == 0.0

    def test_list(self) -> None:
        assert _to_float([1, 2]) == 0.0


class TestGoTestJsonParsingExtended:
    """Extended JSON parsing tests for edge cases."""

    def test_non_json_lines_ignored(self) -> None:
        stdout = """\
not json
{"Action":"pass","Package":"p","Test":"T","Elapsed":0.001}
more garbage
"""
        result = _parse_go_test_json(stdout, stdout, 0)
        assert result.passed == 1

    def test_non_dict_json_ignored(self) -> None:
        stdout = '["array"]\n{"Action":"pass","Package":"p","Test":"T","Elapsed":0.001}\n'
        result = _parse_go_test_json(stdout, stdout, 0)
        assert result.passed == 1

    def test_package_level_pass_ignored(self) -> None:
        # Actions without Test name should be ignored
        stdout = '{"Action":"pass","Package":"mypkg","Elapsed":0.5}\n'
        result = _parse_go_test_json(stdout, stdout, 0)
        assert result.total == 0

    def test_last_event_wins(self) -> None:
        # If a test has both run and pass, pass wins
        stdout = """\
{"Action":"run","Package":"p","Test":"T1"}
{"Action":"output","Package":"p","Test":"T1","Output":"something"}
{"Action":"pass","Package":"p","Test":"T1","Elapsed":0.001}
"""
        result = _parse_go_test_json(stdout, stdout, 0)
        assert result.passed == 1
        assert result.failed == 0

    def test_exit_code_nonzero_no_failures(self) -> None:
        # No test events but nonzero exit code
        result = _parse_go_test_json("", "", 1)
        assert result.success is False

    def test_full_name_with_package(self) -> None:
        stdout = (
            '{"Action":"pass","Package":"github.com/user/pkg",'
            '"Test":"TestSomething","Elapsed":0.001}\n'
        )
        result = _parse_go_test_json(stdout, stdout, 0)
        assert result.test_cases[0].name == "github.com/user/pkg/TestSomething"

    def test_full_name_without_package(self) -> None:
        stdout = '{"Action":"pass","Package":"","Test":"TestSomething","Elapsed":0.001}\n'
        result = _parse_go_test_json(stdout, stdout, 0)
        assert result.test_cases[0].name == "TestSomething"


class TestGoTestRunTestsExtended:
    """Extended async run_tests tests."""

    @pytest.mark.asyncio
    async def test_run_tests_with_test_files_filter(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(tmp_path, "go.mod", "module example.com/mypkg\n")
        test_file = tmp_path / "pkg" / "foo_test.go"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(_VALID_GO_TEST)

        # Track the command that was used
        captured_cmds: list[list[str]] = []

        async def _fake_subprocess(*args: object, **kwargs: object) -> object:
            cmd = args
            captured_cmds.append([str(a) for a in cmd])

            class FakeProc:
                returncode = 0

                async def communicate(self) -> tuple[bytes, bytes]:
                    json_out = (
                        '{"Action":"pass","Package":"./pkg","Test":"TestAdd","Elapsed":0.001}\n'
                    )
                    return json_out.encode(), b""

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_subprocess)

        adapter = GoTestAdapter()
        result = await adapter.run_tests(
            tmp_path, test_files=[test_file], timeout=5.0, collect_coverage=False
        )
        assert result.passed >= 1

    @pytest.mark.asyncio
    async def test_run_tests_non_go_files_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(tmp_path, "go.mod", "module example.com/mypkg\n")

        async def _fake_subprocess(*args: object, **kwargs: object) -> object:
            class FakeProc:
                returncode = 0

                async def communicate(self) -> tuple[bytes, bytes]:
                    return b"", b""

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_subprocess)

        adapter = GoTestAdapter()
        # Pass a non-.go test file
        result = await adapter.run_tests(
            tmp_path,
            test_files=[tmp_path / "readme.txt"],
            timeout=5.0,
            collect_coverage=False,
        )
        # Should still run since non-go files are filtered out
        assert isinstance(result.passed, int)


class TestGoTestRequiredCommands:
    """Tests for get_required_packages and get_required_commands."""

    def test_required_packages_empty(self) -> None:
        assert GoTestAdapter().get_required_packages() == []

    def test_required_commands_go(self) -> None:
        assert "go" in GoTestAdapter().get_required_commands()
