"""Next.js route discovery - supports both Pages Router and App Router."""

from __future__ import annotations

import logging
import re
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, cast

from nit.models.route import (
    HTTPMethod,
    RouteHandler,
    RouteInfo,
    RouteType,
)
from nit.parsing.treesitter import detect_language, parse_file

if TYPE_CHECKING:
    import tree_sitter

logger = logging.getLogger(__name__)


def discover_nextjs_routes(project_root: str | Path) -> list[RouteInfo]:
    """Discover all Next.js routes (Pages Router + App Router).

    Args:
        project_root: Path to the Next.js project root.

    Returns:
        List of discovered routes.
    """
    root = Path(project_root)
    routes: list[RouteInfo] = []

    # Try Pages Router
    pages_dir = root / "pages"
    if pages_dir.exists():
        routes.extend(_discover_pages_router(pages_dir, root))

    # Try App Router (Next.js 13+)
    app_dir = root / "app"
    if app_dir.exists():
        routes.extend(_discover_app_router(app_dir, root))

    # Also check src/ directory variants
    src_pages = root / "src" / "pages"
    if src_pages.exists():
        routes.extend(_discover_pages_router(src_pages, root))

    src_app = root / "src" / "app"
    if src_app.exists():
        routes.extend(_discover_app_router(src_app, root))

    return routes


def _discover_pages_router(pages_dir: Path, root: Path) -> list[RouteInfo]:
    """Discover routes from Next.js Pages Router (pages/ directory).

    File-based routing rules:
    - pages/index.js → /
    - pages/about.js → /about
    - pages/blog/[slug].js → /blog/:slug
    - pages/posts/[...slug].js → /posts/*slug
    - pages/api/users.js → /api/users (API route)
    """
    routes: list[RouteInfo] = []

    for file_path in pages_dir.rglob("*"):
        if not file_path.is_file():
            continue

        # Only process JS/TS files
        if file_path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue

        # Skip _app, _document, _error (special Next.js files)
        if file_path.stem in {"_app", "_document", "_error"}:
            continue

        route_info = _pages_file_to_route(file_path, pages_dir, root)
        if route_info:
            routes.append(route_info)

    return routes


def _pages_file_to_route(file_path: Path, pages_dir: Path, root: Path) -> RouteInfo | None:
    """Convert a pages/ file to a RouteInfo."""
    # Get relative path from pages directory
    rel_path = file_path.relative_to(pages_dir)

    # Remove file extension
    route_parts = list(rel_path.with_suffix("").parts)

    # Convert index to root
    if route_parts and route_parts[-1] == "index":
        route_parts.pop()

    # Build route path
    route_path_parts: list[str] = []
    params: list[str] = []

    for part in route_parts:
        # Dynamic segment: [id] → :id
        if part.startswith("[") and part.endswith("]"):
            param_name = part[1:-1]

            # Catch-all segment: [...slug] → *slug
            if param_name.startswith("..."):
                param_name = param_name[3:]
                route_path_parts.append(f"*{param_name}")
                params.append(param_name)
            # Optional catch-all: [[...slug]] → *slug?
            elif param_name.startswith("[...") and param_name.endswith("]"):
                param_name = param_name[4:-1]
                route_path_parts.append(f"*{param_name}?")
                params.append(param_name)
            else:
                route_path_parts.append(f":{param_name}")
                params.append(param_name)
        else:
            route_path_parts.append(part)

    route_path = "/" + "/".join(route_path_parts) if route_path_parts else "/"

    # Determine route type
    is_api_route = route_path.startswith("/api")
    route_type = RouteType.API if is_api_route else RouteType.PAGE

    # Determine HTTP methods for API routes
    methods = (
        _extract_api_methods_from_file(file_path)
        if is_api_route
        else [HTTPMethod.GET]  # Pages are GET by default
    )

    # Extract handler info
    handler = _extract_handler_info(file_path, root)

    return RouteInfo(
        path=route_path,
        route_type=route_type,
        methods=methods,
        handler=handler,
        params=params,
        framework="nextjs-pages",
    )


def _discover_app_router(app_dir: Path, root: Path) -> list[RouteInfo]:
    """Discover routes from Next.js App Router (app/ directory).

    Folder-based routing rules:
    - app/page.js → /
    - app/about/page.js → /about
    - app/blog/[slug]/page.js → /blog/:slug
    - app/api/users/route.js → /api/users (API route)
    """
    routes: list[RouteInfo] = []

    # Find all page.{js,jsx,ts,tsx} and route.{js,jsx,ts,tsx} files
    page_files = list(app_dir.rglob("page.*"))
    route_files = list(app_dir.rglob("route.*"))

    for file_path in page_files:
        if file_path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        route_info = _app_file_to_route(file_path, app_dir, root, is_route_handler=False)
        if route_info:
            routes.append(route_info)

    for file_path in route_files:
        if file_path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        route_info = _app_file_to_route(file_path, app_dir, root, is_route_handler=True)
        if route_info:
            routes.append(route_info)

    return routes


