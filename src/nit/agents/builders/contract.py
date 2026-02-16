"""ContractTestBuilder -- generates test plans for Pact contract testing.

This builder:
1. Receives a ContractAnalysisResult from the contract analyzer
2. Generates a test plan with consumer and provider test cases
3. Produces ContractTestCase entries for each interaction
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nit.agents.analyzers.contract import ContractAnalysisResult
    from nit.llm.prompts.base import PromptTemplate

logger = logging.getLogger(__name__)


@dataclass
class ContractTestCase:
    """A single contract test case to be generated."""

    consumer: str
    """Name of the consumer service."""

    provider: str
    """Name of the provider service."""

    interaction_description: str
    """Description of the interaction being tested."""

    test_name: str
    """Generated test function/method name."""

    test_type: str
    """Type of test: 'consumer_mock', 'provider_verification', or 'schema_validation'."""

    description: str
    """Human-readable description of what this test verifies."""


def _slugify(text: str) -> str:
    """Convert a description string into a valid test-name slug.

    Args:
        text: Arbitrary description string.

    Returns:
        Lowercased, underscore-separated slug suitable for a test name.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug or "unnamed"


class ContractTestBuilder:
    """Generates test plans from Pact contract analysis results.

    For each interaction in each contract, the builder creates:
    - A consumer mock test (verifying the consumer sends the correct request)
    - A provider verification test (verifying the provider returns the expected response)
    """

    def get_prompt_template(self, framework: str = "pytest") -> PromptTemplate:
        """Return the prompt template for contract test generation.

        Args:
            framework: The testing framework (``"pytest"``, ``"jest"``, or ``"vitest"``).

        Returns:
            A framework-specific contract test prompt template.
        """
        from nit.llm.prompts.contract_test_prompt import (
            JestPactTemplate,
            PytestPactTemplate,
            VitestPactTemplate,
        )

        templates = {
            "jest": JestPactTemplate,
            "vitest": VitestPactTemplate,
        }
        cls = templates.get(framework, PytestPactTemplate)
        return cls()

    def generate_test_plan(self, analysis: ContractAnalysisResult) -> list[ContractTestCase]:
        """Generate a list of contract test cases from the analysis result.

        For each interaction, two test cases are produced:
        1. ``consumer_mock`` -- verifies the consumer sends correct requests
        2. ``provider_verification`` -- verifies the provider returns correct responses

        Args:
            analysis: The result from :func:`analyze_contracts`.

        Returns:
            List of ContractTestCase entries ready for code generation.
        """
        test_cases: list[ContractTestCase] = []

        for contract in analysis.contracts:
            for interaction in contract.interactions:
                slug = _slugify(interaction.description)

                # Consumer mock test
                test_cases.append(
                    ContractTestCase(
                        consumer=contract.consumer,
                        provider=contract.provider,
                        interaction_description=interaction.description,
                        test_name=f"test_consumer_{slug}",
                        test_type="consumer_mock",
                        description=(
                            f"Verify consumer '{contract.consumer}' sends correct "
                            f"request for: {interaction.description}"
                        ),
                    )
                )

                # Provider verification test
                test_cases.append(
                    ContractTestCase(
                        consumer=contract.consumer,
                        provider=contract.provider,
                        interaction_description=interaction.description,
                        test_name=f"test_provider_{slug}",
                        test_type="provider_verification",
                        description=(
                            f"Verify provider '{contract.provider}' returns correct "
                            f"response for: {interaction.description}"
                        ),
                    )
                )

        logger.info(
            "Generated %d contract test cases from %d contracts",
            len(test_cases),
            len(analysis.contracts),
        )

        return test_cases
