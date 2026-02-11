"""Testify-specific prompt template for Go tests.

Extends Go testing with testify/suite and testify/assert patterns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.go_test_prompt import GoTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_TESTIFY_INSTRUCTIONS = """\
Framework: Go with Testify (github.com/stretchr/testify)

Testify-specific rules:
- Use ``suite.Run(t, &MySuite{})`` for suite-based tests; struct embeds ``suite.Suite``.
- Use ``assert``: ``assert.Equal``, ``assert.NoError``, ``assert.True``.
- Use ``require`` for fatal assertions: ``require.NoError``, ``require.NotNil``.
- Prefer ``assert``/``require`` over manual ``t.Error``.
- Setup/teardown: ``suite.SetupTest()`` / ``TearDownTest()`` or ``SetupSuite`` / ``TearDownSuite``.
- Table-driven: loop cases and call ``assert.Equal(t, tt.expected, got)``.
- Import: ``"github.com/stretchr/testify/assert"`` and/or ``require`` and/or ``suite``.
- Return ONLY the test code — no explanations, no markdown fences.\
"""

_TESTIFY_EXAMPLE = """\
package mypkg

import (
    "testing"

    "github.com/stretchr/testify/assert"
    "github.com/stretchr/testify/require"
)

func TestAdd(t *testing.T) {
    assert.Equal(t, 5, Add(2, 3))
    assert.Equal(t, 0, Add(-1, 1))
}

func TestDivideRequiresNonZero(t *testing.T) {
    _, err := Divide(1, 0)
    require.Error(t, err)
}

type MySuite struct {
    suite.Suite
}

func TestMySuite(t *testing.T) {
    suite.Run(t, &MySuite{})
}

func (s *MySuite) TestSomething() {
    s.Assert().Equal(42, compute())
}
"""


class TestifyTemplate(GoTestTemplate):
    """Testify-specific Go test prompt template."""

    @property
    def name(self) -> str:
        return "testify"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        base = super()._framework_instructions(_context)
        return f"{base}\n\n{_TESTIFY_INSTRUCTIONS}"

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        sections = super()._extra_sections(_context)
        sections.append(
            PromptSection(
                label="Testify example",
                content=f"```go\n{_TESTIFY_EXAMPLE}\n```",
            ),
        )
        return sections

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete Go test file (``*_test.go``) using testify.\n"
                "Use ``assert`` and/or ``require`` for assertions and optionally "
                "``suite.Suite`` for suite-based tests.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
