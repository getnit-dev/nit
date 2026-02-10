"""Tests for route discovery functionality."""

from __future__ import annotations

import json
from pathlib import Path

from nit.agents.analyzers.route_discovery import RouteDiscoveryAgent, discover_routes
from nit.agents.analyzers.routes.django import discover_django_routes
from nit.agents.analyzers.routes.express import discover_express_routes
from nit.agents.analyzers.routes.fastapi import discover_fastapi_routes
from nit.agents.analyzers.routes.flask import discover_flask_routes
from nit.agents.analyzers.routes.go import discover_go_routes
from nit.agents.analyzers.routes.nextjs import discover_nextjs_routes
from nit.models.profile import ProjectProfile
from nit.models.route import HTTPMethod, RouteType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_files(root: Path, rel_paths: list[str]) -> None:
    """Create empty files at the given relative paths under *root*."""
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


def _write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file at *root/rel*."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _write_package_json(root: Path, data: dict[str, object]) -> None:
    """Write a ``package.json`` to *root*."""
    _write_file(root, "package.json", json.dumps(data))


# ---------------------------------------------------------------------------
# Next.js Tests
# ---------------------------------------------------------------------------


class TestNextJsPagesRouter:
    """Tests for Next.js Pages Router route discovery."""

    def test_basic_page_route(self, tmp_path: Path) -> None:
        """Test basic page route: pages/about.tsx → /about."""
        _write_file(
            tmp_path,
            "pages/about.tsx",
            """
export default function About() {
  return <div>About</div>
}
""",
        )

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 1
        assert routes[0].path == "/about"
        assert routes[0].route_type == RouteType.PAGE
        assert HTTPMethod.GET in routes[0].methods

    def test_index_route(self, tmp_path: Path) -> None:
        """Test index route: pages/index.tsx → /."""
        _write_file(
            tmp_path,
            "pages/index.tsx",
            """
export default function Home() {
  return <div>Home</div>
}
""",
        )

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 1
        assert routes[0].path == "/"

    def test_dynamic_route(self, tmp_path: Path) -> None:
        """Test dynamic route: pages/posts/[id].tsx → /posts/:id."""
        _write_file(
            tmp_path,
            "pages/posts/[id].tsx",
            """
export default function Post() {
  return <div>Post</div>
}
""",
        )

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 1
        assert routes[0].path == "/posts/:id"
        assert "id" in routes[0].params

    def test_catch_all_route(self, tmp_path: Path) -> None:
        """Test catch-all route: pages/docs/[...slug].tsx → /docs/*slug."""
        _write_file(
            tmp_path,
            "pages/docs/[...slug].tsx",
            """
export default function Docs() {
  return <div>Docs</div>
}
""",
        )

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 1
        assert routes[0].path == "/docs/*slug"
        assert "slug" in routes[0].params

    def test_api_route(self, tmp_path: Path) -> None:
        """Test API route: pages/api/users.ts → /api/users."""
        _write_file(
            tmp_path,
            "pages/api/users.ts",
            """
export default function handler(req, res) {
  res.status(200).json({ users: [] })
}
""",
        )

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 1
        assert routes[0].path == "/api/users"
        assert routes[0].route_type == RouteType.API

    def test_nested_routes(self, tmp_path: Path) -> None:
        """Test nested routes."""
        _write_file(tmp_path, "pages/blog/index.tsx", "export default () => <div/>")
        _write_file(tmp_path, "pages/blog/[slug].tsx", "export default () => <div/>")

        routes = discover_nextjs_routes(tmp_path)
        paths = {r.path for r in routes}
        assert "/blog" in paths
        assert "/blog/:slug" in paths


