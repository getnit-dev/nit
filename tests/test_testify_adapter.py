"""Tests for TestifyAdapter (adapters/unit/testify_adapter.py).

Covers detection (go.mod + testify), prompt template, and that execution
and validation delegate to GoTestAdapter.
"""

from __future__ import annotations

from pathlib import Path

from nit.adapters.base import TestFrameworkAdapter
from nit.adapters.unit.go_test_adapter import GoTestAdapter
from nit.adapters.unit.testify_adapter import TestifyAdapter
from nit.llm.prompts.testify_prompt import TestifyTemplate


def _write_file(root: Path, rel: str, content: str) -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


class TestTestifyAdapterIdentity:
    def test_implements_test_framework_adapter(self) -> None:
        assert isinstance(TestifyAdapter(), TestFrameworkAdapter)

    def test_name(self) -> None:
        assert TestifyAdapter().name == "testify"

    def test_language(self) -> None:
        assert TestifyAdapter().language == "go"


class TestTestifyDetection:
    def test_detect_when_testify_in_go_mod(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "go.mod",
            "module example.com/mypkg\n\nrequire github.com/stretchr/testify v1.8.0\n",
        )
        _write_file(
            tmp_path,
            "pkg_test.go",
            'package mypkg\nimport "testing"\nfunc TestX(t *testing.T) {}\n',
        )
        assert TestifyAdapter().detect(tmp_path) is True

    def test_no_detection_without_testify_in_go_mod(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "go.mod", "module example.com/mypkg\n")
        _write_file(
            tmp_path,
            "pkg_test.go",
            'package mypkg\nimport "testing"\nfunc TestX(t *testing.T) {}\n',
        )
        assert TestifyAdapter().detect(tmp_path) is False

    def test_no_detection_without_go_mod(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "pkg_test.go", "package mypkg\n")
        assert TestifyAdapter().detect(tmp_path) is False


class TestTestifyPromptTemplate:
    def test_returns_testify_template(self) -> None:
        template = TestifyAdapter().get_prompt_template()
        assert isinstance(template, TestifyTemplate)

    def test_template_name(self) -> None:
        template = TestifyAdapter().get_prompt_template()
        assert template.name == "testify"


class TestTestifyInheritsGoTest:
    def test_get_test_pattern_same_as_go(self) -> None:
        assert TestifyAdapter().get_test_pattern() == GoTestAdapter().get_test_pattern()

    def test_validate_test_valid_go(self) -> None:
        code = 'package pkg\nimport "testing"\nfunc TestX(t *testing.T) {}\n'
        result = TestifyAdapter().validate_test(code)
        assert result.valid is True
