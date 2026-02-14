"""API test prompt template for generating HTTP API tests.

Generates test code for API endpoints based on OpenAPI/Swagger analysis,
using the ``requests`` library for Python and standard HTTP testing patterns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import PromptSection, PromptTemplate

if TYPE_CHECKING:
    from nit.agents.builders.api import APITestCase
    from nit.llm.context import AssembledContext

# ── System instruction ───────────────────────────────────────────

_API_TEST_SYSTEM_INSTRUCTION = """\
You are an expert API test engineer. Your task is to generate robust, \
maintainable HTTP API tests using Python's ``requests`` library and ``pytest``.

Key principles:
1. **Correctness**: Validate status codes, response schemas, and business logic.
2. **Isolation**: Each test should be independent and idempotent.
3. **Readability**: Use clear test names and descriptive assertions.
4. **Coverage**: Cover happy paths, validation errors, auth failures, and edge cases.
5. **Maintainability**: Use fixtures for base URL and auth tokens; avoid hardcoded values.

HTTP testing patterns:
- Use ``requests.get()``, ``requests.post()``, etc. for HTTP calls.
- Assert ``response.status_code`` against expected codes (200, 201, 400, 401, 404).
- Use ``response.json()`` to parse and validate response bodies.
- Use ``pytest.fixture`` for shared setup (base URL, headers, auth tokens).
- Group related tests with descriptive names: ``test_<resource>_<scenario>``.

Output only the test code in a single Python file. \
Do NOT include explanations or markdown formatting.\
"""

# ── Framework instructions ───────────────────────────────────────

_API_TEST_INSTRUCTIONS = """\
Framework: pytest + requests (Python)

Testing rules:
- Import ``requests`` and ``pytest`` at the top of the file.
- Define a ``base_url`` fixture that returns the API base URL.
- For authenticated endpoints, define an ``auth_headers`` fixture.
- Use ``response.status_code`` for status assertions.
- Use ``response.json()`` to validate response payloads.
- For validation tests, send requests with missing required fields and assert 400/422.
- For auth tests, send requests without credentials and assert 401/403.
- For error handling tests, use invalid resource IDs and assert 404.
- Use ``pytest.mark.parametrize`` for testing multiple input variations when appropriate.
- Always close or use context managers for sessions if creating them explicitly.\
"""

# ── Example ──────────────────────────────────────────────────────

_API_TEST_EXAMPLE = """\
import pytest
import requests


@pytest.fixture
def base_url():
    return "http://localhost:8000"


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_get_users_happy_path(base_url, auth_headers):
    response = requests.get(f"{base_url}/users", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_create_user_validation(base_url, auth_headers):
    response = requests.post(
        f"{base_url}/users",
        json={},  # Missing required fields
        headers=auth_headers,
    )
    assert response.status_code in (400, 422)


def test_get_users_unauthorized(base_url):
    response = requests.get(f"{base_url}/users")
    assert response.status_code in (401, 403)


def test_get_user_not_found(base_url, auth_headers):
    response = requests.get(
        f"{base_url}/users/nonexistent-id",
        headers=auth_headers,
    )
    assert response.status_code == 404\
"""


# ── Template class ───────────────────────────────────────────────


class APITestTemplate(PromptTemplate):
    """Prompt template for generating API tests from OpenAPI analysis.

    Extends the base ``PromptTemplate`` to inject API-specific instructions,
    endpoint details, and test case plans into the LLM prompt.
    """

    def __init__(
        self,
        test_cases: list[APITestCase] | None = None,
        base_url: str = "",
        security_schemes: dict[str, str] | None = None,
    ) -> None:
        """Initialize the API test template.

        Args:
            test_cases: List of test cases from APITestBuilder.
            base_url: Base URL for the API under test.
            security_schemes: Security scheme names mapped to their types.
        """
        self._test_cases = test_cases or []
        self._base_url = base_url
        self._security_schemes = security_schemes or {}

    @property
    def name(self) -> str:
        """Template identifier."""
        return "api_test"

    def _system_instruction(self, _context: AssembledContext) -> str:
        """Return the system-level instruction for API test generation.

        Args:
            _context: Assembled context (unused; required by base class contract).

        Returns:
            System instruction string.
        """
        return _API_TEST_SYSTEM_INSTRUCTION

    def _build_sections(self, context: AssembledContext) -> list[PromptSection]:
        """Build the prompt sections for API test generation.

        Args:
            context: Assembled context for the source file under test.

        Returns:
            Ordered list of prompt sections forming the user message.
        """
        sections: list[PromptSection] = []

        # Instructions section
        sections.append(PromptSection(label="Instructions", content=_API_TEST_INSTRUCTIONS))

        # Example section
        sections.append(PromptSection(label="Example", content=_API_TEST_EXAMPLE))

        # API configuration
        config_lines: list[str] = []
        if self._base_url:
            config_lines.append(f"Base URL: {self._base_url}")
        if self._security_schemes:
            config_lines.append("Security schemes:")
            for scheme_name, scheme_type in self._security_schemes.items():
                config_lines.append(f"  - {scheme_name}: {scheme_type}")
        if config_lines:
            sections.append(
                PromptSection(label="API Configuration", content="\n".join(config_lines))
            )

        # Test plan section
        if self._test_cases:
            plan_lines: list[str] = []
            for tc in self._test_cases:
                plan_lines.append(f"### {tc.test_name}")
                plan_lines.append(f"- Endpoint: {tc.method} {tc.endpoint_path}")
                plan_lines.append(f"- Type: {tc.test_type}")
                plan_lines.append(f"- Description: {tc.description}")
                plan_lines.append("")
            sections.append(PromptSection(label="Test Plan", content="\n".join(plan_lines)))

        # Source context (if the user is testing a specific handler file)
        if context.source_code:
            sections.append(
                PromptSection(
                    label="Source File",
                    content=(
                        f"File: {context.source_path}\n"
                        f"Language: {context.language}\n\n"
                        f"```{context.language}\n{context.source_code}\n```"
                    ),
                )
            )

        return sections
