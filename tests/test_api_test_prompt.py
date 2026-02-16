"""Tests for API test prompt template (src/nit/llm/prompts/api_test_prompt.py)."""

from __future__ import annotations

from nit.agents.builders.api import APITestCase
from nit.llm.prompts.api_test_prompt import APITestTemplate
from nit.llm.prompts.base import PromptTemplate
from tests.test_prompts import _make_context

# ── APITestTemplate Tests ───────────────────────────────────────


def test_is_prompt_template() -> None:
    assert isinstance(APITestTemplate(), PromptTemplate)


def test_name() -> None:
    assert APITestTemplate().name == "api_test"


def test_system_instruction_mentions_api() -> None:
    tmpl = APITestTemplate()
    ctx = _make_context()
    system = tmpl._system_instruction(ctx)
    assert "api" in system.lower()
    assert "requests" in system.lower()


def test_render_produces_two_messages() -> None:
    tmpl = APITestTemplate()
    ctx = _make_context()
    result = tmpl.render(ctx)
    assert len(result.messages) == 2
    assert result.messages[0].role == "system"
    assert result.messages[1].role == "user"


def test_includes_instructions_section() -> None:
    tmpl = APITestTemplate()
    ctx = _make_context()
    result = tmpl.render(ctx)
    assert "Instructions" in result.user_message
    assert "pytest + requests" in result.user_message


def test_includes_example_section() -> None:
    tmpl = APITestTemplate()
    ctx = _make_context()
    result = tmpl.render(ctx)
    assert "Example" in result.user_message
    assert "base_url" in result.user_message


def test_no_config_section_when_empty() -> None:
    tmpl = APITestTemplate(base_url="", security_schemes=None)
    ctx = _make_context()
    result = tmpl.render(ctx)
    assert "API Configuration" not in result.user_message


def test_config_section_with_base_url() -> None:
    tmpl = APITestTemplate(base_url="http://localhost:8000")
    ctx = _make_context()
    result = tmpl.render(ctx)
    assert "API Configuration" in result.user_message
    assert "http://localhost:8000" in result.user_message


def test_config_section_with_security_schemes() -> None:
    tmpl = APITestTemplate(
        security_schemes={"bearerAuth": "http", "apiKey": "apiKey"},
    )
    ctx = _make_context()
    result = tmpl.render(ctx)
    assert "API Configuration" in result.user_message
    assert "bearerAuth" in result.user_message
    assert "apiKey" in result.user_message


def test_config_section_with_both() -> None:
    tmpl = APITestTemplate(
        base_url="https://api.example.com",
        security_schemes={"oauth2": "oauth2"},
    )
    ctx = _make_context()
    result = tmpl.render(ctx)
    assert "https://api.example.com" in result.user_message
    assert "oauth2" in result.user_message


def test_no_test_plan_when_no_cases() -> None:
    tmpl = APITestTemplate(test_cases=[])
    ctx = _make_context()
    result = tmpl.render(ctx)
    assert "Test Plan" not in result.user_message


def test_test_plan_with_cases() -> None:
    cases = [
        APITestCase(
            endpoint_path="/users",
            method="GET",
            test_name="test_get_users_happy_path",
            test_type="happy_path",
            description="Send a valid GET request to /users.",
        ),
        APITestCase(
            endpoint_path="/users",
            method="POST",
            test_name="test_create_user_validation",
            test_type="validation",
            description="Send POST with missing fields.",
        ),
    ]
    tmpl = APITestTemplate(test_cases=cases)
    ctx = _make_context()
    result = tmpl.render(ctx)
    assert "Test Plan" in result.user_message
    assert "test_get_users_happy_path" in result.user_message
    assert "GET /users" in result.user_message
    assert "happy_path" in result.user_message
    assert "test_create_user_validation" in result.user_message
    assert "validation" in result.user_message


def test_includes_source_when_present() -> None:
    tmpl = APITestTemplate()
    ctx = _make_context(source_code="def handler(): pass\n")
    result = tmpl.render(ctx)
    assert "Source File" in result.user_message
    assert "def handler" in result.user_message


def test_omits_source_when_empty() -> None:
    tmpl = APITestTemplate()
    ctx = _make_context(source_code="")
    result = tmpl.render(ctx)
    assert "Source File" not in result.user_message
