"""OpenAPI/Swagger spec analyzer — parses API specifications and extracts endpoints.

This analyzer:
1. Detects OpenAPI (3.x) and Swagger (2.0) specification files in a project
2. Parses JSON or YAML spec files using yaml.safe_load
3. Extracts endpoints with HTTP methods, parameters, request bodies, and responses
4. Extracts security schemes defined in the specification
5. Provides structured results for downstream API test generation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

SPEC_FILE_NAMES = (
    "openapi.json",
    "openapi.yaml",
    "openapi.yml",
    "swagger.json",
    "swagger.yaml",
    "swagger.yml",
)
"""File names recognized as OpenAPI/Swagger specification files."""

SPEC_SUBDIRECTORIES = ("docs", "api", "spec")
"""Common subdirectories where spec files may reside."""

SWAGGER_2_VERSION_PREFIX = "2."
"""Version prefix identifying Swagger 2.0 specs."""

OPENAPI_3_VERSION_PREFIX = "3."
"""Version prefix identifying OpenAPI 3.x specs."""


# ── Data models ──────────────────────────────────────────────────


@dataclass
class OpenAPIParameter:
    """A parameter defined on an API endpoint."""

    name: str
    """Parameter name (e.g. 'id', 'page')."""

    location: str
    """Where the parameter appears: 'path', 'query', 'header', or 'cookie'."""

    required: bool
    """Whether the parameter is required."""

    schema_type: str
    """Data type of the parameter (e.g. 'string', 'integer')."""


@dataclass
class OpenAPIEndpoint:
    """A single API endpoint extracted from the specification."""

    path: str
    """URL path (e.g. '/users/{id}')."""

    method: str
    """HTTP method in uppercase (e.g. 'GET', 'POST')."""

    operation_id: str
    """Unique operation identifier, or empty string if not specified."""

    parameters: list[OpenAPIParameter] = field(default_factory=list)
    """Parameters for this endpoint (path, query, header, cookie)."""

    request_body_schema: dict[str, object] = field(default_factory=dict)
    """Request body schema definition, if any."""

    responses: dict[str, str] = field(default_factory=dict)
    """Response status codes mapped to their descriptions."""

    security: list[str] = field(default_factory=list)
    """Security scheme names required for this endpoint."""


@dataclass
class OpenAPIAnalysisResult:
    """Complete result of analyzing an OpenAPI/Swagger specification."""

    spec_version: str
    """Specification version string (e.g. '3.0.1', '2.0')."""

    base_url: str
    """Base URL extracted from the spec (servers or host+basePath)."""

    endpoints: list[OpenAPIEndpoint] = field(default_factory=list)
    """All endpoints discovered in the specification."""

    security_schemes: dict[str, str] = field(default_factory=dict)
    """Security scheme names mapped to their type (e.g. 'apiKey', 'oauth2')."""

    total_endpoints: int = 0
    """Total number of endpoints extracted."""


# ── HTTP methods to scan ─────────────────────────────────────────

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


# ── Public API ───────────────────────────────────────────────────


def detect_openapi_specs(project_root: Path) -> list[Path]:
    """Find OpenAPI/Swagger specification files in a project.

    Searches the project root and common subdirectories (docs/, api/, spec/)
    for files with recognized spec names.

    Args:
        project_root: Root directory of the project to search.

    Returns:
        List of paths to discovered specification files, sorted alphabetically.
    """
    found: list[Path] = []

    search_dirs = [project_root]
    search_dirs.extend(project_root / sub for sub in SPEC_SUBDIRECTORIES)

    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for name in SPEC_FILE_NAMES:
            candidate = directory / name
            if candidate.is_file():
                found.append(candidate)

    found.sort()
    return found


def analyze_openapi_spec(spec_path: Path) -> OpenAPIAnalysisResult:
    """Parse an OpenAPI or Swagger spec file and extract structured information.

    Supports both OpenAPI 3.x and Swagger 2.0 formats. The file may be
    JSON or YAML; both are handled transparently via ``yaml.safe_load``.

    Args:
        spec_path: Path to the specification file.

    Returns:
        An ``OpenAPIAnalysisResult`` containing extracted endpoints,
        security schemes, and metadata.

    Raises:
        FileNotFoundError: If the spec file does not exist.
        ValueError: If the spec cannot be parsed or has no recognized version.
    """
    if not spec_path.is_file():
        raise FileNotFoundError(f"Spec file not found: {spec_path}")

    raw = spec_path.read_text(encoding="utf-8")

    try:
        spec = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse spec file {spec_path}: {exc}") from exc

    if not isinstance(spec, dict):
        raise ValueError(f"Spec file does not contain a mapping: {spec_path}")

    # Determine spec version
    if "openapi" in spec:
        return _parse_openapi_3(spec)
    if "swagger" in spec:
        return _parse_swagger_2(spec)

    raise ValueError(f"Unrecognized spec format (no 'openapi' or 'swagger' key): {spec_path}")


# ── Internal parsers ─────────────────────────────────────────────


def _parse_openapi_3(spec: dict[str, object]) -> OpenAPIAnalysisResult:
    """Parse an OpenAPI 3.x specification.

    Args:
        spec: Parsed specification dictionary.

    Returns:
        Populated ``OpenAPIAnalysisResult``.
    """
    version = str(spec.get("openapi", ""))
    base_url = _extract_base_url_v3(spec)
    security_schemes = _extract_security_schemes_v3(spec)
    global_security = _extract_global_security(spec)
    endpoints = _extract_endpoints(spec, global_security, is_swagger2=False)

    return OpenAPIAnalysisResult(
        spec_version=version,
        base_url=base_url,
        endpoints=endpoints,
        security_schemes=security_schemes,
        total_endpoints=len(endpoints),
    )


def _parse_swagger_2(spec: dict[str, object]) -> OpenAPIAnalysisResult:
    """Parse a Swagger 2.0 specification.

    Args:
        spec: Parsed specification dictionary.

    Returns:
        Populated ``OpenAPIAnalysisResult``.
    """
    version = str(spec.get("swagger", ""))
    base_url = _extract_base_url_v2(spec)
    security_schemes = _extract_security_schemes_v2(spec)
    global_security = _extract_global_security(spec)
    endpoints = _extract_endpoints(spec, global_security, is_swagger2=True)

    return OpenAPIAnalysisResult(
        spec_version=version,
        base_url=base_url,
        endpoints=endpoints,
        security_schemes=security_schemes,
        total_endpoints=len(endpoints),
    )


# ── URL extraction ───────────────────────────────────────────────


def _extract_base_url_v3(spec: dict[str, object]) -> str:
    """Extract the base URL from an OpenAPI 3.x servers block.

    Args:
        spec: Parsed specification dictionary.

    Returns:
        First server URL, or empty string if none defined.
    """
    servers = spec.get("servers")
    if isinstance(servers, list) and servers:
        first = servers[0]
        if isinstance(first, dict):
            return str(first.get("url", ""))
    return ""


def _extract_base_url_v2(spec: dict[str, object]) -> str:
    """Extract the base URL from a Swagger 2.0 host + basePath.

    Args:
        spec: Parsed specification dictionary.

    Returns:
        Constructed base URL, or empty string if host is not defined.
    """
    host = spec.get("host", "")
    base_path = spec.get("basePath", "")
    if not host:
        return ""

    schemes = spec.get("schemes")
    scheme = "https"
    if isinstance(schemes, list) and schemes:
        scheme = str(schemes[0])

    return f"{scheme}://{host}{base_path}"


# ── Security scheme extraction ───────────────────────────────────


def _extract_security_schemes_v3(spec: dict[str, object]) -> dict[str, str]:
    """Extract security schemes from an OpenAPI 3.x spec.

    Args:
        spec: Parsed specification dictionary.

    Returns:
        Mapping of scheme name to scheme type.
    """
    components = spec.get("components")
    if not isinstance(components, dict):
        return {}

    schemes = components.get("securitySchemes")
    if not isinstance(schemes, dict):
        return {}

    return {
        name: str(defn.get("type", "unknown"))
        for name, defn in schemes.items()
        if isinstance(defn, dict)
    }


def _extract_security_schemes_v2(spec: dict[str, object]) -> dict[str, str]:
    """Extract security definitions from a Swagger 2.0 spec.

    Args:
        spec: Parsed specification dictionary.

    Returns:
        Mapping of definition name to security type.
    """
    definitions = spec.get("securityDefinitions")
    if not isinstance(definitions, dict):
        return {}

    return {
        name: str(defn.get("type", "unknown"))
        for name, defn in definitions.items()
        if isinstance(defn, dict)
    }


def _extract_global_security(spec: dict[str, object]) -> list[str]:
    """Extract globally-applied security scheme names.

    Args:
        spec: Parsed specification dictionary.

    Returns:
        List of security scheme names applied at the top level.
    """
    security = spec.get("security")
    if not isinstance(security, list):
        return []

    names: list[str] = []
    for entry in security:
        if isinstance(entry, dict):
            names.extend(entry.keys())
    return names


# ── Endpoint extraction ──────────────────────────────────────────


def _extract_endpoints(
    spec: dict[str, object],
    global_security: list[str],
    *,
    is_swagger2: bool,
) -> list[OpenAPIEndpoint]:
    """Extract all endpoints from the paths object.

    Args:
        spec: Parsed specification dictionary.
        global_security: Security schemes applied globally.
        is_swagger2: Whether this is a Swagger 2.0 spec.

    Returns:
        List of extracted endpoints.
    """
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return []

    endpoints: list[OpenAPIEndpoint] = []

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        # Path-level parameters apply to all operations under this path
        path_params = _extract_parameters(path_item.get("parameters", []))

        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            op_id = str(operation.get("operationId", ""))
            merged_params = _merge_parameters(
                _extract_parameters(operation.get("parameters", [])),
                path_params,
            )
            request_body = _extract_request_body(operation, is_swagger2=is_swagger2)
            responses = _extract_responses(operation.get("responses", {}))
            security = _extract_operation_security(operation, global_security)

            endpoints.append(
                OpenAPIEndpoint(
                    path=str(path),
                    method=method.upper(),
                    operation_id=op_id,
                    parameters=merged_params,
                    request_body_schema=request_body,
                    responses=responses,
                    security=security,
                )
            )

    return endpoints


def _merge_parameters(
    op_params: list[OpenAPIParameter],
    path_params: list[OpenAPIParameter],
) -> list[OpenAPIParameter]:
    """Merge operation-level and path-level parameters.

    Operation parameters take precedence over path parameters with the
    same name.

    Args:
        op_params: Operation-level parameters.
        path_params: Path-level parameters.

    Returns:
        Merged parameter list.
    """
    seen_names = {param.name for param in op_params}
    merged = list(op_params)
    merged.extend(p for p in path_params if p.name not in seen_names)
    return merged


def _extract_request_body(operation: dict[str, object], *, is_swagger2: bool) -> dict[str, object]:
    """Extract request body schema from an operation.

    Args:
        operation: The operation object from the spec.
        is_swagger2: Whether the source is a Swagger 2.0 spec.

    Returns:
        Schema dictionary, or empty dict if no request body.
    """
    if not is_swagger2:
        rb = operation.get("requestBody")
        if isinstance(rb, dict):
            return _extract_request_body_v3(rb)
        return {}

    # Swagger 2.0: body parameters serve as the request body
    body_params = operation.get("parameters", [])
    if isinstance(body_params, list):
        for p in body_params:
            if isinstance(p, dict) and p.get("in") == "body":
                schema = p.get("schema")
                if isinstance(schema, dict):
                    return dict(schema)
                break
    return {}


def _extract_parameters(raw_params: object) -> list[OpenAPIParameter]:
    """Extract parameters from a list of parameter objects.

    Args:
        raw_params: Raw parameters value (expected to be a list of dicts).

    Returns:
        List of parsed ``OpenAPIParameter`` instances.
    """
    if not isinstance(raw_params, list):
        return []

    params: list[OpenAPIParameter] = []
    for p in raw_params:
        if not isinstance(p, dict):
            continue
        # Skip body parameters (Swagger 2.0 request body)
        if p.get("in") == "body":
            continue

        schema_type = "string"
        schema = p.get("schema")
        if isinstance(schema, dict):
            schema_type = str(schema.get("type", "string"))
        elif "type" in p:
            schema_type = str(p["type"])

        params.append(
            OpenAPIParameter(
                name=str(p.get("name", "")),
                location=str(p.get("in", "")),
                required=bool(p.get("required", False)),
                schema_type=schema_type,
            )
        )

    return params


def _extract_request_body_v3(rb: dict[str, object]) -> dict[str, object]:
    """Extract request body schema from an OpenAPI 3.x requestBody object.

    Args:
        rb: The requestBody object from the spec.

    Returns:
        Schema dictionary, or empty dict if not found.
    """
    content = rb.get("content")
    if not isinstance(content, dict):
        return {}

    # Prefer application/json, fall back to first content type
    json_content = content.get("application/json")
    if isinstance(json_content, dict):
        schema = json_content.get("schema")
        if isinstance(schema, dict):
            return dict(schema)

    # Fall back to first available content type
    for media_obj in content.values():
        if isinstance(media_obj, dict):
            schema = media_obj.get("schema")
            if isinstance(schema, dict):
                return dict(schema)

    return {}


def _extract_responses(raw_responses: object) -> dict[str, str]:
    """Extract response status codes and descriptions.

    Args:
        raw_responses: Raw responses object from the spec.

    Returns:
        Mapping of status code to description.
    """
    if not isinstance(raw_responses, dict):
        return {}

    return {
        str(code): str(resp.get("description", ""))
        for code, resp in raw_responses.items()
        if isinstance(resp, dict)
    }


def _extract_operation_security(
    operation: dict[str, object],
    global_security: list[str],
) -> list[str]:
    """Extract security scheme names for an operation.

    Uses operation-level security if defined, otherwise falls back to global.

    Args:
        operation: The operation object from the spec.
        global_security: Globally-applied security scheme names.

    Returns:
        List of security scheme names.
    """
    security = operation.get("security")
    if isinstance(security, list):
        names: list[str] = []
        for entry in security:
            if isinstance(entry, dict):
                names.extend(entry.keys())
        return names

    return list(global_security)
