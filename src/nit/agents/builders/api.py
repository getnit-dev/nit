"""APITestBuilder — generates API test plans from OpenAPI analysis results.

This builder:
1. Receives an OpenAPIAnalysisResult from the OpenAPI analyzer
2. Generates a structured list of APITestCase entries for each endpoint
3. Covers happy path, validation, auth, and error handling test types
4. Provides test plans that downstream LLM prompts can expand into full tests
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nit.agents.analyzers.openapi import OpenAPIAnalysisResult, OpenAPIEndpoint
    from nit.llm.prompts.base import PromptTemplate

logger = logging.getLogger(__name__)

# ── Test type constants ──────────────────────────────────────────

TEST_TYPE_HAPPY_PATH = "happy_path"
"""Valid request with correct parameters and expected success response."""

TEST_TYPE_VALIDATION = "validation"
"""Request with missing or invalid required parameters."""

TEST_TYPE_AUTH = "auth"
"""Request to a secured endpoint without valid credentials."""

TEST_TYPE_ERROR_HANDLING = "error_handling"
"""Request designed to trigger error responses (404, invalid input)."""


# ── Data models ──────────────────────────────────────────────────


@dataclass
class APITestCase:
    """A single API test case to be generated."""

    endpoint_path: str
    """URL path of the endpoint under test (e.g. '/users/{id}')."""

    method: str
    """HTTP method in uppercase (e.g. 'GET', 'POST')."""

    test_name: str
    """Descriptive test function name (e.g. 'test_get_users_happy_path')."""

    test_type: str
    """Category of the test: 'happy_path', 'validation', 'auth', or 'error_handling'."""

    description: str
    """Human-readable description of what this test verifies."""


# ── APITestBuilder ───────────────────────────────────────────────


class APITestBuilder:
    """Generates API test plans from OpenAPI analysis results.

    For each endpoint in the analysis result, the builder creates test cases
    covering happy path, validation, authentication, and error handling
    scenarios. The generated plan can be fed into an LLM prompt template
    for full test code generation.
    """

    def get_prompt_template(
        self,
        test_cases: list[APITestCase] | None = None,
        base_url: str = "",
        security_schemes: dict[str, str] | None = None,
    ) -> PromptTemplate:
        """Return the prompt template for API test generation.

        Args:
            test_cases: Test cases to embed in the template.
            base_url: Base URL for the API under test.
            security_schemes: Security scheme names mapped to their types.

        Returns:
            An ``APITestTemplate`` instance.
        """
        from nit.llm.prompts.api_test_prompt import APITestTemplate

        return APITestTemplate(
            test_cases=test_cases or [],
            base_url=base_url,
            security_schemes=security_schemes,
        )

    def generate_test_plan(self, analysis: OpenAPIAnalysisResult) -> list[APITestCase]:
        """Generate a comprehensive test plan for all endpoints in the analysis.

        For each endpoint, generates:
        - A happy-path test (valid request, expected success)
        - A validation test (missing required parameters) if the endpoint has required params
        - An auth test (unauthenticated request) if the endpoint has security requirements
        - An error-handling test (404, invalid input)

        Args:
            analysis: The result of analyzing an OpenAPI/Swagger specification.

        Returns:
            List of ``APITestCase`` entries covering all endpoints.
        """
        test_cases: list[APITestCase] = []

        for endpoint in analysis.endpoints:
            test_cases.extend(self._generate_endpoint_tests(endpoint))

        logger.info(
            "Generated %d test cases for %d endpoints",
            len(test_cases),
            analysis.total_endpoints,
        )
        return test_cases

    def _generate_endpoint_tests(self, endpoint: OpenAPIEndpoint) -> list[APITestCase]:
        """Generate test cases for a single endpoint.

        Args:
            endpoint: The endpoint to generate tests for.

        Returns:
            List of test cases for this endpoint.
        """
        cases: list[APITestCase] = []
        name_base = _build_test_name_base(endpoint)

        # Happy path: valid request with correct parameters
        cases.append(
            APITestCase(
                endpoint_path=endpoint.path,
                method=endpoint.method,
                test_name=f"test_{name_base}_happy_path",
                test_type=TEST_TYPE_HAPPY_PATH,
                description=(
                    f"Send a valid {endpoint.method} request to {endpoint.path} "
                    f"and verify a successful response."
                ),
            )
        )

        # Validation: missing required parameters
        required_params = [p for p in endpoint.parameters if p.required]
        if required_params or endpoint.request_body_schema:
            cases.append(
                APITestCase(
                    endpoint_path=endpoint.path,
                    method=endpoint.method,
                    test_name=f"test_{name_base}_validation",
                    test_type=TEST_TYPE_VALIDATION,
                    description=(
                        f"Send a {endpoint.method} request to {endpoint.path} "
                        f"with missing or invalid required parameters and "
                        f"verify a 4xx error response."
                    ),
                )
            )

        # Auth: request without credentials
        if endpoint.security:
            cases.append(
                APITestCase(
                    endpoint_path=endpoint.path,
                    method=endpoint.method,
                    test_name=f"test_{name_base}_auth",
                    test_type=TEST_TYPE_AUTH,
                    description=(
                        f"Send an unauthenticated {endpoint.method} request to "
                        f"{endpoint.path} and verify a 401/403 response."
                    ),
                )
            )

        # Error handling: 404 / invalid input
        cases.append(
            APITestCase(
                endpoint_path=endpoint.path,
                method=endpoint.method,
                test_name=f"test_{name_base}_error_handling",
                test_type=TEST_TYPE_ERROR_HANDLING,
                description=(
                    f"Send a {endpoint.method} request to {endpoint.path} "
                    f"with invalid input or a non-existent resource and "
                    f"verify proper error handling."
                ),
            )
        )

        return cases


# ── Helpers ──────────────────────────────────────────────────────


def _build_test_name_base(endpoint: OpenAPIEndpoint) -> str:
    """Build a base test function name from an endpoint.

    Converts path and method into a snake_case identifier.
    For example, ``GET /users/{id}`` becomes ``get_users_id``.

    Args:
        endpoint: The endpoint to build a name from.

    Returns:
        Snake_case base name suitable for a test function.
    """
    # Use operation_id if available, otherwise derive from path
    if endpoint.operation_id:
        return _sanitize_name(endpoint.operation_id)

    method_lower = endpoint.method.lower()
    # Strip leading slash, replace path separators and braces
    path_part = endpoint.path.strip("/")
    path_part = path_part.replace("/", "_").replace("{", "").replace("}", "")
    path_part = _sanitize_name(path_part)

    return f"{method_lower}_{path_part}" if path_part else method_lower


def _sanitize_name(name: str) -> str:
    """Sanitize a string into a valid Python identifier fragment.

    Replaces non-alphanumeric characters with underscores and collapses
    consecutive underscores.

    Args:
        name: Raw name string.

    Returns:
        Sanitized snake_case string.
    """
    result: list[str] = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            result.append(ch.lower())
        else:
            result.append("_")

    sanitized = "".join(result)

    # Collapse consecutive underscores
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")

    return sanitized.strip("_")
