"""Integration tests for adapter detect -> validate lifecycle.

Tests each adapter's detect() and validate_test() methods with realistic
project fixtures and code samples.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from nit.adapters.base import TestFrameworkAdapter

from nit.adapters.unit.cargo_test_adapter import CargoTestAdapter
from nit.adapters.unit.catch2_adapter import Catch2Adapter
from nit.adapters.unit.go_test_adapter import GoTestAdapter
from nit.adapters.unit.gtest_adapter import GTestAdapter
from nit.adapters.unit.junit5_adapter import JUnit5Adapter
from nit.adapters.unit.pytest_adapter import PytestAdapter
from nit.adapters.unit.vitest_adapter import VitestAdapter
from nit.adapters.unit.xunit_adapter import XUnitAdapter

# ── Valid code samples per adapter ───────────────────────────────

_VALID_CODE: dict[str, str] = {
    "pytest": (
        "import pytest\n\n"
        "def test_addition():\n"
        "    assert 1 + 1 == 2\n\n"
        "def test_subtraction():\n"
        "    assert 3 - 1 == 2\n\n"
        '@pytest.mark.parametrize("x,y,expected", [(1, 2, 3), (2, 3, 5)])\n'
        "def test_add_parametrize(x, y, expected):\n"
        "    assert x + y == expected\n"
    ),
    "vitest": (
        'import { describe, it, expect } from "vitest";\n\n'
        'describe("Calculator", () => {\n'
        '  it("adds numbers", () => {\n'
        "    expect(1 + 1).toBe(2);\n"
        "  });\n\n"
        '  it("subtracts numbers", () => {\n'
        "    expect(3 - 1).toBe(2);\n"
        "  });\n"
        "});\n"
    ),
    "gtest": (
        "#include <gtest/gtest.h>\n\n"
        "TEST(CalculatorTest, Add) {\n"
        "  EXPECT_EQ(1 + 1, 2);\n"
        "}\n\n"
        "TEST(CalculatorTest, Subtract) {\n"
        "  EXPECT_EQ(3 - 1, 2);\n"
        "}\n"
    ),
    "catch2": (
        "#include <catch2/catch_test_macros.hpp>\n\n"
        'TEST_CASE("Addition works", "[math]") {\n'
        "  REQUIRE(1 + 1 == 2);\n"
        "}\n\n"
        'TEST_CASE("Subtraction works", "[math]") {\n'
        "  REQUIRE(3 - 1 == 2);\n"
        "}\n"
    ),
    "cargo_test": (
        "#[cfg(test)]\n"
        "mod tests {\n"
        "    #[test]\n"
        "    fn test_addition() {\n"
        "        assert_eq!(1 + 1, 2);\n"
        "    }\n\n"
        "    #[test]\n"
        "    fn test_subtraction() {\n"
        "        assert_eq!(3 - 1, 2);\n"
        "    }\n"
        "}\n"
    ),
    "gotest": (
        'package calc\n\nimport "testing"\n\n'
        "func TestAdd(t *testing.T) {\n"
        "    if 1+1 != 2 {\n"
        '        t.Error("expected 2")\n'
        "    }\n"
        "}\n\n"
        "func TestSub(t *testing.T) {\n"
        "    if 3-1 != 2 {\n"
        '        t.Error("expected 2")\n'
        "    }\n"
        "}\n"
    ),
    "junit5": (
        "package com.example;\n\n"
        "import org.junit.jupiter.api.Test;\n"
        "import static org.junit.jupiter.api.Assertions.*;\n\n"
        "class CalculatorTest {\n"
        "    @Test\n"
        "    void addsNumbers() {\n"
        "        assertEquals(2, 1 + 1);\n"
        "    }\n\n"
        "    @Test\n"
        "    void subtractsNumbers() {\n"
        "        assertEquals(2, 3 - 1);\n"
        "    }\n"
        "}\n"
    ),
    "xunit": (
        "using Xunit;\n\n"
        "public class CalculatorTests\n"
        "{\n"
        "    [Fact]\n"
        "    public void Add_ReturnsSum()\n"
        "    {\n"
        "        Assert.Equal(2, 1 + 1);\n"
        "    }\n\n"
        "    [Theory]\n"
        "    [InlineData(1, 2, 3)]\n"
        "    [InlineData(2, 3, 5)]\n"
        "    public void Add_Parametrized(int a, int b, int expected)\n"
        "    {\n"
        "        Assert.Equal(expected, a + b);\n"
        "    }\n"
        "}\n"
    ),
}

# Invalid code samples (syntax errors) per adapter language
_INVALID_PYTEST = "def test_broken(:\n    pass\n"

_INVALID_VITEST = "describe('broken', () => {\n  it('x', () => { expect(1.toBe(2) });\n);\n"

_INVALID_GTEST = "#include <gtest/gtest.h>\n\nTEST(Broken, { EXPECT_EQ(1, 2) }\n"

_INVALID_CATCH2 = '#include <catch2/catch.hpp>\n\nTEST_CASE("Broken" {\n  REQUIRE(1 == 2)\n}\n'

_INVALID_CARGO_TEST = (
    "#[cfg(test)]\nmod tests {\n"
    "    #[test]\n    fn broken( {\n"
    "        assert_eq!(1, 2)\n    }\n}\n"
)

_INVALID_GOTEST = 'package calc\n\nimport "testing"\n\nfunc TestBad(t *testing.T {\n}\n'

_INVALID_JUNIT5 = (
    "package com.example;\n\n"
    "import org.junit.jupiter.api.Test;\n\n"
    "class Broken {\n    @Test\n"
    "    void broken( {\n    }\n}\n"
)

_INVALID_XUNIT = (
    "using Xunit;\n\npublic class Broken\n{\n"
    "    [Fact]\n    public void Broken_Test(\n"
    "    {\n    }\n}\n"
)

_INVALID_CODE: dict[str, str] = {
    "pytest": _INVALID_PYTEST,
    "vitest": _INVALID_VITEST,
    "gtest": _INVALID_GTEST,
    "catch2": _INVALID_CATCH2,
    "cargo_test": _INVALID_CARGO_TEST,
    "gotest": _INVALID_GOTEST,
    "junit5": _INVALID_JUNIT5,
    "xunit": _INVALID_XUNIT,
}


# ── Adapter + fixture pairs ──────────────────────────────────────

_ADAPTER_FIXTURE_MAP: dict[str, type[TestFrameworkAdapter]] = {
    "py_test_project": PytestAdapter,
    "vitest_project": VitestAdapter,
    "gtest_project": GTestAdapter,
    "catch2_project": Catch2Adapter,
    "cargo_project": CargoTestAdapter,
    "go_project": GoTestAdapter,
    "junit5_project": JUnit5Adapter,
    "xunit_project": XUnitAdapter,
}


# ── Parametrized detection tests ─────────────────────────────────


@pytest.mark.integration
class TestAdapterDetection:
    """Test that each adapter correctly detects its matching project."""

    @pytest.mark.parametrize(
        ("fixture_name", "adapter_cls"),
        [
            ("py_test_project", PytestAdapter),
            ("vitest_project", VitestAdapter),
            ("gtest_project", GTestAdapter),
            ("catch2_project", Catch2Adapter),
            ("cargo_project", CargoTestAdapter),
            ("go_project", GoTestAdapter),
            ("junit5_project", JUnit5Adapter),
            ("xunit_project", XUnitAdapter),
        ],
    )
    def test_detect_returns_true(
        self,
        fixture_name: str,
        adapter_cls: type[TestFrameworkAdapter],
        request: pytest.FixtureRequest,
    ) -> None:
        """adapter.detect() returns True for its matching project."""
        project_path: Path = request.getfixturevalue(fixture_name)
        adapter = adapter_cls()
        assert adapter.detect(
            project_path
        ), f"{adapter_cls.__name__}.detect() returned False for {fixture_name}"

    @pytest.mark.parametrize(
        ("fixture_name", "adapter_cls"),
        [
            ("py_test_project", VitestAdapter),
            ("vitest_project", PytestAdapter),
            ("gtest_project", CargoTestAdapter),
            ("cargo_project", GoTestAdapter),
            ("go_project", JUnit5Adapter),
            ("junit5_project", XUnitAdapter),
        ],
    )
    def test_detect_returns_false_for_wrong_project(
        self,
        fixture_name: str,
        adapter_cls: type[TestFrameworkAdapter],
        request: pytest.FixtureRequest,
    ) -> None:
        """adapter.detect() returns False for a non-matching project."""
        project_path: Path = request.getfixturevalue(fixture_name)
        adapter = adapter_cls()
        assert not adapter.detect(
            project_path
        ), f"{adapter_cls.__name__}.detect() unexpectedly returned True for {fixture_name}"

    def test_detect_empty_directory_returns_false(self, tmp_path: Path) -> None:
        """All adapters return False for an empty directory."""
        for adapter_cls in _ADAPTER_FIXTURE_MAP.values():
            adapter = adapter_cls()
            assert not adapter.detect(
                tmp_path
            ), f"{adapter_cls.__name__}.detect() returned True for empty dir"


# ── Parametrized validation tests ────────────────────────────────


@pytest.mark.integration
class TestAdapterValidation:
    """Test validate_test() with valid and invalid code samples."""

    @pytest.mark.parametrize(
        ("adapter_cls", "adapter_name"),
        [
            (PytestAdapter, "pytest"),
            (VitestAdapter, "vitest"),
            (GTestAdapter, "gtest"),
            (Catch2Adapter, "catch2"),
            (CargoTestAdapter, "cargo_test"),
            (GoTestAdapter, "gotest"),
            (JUnit5Adapter, "junit5"),
            (XUnitAdapter, "xunit"),
        ],
    )
    def test_validate_valid_code(
        self,
        adapter_cls: type[TestFrameworkAdapter],
        adapter_name: str,
    ) -> None:
        """validate_test() returns valid=True for correct test code."""
        adapter = adapter_cls()
        code = _VALID_CODE[adapter_name]
        result = adapter.validate_test(code)
        assert result.valid, f"{adapter_name} validation failed for valid code: {result.errors}"
        assert not result.errors

    @pytest.mark.parametrize(
        ("adapter_cls", "adapter_name"),
        [
            (PytestAdapter, "pytest"),
            (VitestAdapter, "vitest"),
            (GTestAdapter, "gtest"),
            (Catch2Adapter, "catch2"),
            (CargoTestAdapter, "cargo_test"),
            (GoTestAdapter, "gotest"),
            (JUnit5Adapter, "junit5"),
            (XUnitAdapter, "xunit"),
        ],
    )
    def test_validate_invalid_code(
        self,
        adapter_cls: type[TestFrameworkAdapter],
        adapter_name: str,
    ) -> None:
        """validate_test() returns valid=False for code with syntax errors."""
        adapter = adapter_cls()
        code = _INVALID_CODE[adapter_name]
        result = adapter.validate_test(code)
        assert not result.valid, f"{adapter_name} validation incorrectly accepted invalid code"
        assert len(result.errors) > 0


# ── Adapter identity and patterns ────────────────────────────────


@pytest.mark.integration
class TestAdapterIdentity:
    """Test adapter identity properties and test patterns."""

    @pytest.mark.parametrize(
        ("adapter_cls", "expected_name", "expected_lang"),
        [
            (PytestAdapter, "pytest", "python"),
            (VitestAdapter, "vitest", "typescript"),
            (GTestAdapter, "gtest", "cpp"),
            (Catch2Adapter, "catch2", "cpp"),
            (CargoTestAdapter, "cargo_test", "rust"),
            (GoTestAdapter, "gotest", "go"),
            (JUnit5Adapter, "junit5", "java"),
            (XUnitAdapter, "xunit", "csharp"),
        ],
    )
    def test_name_and_language(
        self,
        adapter_cls: type[TestFrameworkAdapter],
        expected_name: str,
        expected_lang: str,
    ) -> None:
        """Each adapter reports correct name and language."""
        adapter = adapter_cls()
        assert adapter.name == expected_name
        assert adapter.language == expected_lang

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            PytestAdapter,
            VitestAdapter,
            GTestAdapter,
            Catch2Adapter,
            CargoTestAdapter,
            GoTestAdapter,
            JUnit5Adapter,
            XUnitAdapter,
        ],
    )
    def test_get_test_pattern_returns_nonempty_list(
        self,
        adapter_cls: type[TestFrameworkAdapter],
    ) -> None:
        """Each adapter returns at least one test file pattern."""
        adapter = adapter_cls()
        patterns = adapter.get_test_pattern()
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        for pat in patterns:
            assert isinstance(pat, str)
            assert len(pat) > 0

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            PytestAdapter,
            VitestAdapter,
            GTestAdapter,
            Catch2Adapter,
            CargoTestAdapter,
            GoTestAdapter,
            JUnit5Adapter,
            XUnitAdapter,
        ],
    )
    def test_get_prompt_template_returns_valid_object(
        self,
        adapter_cls: type[TestFrameworkAdapter],
    ) -> None:
        """Each adapter returns a prompt template with the expected interface."""
        adapter = adapter_cls()
        template = adapter.get_prompt_template()
        assert template is not None
        # All templates should have a render method
        assert hasattr(template, "render")
