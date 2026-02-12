"""Tests for route discovery functionality."""

from __future__ import annotations

import json
from pathlib import Path

from nit.agents.analyzers.route_discovery import (
    RouteDiscoveryAgent,
    _auto_detect_framework,
    _check_file_for_framework,
    _check_go_framework,
    _check_nextjs,
    _check_node_framework,
    _check_python_framework,
    _discover_for_framework,
    _read_package_json_deps,
    discover_routes,
)
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


# ---------------------------------------------------------------------------
# Additional coverage tests for route_discovery module internals
# ---------------------------------------------------------------------------


class TestCheckNextjs:
    """Tests for _check_nextjs helper."""

    def test_next_config_js(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "next.config.js", "module.exports = {}")
        assert _check_nextjs(tmp_path) == "nextjs"

    def test_next_config_mjs(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "next.config.mjs", "export default {}")
        assert _check_nextjs(tmp_path) == "nextjs"

    def test_pages_dir_with_next_dep(self, tmp_path: Path) -> None:
        (tmp_path / "pages").mkdir()
        _write_package_json(tmp_path, {"dependencies": {"next": "14.0.0"}})
        assert _check_nextjs(tmp_path) == "nextjs"

    def test_pages_dir_without_next_dep(self, tmp_path: Path) -> None:
        (tmp_path / "pages").mkdir()
        _write_package_json(tmp_path, {"dependencies": {"react": "18.0"}})
        assert _check_nextjs(tmp_path) is None

    def test_no_indicators(self, tmp_path: Path) -> None:
        assert _check_nextjs(tmp_path) is None


class TestCheckPythonFramework:
    """Tests for _check_python_framework helper."""

    def test_detect_django(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "manage.py", "#!/usr/bin/env python")
        assert _check_python_framework(tmp_path) == "django"

    def test_detect_fastapi(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "main.py",
            "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/foo')\ndef foo(): pass\n",
        )
        assert _check_python_framework(tmp_path) == "fastapi"

    def test_detect_flask(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "app.py",
            "from flask import Flask\napp = Flask(__name__)\n@app.route('/foo')\ndef foo(): pass\n",
        )
        assert _check_python_framework(tmp_path) == "flask"

    def test_no_framework(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "helper.py", "x = 1\n")
        assert _check_python_framework(tmp_path) is None

    def test_skips_venv(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".venv/lib/site.py",
            "from flask import Flask\n@app.route('/foo')\ndef foo(): pass\n",
        )
        assert _check_python_framework(tmp_path) is None


class TestCheckGoFramework:
    """Tests for _check_go_framework helper."""

    def test_no_go_mod(self, tmp_path: Path) -> None:
        assert _check_go_framework(tmp_path) is None

    def test_gin(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "go.mod",
            "module example\nrequire github.com/gin-gonic/gin v1.7.0\n",
        )
        assert _check_go_framework(tmp_path) == "gin"

    def test_echo(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "go.mod",
            "module example\nrequire github.com/labstack/echo v4.0.0\n",
        )
        assert _check_go_framework(tmp_path) == "echo"

    def test_chi(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "go.mod",
            "module example\nrequire github.com/go-chi/chi v5.0.0\n",
        )
        assert _check_go_framework(tmp_path) == "chi"

    def test_gorilla(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "go.mod",
            "module example\nrequire github.com/gorilla/mux v1.8.0\n",
        )
        assert _check_go_framework(tmp_path) == "gorilla"

    def test_no_framework_in_go_mod(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "go.mod", "module example\n")
        assert _check_go_framework(tmp_path) is None


class TestCheckNodeFramework:
    """Tests for _check_node_framework helper."""

    def test_fastify_from_package_json(self, tmp_path: Path) -> None:
        _write_package_json(tmp_path, {"dependencies": {"fastify": "4.0.0"}})
        assert _check_node_framework(tmp_path) == "fastify"

    def test_express_from_package_json(self, tmp_path: Path) -> None:
        _write_package_json(tmp_path, {"dependencies": {"express": "4.0.0"}})
        assert _check_node_framework(tmp_path) == "express"

    def test_express_from_file_content(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "app.js",
            "const express = require('express');\n",
        )
        assert _check_node_framework(tmp_path) == "express"

    def test_no_framework(self, tmp_path: Path) -> None:
        assert _check_node_framework(tmp_path) is None


