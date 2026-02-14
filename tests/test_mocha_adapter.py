"""Tests for the MochaAdapter (adapters/unit/mocha_adapter.py).

Covers detection (config files, package.json deps),
test patterns, prompt template, JSON parsing, and validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nit.adapters.base import TestFrameworkAdapter, ValidationResult
from nit.adapters.unit.mocha_adapter import MochaAdapter, _parse_mocha_json
from nit.llm.prompts.mocha_prompt import MochaTemplate

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
def adapter() -> MochaAdapter:
    return MochaAdapter()


@pytest.fixture
def project_with_mocharc_yml(tmp_path: Path) -> Path:
    _write_file(tmp_path, ".mocharc.yml", "spec: test/**/*.spec.js\n")
    return tmp_path


@pytest.fixture
def project_with_mocharc_json(tmp_path: Path) -> Path:
    _write_file(tmp_path, ".mocharc.json", '{"spec": "test/**/*.spec.js"}')
    return tmp_path


@pytest.fixture
def project_with_dep(tmp_path: Path) -> Path:
    _write_package_json(tmp_path, {"devDependencies": {"mocha": "^10.0.0"}})
    return tmp_path


@pytest.fixture
def project_no_mocha(tmp_path: Path) -> Path:
    _write_file(tmp_path, "README.md", "No Mocha here.")
    return tmp_path


# ── Identity ─────────────────────────────────────────────────────


def test_adapter_is_test_framework_adapter(adapter: MochaAdapter) -> None:
    assert isinstance(adapter, TestFrameworkAdapter)


def test_adapter_name(adapter: MochaAdapter) -> None:
    assert adapter.name == "mocha"


def test_adapter_language(adapter: MochaAdapter) -> None:
    assert adapter.language == "javascript"


# ── Detection ────────────────────────────────────────────────────


def test_detect_via_mocharc_yml(adapter: MochaAdapter, project_with_mocharc_yml: Path) -> None:
    assert adapter.detect(project_with_mocharc_yml) is True


def test_detect_via_mocharc_json(adapter: MochaAdapter, project_with_mocharc_json: Path) -> None:
    assert adapter.detect(project_with_mocharc_json) is True


def test_detect_via_dep(adapter: MochaAdapter, project_with_dep: Path) -> None:
    assert adapter.detect(project_with_dep) is True


def test_detect_fails_no_mocha(adapter: MochaAdapter, project_no_mocha: Path) -> None:
    assert adapter.detect(project_no_mocha) is False


def test_detect_empty_project(adapter: MochaAdapter, tmp_path: Path) -> None:
    assert adapter.detect(tmp_path) is False


# ── Test patterns ────────────────────────────────────────────────


def test_get_test_pattern(adapter: MochaAdapter) -> None:
    patterns = adapter.get_test_pattern()
    assert "**/*.test.js" in patterns
    assert "**/*.spec.js" in patterns
    assert "test/**/*.js" in patterns


# ── Prompt template ──────────────────────────────────────────────


def test_get_prompt_template(adapter: MochaAdapter) -> None:
    template = adapter.get_prompt_template()
    assert isinstance(template, MochaTemplate)
    assert template.name == "mocha"


# ── JSON parsing ─────────────────────────────────────────────────


def test_parse_mocha_json_success() -> None:

    mocha_output = json.dumps(
        {
            "stats": {
                "suites": 1,
                "tests": 3,
                "passes": 2,
                "pending": 0,
                "failures": 1,
                "duration": 150,
            },
            "tests": [
                {
                    "title": "should add two numbers",
                    "fullTitle": "add should add two numbers",
                    "duration": 5,
                    "err": {},
                },
                {
                    "title": "should handle zero",
                    "fullTitle": "add should handle zero",
                    "duration": 3,
                    "err": {},
                },
                {
                    "title": "should throw on invalid input",
                    "fullTitle": "add should throw on invalid input",
                    "duration": 10,
                    "err": {"message": "Expected error was not thrown"},
                },
            ],
            "passes": [],
            "failures": [],
        }
    )

    result = _parse_mocha_json(mocha_output, mocha_output)
    assert result.passed == 2
    assert result.failed == 1
    assert result.skipped == 0
    assert result.success is False
    assert len(result.test_cases) == 3


def test_parse_mocha_json_all_pass() -> None:

    mocha_output = json.dumps(
        {
            "stats": {"passes": 2, "failures": 0, "pending": 0, "duration": 50},
            "tests": [
                {"title": "t1", "fullTitle": "t1", "duration": 20, "err": {}},
                {"title": "t2", "fullTitle": "t2", "duration": 30, "err": {}},
            ],
        }
    )

    result = _parse_mocha_json(mocha_output, mocha_output)
    assert result.passed == 2
    assert result.failed == 0
    assert result.success is True


def test_parse_mocha_json_with_pending() -> None:

    mocha_output = json.dumps(
        {
            "stats": {"passes": 1, "failures": 0, "pending": 1, "duration": 50},
            "tests": [
                {"title": "t1", "fullTitle": "t1", "duration": 20, "err": {}},
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

    result = _parse_mocha_json(mocha_output, mocha_output)
    assert result.passed == 1
    assert result.skipped == 1
    assert result.success is True


def test_parse_mocha_json_invalid_output() -> None:

    result = _parse_mocha_json("not json", "not json")
    assert result.success is False


# ── Validation ───────────────────────────────────────────────────


def test_validate_valid_js(adapter: MochaAdapter) -> None:
    code = """
const { expect } = require('chai');
const { add } = require('../math');

describe('add', () => {
  it('should add', () => {
    expect(add(1, 2)).to.equal(3);
  });
});
"""
    result = adapter.validate_test(code)
    assert isinstance(result, ValidationResult)
    assert result.valid is True


def test_validate_invalid_syntax(adapter: MochaAdapter) -> None:
    code = "describe('broken', () => { it('missing close' };"
    result = adapter.validate_test(code)
    assert result.valid is False
    assert len(result.errors) > 0


# ── Required packages/commands ───────────────────────────────────


def test_required_packages(adapter: MochaAdapter) -> None:
    assert "mocha" in adapter.get_required_packages()


def test_required_commands(adapter: MochaAdapter) -> None:
    cmds = adapter.get_required_commands()
    assert "node" in cmds
    assert "npx" in cmds
