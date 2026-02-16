"""GraphQLTestBuilder — generates test plans for GraphQL schemas.

This builder:
1. Receives a GraphQLSchemaAnalysis from the analyzer
2. Generates test cases for each query, mutation, and subscription
3. Produces test cases of different types: execution, validation, auth, error_handling
4. Returns a structured list of GraphQLTestCase instances
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nit.agents.analyzers.graphql import GraphQLSchemaAnalysis
    from nit.llm.prompts.base import PromptTemplate

logger = logging.getLogger(__name__)

# ── Data models ──────────────────────────────────────────────────

# Valid test type values
_TEST_TYPES = ("execution", "validation", "auth", "error_handling")


@dataclass
class GraphQLTestCase:
    """Represents a single test case for a GraphQL operation."""

    operation_name: str
    """Name of the GraphQL operation under test."""

    operation_type: str
    """One of 'query', 'mutation', or 'subscription'."""

    test_name: str
    """Descriptive name for the test case."""

    test_type: str
    """Category: 'execution', 'validation', 'auth', or 'error_handling'."""

    description: str = ""
    """Human-readable description of what this test verifies."""


# ── Builder ──────────────────────────────────────────────────────


class GraphQLTestBuilder:
    """Generates a structured test plan from a GraphQL schema analysis.

    For each query and mutation, the builder produces a set of test cases
    covering execution, input validation, authorization, and error handling.
    Subscriptions receive execution and error handling tests.
    """

    def get_prompt_template(self) -> PromptTemplate:
        """Return the prompt template for GraphQL test generation."""
        from nit.llm.prompts.graphql_test_prompt import GraphQLTestTemplate

        return GraphQLTestTemplate()

    def generate_test_plan(self, analysis: GraphQLSchemaAnalysis) -> list[GraphQLTestCase]:
        """Generate test cases for all operations in the schema analysis.

        Args:
            analysis: A ``GraphQLSchemaAnalysis`` produced by the analyzer.

        Returns:
            List of ``GraphQLTestCase`` instances covering queries,
            mutations, and subscriptions.
        """
        cases: list[GraphQLTestCase] = []

        for op in analysis.queries:
            cases.extend(self._generate_query_tests(op.name))

        for op in analysis.mutations:
            cases.extend(self._generate_mutation_tests(op.name))

        for op in analysis.subscriptions:
            cases.extend(self._generate_subscription_tests(op.name))

        logger.info(
            "Generated %d test cases (%d queries, %d mutations, %d subscriptions)",
            len(cases),
            len(analysis.queries),
            len(analysis.mutations),
            len(analysis.subscriptions),
        )

        return cases

    # ── Private helpers ──────────────────────────────────────────

    def _generate_query_tests(self, name: str) -> list[GraphQLTestCase]:
        """Generate test cases for a single query operation.

        Args:
            name: Name of the query field.

        Returns:
            List of test cases covering execution, validation, auth,
            and error handling.
        """
        return [
            GraphQLTestCase(
                operation_name=name,
                operation_type="query",
                test_name=f"test_{name}_returns_expected_data",
                test_type="execution",
                description=f"Verify that the {name} query returns the expected data shape.",
            ),
            GraphQLTestCase(
                operation_name=name,
                operation_type="query",
                test_name=f"test_{name}_validates_arguments",
                test_type="validation",
                description=f"Verify that the {name} query rejects invalid or missing arguments.",
            ),
            GraphQLTestCase(
                operation_name=name,
                operation_type="query",
                test_name=f"test_{name}_requires_authentication",
                test_type="auth",
                description=(
                    f"Verify that the {name} query returns an auth error "
                    "when called without valid credentials."
                ),
            ),
            GraphQLTestCase(
                operation_name=name,
                operation_type="query",
                test_name=f"test_{name}_handles_not_found",
                test_type="error_handling",
                description=(
                    f"Verify that the {name} query returns a proper error "
                    "when the requested resource does not exist."
                ),
            ),
        ]

    def _generate_mutation_tests(self, name: str) -> list[GraphQLTestCase]:
        """Generate test cases for a single mutation operation.

        Args:
            name: Name of the mutation field.

        Returns:
            List of test cases covering execution, validation, auth,
            and error handling.
        """
        return [
            GraphQLTestCase(
                operation_name=name,
                operation_type="mutation",
                test_name=f"test_{name}_succeeds_with_valid_input",
                test_type="execution",
                description=f"Verify that the {name} mutation succeeds with valid input data.",
            ),
            GraphQLTestCase(
                operation_name=name,
                operation_type="mutation",
                test_name=f"test_{name}_rejects_invalid_input",
                test_type="validation",
                description=(
                    f"Verify that the {name} mutation returns validation errors "
                    "for invalid input data."
                ),
            ),
            GraphQLTestCase(
                operation_name=name,
                operation_type="mutation",
                test_name=f"test_{name}_requires_authorization",
                test_type="auth",
                description=(
                    f"Verify that the {name} mutation returns an auth error "
                    "when called without proper permissions."
                ),
            ),
            GraphQLTestCase(
                operation_name=name,
                operation_type="mutation",
                test_name=f"test_{name}_handles_conflict",
                test_type="error_handling",
                description=(
                    f"Verify that the {name} mutation returns a proper error "
                    "on duplicate or conflicting data."
                ),
            ),
        ]

    def _generate_subscription_tests(self, name: str) -> list[GraphQLTestCase]:
        """Generate test cases for a single subscription operation.

        Args:
            name: Name of the subscription field.

        Returns:
            List of test cases covering execution and error handling.
        """
        return [
            GraphQLTestCase(
                operation_name=name,
                operation_type="subscription",
                test_name=f"test_{name}_receives_events",
                test_type="execution",
                description=(
                    f"Verify that the {name} subscription emits events "
                    "when the corresponding data changes."
                ),
            ),
            GraphQLTestCase(
                operation_name=name,
                operation_type="subscription",
                test_name=f"test_{name}_handles_disconnect",
                test_type="error_handling",
                description=(
                    f"Verify that the {name} subscription handles "
                    "disconnection and reconnection gracefully."
                ),
            ),
        ]
