"""AccessibilityTestBuilder -- generates test plans for accessibility testing.

This builder:
1. Receives an AccessibilityAnalysisResult from the accessibility analyzer
2. Generates test cases for axe scanning, keyboard navigation, ARIA labels,
   and focus management for each discovered route
3. Produces AccessibilityTestCase entries ready for code generation
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nit.agents.analyzers.accessibility import AccessibilityAnalysisResult
    from nit.llm.prompts.base import PromptTemplate

logger = logging.getLogger(__name__)


# ── Data model ───────────────────────────────────────────────────


@dataclass
class AccessibilityTestCase:
    """A single accessibility test case to be generated."""

    url_or_route: str
    """URL or route path to test."""

    test_name: str
    """Generated test function/method name."""

    test_type: str
    """Type of test: 'axe_scan', 'keyboard_nav', 'aria_labels', 'focus_management',
    or 'color_contrast'."""

    description: str
    """Human-readable description of what this test verifies."""

    wcag_criteria: str = ""
    """Related WCAG success criteria (e.g., '2.1.1 Keyboard')."""


# ── Helpers ──────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    """Convert a string into a valid test-name slug.

    Args:
        text: Arbitrary string.

    Returns:
        Lowercased, underscore-separated slug suitable for a test name.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug or "unnamed"


# Test type metadata: (type_key, wcag_criteria, description_template)
_TEST_TYPES: list[tuple[str, str, str]] = [
    ("axe_scan", "4.1.1 Parsing", "Run axe-core accessibility scan on {route}"),
    ("keyboard_nav", "2.1.1 Keyboard", "Verify keyboard navigation works on {route}"),
    ("aria_labels", "4.1.2 Name, Role, Value", "Verify ARIA labels are present on {route}"),
    (
        "focus_management",
        "2.4.3 Focus Order",
        "Verify focus management and tab order on {route}",
    ),
]


# ── Builder ──────────────────────────────────────────────────────


class AccessibilityTestBuilder:
    """Generates test plans from accessibility analysis results.

    For each route or URL found in the analysis, the builder creates test
    cases for axe scanning, keyboard navigation, ARIA labels, and focus
    management.
    """

    def get_prompt_template(self, framework: str = "playwright") -> PromptTemplate:
        """Return the prompt template for accessibility test generation.

        Args:
            framework: The testing framework (``"playwright"`` or ``"jest"``).

        Returns:
            A framework-specific accessibility test prompt template.
        """
        from nit.llm.prompts.accessibility_test_prompt import (
            JestAxeTemplate,
            PlaywrightAxeTemplate,
        )

        if framework == "jest":
            return JestAxeTemplate()
        return PlaywrightAxeTemplate()

    def generate_test_plan(
        self, analysis: AccessibilityAnalysisResult
    ) -> list[AccessibilityTestCase]:
        """Generate a list of accessibility test cases from the analysis result.

        For each route, four test cases are produced:
        1. ``axe_scan`` -- run axe-core automated scan
        2. ``keyboard_nav`` -- verify keyboard navigation
        3. ``aria_labels`` -- verify ARIA labels
        4. ``focus_management`` -- verify focus order

        Args:
            analysis: The result from :func:`analyze_accessibility`.

        Returns:
            List of AccessibilityTestCase entries ready for code generation.
        """
        test_cases: list[AccessibilityTestCase] = []

        for route in analysis.routes:
            slug = _slugify(route)

            for test_type, wcag_criteria, desc_template in _TEST_TYPES:
                test_cases.append(
                    AccessibilityTestCase(
                        url_or_route=route,
                        test_name=f"test_{test_type}_{slug}",
                        test_type=test_type,
                        description=desc_template.format(route=route),
                        wcag_criteria=wcag_criteria,
                    )
                )

        logger.info(
            "Generated %d accessibility test cases from %d routes",
            len(test_cases),
            len(analysis.routes),
        )

        return test_cases