class TestNextJsAppRouter:
    """Tests for Next.js App Router route discovery."""

    def test_basic_page_route(self, tmp_path: Path) -> None:
        """Test basic page route: app/about/page.tsx → /about."""
        _write_file(
            tmp_path,
            "app/about/page.tsx",
            """
export default function About() {
  return <div>About</div>
}
""",
        )

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 1
        assert routes[0].path == "/about"
        assert routes[0].framework == "nextjs-app"

    def test_root_page(self, tmp_path: Path) -> None:
        """Test root page: app/page.tsx → /."""
        _write_file(
            tmp_path,
            "app/page.tsx",
            """
export default function Home() {
  return <div>Home</div>
}
""",
        )

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 1
        assert routes[0].path == "/"

    def test_dynamic_route(self, tmp_path: Path) -> None:
        """Test dynamic route: app/posts/[id]/page.tsx → /posts/:id."""
        _write_file(
            tmp_path,
            "app/posts/[id]/page.tsx",
            """
export default function Post() {
  return <div>Post</div>
}
""",
        )

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 1
        assert routes[0].path == "/posts/:id"
        assert "id" in routes[0].params

    def test_route_handler(self, tmp_path: Path) -> None:
        """Test route handler: app/api/users/route.ts → /api/users."""
        _write_file(
            tmp_path,
            "app/api/users/route.ts",
            """
export async function GET() {
  return Response.json({ users: [] })
}

export async function POST(request) {
  return Response.json({ ok: true })
}
""",
        )

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 1
        assert routes[0].path == "/api/users"
        assert routes[0].route_type == RouteType.API
        assert HTTPMethod.GET in routes[0].methods
        assert HTTPMethod.POST in routes[0].methods

    def test_route_groups_ignored(self, tmp_path: Path) -> None:
        """Test route groups are ignored: app/(auth)/login/page.tsx → /login."""
        _write_file(
            tmp_path,
            "app/(auth)/login/page.tsx",
            """
export default function Login() {
  return <div>Login</div>
}
""",
        )

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 1
        assert routes[0].path == "/login"


# ---------------------------------------------------------------------------
# Express Tests
# ---------------------------------------------------------------------------


class TestExpressRouteDiscovery:
    """Tests for Express route discovery."""

    def test_basic_get_route(self, tmp_path: Path) -> None:
        """Test basic GET route."""
        _write_file(
            tmp_path,
            "app.js",
            """
const express = require('express');
const app = express();

app.get('/users', (req, res) => {
  res.json({ users: [] });
});
""",
        )

        routes = discover_express_routes(tmp_path)
        assert len(routes) >= 1
        user_route = next((r for r in routes if r.path == "/users"), None)
        assert user_route is not None
        assert HTTPMethod.GET in user_route.methods

    def test_multiple_http_methods(self, tmp_path: Path) -> None:
        """Test multiple HTTP methods on same path."""
        _write_file(
            tmp_path,
            "routes/api.js",
            """
router.get('/items', getItems);
router.post('/items', createItem);
router.delete('/items/:id', deleteItem);
""",
        )

        routes = discover_express_routes(tmp_path)
        paths = [r.path for r in routes]
        assert "/items" in paths
        assert "/items/:id" in paths

    def test_dynamic_parameters(self, tmp_path: Path) -> None:
        """Test dynamic route parameters."""
        _write_file(
            tmp_path,
            "app.js",
            """
app.get('/users/:userId/posts/:postId', handler);
""",
        )

        routes = discover_express_routes(tmp_path)
        route = next((r for r in routes if "userId" in r.path), None)
        assert route is not None
        assert "userId" in route.params
        assert "postId" in route.params


# ---------------------------------------------------------------------------
# Django Tests
# ---------------------------------------------------------------------------


