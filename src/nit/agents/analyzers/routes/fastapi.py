"""FastAPI route discovery via decorator parsing."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from nit.models.route import (
    HTTPMethod,
    RouteHandler,
    RouteInfo,
    RouteType,
)

# Minimum number of parts in a decorator name to identify a method call (e.g. "app.get")
MIN_DECORATOR_PARTS = 2

VALID_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def discover_fastapi_routes(project_root: str | Path) -> list[RouteInfo]:
    """Discover FastAPI routes by parsing Python files for @app decorators.

    Args:
        project_root: Path to the FastAPI project root.

    Returns:
        List of discovered routes.
    """
    root = Path(project_root)
    routes: list[RouteInfo] = []

    # Common FastAPI file locations
    search_paths = [
        root / "app",
        root / "src",
        root / "api",
        root,
    ]

    for search_path in search_paths:
        if not search_path.exists():
            continue

        for file_path in search_path.rglob("*.py"):
            if "venv" in file_path.parts or ".venv" in file_path.parts:
                continue
            if "site-packages" in str(file_path):
                continue

            routes.extend(_extract_fastapi_routes_from_file(file_path, root))

    return routes


def _extract_fastapi_routes_from_file(file_path: Path, root: Path) -> list[RouteInfo]:
    """Extract FastAPI routes from a single Python file."""
    routes: list[RouteInfo] = []

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                route_infos = _extract_fastapi_routes_from_function(node, file_path, root)
                routes.extend(route_infos)

    except (SyntaxError, UnicodeDecodeError):
        # Skip files that can't be parsed
        pass

    return routes


def _extract_fastapi_routes_from_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: Path,
    root: Path,
) -> list[RouteInfo]:
    """Extract route info from a FastAPI function with HTTP method decorators."""
    routes: list[RouteInfo] = []

    for decorator in func_node.decorator_list:
        route_info = _parse_fastapi_decorator(decorator, func_node, file_path, root)
        if route_info:
            routes.append(route_info)

    return routes


def _resolve_http_method(decorator_name: str) -> HTTPMethod | None:
    """Resolve an HTTP method from a decorator name like 'app.get'.

    Returns:
        HTTPMethod if valid, None otherwise.
    """
    parts = decorator_name.split(".")
    if len(parts) < MIN_DECORATOR_PARTS:
        return None

    method_name = parts[-1].upper()
    if method_name not in VALID_HTTP_METHODS:
        return None

    try:
        return HTTPMethod[method_name]
    except KeyError:
        return None


def _extract_method_and_path(
    decorator: ast.expr,
) -> tuple[HTTPMethod, str] | None:
    """Extract HTTP method and path from a FastAPI decorator.

    Returns:
        Tuple of (method, path) if valid, None otherwise.
    """
    if not isinstance(decorator, ast.Call):
        return None

    decorator_name = _get_decorator_name(decorator.func)
    if not decorator_name:
        return None

    method = _resolve_http_method(decorator_name)
    if method is None or not decorator.args:
        return None

    path = _extract_string_from_node(decorator.args[0])
    if not path:
        return None

    return method, path


def _parse_fastapi_decorator(
    decorator: ast.expr,
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: Path,
    _root: Path,
) -> RouteInfo | None:
    """Parse a FastAPI HTTP method decorator."""
    extracted = _extract_method_and_path(decorator)
    if extracted is None:
        return None

    method, path = extracted

    # Extract route parameters
    params = _extract_fastapi_params(path)

    # Create handler info
    handler = RouteHandler(
        file_path=str(file_path.absolute()),
        name=func_node.name,
        start_line=func_node.lineno,
        end_line=func_node.end_lineno or func_node.lineno,
        is_async=isinstance(func_node, ast.AsyncFunctionDef),
    )

    return RouteInfo(
        path=path,
        route_type=RouteType.API,
        methods=[method],
        handler=handler,
        params=params,
        framework="fastapi",
    )


def _get_decorator_name(node: ast.expr) -> str | None:
    """Get decorator name from AST node."""
    if isinstance(node, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            parts.insert(0, current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.insert(0, current.id)
        return ".".join(parts)
    if isinstance(node, ast.Name):
        return node.id
    return None


def _extract_string_from_node(node: ast.expr) -> str | None:
    """Extract string value from AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # Python 3.7 compatibility
    if hasattr(ast, "Str") and isinstance(node, ast.Str):
        return str(node.s)
    return None


def _extract_fastapi_params(path: str) -> list[str]:
    """Extract dynamic parameters from FastAPI route path.

    FastAPI uses {param} syntax for path parameters.
    Examples:
    - /users/{id} → ['id']
    - /posts/{post_id}/comments/{comment_id} → ['post_id', 'comment_id']
    """
    params: list[str] = []
    param_pattern = r"\{(\w+)\}"
    matches = re.findall(param_pattern, path)
    params.extend(matches)
    return params
