"""Tests for the OpenAPI analyzer and API test builder.

Covers:
- Detecting OpenAPI/Swagger spec files in a project
- Parsing OpenAPI 3.x specifications
- Parsing Swagger 2.0 specifications
- Endpoint extraction (path, method, parameters)
- Security scheme extraction
- APITestBuilder test plan generation
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.agents.analyzers.openapi import (
    OpenAPIAnalysisResult,
    OpenAPIEndpoint,
    OpenAPIParameter,
    analyze_openapi_spec,
    detect_openapi_specs,
)
from nit.agents.builders.api import (
    TEST_TYPE_AUTH,
    TEST_TYPE_ERROR_HANDLING,
    TEST_TYPE_HAPPY_PATH,
    TEST_TYPE_VALIDATION,
    APITestBuilder,
)

# ── Sample specs ─────────────────────────────────────────────────

_OPENAPI_3_SPEC = """\
openapi: "3.0.1"
info:
  title: Test API
  version: "1.0.0"
servers:
  - url: https://api.example.com/v1
paths:
  /users:
    get:
      operationId: listUsers
      parameters:
        - name: page
          in: query
          required: false
          schema:
            type: integer
      responses:
        "200":
          description: List of users
    post:
      operationId: createUser
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                email:
                  type: string
      responses:
        "201":
          description: User created
        "400":
          description: Validation error
      security:
        - bearerAuth: []
  /users/{id}:
    get:
      operationId: getUser
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
      responses:
        "200":
          description: User details
        "404":
          description: User not found
      security:
        - bearerAuth: []
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
    apiKey:
      type: apiKey
      name: X-API-Key
      in: header
"""

_SWAGGER_2_SPEC = """\
swagger: "2.0"
info:
  title: Legacy API
  version: "1.0"
host: api.legacy.com
basePath: /v1
schemes:
  - https
paths:
  /items:
    get:
      operationId: getItems
      parameters:
        - name: limit
          in: query
          required: false
          type: integer
      responses:
        "200":
          description: List of items
    post:
      operationId: createItem
      parameters:
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
              name:
                type: string
      responses:
        "201":
          description: Item created
  /items/{itemId}:
    get:
      operationId: getItem
      parameters:
        - name: itemId
          in: path
          required: true
          type: string
      responses:
        "200":
          description: Item details
        "404":
          description: Not found
security:
  - apiKey: []
securityDefinitions:
  apiKey:
    type: apiKey
    name: Authorization
    in: header
