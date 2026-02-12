"""Go web framework route discovery (Gin, Echo, Chi, Gorilla Mux)."""

from __future__ import annotations

import re
from contextlib import suppress
from pathlib import Path

from nit.models.route import (
    HTTPMethod,
    RouteHandler,
    RouteInfo,
    RouteType,
)


def discover_go_routes(project_root: str | Path, framework: str = "gin") -> list[RouteInfo]:
    """Discover Go web framework routes.

    Args:
        project_root: Path to the Go project root.
        framework: Framework name (gin, echo, chi, gorilla).

    Returns:
        List of discovered routes.
    """
    root = Path(project_root)
    routes: list[RouteInfo] = []

    # Find all .go files
    for file_path in root.rglob("*.go"):
        if "vendor" in file_path.parts:
            continue

        routes.extend(_extract_go_routes_from_file(file_path, root, framework))

    return routes


def _extract_go_routes_from_file(file_path: Path, root: Path, framework: str) -> list[RouteInfo]:
    """Extract routes from a Go file based on framework patterns."""
    routes: list[RouteInfo] = []

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return routes

    # Different patterns for different frameworks
    if framework == "gin":
        routes.extend(_extract_gin_routes(content, file_path, root))
    elif framework == "echo":
        routes.extend(_extract_echo_routes(content, file_path, root))
    elif framework == "chi":
        routes.extend(_extract_chi_routes(content, file_path, root))
    elif framework == "gorilla":
        routes.extend(_extract_gorilla_routes(content, file_path, root))

    return routes


def _extract_gin_routes(content: str, file_path: Path, _root: Path) -> list[RouteInfo]:
    """Extract Gin routes from Go file.

    Gin patterns:
    - router.GET("/path", handler)
    - router.POST("/users/:id", handler)
    - r.Group("/api").GET("/users", handler)
    """
    routes: list[RouteInfo] = []

    # Regex pattern for route definitions like router.GET("/path", ...)
    pattern = r'(\w+)\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\(\s*"([^"]+)"'

    for match in re.finditer(pattern, content):
        # match.group(1) is the router variable name, not needed
        method_name = match.group(2)
        path = match.group(3)

        try:
            method = HTTPMethod[method_name]
        except KeyError:
            continue

        # Extract parameters from Gin path syntax
        params = _extract_gin_params(path)

        handler = RouteHandler(
            file_path=str(file_path.absolute()),
            name=None,  # Go doesn't always have named handlers
        )

        route_info = RouteInfo(
            path=path.replace(":", "{").replace("/", "/{", 1) if ":" in path else path,
            route_type=RouteType.API,
            methods=[method],
            handler=handler,
            params=params,
            framework="gin",
        )

        routes.append(route_info)

    return routes


def _extract_echo_routes(content: str, file_path: Path, _root: Path) -> list[RouteInfo]:
    """Extract Echo routes from Go file.

    Echo patterns:
    - e.GET("/path", handler)
    - e.POST("/users/:id", handler)
    """
    routes: list[RouteInfo] = []

    # Regex pattern for routes like e.GET("/path", ...)
    pattern = r'(\w+)\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\(\s*"([^"]+)"'

    for match in re.finditer(pattern, content):
        method_name = match.group(2)
        path = match.group(3)

        try:
            method = HTTPMethod[method_name]
        except KeyError:
            continue

        params = _extract_echo_params(path)

        handler = RouteHandler(
            file_path=str(file_path.absolute()),
            name=None,
        )

        route_info = RouteInfo(
            path=path.replace(":", "{").replace("/", "/{", 1) if ":" in path else path,
            route_type=RouteType.API,
            methods=[method],
            handler=handler,
            params=params,
            framework="echo",
        )

        routes.append(route_info)

    return routes


def _extract_chi_routes(content: str, file_path: Path, _root: Path) -> list[RouteInfo]:
    """Extract Chi routes from Go file.

    Chi patterns:
    - r.Get("/path", handler)
    - r.Post("/users/{id}", handler)
    """
    routes: list[RouteInfo] = []

    # Regex pattern for route definitions like r.Get("/path", ...)
    pattern = r'(\w+)\.(Get|Post|Put|Patch|Delete|Head|Options)\s*\(\s*"([^"]+)"'

    for match in re.finditer(pattern, content):
        method_name = match.group(2).upper()
        path = match.group(3)

        try:
            method = HTTPMethod[method_name]
        except KeyError:
            continue

        params = _extract_chi_params(path)

        handler = RouteHandler(
            file_path=str(file_path.absolute()),
            name=None,
        )

        route_info = RouteInfo(
            path=path,
            route_type=RouteType.API,
            methods=[method],
            handler=handler,
            params=params,
            framework="chi",
        )

        routes.append(route_info)

    return routes


def _extract_gorilla_routes(content: str, file_path: Path, _root: Path) -> list[RouteInfo]:
    """Extract Gorilla Mux routes from Go file.

    Gorilla patterns:
    - r.HandleFunc("/path", handler).Methods("GET")
    - r.HandleFunc("/users/{id}", handler).Methods("GET", "POST")
    """
    routes: list[RouteInfo] = []

    # Regex pattern for routes like r.HandleFunc("/path", ...).Methods("GET", "POST")
    pattern = r'HandleFunc\s*\(\s*"([^"]+)"[^)]+\)\.Methods\s*\(\s*([^)]+)\)'

    for match in re.finditer(pattern, content):
        path = match.group(1)
        methods_str = match.group(2)

        # Extract methods from quoted strings
        methods: list[HTTPMethod] = []
        for method_match in re.finditer(r'"([^"]+)"', methods_str):
            method_name = method_match.group(1)
            with suppress(KeyError):
                methods.append(HTTPMethod[method_name])

        if not methods:
            methods = [HTTPMethod.GET]

        params = _extract_gorilla_params(path)

        handler = RouteHandler(
            file_path=str(file_path.absolute()),
            name=None,
        )

        route_info = RouteInfo(
            path=path,
            route_type=RouteType.API,
            methods=methods,
            handler=handler,
            params=params,
            framework="gorilla",
        )

        routes.append(route_info)

    return routes


def _extract_gin_params(path: str) -> list[str]:
    """Extract parameters from Gin path.

    Gin uses :param syntax: /users/:id → ['id']
    """
    params: list[str] = []
    param_pattern = r":(\w+)"
    matches = re.findall(param_pattern, path)
    params.extend(matches)
    return params


def _extract_echo_params(path: str) -> list[str]:
    """Extract parameters from Echo path.

    Echo uses :param syntax: /users/:id → ['id']
    """
    params: list[str] = []
    param_pattern = r":(\w+)"
    matches = re.findall(param_pattern, path)
    params.extend(matches)
    return params


def _extract_chi_params(path: str) -> list[str]:
    """Extract parameters from Chi path.

    Chi uses {param} syntax: /users/{id} → ['id']
    """
    params: list[str] = []
    param_pattern = r"\{(\w+)\}"
    matches = re.findall(param_pattern, path)
    params.extend(matches)
    return params


def _extract_gorilla_params(path: str) -> list[str]:
    """Extract parameters from Gorilla Mux path.

    Gorilla uses {param} syntax: /users/{id} → ['id']
    """
    params: list[str] = []
    param_pattern = r"\{(\w+)\}"
    matches = re.findall(param_pattern, path)
    params.extend(matches)
    return params
