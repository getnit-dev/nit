"""Mocha-specific prompt template for JavaScript unit tests.

Extends the generic unit test template with Mocha conventions:
``describe``/``it`` blocks, Chai assertions (``expect``), and
Sinon mocking/stubbing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_MOCHA_INSTRUCTIONS = """\
Framework: Mocha + Chai + Sinon (JavaScript)

Mocha-specific rules:
- Structure tests with ``describe()`` blocks grouped by function/class \
and ``it()`` blocks for individual cases.
- Use Chai ``expect`` for assertions: \
``expect(value).to.equal()``, ``to.deep.equal()``, ``to.be.true``, \
``to.have.lengthOf()``, ``to.throw()``, etc.
- Use ``before`` / ``after`` for one-time setup/teardown.
- Use ``beforeEach`` / ``afterEach`` for per-test setup/teardown.
- For mocking, use Sinon: ``sinon.stub()``, ``sinon.spy()``, \
``sinon.mock()``, ``sinon.fake()``.
- Restore stubs in ``afterEach``: ``sinon.restore()``.
- For async tests, return a Promise or use ``async``/``await``.
- Use ``require()`` or ``import`` for module loading.\
"""

_MOCHA_EXAMPLE = """\
const { expect } = require('chai');
const sinon = require('sinon');
const { add, multiply } = require('../math');

describe('add', () => {
  it('should return the sum of two positive numbers', () => {
    expect(add(2, 3)).to.equal(5);
  });

  it('should handle negative numbers', () => {
    expect(add(-1, -2)).to.equal(-3);
  });

  it('should return 0 when both arguments are 0', () => {
    expect(add(0, 0)).to.equal(0);
  });
});

describe('multiply', () => {
  afterEach(() => {
    sinon.restore();
  });

  it('should return the product of two numbers', () => {
    expect(multiply(3, 4)).to.equal(12);
  });

  it('should return 0 when either argument is 0', () => {
    expect(multiply(5, 0)).to.equal(0);
  });
});\
"""


class MochaTemplate(UnitTestTemplate):
    """Mocha-specific unit test prompt template."""

    @property
    def name(self) -> str:
        return "mocha"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _MOCHA_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="Mocha + Chai Example",
                content=f"```javascript\n{_MOCHA_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete Mocha test file for the source code above.\n"
                "Use ``describe``/``it`` blocks, Chai ``expect()`` assertions, "
                "and Sinon for mocking/stubbing.\n"
                "Import the module under test with a relative path.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