class TestDjangoRouteDiscovery:
    """Tests for Django route discovery."""

    def test_basic_path_route(self, tmp_path: Path) -> None:
        """Test basic path() route."""
        _write_file(
            tmp_path,
            "urls.py",
            """
from django.urls import path
from . import views

urlpatterns = [
    path('about/', views.about),
    path('users/', views.user_list),
]
""",
        )

        routes = discover_django_routes(tmp_path)
        paths = [r.path for r in routes]
        assert "/about" in paths
        assert "/users" in paths

    def test_dynamic_path_route(self, tmp_path: Path) -> None:
        """Test dynamic path() route with parameters."""
        _write_file(
            tmp_path,
            "urls.py",
            """
from django.urls import path
from . import views

urlpatterns = [
    path('users/<int:id>/', views.user_detail),
    path('posts/<str:slug>/', views.post_detail),
]
""",
        )

        routes = discover_django_routes(tmp_path)
        assert len(routes) >= 2

        user_route = next((r for r in routes if "users" in r.path), None)
        assert user_route is not None
        assert "id" in user_route.params

        post_route = next((r for r in routes if "posts" in r.path), None)
        assert post_route is not None
        assert "slug" in post_route.params

    def test_re_path_route(self, tmp_path: Path) -> None:
        """Test re_path() regex route."""
        _write_file(
            tmp_path,
            "urls.py",
            r"""
from django.urls import re_path
from . import views

urlpatterns = [
    re_path(r'^articles/(?P<year>[0-9]{4})/$', views.year_archive),
]
""",
        )

        routes = discover_django_routes(tmp_path)
        assert len(routes) >= 1
        route = routes[0]
        assert "year" in route.params


# ---------------------------------------------------------------------------
# RouteDiscoveryAgent Tests
# ---------------------------------------------------------------------------


class TestRouteDiscoveryAgent:
    """Tests for the RouteDiscoveryAgent."""

    def test_nextjs_detection(self, tmp_path: Path) -> None:
        """Test automatic Next.js framework detection."""
        _write_file(tmp_path, "next.config.js", "module.exports = {}")
        _write_file(tmp_path, "pages/index.tsx", "export default () => <div/>")

        profile = ProjectProfile(root=str(tmp_path))
        agent = RouteDiscoveryAgent()
        result = agent.run(profile)

        assert result.framework == "nextjs"
        assert len(result.routes) >= 1

    def test_django_detection(self, tmp_path: Path) -> None:
        """Test automatic Django framework detection."""
        _write_file(tmp_path, "manage.py", "#!/usr/bin/env python")
        _write_file(
            tmp_path,
            "urls.py",
            """
from django.urls import path
urlpatterns = [path('', lambda: None)]
""",
        )

        profile = ProjectProfile(root=str(tmp_path))
        agent = RouteDiscoveryAgent()
        result = agent.run(profile)

        assert result.framework == "django"

    def test_express_detection(self, tmp_path: Path) -> None:
        """Test automatic Express framework detection."""
        _write_package_json(tmp_path, {"dependencies": {"express": "^4.0.0"}})
        _write_file(
            tmp_path,
            "app.js",
            """
const express = require('express');
app.get('/', handler);
""",
        )

        profile = ProjectProfile(root=str(tmp_path))
        agent = RouteDiscoveryAgent()
        result = agent.run(profile)

        assert result.framework == "express"


# ---------------------------------------------------------------------------
# Convenience Function Tests
# ---------------------------------------------------------------------------


class TestDiscoverRoutesFunction:
    """Tests for the discover_routes convenience function."""

    def test_auto_detect_nextjs(self, tmp_path: Path) -> None:
        """Test auto-detection of Next.js."""
        _write_file(tmp_path, "next.config.js", "module.exports = {}")
        _write_file(tmp_path, "pages/about.tsx", "export default () => <div/>")

        result = discover_routes(tmp_path)
        assert result.framework == "nextjs"
        assert len(result.routes) >= 1

    def test_explicit_framework(self, tmp_path: Path) -> None:
        """Test explicit framework specification."""
        _write_file(
            tmp_path,
            "urls.py",
            """
from django.urls import path
urlpatterns = [path('test/', lambda: None)]
""",
        )

        result = discover_routes(tmp_path, framework="django")
        assert result.framework == "django"
        assert len(result.routes) >= 1


