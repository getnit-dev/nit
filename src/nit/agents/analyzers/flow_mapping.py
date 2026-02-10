"""Flow mapping — identify critical user paths through the application.

Analyzes discovered routes to identify common user flows and critical paths
that should be tested end-to-end. Examples:
- Authentication flow: login → dashboard
- CRUD flow: list → create → edit → delete
- Checkout flow: cart → shipping → payment → confirmation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nit.models.route import RouteDiscoveryResult, RouteInfo

logger = logging.getLogger(__name__)

# Constants
HIGH_PRIORITY_THRESHOLD = 80
MIN_CRUD_OPERATIONS = 2


@dataclass
class UserFlow:
    """Represents a sequence of routes forming a user workflow."""

    name: str
    """Human-readable name for this flow (e.g., 'Authentication Flow')."""

    description: str
    """Description of what this flow represents."""

    routes: list[RouteInfo] = field(default_factory=list)
    """Ordered sequence of routes in this flow."""

    priority: int = 0
    """Priority level (higher = more critical, should be tested first)."""

    requires_auth: bool = False
    """Whether this flow requires authentication."""

    def to_dict(self) -> dict[str, object]:
        """Serialize to JSON-compatible dict."""
        return {
            "name": self.name,
            "description": self.description,
            "routes": [
                {"path": r.path, "methods": [m.value for m in r.methods]} for r in self.routes
            ],
            "priority": self.priority,
            "requires_auth": self.requires_auth,
        }


@dataclass
class FlowMappingResult:
    """Result of flow mapping analysis."""

    flows: list[UserFlow] = field(default_factory=list)
    """Identified user flows."""

    def get_high_priority_flows(self) -> list[UserFlow]:
        """Get flows with priority >= HIGH_PRIORITY_THRESHOLD."""
        return [f for f in self.flows if f.priority >= HIGH_PRIORITY_THRESHOLD]

    def get_auth_flows(self) -> list[UserFlow]:
        """Get flows that require authentication."""
        return [f for f in self.flows if f.requires_auth]

    def to_dict(self) -> dict[str, object]:
        """Serialize to JSON-compatible dict."""
        return {
            "flows": [f.to_dict() for f in self.flows],
            "total_flows": len(self.flows),
            "high_priority_flows": len(self.get_high_priority_flows()),
        }


class FlowMapper:
    """Analyzes routes to identify critical user flows."""

    def map_flows(self, discovery_result: RouteDiscoveryResult) -> FlowMappingResult:
        """Identify user flows from discovered routes.

        Args:
            discovery_result: Result from RouteDiscovery

        Returns:
            FlowMappingResult with identified flows
        """
        flows: list[UserFlow] = []

        # Identify authentication flow
        auth_flow = self._identify_auth_flow(discovery_result)
        if auth_flow:
            flows.append(auth_flow)

        # Identify dashboard/home flow
        dashboard_flow = self._identify_dashboard_flow(discovery_result)
        if dashboard_flow:
            flows.append(dashboard_flow)

        # Identify CRUD flows for each resource
        crud_flows = self._identify_crud_flows(discovery_result)
        flows.extend(crud_flows)

        # Identify API flows
        api_flows = self._identify_api_flows(discovery_result)
        flows.extend(api_flows)

        # Sort by priority (descending)
        flows.sort(key=lambda f: f.priority, reverse=True)

        logger.info("Identified %d user flows", len(flows))
        return FlowMappingResult(flows=flows)

    def _identify_auth_flow(self, discovery_result: RouteDiscoveryResult) -> UserFlow | None:
        """Identify authentication-related flows."""
        auth_keywords = ["login", "signin", "auth", "authenticate"]
        dashboard_keywords = ["dashboard", "home", "index"]

        # Find login route
        login_route = None
        for route in discovery_result.routes:
            if any(keyword in route.path.lower() for keyword in auth_keywords):
                login_route = route
                break

        if not login_route:
            return None

        # Find dashboard/home route
        dashboard_route = None
        for route in discovery_result.routes:
            if route.auth_required and any(
                keyword in route.path.lower() for keyword in dashboard_keywords
            ):
                dashboard_route = route
                break

        # If no specific dashboard found, use first authenticated page route
        if not dashboard_route:
            for route in discovery_result.routes:
                if route.auth_required and route.route_type.value == "page":
                    dashboard_route = route
                    break

        routes = [login_route]
        if dashboard_route:
            routes.append(dashboard_route)

        return UserFlow(
            name="Authentication Flow",
            description="User login and navigation to authenticated area",
            routes=routes,
            priority=100,  # Highest priority
            requires_auth=False,  # The flow itself creates auth
        )

    def _identify_dashboard_flow(self, discovery_result: RouteDiscoveryResult) -> UserFlow | None:
        """Identify dashboard navigation flow."""
        dashboard_keywords = ["dashboard", "home", "index"]

        dashboard_route = None
        for route in discovery_result.routes:
            if any(keyword in route.path.lower() for keyword in dashboard_keywords):
                dashboard_route = route
                break

        if not dashboard_route:
            return None

        return UserFlow(
            name="Dashboard Navigation",
            description="Access and navigate dashboard",
            routes=[dashboard_route],
            priority=90,
            requires_auth=dashboard_route.auth_required,
        )

    def _identify_crud_flows(self, discovery_result: RouteDiscoveryResult) -> list[UserFlow]:
        """Identify CRUD flows for each resource.

        Groups routes by resource (e.g., /users, /users/:id, /users/new)
        and creates flows for common CRUD patterns.
        """
        flows: list[UserFlow] = []

        # Group routes by resource
        resource_routes: dict[str, list[RouteInfo]] = {}
        for route in discovery_result.routes:
            resource = self._extract_resource_name(route.path)
            if resource:
                resource_routes.setdefault(resource, []).append(route)

        # Create flows for each resource
        for resource, routes in resource_routes.items():
            crud_flow = self._build_crud_flow_for_resource(resource, routes)
            if crud_flow:
                flows.append(crud_flow)

        return flows

    def _build_crud_flow_for_resource(
        self, resource: str, routes: list[RouteInfo]
    ) -> UserFlow | None:
        """Build a CRUD flow for a specific resource if it has enough operations."""
        # Check if we have CRUD operations
        has_list = any(r.path.endswith(resource) or r.path.endswith(f"/{resource}") for r in routes)
        has_create = any("create" in r.path.lower() or "new" in r.path.lower() for r in routes)
        has_update = any("edit" in r.path.lower() or "update" in r.path.lower() for r in routes)
        has_delete = any("delete" in r.path.lower() for r in routes)

        # If we have at least MIN_CRUD_OPERATIONS, create a flow
        crud_count = sum([has_list, has_create, has_update, has_delete])
        if crud_count < MIN_CRUD_OPERATIONS:
            return None

        # Order: list → create → edit → delete
        ordered_routes = self._collect_crud_routes(resource, routes)

        if not ordered_routes:
            return None

        auth_required = any(r.auth_required for r in ordered_routes)
        return UserFlow(
            name=f"{resource.title()} CRUD Flow",
            description=f"Create, read, update, delete {resource}",
            routes=ordered_routes,
            priority=70,
            requires_auth=auth_required,
        )

    def _collect_crud_routes(self, resource: str, routes: list[RouteInfo]) -> list[RouteInfo]:
        """Collect CRUD routes in canonical order (list, create, edit, delete)."""
        ordered_routes = []

        # Add list route
        for r in routes:
            if r.path.endswith(resource) or r.path.endswith(f"/{resource}"):
                ordered_routes.append(r)
                break

        # Add create route
        for r in routes:
            if "create" in r.path.lower() or "new" in r.path.lower():
                ordered_routes.append(r)
                break

        # Add edit route
        for r in routes:
            if "edit" in r.path.lower() or "update" in r.path.lower():
                ordered_routes.append(r)
                break

        # Add delete route
        for r in routes:
            if "delete" in r.path.lower():
                ordered_routes.append(r)
                break

        return ordered_routes

    def _identify_api_flows(self, discovery_result: RouteDiscoveryResult) -> list[UserFlow]:
        """Identify API endpoint flows."""
        api_routes = discovery_result.get_api_routes()

        if not api_routes:
            return []

        flows: list[UserFlow] = []

        # Group API routes by resource
        resource_routes: dict[str, list[RouteInfo]] = {}
        for route in api_routes:
            resource = self._extract_resource_name(route.path)
            if resource:
                resource_routes.setdefault(resource, []).append(route)

        # Create a flow for each API resource
        for resource, routes in resource_routes.items():
            auth_required = any(r.auth_required for r in routes)
            flows.append(
                UserFlow(
                    name=f"{resource.title()} API",
                    description=f"API operations for {resource}",
                    routes=routes,
                    priority=60,
                    requires_auth=auth_required,
                )
            )

        return flows

    def _extract_resource_name(self, path: str) -> str | None:
        """Extract the primary resource name from a route path.

        Examples:
        - /users → users
        - /api/users → users
        - /users/:id → users
        - /users/:id/edit → users
        """
        # Remove leading/trailing slashes
        path = path.strip("/")

        # Split by slashes
        segments = path.split("/")

        # Remove common prefixes
        if segments and segments[0] in ("api", "v1", "v2", "admin"):
            segments = segments[1:]

        if not segments:
            return None

        # Return the first segment (the resource)
        resource = segments[0]

        # Skip if it looks like a parameter
        if resource.startswith((":", "{")):
            return None

        return resource
