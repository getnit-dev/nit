"""Django route discovery via urls.py parsing."""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

from nit.models.route import (
    HTTPMethod,
    RouteHandler,
    RouteInfo,
    RouteType,
)

logger = logging.getLogger(__name__)

# Constants
MIN_URL_PATTERN_ARGS = 2  # path() requires at least pattern and view
MIN_VIEW_NAME_PARTS = 2  # module.view minimum format
MIN_VIEW_PARTS_FOR_MODULE = 3  # app.views.module minimum format


def discover_django_routes(project_root: str | Path) -> list[RouteInfo]:
    """Discover Django routes by parsing urls.py files.

    Args:
        project_root: Path to the Django project root.

    Returns:
        List of discovered routes.
    """
    root = Path(project_root)
    routes: list[RouteInfo] = []

    # Find all urls.py files
    urls_files = list(root.rglob("urls.py"))

    # Also check common Django locations
    for subdir in ["", "config", "project"]:
        urls_path = root / subdir / "urls.py"
        if urls_path.exists() and urls_path not in urls_files:
            urls_files.append(urls_path)

    # Parse each urls.py file
    for urls_file in urls_files:
        if "site-packages" in str(urls_file) or "venv" in str(urls_file):
            continue

        routes.extend(_parse_urls_file(urls_file, root))

    return routes


def _parse_urls_file(urls_file: Path, root: Path, prefix: str = "") -> list[RouteInfo]:
    """Parse a Django urls.py file to extract routes.

    Args:
        urls_file: Path to urls.py file.
        root: Project root directory.
        prefix: URL prefix from parent urlpatterns.

    Returns:
        List of discovered routes.
    """
    routes: list[RouteInfo] = []

    try:
        content = urls_file.read_text(encoding="utf-8")

        # Parse Python AST
        tree = ast.parse(content, filename=str(urls_file))

        # Find urlpatterns assignment
        urlpatterns = _find_urlpatterns(tree)

        if not urlpatterns:
            return routes

        # Process each pattern
        for pattern_node in urlpatterns:
            route_info = _process_url_pattern(pattern_node, urls_file, root, prefix)
            if route_info:
                routes.append(route_info)

    except SyntaxError as exc:
        # Invalid Python file, skip
        logger.debug("Syntax error parsing %s: %s", urls_file, exc)
    except Exception as exc:
        # Other errors, skip
        logger.debug("Error processing %s: %s", urls_file, exc)

    return routes


