"""Tests for the PlaywrightAdapter (adapters/e2e/playwright_adapter.py).

Covers detection, prompt template, JSON reporter parsing, and
tree-sitter validation with sample TypeScript fixtures.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.base import CaseStatus
from nit.adapters.e2e.playwright_adapter import (
    PlaywrightAdapter,
    _has_config_file,
    _has_playwright_dependency,
    _map_playwright_status,
    _parse_playwright_json,
    _validate_typescript,
)
from nit.llm.prompts.e2e_test import E2ETestTemplate

# ── Helpers ──────────────────────────────────────────────────────


def _make_files(root: Path, rel_paths: list[str]) -> None:
    """Create empty files (with parent directories) under *root*."""
    for rel in rel_paths:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()


def _write_package_json(root: Path, data: dict[str, object]) -> None:
    """Write a ``package.json`` at *root*."""
    (root / "package.json").write_text(json.dumps(data), encoding="utf-8")


# ── Sample Playwright JSON reporter output ──────────────────────

_PLAYWRIGHT_JSON_ALL_PASS = json.dumps(
    {
        "suites": [
            {
                "title": "Authentication Flow",
                "tests": [
                    {
                        "title": "should login successfully",
                        "status": "passed",
                        "duration": 1250,
                        "location": {"file": "tests/auth.spec.ts", "line": 10},
                    },
                    {
                        "title": "should show error for invalid credentials",
                        "status": "passed",
                        "duration": 850,
                        "location": {"file": "tests/auth.spec.ts", "line": 20},
                    },
                ],
            },
        ],
    }
)

_PLAYWRIGHT_JSON_WITH_FAILURES = json.dumps(
    {
        "suites": [
            {
                "title": "Dashboard",
                "tests": [
                    {
                        "title": "should display user info",
                        "status": "passed",
                        "duration": 500,
                    },
                    {
                        "title": "should load data",
                        "status": "failed",
                        "duration": 2000,
                        "error": {
                            "message": "expect(received).toBeVisible()\n\nReceived: <hidden>"
                        },
                    },
                ],
                "suites": [
                    {
                        "title": "nested suite",
                        "tests": [
                            {
                                "title": "nested test",
                                "status": "skipped",
                                "duration": 0,
                            },
                        ],
                    },
                ],
            },
        ],
    }
)

# ── Sample valid/invalid TypeScript test code ───────────────────

_VALID_TS_TEST = """
import { test, expect } from '@playwright/test';

test('homepage', async ({ page }) => {
  await page.goto('https://example.com');
  await expect(page).toHaveTitle(/Example/);
});
"""

_INVALID_TS_TEST = """
import { test, expect } from '@playwright/test';

