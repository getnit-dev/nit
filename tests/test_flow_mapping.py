"""Tests for the FlowMapper (agents/analyzers/flow_mapping.py).

Covers:
- FlowMapper.map_flows: identification of auth, dashboard, CRUD, API flows
- _identify_auth_flow with/without login/dashboard routes
- _identify_dashboard_flow
- _identify_crud_flows with various resource patterns
- _build_crud_flow_for_resource with enough/insufficient CRUD ops
- _collect_crud_routes canonical ordering
- _identify_api_flows grouping by resource
- _extract_resource_name with prefixes, parameters, empty paths
- UserFlow.to_dict serialization
- FlowMappingResult.get_high_priority_flows / get_auth_flows / to_dict
"""

from __future__ import annotations

from nit.agents.analyzers.flow_mapping import (
    FlowMapper,
    FlowMappingResult,
    UserFlow,
)
from nit.models.route import (
    HTTPMethod,
    RouteDiscoveryResult,
    RouteInfo,
    RouteType,
)

# ── Helpers ───────────────────────────────────────────────────────


def _route(
    path: str,
    route_type: RouteType = RouteType.PAGE,
    methods: list[HTTPMethod] | None = None,
    *,
    auth_required: bool = False,
) -> RouteInfo:
    return RouteInfo(
        path=path,
        route_type=route_type,
        methods=methods or [HTTPMethod.GET],
        auth_required=auth_required,
    )


def _discovery(routes: list[RouteInfo], framework: str = "express") -> RouteDiscoveryResult:
    return RouteDiscoveryResult(root="/app", framework=framework, routes=routes)


# ── UserFlow.to_dict ──────────────────────────────────────────────


class TestUserFlowToDict:
    def test_serialization(self) -> None:
        route = _route("/login", methods=[HTTPMethod.GET, HTTPMethod.POST])
        flow = UserFlow(
            name="Auth",
            description="Authentication flow",
            routes=[route],
            priority=100,
            requires_auth=False,
        )
        d = flow.to_dict()
        assert d["name"] == "Auth"
        assert d["priority"] == 100
        assert d["requires_auth"] is False
        routes_list = d["routes"]
        assert isinstance(routes_list, list)
        assert len(routes_list) == 1
        assert routes_list[0]["path"] == "/login"

    def test_empty_routes(self) -> None:
        flow = UserFlow(name="Empty", description="No routes")
        d = flow.to_dict()
        assert d["routes"] == []


# ── FlowMappingResult ────────────────────────────────────────────


class TestFlowMappingResult:
    def test_get_high_priority_flows(self) -> None:
        flows = [
            UserFlow(name="High", description="high", priority=90),
            UserFlow(name="Low", description="low", priority=50),
        ]
        result = FlowMappingResult(flows=flows)
        high = result.get_high_priority_flows()
        assert len(high) == 1
        assert high[0].name == "High"

    def test_get_auth_flows(self) -> None:
        flows = [
            UserFlow(name="Auth", description="auth", requires_auth=True),
            UserFlow(name="Public", description="pub", requires_auth=False),
        ]
        result = FlowMappingResult(flows=flows)
        auth = result.get_auth_flows()
        assert len(auth) == 1
        assert auth[0].name == "Auth"

    def test_to_dict(self) -> None:
        result = FlowMappingResult(flows=[UserFlow(name="F", description="d", priority=85)])
        d = result.to_dict()
        assert d["total_flows"] == 1
        assert d["high_priority_flows"] == 1

    def test_empty_result(self) -> None:
        result = FlowMappingResult()
        assert result.get_high_priority_flows() == []
        assert result.get_auth_flows() == []
        d = result.to_dict()
        assert d["total_flows"] == 0


# ── _extract_resource_name ────────────────────────────────────────


class TestExtractResourceName:
    def test_simple_path(self) -> None:
        mapper = FlowMapper()
        assert mapper._extract_resource_name("/users") == "users"

    def test_nested_path(self) -> None:
        mapper = FlowMapper()
        assert mapper._extract_resource_name("/users/:id") == "users"

    def test_api_prefix(self) -> None:
        mapper = FlowMapper()
        assert mapper._extract_resource_name("/api/products") == "products"

    def test_v1_prefix(self) -> None:
        mapper = FlowMapper()
        assert mapper._extract_resource_name("/v1/orders") == "orders"

    def test_admin_prefix(self) -> None:
        mapper = FlowMapper()
        assert mapper._extract_resource_name("/admin/settings") == "settings"

    def test_parameter_only_returns_none(self) -> None:
        mapper = FlowMapper()
        assert mapper._extract_resource_name("/:id") is None

    def test_curly_brace_parameter_returns_none(self) -> None:
        mapper = FlowMapper()
        assert mapper._extract_resource_name("/{id}") is None

    def test_root_path_returns_empty_string(self) -> None:
        mapper = FlowMapper()
        # "/" stripped to "" → segments = [""] → first segment is ""
        assert mapper._extract_resource_name("/") == ""

    def test_trailing_slashes_stripped(self) -> None:
        mapper = FlowMapper()
        assert mapper._extract_resource_name("/users/") == "users"


# ── _identify_auth_flow ──────────────────────────────────────────


