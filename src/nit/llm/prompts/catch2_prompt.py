"""Catch2-specific prompt template for C++ unit tests.

Extends the generic unit test template with Catch2 conventions:
``TEST_CASE``/``SECTION`` macros, ``REQUIRE``/``CHECK`` assertions,
and standard include structure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_CATCH2_INSTRUCTIONS = """\
Framework: Catch2 (C++)

Catch2-specific rules:
- Include ``#include <catch2/catch_test_macros.hpp>`` at the top of the test file.
- Use ``TEST_CASE("name", "[tag]")`` for top-level test cases.
- Use ``SECTION("name")`` to organize related scenarios in the same test case.
- Prefer ``REQUIRE`` for critical preconditions and ``CHECK`` for additional assertions.
- Use clear, behavior-focused names for test cases and sections.
- Keep each test focused on one behavior.
- Test edge cases and failure paths, not only happy paths.
- Include only required headers for the unit under test.
- Avoid shared global mutable state.
"""

_CATCH2_EXAMPLE = """\
#include <catch2/catch_test_macros.hpp>

#include "calculator.h"

TEST_CASE("Add returns expected sum", "[calculator][add]") {
  SECTION("positive integers") {
    REQUIRE(Add(2, 3) == 5);
    CHECK(Add(10, 20) == 30);
  }

  SECTION("mixed sign integers") {
    CHECK(Add(-1, 1) == 0);
    CHECK(Add(-2, -3) == -5);
  }
}

TEST_CASE("Divide handles invalid input", "[calculator][divide]") {
  REQUIRE_THROWS_AS(Divide(10, 0), std::invalid_argument);
}
"""


class Catch2Template(UnitTestTemplate):
    """Catch2-specific unit test prompt template."""

    @property
    def name(self) -> str:
        return "catch2"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _CATCH2_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="Catch2 Example",
                content=f"```cpp\n{_CATCH2_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete Catch2 test file (``*_test.cpp`` or ``*_test.cc``) "
                "for the source code above.\n"
                "Use ``TEST_CASE``/``SECTION`` macros and "
                "``REQUIRE``/``CHECK`` assertions with proper C++ includes.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