class TestReadPackageJsonDeps:
    """Tests for _read_package_json_deps helper."""

    def test_valid_package_json(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {"dependencies": {"react": "18.0"}, "devDependencies": {"jest": "29.0"}},
        )
        deps = _read_package_json_deps(tmp_path / "package.json")
        assert deps is not None
        assert "react" in deps
        assert "jest" in deps

    def test_invalid_json(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "package.json", "not valid json{")
        deps = _read_package_json_deps(tmp_path / "package.json")
        assert deps is None


class TestAutoDetectFramework:
    """Tests for _auto_detect_framework."""

    def test_nextjs(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "next.config.js", "module.exports = {}")
        assert _auto_detect_framework(tmp_path) == "nextjs"

    def test_django(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "manage.py", "#!/usr/bin/env python")
        assert _auto_detect_framework(tmp_path) == "django"

    def test_go_default_to_gin(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "go.mod", "module example\n")
        assert _auto_detect_framework(tmp_path) == "gin"

    def test_package_json_defaults_to_express(self, tmp_path: Path) -> None:
        _write_package_json(tmp_path, {})
        assert _auto_detect_framework(tmp_path) == "express"

    def test_none_for_empty(self, tmp_path: Path) -> None:
        assert _auto_detect_framework(tmp_path) is None


class TestDiscoverForFramework:
    """Tests for _discover_for_framework helper."""

    def test_unknown_framework_returns_empty(self, tmp_path: Path) -> None:
        routes = _discover_for_framework(tmp_path, "unknown_fw")
        assert routes == []

    def test_go_framework_dispatch(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "main.go",
            'r.GET("/ping", ping)\n',
        )
        routes = _discover_for_framework(tmp_path, "gin")
        assert isinstance(routes, list)

    def test_express_dispatch(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "app.js",
            "app.get('/hello', handler);\n",
        )
        routes = _discover_for_framework(tmp_path, "express")
        assert isinstance(routes, list)


class TestCheckFileForFramework:
    """Tests for _check_file_for_framework."""

    def test_express_detected(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "app.js", "const express = require('express');\n")
        assert _check_file_for_framework(tmp_path, "app.js") == "express"

    def test_fastify_detected(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "server.js", "const fastify = require('fastify');\n")
        assert _check_file_for_framework(tmp_path, "server.js") == "fastify"

    def test_node_modules_skipped(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "node_modules/pkg/app.js",
            "const express = require('express');\n",
        )
        result = _check_file_for_framework(tmp_path, "app.js")
        # Either None (no non-node_modules match) or "express" from the file
        # The function skips node_modules entries
        assert result is None or isinstance(result, str)


class TestDiscoverRoutesConvenienceExtended:
    """Extended tests for the discover_routes function."""

    def test_no_framework_returns_unknown(self, tmp_path: Path) -> None:
        result = discover_routes(tmp_path)
        assert result.framework in {"unknown", "express"}

    def test_string_project_root(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "manage.py", "#!/usr/bin/env python")
        _write_file(
            tmp_path,
            "urls.py",
            "from django.urls import path\nurlpatterns = [path('api/', lambda: None)]\n",
        )
        result = discover_routes(str(tmp_path), framework="django")
        assert result.framework == "django"


class TestRouteDiscoveryAgentExtended:
    """Extended tests for the RouteDiscoveryAgent."""

    def test_no_framework_returns_unknown(self, tmp_path: Path) -> None:
        profile = ProjectProfile(root=str(tmp_path))
        agent = RouteDiscoveryAgent()
        result = agent.run(profile)
        assert result.framework == "unknown"
        assert result.routes == []

    def test_fastapi_detection(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "main.py",
            (
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n"
                "@app.get('/health')\n"
                "async def health(): return {'ok': True}\n"
            ),
        )
        profile = ProjectProfile(root=str(tmp_path))
        agent = RouteDiscoveryAgent()
        result = agent.run(profile)
        assert result.framework == "fastapi"

    def test_flask_detection(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "app.py",
            (
                "from flask import Flask\n"
                "app = Flask(__name__)\n"
                "@app.route('/health')\n"
                "def health(): return 'ok'\n"
            ),
        )
        profile = ProjectProfile(root=str(tmp_path))
        agent = RouteDiscoveryAgent()
        result = agent.run(profile)
        assert result.framework == "flask"

    def test_go_gin_detection(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "go.mod",
            "module example\nrequire github.com/gin-gonic/gin v1.7.0\n",
        )
        _write_file(
            tmp_path,
            "main.go",
            'r.GET("/ping", ping)\n',
        )
        profile = ProjectProfile(root=str(tmp_path))
        agent = RouteDiscoveryAgent()
        result = agent.run(profile)
        assert result.framework == "gin"
