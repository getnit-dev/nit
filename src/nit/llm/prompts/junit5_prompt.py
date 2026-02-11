"""JUnit 5-specific prompt template for Java unit tests.

Extends the generic unit test template with JUnit 5 conventions:
@Test, @BeforeEach, @DisplayName, Assertions.*, parameterized tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_JUNIT5_INSTRUCTIONS = """\
Framework: JUnit 5 (Jupiter)

JUnit 5-specific rules:
- Use ``org.junit.jupiter.api.Test`` for test methods.
- Use ``@BeforeEach`` for setup that runs before each test; ``@AfterEach`` for teardown.
- Use ``@DisplayName`` for readable test names when the method name is not enough.
- Use ``org.junit.jupiter.api.Assertions``: ``assertEquals``, ``assertTrue``, ``assertThrows``, etc.
- Prefer ``assertAll`` for multiple related assertions in one test.
- Use ``@ParameterizedTest`` with ``@CsvSource`` or ``@MethodSource`` when appropriate.
- Keep test class in the same package as the class under test (or parallel test source set).
- Use descriptive method names in camelCase (e.g. ``shouldReturnSumWhenAddingPositiveNumbers``).
- Mock with Mockito when needed: ``@ExtendWith(MockitoExtension.class)``, ``@Mock``,
  ``@InjectMocks``.
"""

_JUNIT5_EXAMPLE = """\
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class CalculatorTest {

    private Calculator calculator;

    @BeforeEach
    void setUp() {
        calculator = new Calculator();
    }

    @Test
    @DisplayName("add returns sum of two numbers")
    void addReturnsSumOfTwoNumbers() {
        assertEquals(5, calculator.add(2, 3));
        assertEquals(0, calculator.add(-1, 1));
    }

    @Test
    void divideByZeroThrowsException() {
        assertThrows(ArithmeticException.class, () -> calculator.divide(10, 0));
    }
}
"""


class JUnit5Template(UnitTestTemplate):
    """JUnit 5-specific unit test prompt template."""

    @property
    def name(self) -> str:
        return "junit5"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _JUNIT5_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="JUnit 5 Example",
                content=f"```java\n{_JUNIT5_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete JUnit 5 test class (``*Test.java`` or ``Test*.java``) "
                "for the source code above.\n"
                "Use ``@Test``, ``@BeforeEach``, ``@DisplayName``, ``Assertions.*``.\n"
                "Return ONLY the test code - no explanations, no markdown fences."
            ),
        )
