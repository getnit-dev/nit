"""Tests for the FrameworkDetector agent and detect_frameworks function."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.detectors.framework import (
    FrameworkDetector,
    _resolve_conflicts,
    builtin_rules,
    detect_frameworks,
    needs_llm_fallback,
)
from nit.agents.detectors.signals import (
    ConfigFile,
    Dependency,
    DetectedFramework,
    FilePattern,
    FrameworkCategory,
    FrameworkProfile,
    FrameworkRule,
    ImportPattern,
    PackageJsonField,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_files(root: Path, rel_paths: list[str]) -> None:
    """Create empty files at the given relative paths under *root*."""
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


def _write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file at *root/rel*."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _write_package_json(root: Path, data: dict[str, object]) -> None:
    """Write a ``package.json`` to *root*."""
    _write_file(root, "package.json", json.dumps(data))


# ---------------------------------------------------------------------------
# detect_frameworks — JS/TS frameworks
# ---------------------------------------------------------------------------


class TestVitestDetection:
    def test_vitest_config_file(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["vitest.config.ts", "src/index.ts"])
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "vitest" in names

    def test_vitest_dependency(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {"vitest": "^1.0.0"},
            },
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "vitest" in names

    def test_vitest_import_pattern(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "src/math.test.ts",
            """\
import { describe, it, expect } from 'vitest'

describe('add', () => {
  it('adds numbers', () => {
    expect(1 + 1).toBe(2)
  })
})
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "vitest" in names

    def test_vitest_package_json_script(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {
                "scripts": {"test": "vitest run"},
            },
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "vitest" in names

    def test_vitest_full_project(self, tmp_path: Path) -> None:
        """A realistic Vitest project hits multiple signals → high confidence."""
        _make_files(tmp_path, ["vitest.config.ts"])
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {"vitest": "^1.0.0"},
                "scripts": {"test": "vitest run"},
            },
        )
        _write_file(
            tmp_path,
            "src/utils.test.ts",
            """\
import { expect, test } from 'vitest'
test('works', () => { expect(true).toBe(true) })
""",
        )
        profile = detect_frameworks(tmp_path)
        vitest = next(fw for fw in profile.frameworks if fw.name == "vitest")
        assert vitest.confidence >= 0.5
        assert vitest.category == FrameworkCategory.UNIT_TEST


