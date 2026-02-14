"""Tests for the CypressAdapter (adapters/e2e/cypress_adapter.py).

Covers detection (config files, legacy config, package.json deps),
test patterns, prompt template, JSON parsing, and validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nit.adapters.base import TestFrameworkAdapter, ValidationResult
from nit.adapters.e2e.cypress_adapter import CypressAdapter, _parse_cypress_json
from nit.llm.prompts.cypress_prompt import CypressTemplate

# ── Helpers ──────────────────────────────────────────────────────


def _write_file(root: Path, rel: str, content: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def _write_package_json(root: Path, extra: dict[str, object] | None = None) -> None:
    data: dict[str, object] = {"name": "test-project", "version": "1.0.0"}
    if extra:
        data.update(extra)
    _write_file(root, "package.json", json.dumps(data))


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> CypressAdapter:
    return CypressAdapter()


@pytest.fixture
def project_with_config_js(tmp_path: Path) -> Path:
    _write_file(tmp_path, "cypress.config.js", "module.exports = {};")
    return tmp_path


@pytest.fixture
def project_with_config_ts(tmp_path: Path) -> Path:
    _write_file(tmp_path, "cypress.config.ts", "export default {};")
    return tmp_path


@pytest.fixture
def project_with_legacy_config(tmp_path: Path) -> Path:
    _write_file(tmp_path, "cypress.json", "{}")
    return tmp_path


@pytest.fixture
def project_with_dep(tmp_path: Path) -> Path:
    _write_package_json(tmp_path, {"devDependencies": {"cypress": "^13.0.0"}})
    return tmp_path


@pytest.fixture
def project_no_cypress(tmp_path: Path) -> Path:
    _write_file(tmp_path, "README.md", "No Cypress here.")
    return tmp_path


# ── Identity ─────────────────────────────────────────────────────


def test_adapter_is_test_framework_adapter(adapter: CypressAdapter) -> None:
    assert isinstance(adapter, TestFrameworkAdapter)


def test_adapter_name(adapter: CypressAdapter) -> None:
    assert adapter.name == "cypress"


def test_adapter_language(adapter: CypressAdapter) -> None:
    assert adapter.language == "javascript"


# ── Detection ────────────────────────────────────────────────────


def test_detect_via_config_js(adapter: CypressAdapter, project_with_config_js: Path) -> None:
    assert adapter.detect(project_with_config_js) is True


def test_detect_via_config_ts(adapter: CypressAdapter, project_with_config_ts: Path) -> None:
    assert adapter.detect(project_with_config_ts) is True


def test_detect_via_legacy_config(
    adapter: CypressAdapter, project_with_legacy_config: Path
) -> None:
    assert adapter.detect(project_with_legacy_config) is True


def test_detect_via_dep(adapter: CypressAdapter, project_with_dep: Path) -> None:
    assert adapter.detect(project_with_dep) is True


def test_detect_fails_no_cypress(adapter: CypressAdapter, project_no_cypress: Path) -> None:
    assert adapter.detect(project_no_cypress) is False


def test_detect_empty_project(adapter: CypressAdapter, tmp_path: Path) -> None:
    assert adapter.detect(tmp_path) is False


# ── Test patterns ────────────────────────────────────────────────


def test_get_test_pattern(adapter: CypressAdapter) -> None:
    patterns = adapter.get_test_pattern()
    assert "cypress/e2e/**/*.cy.ts" in patterns
    assert "cypress/e2e/**/*.cy.js" in patterns
    assert len(patterns) >= 4


# ── Prompt template ──────────────────────────────────────────────


def test_get_prompt_template(adapter: CypressAdapter) -> None:
    template = adapter.get_prompt_template()
    assert isinstance(template, CypressTemplate)
    assert template.name == "cypress_e2e"


# ── JSON parsing ─────────────────────────────────────────────────


def test_parse_cypress_json_success() -> None:

    cypress_output = json.dumps(
        {
            "stats": {
                "suites": 1,
                "tests": 3,
                "passes": 2,
                "pending": 0,
                "failures": 1,
                "duration": 5000,
            },
            "tests": [
                {
                    "title": "should login successfully",
                    "fullTitle": "Auth should login successfully",
                    "duration": 1500,
                    "err": {},
                },
                {
                    "title": "should show dashboard",
                    "fullTitle": "Auth should show dashboard",
                    "duration": 1200,
                    "err": {},
                },
                {
                    "title": "should handle errors",
                    "fullTitle": "Auth should handle errors",
                    "duration": 800,
                    "err": {"message": "Element not found"},
                },
            ],
        }
    )

    result = _parse_cypress_json(cypress_output, cypress_output)
    assert result.passed == 2
    assert result.failed == 1
    assert result.skipped == 0
    assert result.success is False
    assert len(result.test_cases) == 3


def test_parse_cypress_json_all_pass() -> None:

    cypress_output = json.dumps(
        {
            "stats": {"passes": 1, "failures": 0, "pending": 0, "duration": 100},
            "tests": [
                {
                    "title": "test 1",
                    "fullTitle": "suite test 1",
                    "duration": 100,
                    "err": {},
                },
            ],
        }
    )

    result = _parse_cypress_json(cypress_output, cypress_output)
    assert result.passed == 1
    assert result.failed == 0
    assert result.success is True


def test_parse_cypress_json_with_pending() -> None:

    cypress_output = json.dumps(
        {
            "stats": {"passes": 1, "failures": 0, "pending": 1, "duration": 100},
            "tests": [
                {"title": "t1", "fullTitle": "t1", "duration": 50, "err": {}},
                {
                    "title": "t2",
                    "fullTitle": "t2",
                    "duration": 0,
                    "err": {},
                    "pending": True,
                },
            ],
        }
    )

    result = _parse_cypress_json(cypress_output, cypress_output)
    assert result.passed == 1
    assert result.skipped == 1
    assert result.success is True


def test_parse_cypress_json_invalid_output() -> None:

    result = _parse_cypress_json("not json", "not json")
    assert result.success is False


# ── Validation ───────────────────────────────────────────────────


def test_validate_valid_js(adapter: CypressAdapter) -> None:
    code = """
describe('Login', () => {
  it('should login', () => {
    cy.visit('/login');
    cy.get('[data-cy="username"]').type('user@test.com');
    cy.get('[data-cy="login-button"]').click();
    cy.url().should('include', '/dashboard');
  });
});
"""
    result = adapter.validate_test(code)
    assert isinstance(result, ValidationResult)
    assert result.valid is True


def test_validate_valid_ts(adapter: CypressAdapter) -> None:
    code = """
describe('Login', () => {
  it('should login with typed var', () => {
    const username: string = 'user@test.com';
    cy.visit('/login');
    cy.get('[data-cy="username"]').type(username);
  });
});
"""
    result = adapter.validate_test(code)
    assert result.valid is True


def test_validate_invalid_syntax(adapter: CypressAdapter) -> None:
    code = "describe('broken', () => { it('missing close' };"
    result = adapter.validate_test(code)
    assert result.valid is False
    assert len(result.errors) > 0


# ── Required packages/commands ───────────────────────────────────


def test_required_packages(adapter: CypressAdapter) -> None:
    assert "cypress" in adapter.get_required_packages()


def test_required_commands(adapter: CypressAdapter) -> None:
    cmds = adapter.get_required_commands()
    assert "node" in cmds
    assert "npx" in cmds
