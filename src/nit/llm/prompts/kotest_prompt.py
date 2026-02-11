"""Kotest-specific prompt template for Kotlin unit tests.

Extends the generic unit test template with Kotest DSL conventions:
StringSpec, FunSpec, BehaviorSpec, ``test``/``context``/``should`` blocks,
and assertion styles (``shouldBe``, ``expect``, etc.).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_KOTEST_INSTRUCTIONS = """\
Framework: Kotest (Kotlin)

Kotest-specific rules:
- Use one of the Kotest spec styles: ``StringSpec``, ``FunSpec``, ``BehaviorSpec``, or ``WordSpec``.
- For ``StringSpec``: use ``"test name" { }`` blocks; simple and readable.
- For ``FunSpec``: use ``test("test name") { }`` and ``context("context name") { }`` for nesting.
- For ``BehaviorSpec``: use ``given("subject") { when("action") { then("outcome") { } } }``.
- Use ``io.kotest.matchers.should.*`` for assertions: ``x.shouldBe(5)``, ``list.shouldContain(e)``,
  ``obj.shouldNotBeNull()``.
- Use ``io.kotest.assertions.throwables.shouldThrow<ExceptionType> { }`` for expected exceptions.
- Prefer ``init { }`` block in the spec class for one-time setup; use ``beforeTest``/``afterTest`` \
  for per-test setup/teardown when needed.
- Use ``io.kotest.matchers.collections.shouldBeEmpty``, ``shouldHaveSize``, etc. for collections.
- Keep test names descriptive; use backtick strings in StringSpec (e.g. ``"returns sum..."``).
- Kotest runs on JUnit 5; ensure ``io.kotest:kotest-runner-junit5`` is on the test classpath.\
"""

_KOTEST_EXAMPLE = """\
import io.kotest.core.spec.style.FunSpec
import io.kotest.matchers.shouldBe
import io.kotest.assertions.throwables.shouldThrow

class CalculatorTest : FunSpec({
    context("divide") {
        test("returns correct result") {
            divide(10, 2) shouldBe 5.0
        }
        test("throws when divisor is zero") {
            shouldThrow<ArithmeticException> {
                divide(1, 0)
            }
        }
    }
})

// StringSpec alternative:
// class CalculatorTest : StringSpec({
//     "divide returns correct result" {
//         divide(10, 2) shouldBe 5.0
//     }
// })\
"""


class KotestTemplate(UnitTestTemplate):
    """Kotest-specific unit test prompt template."""

    @property
    def name(self) -> str:
        return "kotest"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _KOTEST_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="Kotest Example",
                content=f"```kotlin\n{_KOTEST_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete Kotest test file (``*Test.kt`` or ``*Spec.kt``) "
                "for the source code above.\n"
                "Use Kotest spec style (e.g. ``FunSpec`` or ``StringSpec``), "
                "``test``/``context``/``should`` blocks as appropriate, and "
                "``io.kotest.matchers.should.*`` assertions.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
