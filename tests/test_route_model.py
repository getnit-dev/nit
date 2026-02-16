"""Tests for route models (src/nit/models/route.py)."""

from __future__ import annotations

from nit.models.route import (
    HTTPMethod,
    RouteDiscoveryResult,
    RouteHandler,
    RouteInfo,
    RouteType,
)

# ── RouteInfo.to_dict ───────────────────────────────────────────


def test_route_info_to_dict_with_handler() -> None:
    handler = RouteHandler(
        file_path="/src/app.py",
        name="get_users",
        start_line=10,
        end_line=20,
        is_async=True,
        dependencies=["sqlalchemy"],
    )
    route = RouteInfo(
        path="/users",
        route_type=RouteType.API,
        methods=[HTTPMethod.GET, HTTPMethod.POST],
        handler=handler,
        params=["id"],
        framework="fastapi",
    )
    d = route.to_dict()
    assert d["path"] == "/users"
    assert d["route_type"] == "api"
    assert d["methods"] == ["GET", "POST"]
    assert d["params"] == ["id"]
    assert d["framework"] == "fastapi"
    handler_dict = d["handler"]
    assert handler_dict is not None
    assert isinstance(handler_dict, dict)
    assert handler_dict["name"] == "get_users"
    assert handler_dict["is_async"] is True


def test_route_info_to_dict_without_handler() -> None:
    route = RouteInfo(path="/home", route_type=RouteType.PAGE)
    d = route.to_dict()
    assert d["handler"] is None


# ── RouteDiscoveryResult ────────────────────────────────────────


def test_route_discovery_result_to_dict() -> None:
    result = RouteDiscoveryResult(
        root="/project",
        framework="express",
        routes=[
            RouteInfo(path="/api/users", route_type=RouteType.API),
            RouteInfo(path="/home", route_type=RouteType.PAGE),
        ],
    )
    d = result.to_dict()
    assert d["root"] == "/project"
    assert d["framework"] == "express"
    routes = d["routes"]
    assert isinstance(routes, list)
    assert len(routes) == 2


def test_get_page_routes() -> None:
    result = RouteDiscoveryResult(
        root="/project",
        framework="next",
        routes=[
            RouteInfo(path="/api/users", route_type=RouteType.API),
            RouteInfo(path="/home", route_type=RouteType.PAGE),
            RouteInfo(path="/about", route_type=RouteType.PAGE),
        ],
    )
    pages = result.get_page_routes()
    assert len(pages) == 2
    assert all(r.route_type == RouteType.PAGE for r in pages)


def test_get_dynamic_routes() -> None:
    result = RouteDiscoveryResult(
        root="/project",
        framework="express",
        routes=[
            RouteInfo(path="/users/:id", route_type=RouteType.API, params=["id"]),
            RouteInfo(path="/home", route_type=RouteType.PAGE),
            RouteInfo(
                path="/posts/:slug/comments/:cid",
                route_type=RouteType.API,
                params=["slug", "cid"],
            ),
        ],
    )
    dynamic = result.get_dynamic_routes()
    assert len(dynamic) == 2
    assert all(r.params for r in dynamic)
