"""xUnit-specific prompt template for C#/.NET unit tests.

Extends the generic unit test template with xUnit conventions:
[Fact], [Theory], [InlineData], Assert.*, IClassFixture for shared setup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_XUNIT_INSTRUCTIONS = """\
Framework: xUnit (.NET)

xUnit-specific rules:
- Use ``[Fact]`` for a single test method; use ``[Theory]`` for parameterized tests.
- Use ``[InlineData(...)]`` (one or more) with ``[Theory]`` to supply test data.
- Use ``Assert.*`` from ``Xunit``: ``Assert.Equal``, ``Assert.True``, ``Assert.Throws``, etc.
- Use ``using Xunit;`` at the top of the test file.
- Use descriptive method names in PascalCase (e.g. ``Add_ReturnsSum_WhenGivenTwoNumbers``).
- For shared setup per test class, use ``IClassFixture<T>``; for per-test setup use the
  constructor or ``IDisposable``.
- Do not use ``[SetUp]`` or ``[TearDown]`` (NUnit/MSTest); xUnit uses constructor and
  ``IDisposable`` instead.
- Prefer ``Assert.NotNull``, ``Assert.Equal(expected, actual)`` with optional comparer when needed.
"""

_XUNIT_EXAMPLE = """\
using Xunit;

public class CalculatorTests
{
    [Fact]
    public void Add_ReturnsSum_WhenGivenTwoNumbers()
    {
        var calculator = new Calculator();
        Assert.Equal(5, calculator.Add(2, 3));
        Assert.Equal(0, calculator.Add(-1, 1));
    }

    [Theory]
    [InlineData(10, 0)]
    [InlineData(-5, 0)]
    public void Divide_Throws_WhenDivisorIsZero(int a, int b)
    {
        var calculator = new Calculator();
        Assert.Throws<DivideByZeroException>(() => calculator.Divide(a, b));
    }
}
"""


class XUnitTemplate(UnitTestTemplate):
    """xUnit-specific unit test prompt template."""

    @property
    def name(self) -> str:
        return "xunit"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _XUNIT_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="xUnit Example",
                content=f"```csharp\n{_XUNIT_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete xUnit test class (``*Tests.cs`` or ``*Test.cs``) "
                "for the source code above.\n"
                "Use ``[Fact]``, ``[Theory]``, ``[InlineData]``, ``Assert.*`` as appropriate.\n"
                "Return ONLY the test code - no explanations, no markdown fences."
            ),
        )
