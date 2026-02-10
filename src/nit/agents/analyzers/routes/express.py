"""Express/Fastify route discovery via tree-sitter AST parsing."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import cast

from nit.models.route import (
    HTTPMethod,
    RouteHandler,
    RouteInfo,
    RouteType,
)
from nit.parsing.treesitter import detect_language, parse_file

logger = logging.getLogger(__name__)

# Tree-sitter query for Express/Fastify route definitions
ROUTE_QUERY = """
(call_expression
  function: (member_expression
    object: (identifier) @router_obj
    property: (property_identifier) @method)
  arguments: (arguments
    (string) @path
    .
    (_)* @handler))

(call_expression
  function: (member_expression
    object: (call_expression
      function: (member_expression
        object: (identifier) @router_obj
        property: (property_identifier) @method_name))
    property: (property_identifier))
  arguments: (arguments
    (string) @route_path))
"""


def discover_express_routes(project_root: str | Path) -> list[RouteInfo]:
    """Discover Express/Fastify routes by parsing JS/TS files.

    Args:
        project_root: Path to the project root.

    Returns:
        List of discovered routes.
    """
    root = Path(project_root)
    routes: list[RouteInfo] = []

    # Common Express/Fastify file locations
    search_paths = [
        root / "src",
        root / "server",
        root / "api",
        root / "routes",
        root / "app",
    ]

    # Also check root directory
    search_paths.append(root)

    for search_path in search_paths:
        if not search_path.exists():
            continue

        # Find all JS/TS files
        for file_path in search_path.rglob("*"):
            if not file_path.is_file():
                continue

            if file_path.suffix not in {".js", ".ts", ".mjs", ".cjs"}:
                continue

            # Skip node_modules
            if "node_modules" in file_path.parts:
                continue

            routes.extend(_extract_routes_from_file(file_path))

    return routes


def _extract_routes_from_file(file_path: Path) -> list[RouteInfo]:
    """Extract routes from a single Express/Fastify file."""
    routes: list[RouteInfo] = []

    try:
        language = detect_language(file_path)
        if language not in {"javascript", "typescript"}:
            return routes

        tree = parse_file(file_path)
        root_node = tree.root_node

        # Find route definitions using text patterns
        # More robust than tree-sitter queries for this use case
        source_text = root_node.text.decode("utf-8", errors="replace") if root_node.text else ""

        route_defs = _find_route_definitions(source_text)

        for route_def in route_defs:
            handler = RouteHandler(
                file_path=str(file_path.absolute()),
                name=cast("str | None", route_def.get("handler_name")),
                start_line=cast("int", route_def.get("line", 0)),
            )

            method_str = cast("str", route_def["method"])
            methods = [HTTPMethod[method_str.upper()]]

            path_str = cast("str", route_def["path"])
            route_info = RouteInfo(
                path=path_str,
                route_type=RouteType.API,
                methods=methods,
                handler=handler,
                params=_extract_route_params(path_str),
                framework=cast("str", route_def.get("framework", "express")),
            )

            routes.append(route_info)

    except Exception as exc:
        # On error, return empty list
        logger.debug("Error extracting routes from %s: %s", file_path, exc)

    return routes


def _find_route_definitions(source_text: str) -> list[dict[str, object]]:
    """Find route definitions in Express/Fastify source code.

    Patterns:
    - app.get('/path', handler)
    - router.post('/users', async (req, res) => {})
    - fastify.delete('/items/:id', handler)
    """
    route_defs: list[dict[str, object]] = []

    # Regex pattern matches route definitions like app.get('/path', ...)
    # and captures the object name, HTTP method, and path
    pattern = r"(app|router|fastify|server)\.(\w+)\s*\(\s*['\"]([^'\"]+)['\"]"

    lines = source_text.split("\n")

    for line_num, line in enumerate(lines, start=1):
        matches = re.finditer(pattern, line)

        for match in matches:
            obj_name = match.group(1)
            method = match.group(2).lower()
            path = match.group(3)

            # Check if this is a valid HTTP method
            valid_methods = {"get", "post", "put", "patch", "delete", "head", "options", "all"}

            if method not in valid_methods:
                continue

            # Map 'all' to ANY
            if method == "all":
                method = "any"

            # Try to extract handler name
            handler_name = _extract_handler_name(line)

            # Detect framework from object name
            framework = "fastify" if obj_name == "fastify" else "express"

            route_defs.append(
                {
                    "method": method,
                    "path": path,
                    "handler_name": handler_name,
                    "line": line_num,
                    "framework": framework,
                }
            )

    return route_defs


def _extract_handler_name(line: str) -> str | None:
    """Extract handler function name from route definition line."""
    # Look for named function: handler, userController.create, etc.
    # Pattern after the path string
    handler_pattern = r"['\"][,\s]+([a-zA-Z_$][\w.$]*)"

    match = re.search(handler_pattern, line)
    if match:
        return match.group(1)

    # Look for arrow function with name
    arrow_pattern = r"const\s+(\w+)\s*="
    match = re.search(arrow_pattern, line)
    if match:
        return match.group(1)

    return None


def _extract_route_params(path: str) -> list[str]:
    """Extract dynamic parameters from Express/Fastify route path.

    Examples:
    - /users/:id → ['id']
    - /posts/:postId/comments/:commentId → ['postId', 'commentId']
    - /files/:path* → ['path']
    """
    params: list[str] = []

    # Express/Fastify use :param syntax
    param_pattern = r":(\w+)[\*\+\?]?"

    matches = re.findall(param_pattern, path)
    params.extend(matches)

    return params


def discover_fastify_routes(project_root: str | Path) -> list[RouteInfo]:
    """Discover Fastify routes.

    Uses the same implementation as Express since the routing syntax is similar.

    Args:
        project_root: Path to the project root.

    Returns:
        List of discovered routes.
    """
    # Fastify uses similar syntax to Express
    return discover_express_routes(project_root)
