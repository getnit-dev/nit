"""Route data models for E2E test generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RouteType(Enum):
    """Type of route/endpoint."""

    PAGE = "page"
    API = "api"
    STATIC = "static"
    DYNAMIC = "dynamic"


class HTTPMethod(Enum):
    """HTTP methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    ANY = "ANY"


@dataclass
class RouteHandler:
    """Handler function/component for a route."""

    file_path: str
    """Absolute path to the file containing the handler."""

    name: str | None = None
    """Function/component name, if identifiable."""

    start_line: int = 0
    """Starting line number in the file."""

    end_line: int = 0
    """Ending line number in the file."""

    is_async: bool = False
    """Whether the handler is async."""

    dependencies: list[str] = field(default_factory=list)
    """Imported modules/dependencies used by the handler."""


@dataclass
class RouteInfo:
    """Information about a discovered route."""

    path: str
    """Route path (e.g., /users/:id or /api/posts)."""

    route_type: RouteType
    """Type of route."""

    methods: list[HTTPMethod] = field(default_factory=list)
    """Supported HTTP methods."""

    handler: RouteHandler | None = None
    """Handler function/component information."""

    params: list[str] = field(default_factory=list)
    """Dynamic parameters in the route (e.g., ['id', 'slug'])."""

    framework: str = ""
    """Framework that defined this route (e.g., 'nextjs', 'express', 'django')."""

    middleware: list[str] = field(default_factory=list)
    """Middleware applied to this route."""

    auth_required: bool = False
    """Whether authentication is required for this route."""

    def to_dict(self) -> dict[str, object]:
        """Serialize to JSON-compatible dict."""
        return {
            "path": self.path,
            "route_type": self.route_type.value,
            "methods": [m.value for m in self.methods],
            "params": self.params,
            "framework": self.framework,
            "middleware": self.middleware,
            "auth_required": self.auth_required,
            "handler": (
                {
                    "file_path": self.handler.file_path,
                    "name": self.handler.name,
                    "start_line": self.handler.start_line,
                    "end_line": self.handler.end_line,
                    "is_async": self.handler.is_async,
                    "dependencies": self.handler.dependencies,
                }
                if self.handler
                else None
            ),
        }


@dataclass
class RouteDiscoveryResult:
    """Result of route discovery for a project."""

    root: str
    """Project root directory."""

    framework: str
    """Detected web framework."""

    routes: list[RouteInfo] = field(default_factory=list)
    """Discovered routes."""

    def to_dict(self) -> dict[str, object]:
        """Serialize to JSON-compatible dict."""
        return {
            "root": self.root,
            "framework": self.framework,
            "routes": [r.to_dict() for r in self.routes],
        }

    def get_api_routes(self) -> list[RouteInfo]:
        """Get all API routes."""
        return [r for r in self.routes if r.route_type == RouteType.API]

    def get_page_routes(self) -> list[RouteInfo]:
        """Get all page routes."""
        return [r for r in self.routes if r.route_type == RouteType.PAGE]

    def get_dynamic_routes(self) -> list[RouteInfo]:
        """Get all dynamic routes (with parameters)."""
        return [r for r in self.routes if r.params]
