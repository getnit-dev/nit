"""Flask route discovery via decorator parsing."""

from __future__ import annotations

import ast
import re
from contextlib import suppress
from pathlib import Path

from nit.models.route import (
    HTTPMethod,
    RouteHandler,
    RouteInfo,
    RouteType,
)


def discover_flask_routes(project_root: str | Path) -> list[RouteInfo]:
    """Discover Flask routes by parsing Python files for @app.route decorators.

    Args:
        project_root: Path to the Flask project root.

    Returns:
        List of discovered routes.
    """
    root = Path(project_root)
    routes: list[RouteInfo] = []

    # Common Flask file locations
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

            routes.extend(_extract_flask_routes_from_file(file_path, root))

    return routes


def _extract_flask_routes_from_file(file_path: Path, root: Path) -> list[RouteInfo]:
    """Extract Flask routes from a single Python file."""
    routes: list[RouteInfo] = []

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                route_info = _extract_flask_route_from_function(node, file_path, root)
                if route_info:
                    routes.append(route_info)

    except SyntaxError, UnicodeDecodeError:
        # Skip files that can't be parsed
        pass

    return routes


def _extract_flask_route_from_function(
    func_node: ast.FunctionDef, file_path: Path, root: Path
) -> RouteInfo | None:
    """Extract route info from a Flask function with @app.route decorator."""
    for decorator in func_node.decorator_list:
        route_info = _parse_flask_decorator(decorator, func_node, file_path, root)
        if route_info:
            return route_info

    return None


def _parse_flask_decorator(
    decorator: ast.expr,
    func_node: ast.FunctionDef,
    file_path: Path,
    root: Path,  # noqa: ARG001
) -> RouteInfo | None:
    """Parse a Flask route decorator."""
    # Handle @app.route() or @blueprint.route()
    if not isinstance(decorator, ast.Call):
        return None

    # Check if it's a route decorator
    decorator_name = _get_decorator_name(decorator.func)
    if not decorator_name or not decorator_name.endswith(".route"):
        return None

    # Extract route path from first argument
    if not decorator.args:
        return None

    path = _extract_string_from_node(decorator.args[0])
    if not path:
        return None

    # Extract HTTP methods from 'methods' keyword argument
    methods = _extract_methods_from_decorator(decorator)

    # Determine route type
    route_type = RouteType.API if "/api" in path else RouteType.PAGE

    # Extract route parameters
    params = _extract_flask_params(path)

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
        route_type=route_type,
        methods=methods,
        handler=handler,
        params=params,
        framework="flask",
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


def _extract_methods_from_decorator(decorator: ast.Call) -> list[HTTPMethod]:
    """Extract HTTP methods from Flask decorator keyword arguments."""
    methods: list[HTTPMethod] = []

    for keyword in decorator.keywords:
        if keyword.arg == "methods" and isinstance(keyword.value, ast.List):
            for elt in keyword.value.elts:
                method_str = _extract_string_from_node(elt)
                if method_str:
                    with suppress(KeyError):
                        methods.append(HTTPMethod[method_str.upper()])

    # Default to GET if no methods specified
    if not methods:
        methods = [HTTPMethod.GET]

    return methods


def _extract_flask_params(path: str) -> list[str]:
    """Extract dynamic parameters from Flask route path.

    Flask uses <param> or <type:param> syntax.
    Examples:
    - /users/<id> → ['id']
    - /posts/<int:id> → ['id']
    - /files/<path:filename> → ['filename']
    """
    params: list[str] = []
    param_pattern = r"<(?:\w+:)?(\w+)>"
    matches = re.findall(param_pattern, path)
    params.extend(matches)
    return params
