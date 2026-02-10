"""Google Test-specific prompt template for C++ unit tests.

Extends the generic unit test template with Google Test conventions:
``TEST``/``TEST_F`` macros, ``EXPECT_*``/``ASSERT_*`` assertions,
fixtures, and standard include structure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_GTEST_INSTRUCTIONS = """\
Framework: Google Test (GTest, C++)

Google Test-specific rules:
- Include ``#include <gtest/gtest.h>`` at the top of the test file.
- Use ``TEST(SuiteName, TestName)`` for stateless tests.
- Use ``TEST_F(FixtureName, TestName)`` when shared setup/teardown is needed.
- Prefer ``EXPECT_*`` assertions for non-fatal checks and ``ASSERT_*`` for fatal preconditions.
- Use clear suite/test names in ``PascalCase`` that describe the behavior under test.
- Keep each test focused on one behavior.
- Test edge cases and failure paths, not only happy paths.
- Use relative includes for the unit under test and keep includes minimal.
- Avoid global mutable state; fixture state should be reset per test.
"""

_GTEST_EXAMPLE = """\
#include <gtest/gtest.h>

#include "calculator.h"

TEST(CalculatorTest, AddReturnsSum) {
  EXPECT_EQ(Add(2, 3), 5);
  EXPECT_EQ(Add(-1, 1), 0);
}

class DividerTest : public ::testing::Test {
 protected:
  void SetUp() override {
    dividend = 10;
  }

  int dividend = 0;
};

TEST_F(DividerTest, DivideByNonZero) {
  ASSERT_NE(dividend, 0);
  EXPECT_EQ(Divide(dividend, 2), 5);
}

TEST_F(DividerTest, DivideByZeroThrows) {
  EXPECT_THROW(Divide(dividend, 0), std::invalid_argument);
}
"""


class GTestTemplate(UnitTestTemplate):
    """Google Test-specific unit test prompt template."""

    @property
    def name(self) -> str:
        return "gtest"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _GTEST_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="Google Test Example",
                content=f"```cpp\n{_GTEST_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete Google Test file (``*_test.cpp`` or ``*_test.cc``) "
                "for the source code above.\n"
                "Use ``TEST``/``TEST_F`` macros, ``EXPECT_*``/``ASSERT_*`` assertions, "
                "and proper C++ includes.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