class TestJestDetection:
    def test_jest_config_file(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["jest.config.js", "src/index.js"])
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "jest" in names

    def test_jest_dependency(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {"jest": "^29.0.0"},
            },
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "jest" in names

    def test_jest_top_level_config_in_package_json(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {
                "jest": {"testEnvironment": "node"},
                "devDependencies": {"jest": "^29.0.0"},
            },
        )
        profile = detect_frameworks(tmp_path)
        jest = next(fw for fw in profile.frameworks if fw.name == "jest")
        assert jest.confidence > 0.3

    def test_jest_script(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {
                "scripts": {"test": "jest --coverage"},
            },
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "jest" in names


class TestMochaDetection:
    def test_mocha_config(self, tmp_path: Path) -> None:
        _make_files(tmp_path, [".mocharc.yml"])
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "mocha" in names

    def test_mocha_dependency(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {"mocha": "^10.0.0"},
            },
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "mocha" in names


class TestPlaywrightDetection:
    def test_playwright_config(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["playwright.config.ts"])
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "playwright" in names

    def test_playwright_dependency(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {"@playwright/test": "^1.40.0"},
            },
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "playwright" in names

    def test_playwright_import(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "e2e/login.spec.ts",
            """\
import { test, expect } from '@playwright/test'

test('login page', async ({ page }) => {
  await page.goto('/login')
  await expect(page).toHaveTitle('Login')
})
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "playwright" in names

    def test_playwright_is_e2e_category(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["playwright.config.ts"])
        profile = detect_frameworks(tmp_path)
        pw = next(fw for fw in profile.frameworks if fw.name == "playwright")
        assert pw.category == FrameworkCategory.E2E_TEST


class TestCypressDetection:
    def test_cypress_config(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["cypress.config.ts"])
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "cypress" in names

    def test_cypress_legacy_config(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["cypress.json"])
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "cypress" in names

    def test_cypress_dependency(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {"cypress": "^13.0.0"},
            },
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "cypress" in names

    def test_cypress_is_e2e_category(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["cypress.config.ts"])
        profile = detect_frameworks(tmp_path)
        cy = next(fw for fw in profile.frameworks if fw.name == "cypress")
        assert cy.category == FrameworkCategory.E2E_TEST


# ---------------------------------------------------------------------------
# detect_frameworks — Python frameworks
# ---------------------------------------------------------------------------


class TestPytestDetection:
    def test_conftest_py(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["conftest.py", "tests/test_app.py"])
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "pytest" in names

    def test_pytest_ini(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["pytest.ini"])
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "pytest" in names

    def test_pytest_import(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "tests/test_example.py",
            """\
import pytest

@pytest.fixture
def client():
    return 'test-client'

def test_hello(client):
    assert client == 'test-client'
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "pytest" in names

    def test_pytest_dependency_in_pyproject(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            """\
[project.optional-dependencies]
dev = ["pytest>=7.0", "ruff"]
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "pytest" in names

    def test_pytest_dependency_in_requirements(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "requirements-dev.txt",
            """\
pytest>=7.0.0
pytest-asyncio
ruff
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "pytest" in names

    def test_pytest_test_files(self, tmp_path: Path) -> None:
        _make_files(
            tmp_path,
            [
                "tests/test_core.py",
                "tests/test_utils.py",
            ],
        )
        profile = detect_frameworks(tmp_path)
        # test_*.py file pattern is shared with unittest, but pytest should be present
        names = [fw.name for fw in profile.frameworks]
        assert any(n in ("pytest", "unittest") for n in names)

    def test_pytest_full_project(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["conftest.py"])
        _write_file(
            tmp_path,
            "pyproject.toml",
            """\
[project.optional-dependencies]
dev = ["pytest>=7.0"]
""",
        )
        _write_file(
            tmp_path,
            "tests/test_app.py",
            """\
import pytest

def test_example():
    assert True
""",
        )
        profile = detect_frameworks(tmp_path)
        pytest_fw = next(fw for fw in profile.frameworks if fw.name == "pytest")
        assert pytest_fw.confidence >= 0.5
        assert pytest_fw.category == FrameworkCategory.UNIT_TEST


class TestUnittestDetection:
    def test_unittest_import(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "tests/test_app.py",
            """\
import unittest

class TestApp(unittest.TestCase):
    def test_hello(self):
        self.assertEqual(1, 1)
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "unittest" in names

    def test_unittest_mock_import(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "tests/test_service.py",
            """\
from unittest.mock import MagicMock, patch

def test_service():
    mock = MagicMock()
    assert mock is not None
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "unittest" in names


# ---------------------------------------------------------------------------
# detect_frameworks — C/C++ frameworks
# ---------------------------------------------------------------------------


class TestGTestDetection:
    def test_gtest_cmake_find_package(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            """\
cmake_minimum_required(VERSION 3.20)
project(cpp_project)
enable_testing()
find_package(GTest REQUIRED)
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "gtest" in names

    def test_gtest_cmake_discover_tests(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            """\
add_executable(math_test tests/math_test.cpp)
target_link_libraries(math_test PRIVATE GTest::gtest_main)
gtest_discover_tests(math_test)
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "gtest" in names

    def test_gtest_import_pattern(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "tests/math_test.cpp",
            """\
#include <gtest/gtest.h>

TEST(MathTest, AddsNumbers) {
  EXPECT_EQ(1 + 1, 2);
}
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "gtest" in names

    def test_gtest_is_unit_test_category(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "find_package(GTest REQUIRED)\n",
        )
        profile = detect_frameworks(tmp_path)
        gtest = next(fw for fw in profile.frameworks if fw.name == "gtest")
        assert gtest.category == FrameworkCategory.UNIT_TEST


class TestCatch2Detection:
    def test_catch2_cmake_find_package(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            """\
cmake_minimum_required(VERSION 3.20)
project(cpp_project)
enable_testing()
find_package(Catch2 REQUIRED)
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "catch2" in names

    def test_catch2_cmake_discover_tests(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            """\
add_executable(math_catch2 tests/math.catch2.cpp)
target_link_libraries(math_catch2 PRIVATE Catch2::Catch2WithMain)
catch_discover_tests(math_catch2)
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "catch2" in names

    def test_catch2_import_pattern(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "tests/math.catch2.cpp",
            """\
#include <catch2/catch_test_macros.hpp>

TEST_CASE("Math adds numbers", "[math]") {
  CHECK(1 + 1 == 2);
}
""",
        )
        profile = detect_frameworks(tmp_path, resolve_conflicts=False)
        names = [fw.name for fw in profile.frameworks]
        assert "catch2" in names

    def test_catch2_is_unit_test_category(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "find_package(Catch2 REQUIRED)\n",
        )
        profile = detect_frameworks(tmp_path)
        catch2 = next(fw for fw in profile.frameworks if fw.name == "catch2")
        assert catch2.category == FrameworkCategory.UNIT_TEST


# ---------------------------------------------------------------------------
# Conflict resolution
# ---------------------------------------------------------------------------


class TestConflictResolution:
    def test_same_category_keeps_highest_confidence(self, tmp_path: Path) -> None:
        """When both Vitest and Jest are detected, only the higher one survives."""
        _make_files(tmp_path, ["vitest.config.ts", "jest.config.js"])
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {"vitest": "^1.0.0"},
            },
        )
        profile = detect_frameworks(tmp_path, resolve_conflicts=True)
        unit_test_fws = profile.by_category(FrameworkCategory.UNIT_TEST)
        # After conflict resolution, only one JS unit-test framework
        js_unit = [fw for fw in unit_test_fws if fw.language == "javascript"]
        assert len(js_unit) == 1

    def test_no_conflict_resolution(self, tmp_path: Path) -> None:
        """When resolve_conflicts=False, all detected frameworks are returned."""
        _make_files(tmp_path, ["vitest.config.ts", "jest.config.js"])
        profile = detect_frameworks(tmp_path, resolve_conflicts=False)
        names = [fw.name for fw in profile.frameworks]
        # Both should be present without conflict resolution
        vitest_present = "vitest" in names
        jest_present = "jest" in names
        assert vitest_present or jest_present  # at least one
        # If both config files trigger, both should be kept
        if vitest_present and jest_present:
            assert names.count("vitest") == 1
            assert names.count("jest") == 1

    def test_different_categories_no_conflict(self, tmp_path: Path) -> None:
        """Unit test and E2E frameworks are independent — both survive."""
        _make_files(tmp_path, ["vitest.config.ts", "playwright.config.ts"])
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {
                    "vitest": "^1.0.0",
                    "@playwright/test": "^1.40.0",
                },
            },
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "vitest" in names
        assert "playwright" in names

    def test_resolve_conflicts_function_directly(self) -> None:
        fw_a = DetectedFramework(
            name="a",
            language="js",
            category=FrameworkCategory.UNIT_TEST,
            confidence=0.9,
            matched_signals=[],
        )
        fw_b = DetectedFramework(
            name="b",
            language="js",
            category=FrameworkCategory.UNIT_TEST,
            confidence=0.5,
            matched_signals=[],
        )
        fw_c = DetectedFramework(
            name="c",
            language="js",
            category=FrameworkCategory.E2E_TEST,
            confidence=0.7,
            matched_signals=[],
        )
        result = _resolve_conflicts([fw_a, fw_b, fw_c])
        names = [fw.name for fw in result]
        assert "a" in names  # higher confidence for unit_test
        assert "b" not in names
        assert "c" in names  # different category, survives

    def test_different_languages_no_conflict(self, tmp_path: Path) -> None:
        """pytest (python) and vitest (javascript) don't conflict."""
        _make_files(tmp_path, ["conftest.py", "vitest.config.ts"])
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {"vitest": "^1.0.0"},
            },
        )
        _write_file(
            tmp_path,
            "pyproject.toml",
            """\
[project.optional-dependencies]
dev = ["pytest"]
""",
        )
        profile = detect_frameworks(tmp_path)
        names = [fw.name for fw in profile.frameworks]
        assert "pytest" in names
        assert "vitest" in names


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------


class TestLLMFallback:
    def test_low_confidence_triggers_fallback(self) -> None:
        profile = FrameworkProfile(
            frameworks=[
                DetectedFramework(
                    name="jest",
                    language="javascript",
                    category=FrameworkCategory.UNIT_TEST,
                    confidence=0.5,
                    matched_signals=[],
                ),
            ],
        )
        ambiguous = needs_llm_fallback(profile)
        assert len(ambiguous) == 1
        assert ambiguous[0].name == "jest"

    def test_high_confidence_no_fallback(self) -> None:
        profile = FrameworkProfile(
            frameworks=[
                DetectedFramework(
                    name="vitest",
                    language="javascript",
                    category=FrameworkCategory.UNIT_TEST,
                    confidence=0.9,
                    matched_signals=[],
                ),
            ],
        )
        ambiguous = needs_llm_fallback(profile)
        assert len(ambiguous) == 0

    def test_mixed_confidence(self) -> None:
        profile = FrameworkProfile(
            frameworks=[
                DetectedFramework(
                    name="vitest",
                    language="javascript",
                    category=FrameworkCategory.UNIT_TEST,
                    confidence=0.9,
                    matched_signals=[],
                ),
                DetectedFramework(
                    name="mocha",
                    language="javascript",
                    category=FrameworkCategory.UNIT_TEST,
                    confidence=0.4,
                    matched_signals=[],
                ),
            ],
        )
        ambiguous = needs_llm_fallback(profile)
        assert len(ambiguous) == 1
        assert ambiguous[0].name == "mocha"


# ---------------------------------------------------------------------------
# FrameworkProfile dataclass
# ---------------------------------------------------------------------------


class TestFrameworkProfile:
    def test_by_category(self) -> None:
        fws = [
            DetectedFramework("a", "js", FrameworkCategory.UNIT_TEST, 0.8),
            DetectedFramework("b", "js", FrameworkCategory.E2E_TEST, 0.9),
            DetectedFramework("c", "py", FrameworkCategory.UNIT_TEST, 0.7),
        ]
        profile = FrameworkProfile(frameworks=fws)
        unit = profile.by_category(FrameworkCategory.UNIT_TEST)
        assert len(unit) == 2
        assert unit[0].confidence >= unit[1].confidence

    def test_by_language(self) -> None:
        fws = [
            DetectedFramework("vitest", "javascript", FrameworkCategory.UNIT_TEST, 0.8),
            DetectedFramework("playwright", "javascript", FrameworkCategory.E2E_TEST, 0.9),
            DetectedFramework("pytest", "python", FrameworkCategory.UNIT_TEST, 0.7),
        ]
        profile = FrameworkProfile(frameworks=fws)
        js = profile.by_language("javascript")
        assert len(js) == 2
        assert js[0].name == "playwright"

    def test_by_category_empty(self) -> None:
        profile = FrameworkProfile()
        assert profile.by_category(FrameworkCategory.DOC) == []

    def test_by_language_empty(self) -> None:
        profile = FrameworkProfile()
        assert profile.by_language("rust") == []


# ---------------------------------------------------------------------------
# detect_frameworks — edge cases
# ---------------------------------------------------------------------------


class TestDetectFrameworksEdgeCases:
    def test_empty_directory(self, tmp_path: Path) -> None:
        profile = detect_frameworks(tmp_path)
        assert profile.frameworks == []
        assert profile.root == str(tmp_path)

    def test_non_directory_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.touch()
        with pytest.raises(ValueError, match="Not a directory"):
            detect_frameworks(f)

    def test_no_matching_frameworks(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["main.rs", "lib.rs"])
        profile = detect_frameworks(tmp_path)
        assert profile.frameworks == []

    def test_custom_rules(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["custom.test.config"])
        custom_rule = FrameworkRule(
            name="custom-framework",
            language="python",
            category=FrameworkCategory.UNIT_TEST,
            signals=[ConfigFile("custom.test.config")],
        )
        profile = detect_frameworks(tmp_path, rules=[custom_rule])
        assert len(profile.frameworks) == 1
        assert profile.frameworks[0].name == "custom-framework"

    def test_custom_skip_dirs(self, tmp_path: Path) -> None:
        _make_files(
            tmp_path,
            [
                "conftest.py",
                "hidden/vitest.config.ts",
            ],
        )
        profile = detect_frameworks(tmp_path, skip_dirs=frozenset({"hidden"}))
        names = [fw.name for fw in profile.frameworks]
        assert "pytest" in names
        assert "vitest" not in names

    def test_corrupted_package_json_ignored(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "package.json", "not valid json {{{")
        _make_files(tmp_path, ["vitest.config.ts"])
        profile = detect_frameworks(tmp_path)
        # Should still detect via config file even if package.json is broken
        names = [fw.name for fw in profile.frameworks]
        assert "vitest" in names

    def test_root_recorded(self, tmp_path: Path) -> None:
        profile = detect_frameworks(tmp_path)
        assert profile.root == str(tmp_path)

    def test_builtin_rules_cover_all_frameworks(self) -> None:
        rules = builtin_rules()
        names = {r.name for r in rules}
        assert names == {
            "vitest",
            "jest",
            "mocha",
            "playwright",
            "cypress",
            "pytest",
            "unittest",
            "catch2",
            "gtest",
        }

    def test_minimum_confidence_filter(self, tmp_path: Path) -> None:
        """Frameworks below the minimum confidence threshold are excluded."""
        # A rule with only a weak signal (FilePattern weight=0.5) that matches
        # but total ratio is low should still pass if above _MIN_CONFIDENCE
        _make_files(tmp_path, ["tests/test_app.py"])
        profile = detect_frameworks(tmp_path)
        for fw in profile.frameworks:
            assert fw.confidence >= 0.3


# ---------------------------------------------------------------------------
# Signal dataclasses
# ---------------------------------------------------------------------------


class TestSignalTypes:
    def test_config_file_defaults(self) -> None:
        s = ConfigFile("vitest.config.*")
        assert s.weight == 0.9

    def test_dependency_defaults(self) -> None:
        s = Dependency("vitest")
        assert s.weight == 0.8
        assert s.dev_only is False

    def test_import_pattern_defaults(self) -> None:
        s = ImportPattern(r"import pytest")
        assert s.weight == 0.7

    def test_file_pattern_defaults(self) -> None:
        s = FilePattern("**/*.test.ts")
        assert s.weight == 0.5

    def test_package_json_field_defaults(self) -> None:
        s = PackageJsonField("scripts.test", "vitest")
        assert s.weight == 0.7

    def test_custom_weights(self) -> None:
        s = ConfigFile("custom.config", weight=0.5)
        assert s.weight == 0.5

    def test_frozen_signals(self) -> None:
        s = ConfigFile("vitest.config.*")
        with pytest.raises(AttributeError):
            s.pattern = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FrameworkDetector agent interface
# ---------------------------------------------------------------------------


class TestFrameworkDetectorAgent:
    def test_run_success(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["conftest.py"])
        _write_file(tmp_path, "tests/test_app.py", "import pytest\n")
        agent = FrameworkDetector()
        task = TaskInput(task_type="detect-framework", target=str(tmp_path))
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.COMPLETED
        assert output.result["root"] == str(tmp_path)
        assert len(output.result["frameworks"]) >= 1
        names = [fw["name"] for fw in output.result["frameworks"]]
        assert "pytest" in names

    def test_run_invalid_target(self, tmp_path: Path) -> None:
        agent = FrameworkDetector()
        task = TaskInput(task_type="detect-framework", target=str(tmp_path / "nope"))
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.FAILED
        assert len(output.errors) == 1
        assert "Not a directory" in output.errors[0]

    def test_run_empty_directory(self, tmp_path: Path) -> None:
        agent = FrameworkDetector()
        task = TaskInput(task_type="detect-framework", target=str(tmp_path))
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.COMPLETED
        assert output.result["frameworks"] == []

    def test_agent_properties(self) -> None:
        agent = FrameworkDetector()
        assert agent.name == "framework-detector"
        assert "framework" in agent.description.lower()

    def test_run_with_custom_skip_dirs(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["conftest.py", "hidden/vitest.config.ts"])
        agent = FrameworkDetector()
        task = TaskInput(
            task_type="detect-framework",
            target=str(tmp_path),
            context={"skip_dirs": ["hidden"]},
        )
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.COMPLETED
        names = [fw["name"] for fw in output.result["frameworks"]]
        assert "vitest" not in names

    def test_run_output_framework_fields(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["vitest.config.ts"])
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {"vitest": "^1.0.0"},
            },
        )
        agent = FrameworkDetector()
        task = TaskInput(task_type="detect-framework", target=str(tmp_path))
        output = asyncio.run(agent.run(task))

        fw = output.result["frameworks"][0]
        assert "name" in fw
        assert "language" in fw
        assert "category" in fw
        assert "confidence" in fw
        assert "matched_signals" in fw
        assert isinstance(fw["matched_signals"], list)

    def test_run_reports_llm_fallback(self, tmp_path: Path) -> None:
        agent = FrameworkDetector()
        task = TaskInput(task_type="detect-framework", target=str(tmp_path))
        output = asyncio.run(agent.run(task))
        assert "needs_llm_fallback" in output.result

    def test_run_resolve_conflicts_context(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["vitest.config.ts", "jest.config.js"])
        agent = FrameworkDetector()
        task = TaskInput(
            task_type="detect-framework",
            target=str(tmp_path),
            context={"resolve_conflicts": False},
        )
        output = asyncio.run(agent.run(task))
        assert output.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Realistic multi-framework projects
# ---------------------------------------------------------------------------


class TestRealisticProjects:
    def test_nextjs_project(self, tmp_path: Path) -> None:
        """A Next.js project with Vitest + Playwright."""
        _make_files(
            tmp_path,
            [
                "vitest.config.ts",
                "playwright.config.ts",
                "src/app/page.tsx",
                "src/app/layout.tsx",
            ],
        )
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {
                    "vitest": "^1.0.0",
                    "@playwright/test": "^1.40.0",
                },
                "scripts": {"test": "vitest run", "test:e2e": "playwright test"},
            },
        )
        _write_file(
            tmp_path,
            "src/__tests__/page.test.tsx",
            """\
import { describe, it, expect } from 'vitest'
""",
        )
        profile = detect_frameworks(tmp_path)
        names = {fw.name for fw in profile.frameworks}
        assert "vitest" in names
        assert "playwright" in names

    def test_python_fastapi_project(self, tmp_path: Path) -> None:
        """A FastAPI project using pytest."""
        _make_files(tmp_path, ["conftest.py"])
        _write_file(
            tmp_path,
            "pyproject.toml",
            """\
[project]
name = "my-api"
[project.optional-dependencies]
dev = ["pytest>=7.0", "httpx"]
""",
        )
        _write_file(
            tmp_path,
            "tests/test_api.py",
            """\
import pytest
from unittest.mock import MagicMock

def test_root():
    assert True
""",
        )
        profile = detect_frameworks(tmp_path)
        names = {fw.name for fw in profile.frameworks}
        assert "pytest" in names

    def test_mixed_python_and_js(self, tmp_path: Path) -> None:
        """Monorepo with Python (pytest) and JS (Jest)."""
        _make_files(tmp_path, ["conftest.py", "jest.config.js"])
        _write_package_json(
            tmp_path,
            {
                "devDependencies": {"jest": "^29.0.0"},
            },
        )
        _write_file(
            tmp_path,
            "pyproject.toml",
            """\
[project.optional-dependencies]
dev = ["pytest"]
""",
        )
        profile = detect_frameworks(tmp_path)
        names = {fw.name for fw in profile.frameworks}
        assert "pytest" in names
        assert "jest" in names
