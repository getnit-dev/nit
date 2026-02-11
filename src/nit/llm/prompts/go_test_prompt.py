"""Go stdlib testing prompt template.

Extends the generic unit test template with Go conventions:
table-driven tests, t.Run() subtests, and testing package patterns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_GO_INSTRUCTIONS = """\
Framework: Go standard library (testing package)

Go-specific rules:
- Place tests in ``*_test.go`` files in the same package as the code under test.
- Use ``func TestXxx(t *testing.T)`` for test functions (Xxx must not be lowercase).
- Prefer table-driven tests: slice of struct with inputs/expected, loop with ``t.Run(name, ...)``.
- Use ``t.Helper()`` in helper functions so failures report the caller's line.
- Use ``t.Error`` / ``t.Fatal`` for failures; ``t.Fatal`` stops the test immediately.
- For expected panics, use ``defer func() { _ = recover() }()`` or a small helper.
- Use sub-tests via ``t.Run("subtest name", func(t *testing.T) { ... })`` to group related cases.
- Keep tests focused; test one behavior per test function when possible.
- Use same package for white-box tests, or ``package mypkg_test`` with import for black-box.
- Return ONLY the test code — no explanations, no markdown fences.\
"""

_GO_EXAMPLE = """\
package mypkg

import "testing"

func TestAdd(t *testing.T) {
    tests := []struct {
        name     string
        a, b     int
        expected int
    }{
        {"positive", 2, 3, 5},
        {"zero", 0, 1, 1},
        {"negative", -1, 1, 0},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            if got := Add(tt.a, tt.b); got != tt.expected {
                t.Errorf("Add(%d, %d) = %d, want %d", tt.a, tt.b, got, tt.expected)
            }
        })
    }
}

func TestDivideByZero(t *testing.T) {
    defer func() {
        if r := recover(); r == nil {
            t.Error("expected panic")
        }
    }()
    Divide(1, 0)
}
"""


class GoTestTemplate(UnitTestTemplate):
    """Go stdlib testing prompt template."""

    @property
    def name(self) -> str:
        return "gotest"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _GO_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="Go testing example",
                content=f"```go\n{_GO_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete Go test file (``*_test.go``) for the source code above.\n"
                "Use ``testing`` package, ``TestXxx(t *testing.T)``, and prefer table-driven "
                "tests with ``t.Run()`` subtests.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
