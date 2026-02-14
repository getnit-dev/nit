"""Tests for the JestAdapter (adapters/unit/jest_adapter.py).

Covers detection (config files, package.json deps, inline config),
test patterns, prompt template, JSON parsing, and validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nit.adapters.base import TestFrameworkAdapter, ValidationResult
from nit.adapters.unit.jest_adapter import JestAdapter, _parse_jest_json
from nit.llm.prompts.jest_prompt import JestTemplate

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
def adapter() -> JestAdapter:
    return JestAdapter()


@pytest.fixture
def project_with_config(tmp_path: Path) -> Path:
    _write_file(tmp_path, "jest.config.js", "module.exports = {};")
    return tmp_path


@pytest.fixture
def project_with_ts_config(tmp_path: Path) -> Path:
    _write_file(tmp_path, "jest.config.ts", "export default {};")
    return tmp_path


@pytest.fixture
def project_with_dep(tmp_path: Path) -> Path:
    _write_package_json(tmp_path, {"devDependencies": {"jest": "^29.0.0"}})
    return tmp_path


@pytest.fixture
def project_with_ts_jest(tmp_path: Path) -> Path:
    _write_package_json(tmp_path, {"devDependencies": {"jest": "^29.0.0", "ts-jest": "^29.0.0"}})
    return tmp_path


@pytest.fixture
def project_with_inline_config(tmp_path: Path) -> Path:
    _write_package_json(
        tmp_path,
        {"jest": {"testEnvironment": "node"}, "devDependencies": {}},
    )
    return tmp_path


@pytest.fixture
def project_no_jest(tmp_path: Path) -> Path:
    _write_file(tmp_path, "README.md", "No Jest here.")
    return tmp_path


# ── Identity ─────────────────────────────────────────────────────


def test_adapter_is_test_framework_adapter(adapter: JestAdapter) -> None:
    assert isinstance(adapter, TestFrameworkAdapter)


def test_adapter_name(adapter: JestAdapter) -> None:
    assert adapter.name == "jest"


def test_adapter_language(adapter: JestAdapter) -> None:
    assert adapter.language == "javascript"


# ── Detection ────────────────────────────────────────────────────


def test_detect_via_config_js(adapter: JestAdapter, project_with_config: Path) -> None:
    assert adapter.detect(project_with_config) is True


def test_detect_via_config_ts(adapter: JestAdapter, project_with_ts_config: Path) -> None:
    assert adapter.detect(project_with_ts_config) is True


def test_detect_via_dep(adapter: JestAdapter, project_with_dep: Path) -> None:
    assert adapter.detect(project_with_dep) is True


def test_detect_via_ts_jest(adapter: JestAdapter, project_with_ts_jest: Path) -> None:
    assert adapter.detect(project_with_ts_jest) is True


def test_detect_via_inline_config(adapter: JestAdapter, project_with_inline_config: Path) -> None:
    assert adapter.detect(project_with_inline_config) is True


def test_detect_fails_no_jest(adapter: JestAdapter, project_no_jest: Path) -> None:
    assert adapter.detect(project_no_jest) is False


def test_detect_empty_project(adapter: JestAdapter, tmp_path: Path) -> None:
    assert adapter.detect(tmp_path) is False


# ── Test patterns ────────────────────────────────────────────────


def test_get_test_pattern(adapter: JestAdapter) -> None:
    patterns = adapter.get_test_pattern()
    assert "**/*.test.js" in patterns
    assert "**/*.test.ts" in patterns
    assert "**/*.spec.js" in patterns
    assert len(patterns) >= 4


# ── Prompt template ──────────────────────────────────────────────


def test_get_prompt_template(adapter: JestAdapter) -> None:
    template = adapter.get_prompt_template()
    assert isinstance(template, JestTemplate)
    assert template.name == "jest"


# ── JSON parsing ─────────────────────────────────────────────────


def test_parse_jest_json_success() -> None:

    jest_output = json.dumps(
        {
            "numTotalTests": 3,
            "numPassedTests": 2,
            "numFailedTests": 1,
            "testResults": [
                {
                    "name": "/path/to/test.js",
                    "startTime": 1000,
                    "endTime": 1500,
                    "assertionResults": [
                        {
                            "fullName": "add should add two numbers",
                            "status": "passed",
                            "duration": 5,
                            "failureMessages": [],
                        },
                        {
                            "fullName": "add should handle zero",
                            "status": "passed",
                            "duration": 3,
                            "failureMessages": [],
                        },
                        {
                            "fullName": "add should throw on invalid input",
                            "status": "failed",
                            "duration": 10,
                            "failureMessages": ["Expected error was not thrown"],
                        },
                    ],
                }
            ],
        }
    )

    result = _parse_jest_json(jest_output, jest_output)
    assert result.passed == 2
    assert result.failed == 1
    assert result.skipped == 0
    assert result.success is False
    assert len(result.test_cases) == 3
    assert result.test_cases[2].failure_message == "Expected error was not thrown"


def test_parse_jest_json_all_pass() -> None:

    jest_output = json.dumps(
        {
            "testResults": [
                {
                    "name": "/path/to/test.js",
                    "startTime": 0,
                    "endTime": 100,
                    "assertionResults": [
                        {"fullName": "test 1", "status": "passed", "failureMessages": []},
                    ],
                }
            ],
        }
    )

    result = _parse_jest_json(jest_output, jest_output)
    assert result.passed == 1
    assert result.failed == 0
    assert result.success is True


def test_parse_jest_json_with_pending() -> None:

    jest_output = json.dumps(
        {
            "testResults": [
                {
                    "name": "/path/to/test.js",
                    "startTime": 0,
                    "endTime": 100,
                    "assertionResults": [
                        {"fullName": "test 1", "status": "pending", "failureMessages": []},
                    ],
                }
            ],
        }
    )

    result = _parse_jest_json(jest_output, jest_output)
    assert result.skipped == 1
    assert result.success is True


def test_parse_jest_json_invalid_output() -> None:

    result = _parse_jest_json("not json", "not json")
    assert result.success is False


# ── Validation ───────────────────────────────────────────────────


def test_validate_valid_js(adapter: JestAdapter) -> None:
    code = """
const { add } = require('../math');

describe('add', () => {
  it('should add', () => {
    expect(add(1, 2)).toBe(3);
  });
});
"""
    result = adapter.validate_test(code)
    assert isinstance(result, ValidationResult)
    assert result.valid is True


def test_validate_valid_ts(adapter: JestAdapter) -> None:
    code = """
import { add } from '../math';

describe('add', () => {
  it('should add two numbers', () => {
    const result: number = add(1, 2);
    expect(result).toBe(3);
  });
});
"""
    result = adapter.validate_test(code)
    assert result.valid is True


def test_validate_invalid_syntax(adapter: JestAdapter) -> None:
    code = "describe('broken', () => { it('missing close' };"
    result = adapter.validate_test(code)
    assert result.valid is False
    assert len(result.errors) > 0


# ── Required packages/commands ───────────────────────────────────


def test_required_packages(adapter: JestAdapter) -> None:
    assert "jest" in adapter.get_required_packages()


def test_required_commands(adapter: JestAdapter) -> None:
    cmds = adapter.get_required_commands()
    assert "node" in cmds
    assert "npx" in cmds


# ── Run tests (mocked) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_tests_timeout(adapter: JestAdapter, tmp_path: Path) -> None:
    result = await adapter.run_tests(tmp_path, timeout=0.001)
    assert result.success is False