"""

_OPENAPI_3_JSON_SPEC = """\
{
  "openapi": "3.0.0",
  "info": {"title": "JSON API", "version": "1.0"},
  "servers": [{"url": "http://localhost:3000"}],
  "paths": {
    "/health": {
      "get": {
        "operationId": "healthCheck",
        "responses": {
          "200": {"description": "OK"}
        }
      }
    }
  }
}
"""

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def project_with_specs(tmp_path: Path) -> Path:
    """Create a project directory with spec files in various locations."""
    # Root-level spec
    (tmp_path / "openapi.yaml").write_text(_OPENAPI_3_SPEC)

    # Spec in docs/ subdirectory
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "swagger.json").write_text(_OPENAPI_3_JSON_SPEC)

    # Spec in api/ subdirectory
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    (api_dir / "openapi.yml").write_text(_OPENAPI_3_SPEC)

    return tmp_path


@pytest.fixture
def openapi3_spec_path(tmp_path: Path) -> Path:
    """Create an OpenAPI 3.x YAML spec file."""
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(_OPENAPI_3_SPEC)
    return spec_file


@pytest.fixture
def swagger2_spec_path(tmp_path: Path) -> Path:
    """Create a Swagger 2.0 YAML spec file."""
    spec_file = tmp_path / "swagger.yaml"
    spec_file.write_text(_SWAGGER_2_SPEC)
    return spec_file


@pytest.fixture
def json_spec_path(tmp_path: Path) -> Path:
    """Create an OpenAPI 3.x JSON spec file."""
    spec_file = tmp_path / "openapi.json"
    spec_file.write_text(_OPENAPI_3_JSON_SPEC)
    return spec_file


# ── Tests: detect_openapi_specs ──────────────────────────────────


def test_detect_specs_finds_root_spec(tmp_path: Path) -> None:
    """Detect a spec file placed at the project root."""
    (tmp_path / "openapi.yaml").write_text(_OPENAPI_3_SPEC)

    found = detect_openapi_specs(tmp_path)

    assert len(found) == 1
    assert found[0].name == "openapi.yaml"


def test_detect_specs_finds_subdirectory_specs(project_with_specs: Path) -> None:
    """Detect spec files in docs/, api/, and spec/ subdirectories."""
    found = detect_openapi_specs(project_with_specs)

    # Should find root openapi.yaml, docs/swagger.json, api/openapi.yml
    assert len(found) == 3

    found_names = {f.name for f in found}
    assert "openapi.yaml" in found_names
    assert "swagger.json" in found_names
    assert "openapi.yml" in found_names


def test_detect_specs_returns_empty_for_no_specs(tmp_path: Path) -> None:
    """Return empty list when no spec files exist."""
    found = detect_openapi_specs(tmp_path)
    assert found == []


def test_detect_specs_ignores_non_spec_files(tmp_path: Path) -> None:
    """Ignore YAML/JSON files that are not named as spec files."""
    (tmp_path / "config.yaml").write_text("key: value")
    (tmp_path / "data.json").write_text("{}")

    found = detect_openapi_specs(tmp_path)
    assert found == []


# ── Tests: analyze_openapi_spec (OpenAPI 3.x) ───────────────────


def test_parse_openapi3_version(openapi3_spec_path: Path) -> None:
    """Parse and verify the spec version for OpenAPI 3.x."""
    result = analyze_openapi_spec(openapi3_spec_path)

    assert result.spec_version == "3.0.1"


def test_parse_openapi3_base_url(openapi3_spec_path: Path) -> None:
    """Extract base URL from OpenAPI 3.x servers block."""
    result = analyze_openapi_spec(openapi3_spec_path)

    assert result.base_url == "https://api.example.com/v1"


def test_parse_openapi3_endpoints(openapi3_spec_path: Path) -> None:
    """Extract all endpoints from an OpenAPI 3.x spec."""
    result = analyze_openapi_spec(openapi3_spec_path)

    assert result.total_endpoints == 3

    methods = {(e.path, e.method) for e in result.endpoints}
    assert ("/users", "GET") in methods
    assert ("/users", "POST") in methods
    assert ("/users/{id}", "GET") in methods


def test_parse_openapi3_parameters(openapi3_spec_path: Path) -> None:
    """Extract parameters from an OpenAPI 3.x endpoint."""
    result = analyze_openapi_spec(openapi3_spec_path)

    # Find the GET /users endpoint
    get_users = _find_endpoint(result, "/users", "GET")
    assert get_users is not None

    assert len(get_users.parameters) == 1
    page_param = get_users.parameters[0]
    assert page_param.name == "page"
    assert page_param.location == "query"
    assert page_param.required is False
    assert page_param.schema_type == "integer"


def test_parse_openapi3_path_parameters(openapi3_spec_path: Path) -> None:
    """Extract path parameters from an OpenAPI 3.x endpoint."""
    result = analyze_openapi_spec(openapi3_spec_path)

    get_user = _find_endpoint(result, "/users/{id}", "GET")
    assert get_user is not None

    id_param = get_user.parameters[0]
    assert id_param.name == "id"
    assert id_param.location == "path"
    assert id_param.required is True
    assert id_param.schema_type == "string"


def test_parse_openapi3_request_body(openapi3_spec_path: Path) -> None:
    """Extract request body schema from an OpenAPI 3.x POST endpoint."""
    result = analyze_openapi_spec(openapi3_spec_path)

    post_users = _find_endpoint(result, "/users", "POST")
    assert post_users is not None
    assert post_users.request_body_schema
    assert post_users.request_body_schema.get("type") == "object"


def test_parse_openapi3_responses(openapi3_spec_path: Path) -> None:
    """Extract response definitions from an OpenAPI 3.x endpoint."""
    result = analyze_openapi_spec(openapi3_spec_path)

    post_users = _find_endpoint(result, "/users", "POST")
    assert post_users is not None

    assert "201" in post_users.responses
    assert "400" in post_users.responses
    assert post_users.responses["201"] == "User created"


def test_parse_openapi3_security_schemes(openapi3_spec_path: Path) -> None:
    """Extract security schemes from an OpenAPI 3.x spec."""
    result = analyze_openapi_spec(openapi3_spec_path)

    assert "bearerAuth" in result.security_schemes
    assert result.security_schemes["bearerAuth"] == "http"
    assert "apiKey" in result.security_schemes
    assert result.security_schemes["apiKey"] == "apiKey"


def test_parse_openapi3_endpoint_security(openapi3_spec_path: Path) -> None:
    """Extract per-endpoint security requirements from an OpenAPI 3.x spec."""
    result = analyze_openapi_spec(openapi3_spec_path)

    post_users = _find_endpoint(result, "/users", "POST")
    assert post_users is not None
    assert "bearerAuth" in post_users.security

    # GET /users has no operation-level security and no global security
    get_users = _find_endpoint(result, "/users", "GET")
    assert get_users is not None
    assert get_users.security == []


def test_parse_openapi3_operation_id(openapi3_spec_path: Path) -> None:
    """Extract operationId from endpoints."""
    result = analyze_openapi_spec(openapi3_spec_path)

    get_users = _find_endpoint(result, "/users", "GET")
    assert get_users is not None
    assert get_users.operation_id == "listUsers"


def test_parse_openapi3_json(json_spec_path: Path) -> None:
    """Parse a JSON-formatted OpenAPI 3.x spec."""
    result = analyze_openapi_spec(json_spec_path)

    assert result.spec_version == "3.0.0"
    assert result.base_url == "http://localhost:3000"
    assert result.total_endpoints == 1
    assert result.endpoints[0].path == "/health"
    assert result.endpoints[0].method == "GET"


# ── Tests: analyze_openapi_spec (Swagger 2.0) ───────────────────


def test_parse_swagger2_version(swagger2_spec_path: Path) -> None:
    """Parse and verify the spec version for Swagger 2.0."""
    result = analyze_openapi_spec(swagger2_spec_path)

    assert result.spec_version == "2.0"


def test_parse_swagger2_base_url(swagger2_spec_path: Path) -> None:
    """Extract base URL from Swagger 2.0 host + basePath."""
    result = analyze_openapi_spec(swagger2_spec_path)

    assert result.base_url == "https://api.legacy.com/v1"


def test_parse_swagger2_endpoints(swagger2_spec_path: Path) -> None:
    """Extract all endpoints from a Swagger 2.0 spec."""
    result = analyze_openapi_spec(swagger2_spec_path)

    assert result.total_endpoints == 3

    methods = {(e.path, e.method) for e in result.endpoints}
    assert ("/items", "GET") in methods
    assert ("/items", "POST") in methods
    assert ("/items/{itemId}", "GET") in methods


def test_parse_swagger2_parameters(swagger2_spec_path: Path) -> None:
    """Extract parameters from a Swagger 2.0 endpoint."""
    result = analyze_openapi_spec(swagger2_spec_path)

    get_items = _find_endpoint(result, "/items", "GET")
    assert get_items is not None

    assert len(get_items.parameters) == 1
    limit_param = get_items.parameters[0]
    assert limit_param.name == "limit"
    assert limit_param.location == "query"
    assert limit_param.schema_type == "integer"


def test_parse_swagger2_body_parameter(swagger2_spec_path: Path) -> None:
    """Extract body parameter as request body from Swagger 2.0."""
    result = analyze_openapi_spec(swagger2_spec_path)

    post_items = _find_endpoint(result, "/items", "POST")
    assert post_items is not None
    assert post_items.request_body_schema
    assert post_items.request_body_schema.get("type") == "object"


def test_parse_swagger2_security_definitions(swagger2_spec_path: Path) -> None:
    """Extract security definitions from a Swagger 2.0 spec."""
    result = analyze_openapi_spec(swagger2_spec_path)

    assert "apiKey" in result.security_schemes
    assert result.security_schemes["apiKey"] == "apiKey"


def test_parse_swagger2_global_security(swagger2_spec_path: Path) -> None:
    """Verify global security is applied to endpoints without operation-level security."""
    result = analyze_openapi_spec(swagger2_spec_path)

    # All endpoints should inherit the global apiKey security
    for endpoint in result.endpoints:
        assert "apiKey" in endpoint.security


# ── Tests: error handling ────────────────────────────────────────


def test_analyze_nonexistent_file() -> None:
    """Raise FileNotFoundError for a non-existent spec file."""
    with pytest.raises(FileNotFoundError):
        analyze_openapi_spec(Path("/nonexistent/openapi.yaml"))


def test_analyze_invalid_yaml(tmp_path: Path) -> None:
    """Raise ValueError for unparseable YAML content."""
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text(": : : not valid yaml [[[")

    with pytest.raises(ValueError, match="Failed to parse"):
        analyze_openapi_spec(bad_file)


def test_analyze_unrecognized_format(tmp_path: Path) -> None:
    """Raise ValueError for valid YAML without openapi/swagger key."""
    bad_file = tmp_path / "unknown.yaml"
    bad_file.write_text("title: Not a spec\nversion: 1.0\n")

    with pytest.raises(ValueError, match="Unrecognized spec format"):
        analyze_openapi_spec(bad_file)


def test_analyze_non_mapping(tmp_path: Path) -> None:
    """Raise ValueError for YAML that is not a mapping."""
    bad_file = tmp_path / "list.yaml"
    bad_file.write_text("- item1\n- item2\n")

    with pytest.raises(ValueError, match="does not contain a mapping"):
        analyze_openapi_spec(bad_file)


# ── Tests: APITestBuilder ────────────────────────────────────────


def test_builder_generates_happy_path(openapi3_spec_path: Path) -> None:
    """Builder should generate happy-path tests for every endpoint."""
    result = analyze_openapi_spec(openapi3_spec_path)
    builder = APITestBuilder()

    test_cases = builder.generate_test_plan(result)

    happy_path_cases = [tc for tc in test_cases if tc.test_type == TEST_TYPE_HAPPY_PATH]
    # One happy-path test per endpoint
    assert len(happy_path_cases) == result.total_endpoints


def test_builder_generates_validation_tests(openapi3_spec_path: Path) -> None:
    """Builder should generate validation tests for endpoints with required params or body."""
    result = analyze_openapi_spec(openapi3_spec_path)
    builder = APITestBuilder()

    test_cases = builder.generate_test_plan(result)

    validation_cases = [tc for tc in test_cases if tc.test_type == TEST_TYPE_VALIDATION]
    # POST /users has a request body, GET /users/{id} has a required path param
    assert len(validation_cases) >= 2


def test_builder_generates_auth_tests(openapi3_spec_path: Path) -> None:
    """Builder should generate auth tests for secured endpoints."""
    result = analyze_openapi_spec(openapi3_spec_path)
    builder = APITestBuilder()

    test_cases = builder.generate_test_plan(result)

    auth_cases = [tc for tc in test_cases if tc.test_type == TEST_TYPE_AUTH]
    # POST /users and GET /users/{id} have security
    assert len(auth_cases) == 2


def test_builder_generates_error_handling_tests(openapi3_spec_path: Path) -> None:
    """Builder should generate error-handling tests for every endpoint."""
    result = analyze_openapi_spec(openapi3_spec_path)
    builder = APITestBuilder()

    test_cases = builder.generate_test_plan(result)

    error_cases = [tc for tc in test_cases if tc.test_type == TEST_TYPE_ERROR_HANDLING]
    # One error-handling test per endpoint
    assert len(error_cases) == result.total_endpoints


def test_builder_test_case_fields(openapi3_spec_path: Path) -> None:
    """All test cases should have populated fields."""
    result = analyze_openapi_spec(openapi3_spec_path)
    builder = APITestBuilder()

    test_cases = builder.generate_test_plan(result)

    for tc in test_cases:
        assert tc.endpoint_path
        assert tc.method
        assert tc.test_name
        assert tc.test_type in (
            TEST_TYPE_HAPPY_PATH,
            TEST_TYPE_VALIDATION,
            TEST_TYPE_AUTH,
            TEST_TYPE_ERROR_HANDLING,
        )
        assert tc.description


def test_builder_test_names_use_operation_id(openapi3_spec_path: Path) -> None:
    """Test names should incorporate the operationId when available."""
    result = analyze_openapi_spec(openapi3_spec_path)
    builder = APITestBuilder()

    test_cases = builder.generate_test_plan(result)

    # Find the happy-path test for GET /users (operationId: listUsers)
    list_users_tests = [
        tc
        for tc in test_cases
        if tc.endpoint_path == "/users"
        and tc.method == "GET"
        and tc.test_type == TEST_TYPE_HAPPY_PATH
    ]
    assert len(list_users_tests) == 1
    assert "listusers" in list_users_tests[0].test_name.lower()


def test_builder_empty_analysis() -> None:
    """Builder should return empty list for an analysis with no endpoints."""
    analysis = OpenAPIAnalysisResult(
        spec_version="3.0.0",
        base_url="",
        endpoints=[],
        security_schemes={},
        total_endpoints=0,
    )
    builder = APITestBuilder()

    test_cases = builder.generate_test_plan(analysis)

    assert test_cases == []


def test_builder_no_auth_when_unsecured() -> None:
    """Builder should not generate auth tests for unsecured endpoints."""
    analysis = OpenAPIAnalysisResult(
        spec_version="3.0.0",
        base_url="http://localhost:8000",
        endpoints=[
            OpenAPIEndpoint(
                path="/health",
                method="GET",
                operation_id="healthCheck",
                parameters=[],
                request_body_schema={},
                responses={"200": "OK"},
                security=[],
            ),
        ],
        security_schemes={},
        total_endpoints=1,
    )
    builder = APITestBuilder()

    test_cases = builder.generate_test_plan(analysis)

    auth_cases = [tc for tc in test_cases if tc.test_type == TEST_TYPE_AUTH]
    assert auth_cases == []


def test_builder_no_validation_when_no_required_params() -> None:
    """Builder should not generate validation tests when there are no required params or body."""
    analysis = OpenAPIAnalysisResult(
        spec_version="3.0.0",
        base_url="http://localhost:8000",
        endpoints=[
            OpenAPIEndpoint(
                path="/health",
                method="GET",
                operation_id="healthCheck",
                parameters=[
                    OpenAPIParameter(
                        name="verbose",
                        location="query",
                        required=False,
                        schema_type="boolean",
                    ),
                ],
                request_body_schema={},
                responses={"200": "OK"},
                security=[],
            ),
        ],
        security_schemes={},
        total_endpoints=1,
    )
    builder = APITestBuilder()

    test_cases = builder.generate_test_plan(analysis)

    validation_cases = [tc for tc in test_cases if tc.test_type == TEST_TYPE_VALIDATION]
    assert validation_cases == []


# ── Helpers ──────────────────────────────────────────────────────


def _find_endpoint(result: OpenAPIAnalysisResult, path: str, method: str) -> OpenAPIEndpoint | None:
    """Find an endpoint by path and method in the analysis result.

    Args:
        result: The analysis result to search.
        path: URL path to match.
        method: HTTP method to match (uppercase).

    Returns:
        The matching endpoint, or None if not found.
    """
    for ep in result.endpoints:
        if ep.path == path and ep.method == method:
            return ep
    return None
