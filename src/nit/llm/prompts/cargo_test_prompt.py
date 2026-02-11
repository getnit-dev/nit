"""Rust cargo test prompt template.

Extends the generic unit test template with Rust conventions:
#[test] functions, #[cfg(test)] modules, assert! / assert_eq! macros.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_RUST_INSTRUCTIONS = """\
Framework: Rust standard test harness (cargo test)

Rust-specific rules:
- Mark test functions with ``#[test]``.
- Place unit tests in a ``#[cfg(test)]`` module (e.g. ``mod tests { ... }``) in the same
  file as the code under test.
- Integration tests go in ``tests/*.rs`` as separate crates; each file is a crate.
- Use ``assert!(condition)`` for boolean checks; use ``assert_eq!(left, right)`` or
  ``assert_ne!(left, right)`` for comparisons.
- Use ``#[should_panic]`` for tests that expect a panic; optionally
  ``#[should_panic(expected = "substring")]``.
- Use ``#[ignore]`` for tests that are disabled by default.
- Prefer ``?`` in tests that return ``Result<(), E>``; use
  ``fn test_foo() -> Result<(), E>`` and ``#[test]``.
- Return ONLY the test code — no explanations, no markdown fences.\
"""

_RUST_EXAMPLE = """\
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_add() {
        assert_eq!(add(2, 3), 5);
    }

    #[test]
    fn test_add_zero() {
        assert_eq!(add(0, 1), 1);
    }

    #[test]
    #[should_panic(expected = "overflow")]
    fn test_add_overflow() {
        add(u32::MAX, 1);
    }
}
"""


class CargoTestTemplate(UnitTestTemplate):
    """Rust cargo test prompt template."""

    @property
    def name(self) -> str:
        return "cargo_test"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _RUST_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="Rust testing example",
                content=f"```rust\n{_RUST_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete Rust test module for the source code above.\n"
                "Use ``#[cfg(test)] mod tests``, ``#[test]`` functions, and "
                "``assert!`` / ``assert_eq!`` macros.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