def _find_urlpatterns(tree: ast.Module) -> list[ast.expr]:
    """Find urlpatterns list in the AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "urlpatterns"
                    and isinstance(node.value, ast.List)
                ):
                    return node.value.elts

    return []


def _process_url_pattern(
    node: ast.expr,
    urls_file: Path,
    root: Path,
    prefix: str,
) -> RouteInfo | None:
    """Process a single URL pattern node.

    Handles:
    - path('route/', view) - Django 2.0+ path syntax
    - re_path(r'^route/$', view) - Django regex path
    - url(r'^route/$', view) - legacy Django url
    - include('app.urls') - nested URL configs
    """
    if not isinstance(node, ast.Call):
        return None

    func_name = _get_function_name(node.func)

    if func_name in {"path", "re_path", "url"}:
        return _parse_path_pattern(node, urls_file, root, prefix, func_name)
    if func_name == "include":
        # Handle include() - would need to recursively parse
        # For now, we'll skip nested includes
        return None

    return None


def _parse_path_pattern(
    node: ast.Call,
    urls_file: Path,
    root: Path,
    prefix: str,
    func_name: str,
) -> RouteInfo | None:
    """Parse a path(), re_path(), or url() pattern."""
    if len(node.args) < MIN_URL_PATTERN_ARGS:
        return None

    # First argument is the path pattern
    path_arg = node.args[0]
    path_str = _extract_string_value(path_arg)

    if not path_str:
        return None

    # Second argument is the view
    view_arg = node.args[1]
    view_name = _extract_view_name(view_arg)

    # Convert Django path pattern to standard format
    route_path = _convert_django_path(path_str, func_name)

    # Add prefix if present
    if prefix:
        route_path = prefix.rstrip("/") + "/" + route_path.lstrip("/")

    # Extract route parameters
    params = _extract_django_params(path_str, func_name)

    # Determine HTTP methods
    # Django views typically handle multiple methods, default to common ones
    methods = [HTTPMethod.GET, HTTPMethod.POST]

    # Try to find the view file
    handler = RouteHandler(
        file_path=str(urls_file.absolute()),
        name=view_name,
    )

    # Try to resolve view to actual file
    if view_name:
        view_file = _find_view_file(view_name, root)
        if view_file:
            handler.file_path = str(view_file.absolute())

    return RouteInfo(
        path=route_path,
        route_type=RouteType.API if "/api" in route_path else RouteType.PAGE,
        methods=methods,
        handler=handler,
        params=params,
        framework="django",
    )


def _get_function_name(node: ast.expr) -> str | None:
    """Extract function name from a Call node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _extract_string_value(node: ast.expr) -> str | None:
    """Extract string value from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # Python 3.7 compatibility - Str was removed in 3.8
    if hasattr(ast, "Str") and isinstance(node, ast.Str):
        return str(node.s)
    return None


def _extract_view_name(node: ast.expr) -> str | None:
    """Extract view name from view argument."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        # Handle views.some_view
        parts: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            parts.insert(0, current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.insert(0, current.id)
        return ".".join(parts)
    if isinstance(node, ast.Call):
        # Handle as_view() pattern
        return _get_function_name(node.func)

    return None


def _convert_django_path(path_str: str, func_name: str) -> str:
    """Convert Django path pattern to standard format.

    Django patterns:
    - path: users/<int:id>/ → /users/:id
    - re_path: r'^users/(?P<id>\\d+)/$' → /users/:id
    - url: same as re_path
    """
    route = path_str

    if func_name == "path":
        # Modern Django path() syntax: <type:name>
        # Convert <int:id> → :id, <str:slug> → :slug
        route = re.sub(r"<(?:\w+:)?(\w+)>", r":\1", route)
    else:
        # Regex patterns (re_path, url)
        # Remove regex anchors
        route = route.lstrip("^").rstrip("$")

        # Convert named groups: (?P<name>...) → :name
        route = re.sub(r"\(\?P<(\w+)>[^)]+\)", r":\1", route)

        # Remove other regex patterns
        route = re.sub(r"\([^)]*\)", "", route)
        route = re.sub(r"[\\+*?]", "", route)

    # Ensure leading slash
    if not route.startswith("/"):
        route = "/" + route

    # Remove trailing slash
    route = route.rstrip("/")

    # Handle root path
    if not route:
        route = "/"

    return route


def _extract_django_params(path_str: str, func_name: str) -> list[str]:
    """Extract parameter names from Django path pattern."""
    params: list[str] = []

    if func_name == "path":
        # Extract from <type:name> or <name>
        matches = re.findall(r"<(?:\w+:)?(\w+)>", path_str)
        params.extend(matches)
    else:
        # Extract from (?P<name>...)
        matches = re.findall(r"\(\?P<(\w+)>", path_str)
        params.extend(matches)

    return params


def _find_view_file(view_name: str, root: Path) -> Path | None:
    """Try to find the Python file containing the view."""
    # Convert view_name to possible file path
    # e.g., 'myapp.views.user_list' → myapp/views.py

    parts = view_name.split(".")

    if len(parts) < MIN_VIEW_NAME_PARTS:
        return None

    # Try app/views.py pattern
    app_name = parts[0]
    view_file = root / app_name / "views.py"

    if view_file.exists():
        return view_file

    # Try app/views/module.py pattern
    if len(parts) >= MIN_VIEW_PARTS_FOR_MODULE:
        module_name = parts[1]
        view_file = root / app_name / "views" / f"{module_name}.py"
        if view_file.exists():
            return view_file

    return None