test('broken test', async ({ page }) => {
  await page.goto('https://example.com';
  // Missing closing paren above ^
});
"""

# ── Detection tests ──────────────────────────────────────────────


def test_has_config_file_true(tmp_path: Path) -> None:
    """Detect Playwright when playwright.config.ts exists."""
    _make_files(tmp_path, ["playwright.config.ts"])
    assert _has_config_file(tmp_path) is True


def test_has_config_file_false_no_config(tmp_path: Path) -> None:
    """Return False when no config file exists."""
    assert _has_config_file(tmp_path) is False


def test_has_playwright_dependency_true_devdeps(tmp_path: Path) -> None:
    """Detect Playwright in package.json devDependencies."""
    _write_package_json(
        tmp_path,
        {"devDependencies": {"@playwright/test": "^1.40.0"}},
    )
    assert _has_playwright_dependency(tmp_path) is True


def test_has_playwright_dependency_true_deps(tmp_path: Path) -> None:
    """Detect Playwright in package.json dependencies."""
    _write_package_json(
        tmp_path,
        {"dependencies": {"@playwright/test": "^1.40.0"}},
    )
    assert _has_playwright_dependency(tmp_path) is True


def test_has_playwright_dependency_false_no_package_json(tmp_path: Path) -> None:
    """Return False when package.json is missing."""
    assert _has_playwright_dependency(tmp_path) is False


def test_has_playwright_dependency_false_no_playwright(tmp_path: Path) -> None:
    """Return False when Playwright is not in package.json."""
    _write_package_json(
        tmp_path,
        {"devDependencies": {"vitest": "^1.0.0"}},
    )
    assert _has_playwright_dependency(tmp_path) is False


# ── Adapter identity tests ───────────────────────────────────────


def test_adapter_name() -> None:
    """Verify adapter name is 'playwright'."""
    adapter = PlaywrightAdapter()
    assert adapter.name == "playwright"


def test_adapter_language() -> None:
    """Verify adapter language is 'typescript'."""
    adapter = PlaywrightAdapter()
    assert adapter.language == "typescript"


# ── Detection method tests ───────────────────────────────────────


def test_detect_true_with_config(tmp_path: Path) -> None:
    """Adapter.detect() returns True when config file exists."""
    _make_files(tmp_path, ["playwright.config.ts"])
    adapter = PlaywrightAdapter()
    assert adapter.detect(tmp_path) is True


def test_detect_true_with_dependency(tmp_path: Path) -> None:
    """Adapter.detect() returns True when @playwright/test is in package.json."""
    _write_package_json(
        tmp_path,
        {"devDependencies": {"@playwright/test": "^1.40.0"}},
    )
    adapter = PlaywrightAdapter()
    assert adapter.detect(tmp_path) is True


def test_detect_false_no_indicators(tmp_path: Path) -> None:
    """Adapter.detect() returns False when no Playwright indicators exist."""
    adapter = PlaywrightAdapter()
    assert adapter.detect(tmp_path) is False


# ── Test pattern tests ───────────────────────────────────────────


def test_get_test_pattern() -> None:
    """Verify test file patterns include E2E extensions."""
    adapter = PlaywrightAdapter()
    patterns = adapter.get_test_pattern()

    assert "**/*.spec.ts" in patterns
    assert "**/*.e2e.ts" in patterns
    assert "tests/**/*.ts" in patterns


# ── Prompt template tests ────────────────────────────────────────


def test_get_prompt_template() -> None:
    """Verify adapter returns E2ETestTemplate."""
    adapter = PlaywrightAdapter()
    template = adapter.get_prompt_template()

    assert isinstance(template, E2ETestTemplate)
    assert template.name == "e2e_test"


# ── JSON parsing tests ───────────────────────────────────────────


def test_parse_playwright_json_all_pass() -> None:
    """Parse Playwright JSON with all passing tests."""
    result = _parse_playwright_json(_PLAYWRIGHT_JSON_ALL_PASS, _PLAYWRIGHT_JSON_ALL_PASS)

    assert result.success is True
    assert result.passed == 2
    assert result.failed == 0
    assert result.skipped == 0
    assert result.errors == 0
    assert len(result.test_cases) == 2

    # Check first test case
    case0 = result.test_cases[0]
    assert case0.name == "should login successfully"
    assert case0.status == CaseStatus.PASSED
    assert case0.duration_ms == 1250
    assert case0.file_path == "tests/auth.spec.ts"


def test_parse_playwright_json_with_failures() -> None:
    """Parse Playwright JSON with mixed results including failures and nested suites."""
    result = _parse_playwright_json(_PLAYWRIGHT_JSON_WITH_FAILURES, _PLAYWRIGHT_JSON_WITH_FAILURES)

    assert result.success is False
    assert result.passed == 1
    assert result.failed == 1
    assert result.skipped == 1
    assert result.errors == 0
    assert len(result.test_cases) == 3

    # Check failed test case
    failed_case = result.test_cases[1]
    assert failed_case.name == "should load data"
    assert failed_case.status == CaseStatus.FAILED
    assert "toBeVisible" in failed_case.failure_message

    # Check skipped test case (from nested suite)
    skipped_case = result.test_cases[2]
    assert skipped_case.name == "nested test"
    assert skipped_case.status == CaseStatus.SKIPPED


def test_parse_playwright_json_invalid() -> None:
    """Handle invalid JSON gracefully."""
    result = _parse_playwright_json("not json", "not json")

    assert result.success is False
    assert result.total == 0


# ── Status mapping tests ─────────────────────────────────────────


def test_map_playwright_status_passed() -> None:
    """Map 'passed' to CaseStatus.PASSED."""
    assert _map_playwright_status("passed") == CaseStatus.PASSED


def test_map_playwright_status_failed() -> None:
    """Map 'failed' to CaseStatus.FAILED."""
    assert _map_playwright_status("failed") == CaseStatus.FAILED


def test_map_playwright_status_skipped() -> None:
    """Map 'skipped' to CaseStatus.SKIPPED."""
    assert _map_playwright_status("skipped") == CaseStatus.SKIPPED


def test_map_playwright_status_timedout() -> None:
    """Map 'timedout' to CaseStatus.ERROR."""
    assert _map_playwright_status("timedout") == CaseStatus.ERROR


def test_map_playwright_status_unknown() -> None:
    """Map unknown status to CaseStatus.ERROR."""
    assert _map_playwright_status("unknown") == CaseStatus.ERROR


# ── Validation tests ─────────────────────────────────────────────


def test_validate_typescript_valid() -> None:
    """Validate syntactically correct TypeScript test code."""
    result = _validate_typescript(_VALID_TS_TEST)
    assert result.valid is True
    assert len(result.errors) == 0


def test_validate_typescript_invalid() -> None:
    """Validate syntactically incorrect TypeScript test code."""
    result = _validate_typescript(_INVALID_TS_TEST)
    assert result.valid is False
    assert len(result.errors) > 0


def test_adapter_validate_test_valid() -> None:
    """Adapter.validate_test() with valid TypeScript."""
    adapter = PlaywrightAdapter()
    result = adapter.validate_test(_VALID_TS_TEST)

    assert result.valid is True


def test_adapter_validate_test_invalid() -> None:
    """Adapter.validate_test() with invalid TypeScript."""
    adapter = PlaywrightAdapter()
    result = adapter.validate_test(_INVALID_TS_TEST)

    assert result.valid is False
