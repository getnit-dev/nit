"""Vitest-specific prompt template for TypeScript/JavaScript unit tests.

Extends the generic unit test template with Vitest conventions:
``describe``/``it`` blocks, ``vi.mock()`` usage, ``expect()``
assertions, and proper ESM imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_VITEST_INSTRUCTIONS = """\
Framework: Vitest (TypeScript / JavaScript)

Vitest-specific rules:
- Use ``import { describe, it, expect } from 'vitest'`` at the top.
- Structure tests with ``describe()`` blocks grouped by function/class \
and ``it()`` blocks for individual cases.
- Use ``expect(value).toBe()``, ``toEqual()``, ``toContain()``, \
``toThrow()``, etc. for assertions.
- Mock modules with ``vi.mock('./module')`` and functions with ``vi.fn()``.
- Use ``vi.spyOn(obj, 'method')`` for spying on existing methods.
- Use ``beforeEach`` / ``afterEach`` for shared setup/teardown.
- Prefer ``async``/``await`` for asynchronous tests.
- Use ``vi.mocked()`` to get typed mock references.
- Import the module under test with a relative path from the test file.\
"""

_VITEST_EXAMPLE = """\
import { describe, it, expect, vi } from 'vitest';
import { add, multiply } from '../math';

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


class VitestTemplate(UnitTestTemplate):
    """Vitest-specific unit test prompt template."""

    @property
    def name(self) -> str:
        return "vitest"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _VITEST_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="Vitest Example",
                content=f"```typescript\n{_VITEST_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete Vitest test file (``*.test.ts``) for the "
                "source code above.\n"
                "Use ``describe``/``it`` blocks, ``expect()`` assertions, and "
                "``vi.mock()``/``vi.fn()`` for mocking.\n"
                "Import from ``'vitest'`` and use relative imports for the "
                "module under test.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
