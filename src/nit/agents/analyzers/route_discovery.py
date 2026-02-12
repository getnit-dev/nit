"""Route discovery analyzer - main entry point for E2E route discovery."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nit.agents.analyzers.routes.django import discover_django_routes
from nit.agents.analyzers.routes.express import (
    discover_express_routes,
    discover_fastify_routes,
)
from nit.agents.analyzers.routes.fastapi import discover_fastapi_routes
from nit.agents.analyzers.routes.flask import discover_flask_routes
from nit.agents.analyzers.routes.go import discover_go_routes
from nit.agents.analyzers.routes.nextjs import discover_nextjs_routes
from nit.models.route import RouteDiscoveryResult, RouteInfo

if TYPE_CHECKING:
    from collections.abc import Callable

    from nit.models.profile import ProjectProfile

logger = logging.getLogger(__name__)


def _check_nextjs(root: Path) -> str | None:
    """Check if project is a Next.js application."""
    if (root / "next.config.js").exists() or (root / "next.config.mjs").exists():
        return "nextjs"

    if (root / "pages").exists() or (root / "app").exists():
        package_json = root / "package.json"
        if package_json.exists():
            deps = _read_package_json_deps(package_json)
            if deps and "next" in deps:
                return "nextjs"

    return None


def _check_python_framework(root: Path) -> str | None:
    """Check for Python web frameworks (Django, Flask, FastAPI)."""
    # Check for Django
    if (root / "manage.py").exists() or list(root.rglob("settings.py")):
        return "django"

    # Check for Flask/FastAPI by looking at Python files
    for py_file in root.rglob("*.py"):
        if "venv" in py_file.parts or ".venv" in py_file.parts:
            continue
        if "site-packages" in str(py_file):
            continue

        try:
            content = py_file.read_text(encoding="utf-8")
            # Check for FastAPI
            if ("from fastapi import" in content or "import fastapi" in content) and (
                "@app.get" in content or "@app.post" in content
            ):
                return "fastapi"
            # Check for Flask
            if ("from flask import" in content or "import flask" in content) and (
                "@app.route" in content or "@blueprint.route" in content
            ):
                return "flask"
        except (UnicodeDecodeError, PermissionError):
            continue

    return None


def _check_go_framework(root: Path) -> str | None:
    """Check for Go web frameworks (Gin, Echo, Chi, Gorilla)."""
    if not (root / "go.mod").exists():
        return None

    try:
        go_mod = (root / "go.mod").read_text()

        # Check for specific frameworks in go.mod
        if "github.com/gin-gonic/gin" in go_mod:
            return "gin"
        if "github.com/labstack/echo" in go_mod:
            return "echo"
        if "github.com/go-chi/chi" in go_mod:
            return "chi"
        if "github.com/gorilla/mux" in go_mod:
            return "gorilla"
    except (FileNotFoundError, UnicodeDecodeError):
        pass

    return None


def _check_node_framework(root: Path) -> str | None:
    """Check for Express/Fastify in Node.js project."""
    package_json = root / "package.json"
    if package_json.exists():
        deps = _read_package_json_deps(package_json)
        if deps:
            if "fastify" in deps:
                return "fastify"
            if "express" in deps:
                return "express"

    # Check file contents as fallback
    for pattern in ["app.js", "server.js", "index.js", "main.ts", "app.ts", "server.ts"]:
        framework = _check_file_for_framework(root, pattern)
        if framework:
            return framework

    return None


def _read_package_json_deps(package_json: Path) -> dict[str, str] | None:
    """Read dependencies from package.json."""
    try:
        data = json.loads(package_json.read_text())
        return {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    except Exception:
        return None


def _check_file_for_framework(root: Path, pattern: str) -> str | None:
    """Check files for framework indicators."""
    files = list(root.rglob(pattern))
    for file in files:
        if "node_modules" in file.parts:
            continue

        try:
            content = file.read_text(encoding="utf-8")
            if "fastify" in content.lower():
                return "fastify"
            if "express" in content.lower():
                return "express"
        except Exception as exc:
            logger.debug("Error reading file %s: %s", file, exc)
            continue

    return None


class RouteDiscoveryAgent:
    """Analyzer that discovers web routes for E2E test generation.

    Supports:
    - JavaScript/TypeScript: Next.js, Express, Fastify
    - Python: Django, Flask, FastAPI
    - Go: Gin, Echo, Chi, Gorilla Mux

    The analyzer examines the project structure and framework configuration
    to identify all routes/endpoints that should have E2E tests.
    """

    name = "RouteDiscovery"
    description = "Discovers web routes for E2E test generation"

    def run(self, profile: ProjectProfile) -> RouteDiscoveryResult:
        """Discover routes based on detected frameworks.

        Args:
            profile: Project profile with detected frameworks.

        Returns:
            Route discovery result with all found routes.
        """
        routes: list[RouteInfo] = []
        framework = self._detect_web_framework(profile)

        if not framework:
            return RouteDiscoveryResult(
                root=profile.root,
                framework="unknown",
                routes=[],
            )

        # Dispatch to appropriate discovery function
        if framework == "nextjs":
            routes = discover_nextjs_routes(profile.root)
        elif framework == "express":
            routes = discover_express_routes(profile.root)
        elif framework == "fastify":
            routes = discover_fastify_routes(profile.root)
        elif framework == "django":
            routes = discover_django_routes(profile.root)
        elif framework == "flask":
            routes = discover_flask_routes(profile.root)
        elif framework == "fastapi":
            routes = discover_fastapi_routes(profile.root)
        elif framework in {"gin", "echo", "chi", "gorilla"}:
            routes = discover_go_routes(profile.root, framework)

        return RouteDiscoveryResult(
            root=profile.root,
            framework=framework,
            routes=routes,
        )

    def _detect_web_framework(self, profile: ProjectProfile) -> str | None:
        """Detect which web framework is used in the project.

        Args:
            profile: Project profile.

        Returns:
            Framework name or None if no web framework detected.
        """
        root = Path(profile.root)

        # Check for Next.js
        nextjs = _check_nextjs(root)
        if nextjs:
            return nextjs

        # Check for Python frameworks (Django, Flask, FastAPI)
        python_fw = _check_python_framework(root)
        if python_fw:
            return python_fw

        # Check for Go frameworks (Gin, Echo, Chi, Gorilla)
        go_fw = _check_go_framework(root)
        if go_fw:
            return go_fw

        # Check for Node.js frameworks (Express/Fastify)
        return _check_node_framework(root)


def _auto_detect_framework(root: Path) -> str | None:
    """Auto-detect the web framework used in the project.

    Args:
        root: Project root path.

    Returns:
        Framework name or None.
    """
    if (root / "next.config.js").exists() or (root / "pages").exists():
        return "nextjs"
    if (root / "manage.py").exists():
        return "django"
    if (root / "go.mod").exists():
        return _check_go_framework(root) or "gin"
    if (root / "package.json").exists():
        return "express"
    return _check_python_framework(root)


def _discover_for_framework(root: Path, framework: str) -> list[RouteInfo]:
    """Discover routes for a specific framework.

    Args:
        root: Project root path.
        framework: Framework name.

    Returns:
        List of discovered routes.
    """
    dispatch: dict[str, Callable[[Path, str], list[RouteInfo]]] = {
        "nextjs": lambda r, _fw: discover_nextjs_routes(r),
        "express": lambda r, _fw: discover_express_routes(r),
        "fastify": lambda r, _fw: discover_fastify_routes(r),
        "django": lambda r, _fw: discover_django_routes(r),
        "flask": lambda r, _fw: discover_flask_routes(r),
        "fastapi": lambda r, _fw: discover_fastapi_routes(r),
    }

    handler = dispatch.get(framework)
    if handler:
        return handler(root, framework)

    if framework in {"gin", "echo", "chi", "gorilla"}:
        return discover_go_routes(root, framework)

    return []


def discover_routes(project_root: str | Path, framework: str | None = None) -> RouteDiscoveryResult:
    """Convenience function to discover routes without using the agent.

    Args:
        project_root: Path to the project root.
        framework: Framework name (optional, will auto-detect if not provided).

    Returns:
        Route discovery result.
    """
    root = Path(project_root)

    if not framework:
        framework = _auto_detect_framework(root)

    routes = _discover_for_framework(root, framework) if framework else []

    return RouteDiscoveryResult(
        root=str(root),
        framework=framework or "unknown",
        routes=routes,
    )
