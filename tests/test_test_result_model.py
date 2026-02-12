"""Tests for TestResult data model."""

from __future__ import annotations

from dataclasses import fields

from nit.models.test_result import TestResult


class TestConstruction:
    def test_all_fields(self) -> None:
        result = TestResult(
            name="test_login",
            passed=True,
            duration=0.42,
            error_message="unexpected error",
            file_path="tests/test_auth.py",
        )
        assert result.name == "test_login"
        assert result.passed is True
        assert result.duration == 0.42
        assert result.error_message == "unexpected error"
        assert result.file_path == "tests/test_auth.py"

    def test_minimal_fields(self) -> None:
        result = TestResult(name="test_add", passed=False)
        assert result.name == "test_add"
        assert result.passed is False

    def test_defaults(self) -> None:
        result = TestResult(name="test_x", passed=True)
        assert result.duration is None
        assert result.error_message is None
        assert result.file_path is None


class TestFieldValues:
    def test_passing_result(self) -> None:
        result = TestResult(name="test_ok", passed=True, duration=0.01)
        assert result.passed is True
        assert result.error_message is None

    def test_failing_result_with_error(self) -> None:
        result = TestResult(
            name="test_fail",
            passed=False,
            error_message="AssertionError: 1 != 2",
        )
        assert result.passed is False
        assert result.error_message == "AssertionError: 1 != 2"

    def test_zero_duration(self) -> None:
        result = TestResult(name="test_instant", passed=True, duration=0.0)
        assert result.duration == 0.0

    def test_empty_name(self) -> None:
        result = TestResult(name="", passed=True)
        assert result.name == ""

    def test_empty_error_message(self) -> None:
        result = TestResult(name="test_e", passed=False, error_message="")
        assert result.error_message == ""


class TestDataclassBehavior:
    def test_equality(self) -> None:
        a = TestResult(name="test_eq", passed=True, duration=1.0)
        b = TestResult(name="test_eq", passed=True, duration=1.0)
        assert a == b

    def test_inequality_name(self) -> None:
        a = TestResult(name="test_a", passed=True)
        b = TestResult(name="test_b", passed=True)
        assert a != b

    def test_inequality_passed(self) -> None:
        a = TestResult(name="test_x", passed=True)
        b = TestResult(name="test_x", passed=False)
        assert a != b

    def test_field_names(self) -> None:
        names = [f.name for f in fields(TestResult)]
        assert names == ["name", "passed", "duration", "error_message", "file_path"]

    def test_repr_contains_name(self) -> None:
        result = TestResult(name="test_repr", passed=True)
        assert "test_repr" in repr(result)
