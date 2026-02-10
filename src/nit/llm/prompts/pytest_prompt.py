"""pytest-specific prompt template for Python unit tests.

Extends the generic unit test template with pytest conventions:
function-based tests, ``@pytest.fixture`` usage, plain ``assert``
statements, and conftest patterns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection
from nit.llm.prompts.unit_test import UnitTestTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_PYTEST_INSTRUCTIONS = """\
Framework: pytest (Python)

pytest-specific rules:
- Use plain ``assert`` statements — do NOT use ``self.assertEqual`` or \
``unittest.TestCase``.
- Name test functions ``test_<descriptive_name>`` (snake_case).
- Use ``@pytest.fixture`` for reusable setup; prefer fixtures over \
module-level constants.
- Use ``@pytest.mark.parametrize`` for data-driven tests covering \
multiple inputs.
- Use ``pytest.raises(ExceptionType)`` as a context manager for \
expected exceptions.
- Mock with ``unittest.mock.patch`` or ``monkeypatch`` fixture — \
prefer ``monkeypatch`` for simple attribute/env overrides.
- Place shared fixtures in ``conftest.py`` when they are used across \
multiple test files.
- Use ``tmp_path`` fixture for filesystem operations.
- Use ``capsys`` fixture to capture stdout/stderr.
- Keep tests independent — no shared mutable state between tests.\
"""

_PYTEST_EXAMPLE = """\
import pytest

from mypackage.calculator import Calculator, divide


def test_divide_returns_correct_result() -> None:
    assert divide(10, 2) == 5.0


def test_divide_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (6, 3, 2.0),
        (0, 1, 0.0),
        (-6, 3, -2.0),
    ],
)
def test_divide_parametrized(a: int, b: int, expected: float) -> None:
    assert divide(a, b) == expected


@pytest.fixture
def calculator() -> Calculator:
    return Calculator()


def test_calculator_add(calculator: Calculator) -> None:
    calculator.add(5)
    assert calculator.result == 5\
"""


class PytestTemplate(UnitTestTemplate):
    """pytest-specific unit test prompt template."""

    @property
    def name(self) -> str:
        return "pytest"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return _PYTEST_INSTRUCTIONS

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        return [
            PromptSection(
                label="pytest Example",
                content=f"```python\n{_PYTEST_EXAMPLE}\n```",
            ),
        ]

    def _output_instructions(self, _context: AssembledContext) -> PromptSection:
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete pytest test file (``test_*.py``) for the "
                "source code above.\n"
                "Use function-based tests with ``test_`` prefix, plain "
                "``assert`` statements, and ``@pytest.fixture`` for setup.\n"
                "Use ``@pytest.mark.parametrize`` where multiple input "
                "combinations are useful.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