class TestIdentifyAuthFlow:
    def test_finds_login_route(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/login"), _route("/dashboard", auth_required=True)]
        result = mapper._identify_auth_flow(_discovery(routes))
        assert result is not None
        assert result.name == "Authentication Flow"
        assert result.priority == 100
        assert len(result.routes) == 2

    def test_signin_keyword(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/signin")]
        result = mapper._identify_auth_flow(_discovery(routes))
        assert result is not None

    def test_no_login_returns_none(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/about"), _route("/contact")]
        result = mapper._identify_auth_flow(_discovery(routes))
        assert result is None

    def test_login_without_dashboard(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/login")]
        result = mapper._identify_auth_flow(_discovery(routes))
        assert result is not None
        assert len(result.routes) == 1

    def test_fallback_to_first_authenticated_page(self) -> None:
        mapper = FlowMapper()
        routes = [
            _route("/login"),
            _route("/profile", auth_required=True),
        ]
        result = mapper._identify_auth_flow(_discovery(routes))
        assert result is not None
        assert len(result.routes) == 2
        assert result.routes[1].path == "/profile"


# ── _identify_dashboard_flow ──────────────────────────────────────


class TestIdentifyDashboardFlow:
    def test_finds_dashboard(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/dashboard", auth_required=True)]
        result = mapper._identify_dashboard_flow(_discovery(routes))
        assert result is not None
        assert result.name == "Dashboard Navigation"
        assert result.priority == 90
        assert result.requires_auth is True

    def test_finds_home(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/home")]
        result = mapper._identify_dashboard_flow(_discovery(routes))
        assert result is not None

    def test_no_dashboard_returns_none(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/login"), _route("/users")]
        result = mapper._identify_dashboard_flow(_discovery(routes))
        assert result is None


# ── _identify_crud_flows ──────────────────────────────────────────


class TestIdentifyCRUDFlows:
    def test_full_crud(self) -> None:
        mapper = FlowMapper()
        routes = [
            _route("/users"),
            _route("/users/new"),
            _route("/users/:id/edit"),
            _route("/users/:id/delete"),
        ]
        flows = mapper._identify_crud_flows(_discovery(routes))
        assert len(flows) == 1
        assert "users" in flows[0].name.lower()
        assert flows[0].priority == 70

    def test_partial_crud_with_minimum_ops(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/users"), _route("/users/new")]
        flows = mapper._identify_crud_flows(_discovery(routes))
        assert len(flows) == 1

    def test_insufficient_crud_ops(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/users")]
        flows = mapper._identify_crud_flows(_discovery(routes))
        assert flows == []

    def test_multiple_resources(self) -> None:
        mapper = FlowMapper()
        routes = [
            _route("/users"),
            _route("/users/new"),
            _route("/products"),
            _route("/products/new"),
        ]
        flows = mapper._identify_crud_flows(_discovery(routes))
        assert len(flows) == 2
        names_lower = [f.name.lower() for f in flows]
        assert any("users" in n for n in names_lower)
        assert any("products" in n for n in names_lower)

    def test_auth_required_propagated(self) -> None:
        mapper = FlowMapper()
        routes = [
            _route("/users", auth_required=True),
            _route("/users/new", auth_required=True),
        ]
        flows = mapper._identify_crud_flows(_discovery(routes))
        assert len(flows) == 1
        assert flows[0].requires_auth is True


# ── _collect_crud_routes ──────────────────────────────────────────


class TestCollectCRUDRoutes:
    def test_canonical_order(self) -> None:
        mapper = FlowMapper()
        routes = [
            _route("/users/:id/delete"),
            _route("/users/new"),
            _route("/users"),
            _route("/users/:id/edit"),
        ]
        ordered = mapper._collect_crud_routes("users", routes)
        paths = [r.path for r in ordered]
        # Should be list, create, edit, delete
        assert paths[0] == "/users"
        assert "new" in paths[1]
        assert "edit" in paths[2]
        assert "delete" in paths[3]

    def test_missing_some_operations(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/users"), _route("/users/new")]
        ordered = mapper._collect_crud_routes("users", routes)
        assert len(ordered) == 2


# ── _identify_api_flows ──────────────────────────────────────────


class TestIdentifyAPIFlows:
    def test_groups_api_routes(self) -> None:
        mapper = FlowMapper()
        routes = [
            _route("/api/users", route_type=RouteType.API),
            _route("/api/users/:id", route_type=RouteType.API),
            _route("/api/products", route_type=RouteType.API),
        ]
        flows = mapper._identify_api_flows(_discovery(routes))
        assert len(flows) == 2
        assert all(f.priority == 60 for f in flows)

    def test_no_api_routes(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/home")]
        flows = mapper._identify_api_flows(_discovery(routes))
        assert flows == []

    def test_auth_propagated_in_api(self) -> None:
        mapper = FlowMapper()
        routes = [_route("/api/secret", route_type=RouteType.API, auth_required=True)]
        flows = mapper._identify_api_flows(_discovery(routes))
        assert len(flows) == 1
        assert flows[0].requires_auth is True


# ── map_flows integration ────────────────────────────────────────


class TestMapFlows:
    def test_combined_flows_sorted_by_priority(self) -> None:
        mapper = FlowMapper()
        routes = [
            _route("/login"),
            _route("/dashboard", auth_required=True),
            _route("/users"),
            _route("/users/new"),
            _route("/api/products", route_type=RouteType.API),
        ]
        result = mapper.map_flows(_discovery(routes))
        priorities = [f.priority for f in result.flows]
        assert priorities == sorted(priorities, reverse=True)

    def test_empty_routes(self) -> None:
        mapper = FlowMapper()
        result = mapper.map_flows(_discovery([]))
        assert result.flows == []

    def test_result_type(self) -> None:
        mapper = FlowMapper()
        result = mapper.map_flows(_discovery([]))
        assert isinstance(result, FlowMappingResult)
