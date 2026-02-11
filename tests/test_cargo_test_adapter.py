"""Tests for CargoTestAdapter (adapters/unit/cargo_test_adapter.py).

Covers detection, prompt template, cargo test output parsing, and tree-sitter
validation with sample Rust fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.adapters.base import CaseStatus, TestFrameworkAdapter
from nit.adapters.unit.cargo_test_adapter import (
    CargoTestAdapter,
    _parse_cargo_test_output,
)
from nit.llm.prompts.cargo_test_prompt import CargoTestTemplate


def _write_file(root: Path, rel: str, content: str) -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


# ── Sample cargo test output ──────────────────────────────────────

_CARGO_OUTPUT_TWO_OK = """\
   Compiling mylib v0.1.0
    Finished `test` profile
     Running unittests src/lib.rs
running 2 tests
test tests::test_add ... ok
test tests::test_sub ... ok
test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
"""

_CARGO_TEST_MIXED = """\
running 3 tests
test foo::bar::test_pass ... ok
test foo::bar::test_fail ... FAILED
test foo::bar::test_ignored ... ignored
failures:
    foo::bar::test_fail
test result: FAILED. 1 passed; 1 failed; 1 ignored; 0 measured; 0 filtered out
"""

# ── Valid / invalid Rust test samples ──────────────────────────────

_VALID_RUST_TEST = """\
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_add() {
        assert_eq!(add(2, 3), 5);
    }
}
"""

_INVALID_RUST_TEST = """\
#[cfg(test)]
mod tests {
    #[test]
    fn test_broken() {
        assert_eq!(1
"""


# ── Identity ─────────────────────────────────────────────────────


class TestCargoTestAdapterIdentity:
    def test_implements_test_framework_adapter(self) -> None:
        assert isinstance(CargoTestAdapter(), TestFrameworkAdapter)

    def test_name(self) -> None:
        assert CargoTestAdapter().name == "cargo_test"

    def test_language(self) -> None:
        assert CargoTestAdapter().language == "rust"


# ── Detection ─────────────────────────────────────────────────────


class TestCargoTestDetection:
    def test_detect_cargo_toml_and_rs_file(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "Cargo.toml", '[package]\nname = "mylib"\n')
        _write_file(tmp_path, "src/lib.rs", "pub fn add(a: i32, b: i32) -> i32 { a + b }\n")
        assert CargoTestAdapter().detect(tmp_path) is True

    def test_detect_cargo_toml_and_tests_dir(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "Cargo.toml", '[package]\nname = "mylib"\n')
        _write_file(tmp_path, "tests/integration.rs", "// integration test\n")
        assert CargoTestAdapter().detect(tmp_path) is True

    def test_no_detection_without_cargo_toml(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/lib.rs", "fn main() {}\n")
        assert CargoTestAdapter().detect(tmp_path) is False

    def test_no_detection_without_rs_files(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "Cargo.toml", '[package]\nname = "mylib"\n')
        assert CargoTestAdapter().detect(tmp_path) is False

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert CargoTestAdapter().detect(tmp_path) is False


# ── Test patterns ─────────────────────────────────────────────────


class TestCargoTestPatterns:
    def test_returns_list_of_patterns(self) -> None:
        patterns = CargoTestAdapter().get_test_pattern()
        assert isinstance(patterns, list)
        assert "**/tests/*.rs" in patterns
        assert "**/*.rs" in patterns


# ── Prompt template ──────────────────────────────────────────────


class TestCargoTestPromptTemplate:
    def test_returns_cargo_template(self) -> None:
        template = CargoTestAdapter().get_prompt_template()
        assert isinstance(template, CargoTestTemplate)

    def test_template_name(self) -> None:
        template = CargoTestAdapter().get_prompt_template()
        assert template.name == "cargo_test"


# ── Output parsing ────────────────────────────────────────────────


class TestCargoTestOutputParsing:
    def test_parse_all_passing(self) -> None:
        result = _parse_cargo_test_output(_CARGO_OUTPUT_TWO_OK, 0)
        assert result.success is True
        assert result.passed == 2
        assert result.failed == 0
        assert result.skipped == 0
        assert result.total == 2
        names = [c.name for c in result.test_cases]
        assert "tests::test_add" in names
        assert "tests::test_sub" in names

    def test_parse_mixed_outcomes(self) -> None:
        result = _parse_cargo_test_output(_CARGO_TEST_MIXED, 1)
        assert result.success is False
        assert result.passed == 1
        assert result.failed == 1
        assert result.skipped == 1
        assert result.total == 3
        for c in result.test_cases:
            if c.name == "foo::bar::test_fail":
                assert c.status == CaseStatus.FAILED
            elif c.name == "foo::bar::test_ignored":
                assert c.status == CaseStatus.SKIPPED
            elif c.name == "foo::bar::test_pass":
                assert c.status == CaseStatus.PASSED

    def test_parse_empty_output(self) -> None:
        result = _parse_cargo_test_output("", 0)
        assert result.passed == 0
        assert result.failed == 0
        assert result.total == 0


# ── Validation ───────────────────────────────────────────────────


class TestCargoTestValidation:
    def test_valid_rust_test_code(self) -> None:
        adapter = CargoTestAdapter()
        result = adapter.validate_test(_VALID_RUST_TEST)
        assert result.valid is True
        assert result.errors == []

    def test_invalid_rust_test_code(self) -> None:
        adapter = CargoTestAdapter()
        result = adapter.validate_test(_INVALID_RUST_TEST)
        assert result.valid is False
        assert len(result.errors) >= 1


# ── run_tests (integration) ──────────────────────────────────────


class TestCargoTestRunTests:
    @pytest.mark.asyncio
    async def test_run_tests_empty_dir_returns_failure(self, tmp_path: Path) -> None:
        adapter = CargoTestAdapter()
        result = await adapter.run_tests(tmp_path, timeout=5.0)
        assert result.success is False