def _app_file_to_route(
    file_path: Path, app_dir: Path, root: Path, *, is_route_handler: bool
) -> RouteInfo | None:
    """Convert an app/ file to a RouteInfo."""
    # Get relative path from app directory
    rel_path = file_path.relative_to(app_dir)

    # Remove the file name (page.tsx or route.tsx)
    route_parts = list(rel_path.parent.parts)

    # Build route path
    route_path_parts: list[str] = []
    params: list[str] = []

    for part in route_parts:
        # Dynamic segment: [id] → :id
        if part.startswith("[") and part.endswith("]"):
            param_name = part[1:-1]

            # Catch-all segment: [...slug] → *slug
            if param_name.startswith("..."):
                param_name = param_name[3:]
                route_path_parts.append(f"*{param_name}")
                params.append(param_name)
            # Optional catch-all: [[...slug]] → *slug?
            elif param_name.startswith("[...") and param_name.endswith("]"):
                param_name = param_name[4:-1]
                route_path_parts.append(f"*{param_name}?")
                params.append(param_name)
            else:
                route_path_parts.append(f":{param_name}")
                params.append(param_name)
        # Route groups: (group) → ignore
        elif part.startswith("(") and part.endswith(")"):
            continue
        else:
            route_path_parts.append(part)

    route_path = "/" + "/".join(route_path_parts) if route_path_parts else "/"

    # Determine route type
    route_type = RouteType.API if is_route_handler else RouteType.PAGE

    # Determine HTTP methods
    methods = _extract_api_methods_from_file(file_path) if is_route_handler else [HTTPMethod.GET]

    # Extract handler info
    handler = _extract_handler_info(file_path, root)

    return RouteInfo(
        path=route_path,
        route_type=route_type,
        methods=methods,
        handler=handler,
        params=params,
        framework="nextjs-app",
    )


def _extract_api_methods_from_file(file_path: Path) -> list[HTTPMethod]:
    """Extract exported HTTP method handlers from an API route file.

    Looks for: export function GET(), export async function POST(), etc.
    """
    methods: list[HTTPMethod] = []

    try:
        # Read file content
        content = file_path.read_text(encoding="utf-8")

        # Look for exported HTTP method functions
        # Patterns: export function GET, export async function POST, export const PUT =
        method_pattern = r"export\s+(?:async\s+)?(?:function\s+)?(?:const\s+)?(\w+)"
        matches = re.findall(method_pattern, content)

        for match in matches:
            method_name = match.upper()
            # Not a valid HTTP method will be suppressed
            with suppress(KeyError):
                methods.append(HTTPMethod[method_name])

        # If no methods found, default to all methods
        if not methods:
            methods = [HTTPMethod.ANY]

    except Exception:
        # On error, assume all methods
        methods = [HTTPMethod.ANY]

    return methods


def _extract_handler_info(file_path: Path, _root: Path) -> RouteHandler:
    """Extract handler information from a file using tree-sitter."""
    handler = RouteHandler(
        file_path=str(file_path.absolute()),
        name=file_path.stem,
    )

    try:
        language = detect_language(file_path)
        if not language:
            return handler

        tree = parse_file(file_path)
        root_node = tree.root_node

        # Find default export or main component/function
        default_export = _find_default_export(root_node, language)
        if default_export:
            handler.name = cast("str | None", default_export.get("name", file_path.stem))
            handler.start_line = cast("int", default_export.get("start_line", 0))
            handler.end_line = cast("int", default_export.get("end_line", 0))
            handler.is_async = cast("bool", default_export.get("is_async", False))

        # Extract dependencies
        handler.dependencies = _extract_imports(root_node, language)

    except Exception:
        logger.debug("Failed to extract handler info from %s", file_path)

    return handler


def _find_default_export(root: tree_sitter.Node, _language: str) -> dict[str, object] | None:
    """Find default export in a JS/TS file."""
    # Simple text-based search for default export
    # A more robust implementation would use tree-sitter queries
    source_text = root.text.decode("utf-8", errors="replace") if root.text else ""

    # Look for: export default function NAME, export default NAME
    default_pattern = r"export\s+default\s+(?:async\s+)?(?:function\s+)?(\w+)"
    match = re.search(default_pattern, source_text)

    if match:
        return {
            "name": match.group(1),
            "start_line": 1,
            "end_line": source_text.count("\n") + 1,
            "is_async": "async" in match.group(0),
        }

    return None


def _extract_imports(root: tree_sitter.Node, _language: str) -> list[str]:
    """Extract import statements from JS/TS file."""
    imports: list[str] = []

    source_text = root.text.decode("utf-8", errors="replace") if root.text else ""

    # Simple regex-based extraction
    # Patterns: import X from 'Y', import { A } from 'B'
    import_pattern = r"import\s+.*?from\s+['\"]([^'\"]+)['\"]"
    matches = re.findall(import_pattern, source_text)

    imports.extend(matches)

    return imports