# ---------------------------------------------------------------------------
# Edge Cases & Integration
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_project(self, tmp_path: Path) -> None:
        """Test route discovery on empty project."""
        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) == 0

    def test_no_framework_detected(self, tmp_path: Path) -> None:
        """Test when no framework is detected."""
        result = discover_routes(tmp_path)
        assert result.framework in {"unknown", "express"}  # May default to express
        assert len(result.routes) == 0 or result.framework == "express"

    def test_malformed_urls_file(self, tmp_path: Path) -> None:
        """Test handling of malformed Django urls.py."""
        _write_file(tmp_path, "urls.py", "this is not valid python {[")

        routes = discover_django_routes(tmp_path)
        # Should not crash, just return empty list
        assert isinstance(routes, list)

    def test_src_directory_variants(self, tmp_path: Path) -> None:
        """Test Next.js detection in src/ directory."""
        _write_file(tmp_path, "src/pages/index.tsx", "export default () => <div/>")

        routes = discover_nextjs_routes(tmp_path)
        assert len(routes) >= 1
        assert routes[0].path == "/"


# ---------------------------------------------------------------------------
# Flask Tests
# ---------------------------------------------------------------------------


class TestFlaskRouteDiscovery:
    """Tests for Flask route discovery."""

    def test_basic_flask_route(self, tmp_path: Path) -> None:
        """Test basic Flask route with @app.route."""
        _write_file(
            tmp_path,
            "app.py",
            """
from flask import Flask

app = Flask(__name__)

@app.route('/users')
def users():
    return {'users': []}

@app.route('/posts/<int:id>', methods=['GET', 'POST'])
def post_detail(id):
    return {'post': id}
""",
        )

        routes = discover_flask_routes(tmp_path)
        assert len(routes) >= 2

        users_route = next((r for r in routes if r.path == "/users"), None)
        assert users_route is not None
        assert HTTPMethod.GET in users_route.methods

        post_route = next((r for r in routes if "id" in r.params), None)
        assert post_route is not None
        assert "id" in post_route.params


# ---------------------------------------------------------------------------
# FastAPI Tests
# ---------------------------------------------------------------------------


class TestFastAPIRouteDiscovery:
    """Tests for FastAPI route discovery."""

    def test_basic_fastapi_route(self, tmp_path: Path) -> None:
        """Test basic FastAPI routes with HTTP method decorators."""
        _write_file(
            tmp_path,
            "main.py",
            """
from fastapi import FastAPI

app = FastAPI()

@app.get("/users")
async def get_users():
    return {"users": []}

@app.post("/users")
async def create_user():
    return {"created": True}

@app.get("/posts/{post_id}")
async def get_post(post_id: int):
    return {"post_id": post_id}
""",
        )

        routes = discover_fastapi_routes(tmp_path)
        assert len(routes) >= 3

        get_users = next(
            (r for r in routes if r.path == "/users" and HTTPMethod.GET in r.methods),
            None,
        )
        assert get_users is not None

        post_users = next(
            (r for r in routes if r.path == "/users" and HTTPMethod.POST in r.methods),
            None,
        )
        assert post_users is not None

        get_post = next((r for r in routes if "post_id" in r.params), None)
        assert get_post is not None


# ---------------------------------------------------------------------------
# Go Framework Tests
# ---------------------------------------------------------------------------


class TestGoRouteDiscovery:
    """Tests for Go framework route discovery."""

    def test_gin_routes(self, tmp_path: Path) -> None:
        """Test Gin route discovery."""
        _write_file(
            tmp_path,
            "main.go",
            """
package main

import "github.com/gin-gonic/gin"

func main() {
    r := gin.Default()
    r.GET("/users", getUsers)
    r.POST("/users/:id", updateUser)
}
""",
        )

        routes = discover_go_routes(tmp_path, "gin")
        assert len(routes) >= 2

        get_route = next(
            (r for r in routes if "/users" in r.path and HTTPMethod.GET in r.methods),
            None,
        )
        assert get_route is not None

    def test_chi_routes(self, tmp_path: Path) -> None:
        """Test Chi route discovery."""
        _write_file(
            tmp_path,
            "routes.go",
            """
package main

import "github.com/go-chi/chi/v5"

func setupRoutes() {
    r := chi.NewRouter()
    r.Get("/api/users", getUsers)
    r.Post("/api/users/{id}", updateUser)
}
""",
        )

        routes = discover_go_routes(tmp_path, "chi")
        assert len(routes) >= 2

        get_route = next((r for r in routes if "users" in r.path), None)
        assert get_route is not None
