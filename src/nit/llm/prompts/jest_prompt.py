"""Jest-specific prompt template for JavaScript/TypeScript unit tests.

Extends the generic unit test template with Jest conventions:
``describe``/``it`` blocks, ``jest.fn()`` mocking, ``expect()``
assertions, and CommonJS/ESM imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_JEST_INSTRUCTIONS = """\
Framework: Jest (JavaScript / TypeScript)

Jest-specific rules:
- Use ``describe()`` blocks grouped by function/class \
and ``it()`` or ``test()`` blocks for individual cases.
- Use ``expect(value).toBe()``, ``toEqual()``, ``toContain()``, \
``toThrow()``, etc. for assertions.
- Mock modules with ``jest.mock('./module')`` and functions with ``jest.fn()``.
- Use ``jest.spyOn(obj, 'method')`` for spying on existing methods.
- Use ``beforeEach`` / ``afterEach`` for shared setup/teardown.
- Prefer ``async``/``await`` for asynchronous tests.
- Import the module under test with a relative path from the test file.
- For TypeScript projects, use ``import`` syntax; for JavaScript, \
use ``require`` or ``import`` depending on the project configuration.\
"""

_JEST_EXAMPLE = """\
const { add, multiply } = require('../math');

describe('add', () => {
  it('should return the sum of two positive numbers', () => {
    expect(add(2, 3)).toBe(5);
  });

  it('should handle negative numbers', () => {
    expect(add(-1, -2)).toBe(-3);
  });

  it('should return 0 when both arguments are 0', () => {
    expect(add(0, 0)).toBe(0);
  });
});

describe('multiply', () => {
  it('should return the product of two numbers', () => {
    expect(multiply(3, 4)).toBe(12);
  });

  it('should return 0 when either argument is 0', () => {
    expect(multiply(5, 0)).toBe(0);
  });
});\
"""


class JestTemplate(UnitTestTemplate):
    """Jest-specific unit test prompt template."""

    @property
    def name(self) -> str:
        return "jest"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _JEST_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="Jest Example",
                content=f"```javascript\n{_JEST_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete Jest test file for the source code above.\n"
                "Use ``describe``/``it`` blocks, ``expect()`` assertions, and "
                "``jest.mock()``/``jest.fn()`` for mocking.\n"
                "Import the module under test with a relative path.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
