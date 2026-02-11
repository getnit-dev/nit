"""Tests for GoTestAdapter (adapters/unit/go_test_adapter.py).

Covers detection, prompt template, go test -json parsing, and tree-sitter
validation with sample Go fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.adapters.base import CaseStatus, TestFrameworkAdapter
from nit.adapters.unit.go_test_adapter import (
    GoTestAdapter,
    _parse_go_test_json,
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
