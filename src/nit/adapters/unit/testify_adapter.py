"""Testify adapter for Go — detection and prompt when testify is used.

Uses the same test execution and validation as GoTestAdapter (go test -json,
tree-sitter Go). Overrides detection (go.mod + testify) and prompt template
(suite/assert patterns).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.adapters.unit.go_test_adapter import GoTestAdapter

if TYPE_CHECKING:
    from pathlib import Path
from nit.llm.prompts.testify_prompt import TestifyTemplate

_TESTIFY_MODULE = "github.com/stretchr/testify"


class TestifyAdapter(GoTestAdapter):
    """Go testing adapter when testify is used (suite/assert)."""

    @property
    def name(self) -> str:
        return "testify"

    def detect(self, project_path: Path) -> bool:
        """Return True when go.mod exists and requires testify."""
        go_mod = project_path / "go.mod"
        if not go_mod.is_file():
            return False
        try:
            text = go_mod.read_text(encoding="utf-8")
        except OSError:
            return False
        return _TESTIFY_MODULE in text

    def get_prompt_template(self) -> TestifyTemplate:
        return TestifyTemplate()
