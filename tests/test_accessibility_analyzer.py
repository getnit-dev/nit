"""Tests for the accessibility analyzer and builder.

Covers:
- Detecting frontend frameworks from package.json dependencies
- Detecting frameworks from config files
- Detecting HTML files in project
- Returning empty results for non-frontend projects
- Recommending appropriate tools based on detected frameworks
- Analyzing accessibility configs and routes
- Generating test cases with the AccessibilityTestBuilder
- Test name slugification
- Handling empty analysis results
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nit.agents.analyzers.accessibility import (
    AccessibilityAnalysisResult,
    analyze_accessibility,
    detect_frontend_project,
)
from nit.agents.builders.accessibility import AccessibilityTestBuilder, AccessibilityTestCase

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture()
def react_project(tmp_path: Path) -> Path:
    """Create a project with React in package.json."""
    package_data = {
        "name": "my-react-app",
        "dependencies": {
            "react": "^18.0.0",
            "react-dom": "^18.0.0",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(package_data), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def vue_project(tmp_path: Path) -> Path:
    """Create a project with Vue in package.json."""
    package_data = {
        "name": "my-vue-app",
        "dependencies": {
            "vue": "^3.0.0",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(package_data), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def angular_project(tmp_path: Path) -> Path:
    """Create a project with Angular in package.json."""
    package_data = {
        "name": "my-angular-app",
        "dependencies": {
            "@angular/core": "^16.0.0",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(package_data), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def nextjs_project(tmp_path: Path) -> Path:
    """Create a project with Next.js in package.json and pages directory."""
    package_data = {
        "name": "my-next-app",
        "dependencies": {
            "next": "^14.0.0",
            "react": "^18.0.0",
            "react-dom": "^18.0.0",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(package_data), encoding="utf-8")
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.tsx").write_text("export default function Home() {}", encoding="utf-8")
    (pages_dir / "about.tsx").write_text("export default function About() {}", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def html_project(tmp_path: Path) -> Path:
    """Create a project with HTML files but no framework."""
    (tmp_path / "index.html").write_text("<html><body>Hello</body></html>", encoding="utf-8")
    (tmp_path / "about.html").write_text("<html><body>About</body></html>", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def empty_project(tmp_path: Path) -> Path:
    """Create an empty project with no frontend code."""
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    return tmp_path


# ── detect_frontend_project ──────────────────────────────────────


def test_detect_react_project(react_project: Path) -> None:
    """detect_frontend_project should detect React from package.json."""
    result = detect_frontend_project(react_project)
    assert result.has_frontend is True
    assert "react" in result.frameworks


def test_detect_vue_project(vue_project: Path) -> None:
    """detect_frontend_project should detect Vue from package.json."""
    result = detect_frontend_project(vue_project)
    assert result.has_frontend is True
    assert "vue" in result.frameworks


def test_detect_angular_project(angular_project: Path) -> None:
    """detect_frontend_project should detect Angular from package.json."""
    result = detect_frontend_project(angular_project)
    assert result.has_frontend is True
    assert "angular" in result.frameworks


def test_detect_nextjs_project(nextjs_project: Path) -> None:
    """detect_frontend_project should detect Next.js from package.json."""
    result = detect_frontend_project(nextjs_project)
    assert result.has_frontend is True
    assert "next" in result.frameworks


def test_detect_svelte_project(tmp_path: Path) -> None:
    """detect_frontend_project should detect Svelte from package.json."""
    package_data = {
        "name": "my-svelte-app",
        "dependencies": {"svelte": "^4.0.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(package_data), encoding="utf-8")
    result = detect_frontend_project(tmp_path)
    assert result.has_frontend is True
    assert "svelte" in result.frameworks


def test_detect_html_files(html_project: Path) -> None:
    """detect_frontend_project should detect projects with HTML files."""
    result = detect_frontend_project(html_project)
    assert result.has_frontend is True


def test_detect_returns_empty_for_non_frontend(empty_project: Path) -> None:
    """detect_frontend_project should return empty result for non-frontend project."""
    result = detect_frontend_project(empty_project)
    assert result.has_frontend is False
    assert result.frameworks == []
    assert result.recommended_tools == []


def test_recommends_axe_playwright_for_react(react_project: Path) -> None:
    """detect_frontend_project should recommend @axe-core/playwright for React."""
    result = detect_frontend_project(react_project)
    assert "@axe-core/playwright" in result.recommended_tools


def test_recommends_jest_axe_for_react(react_project: Path) -> None:
    """detect_frontend_project should recommend jest-axe for React projects."""
    result = detect_frontend_project(react_project)
    assert "jest-axe" in result.recommended_tools


def test_recommends_cypress_axe(react_project: Path) -> None:
    """detect_frontend_project should recommend cypress-axe."""
    result = detect_frontend_project(react_project)
    assert "cypress-axe" in result.recommended_tools


def test_detect_angular_from_config(tmp_path: Path) -> None:
    """detect_frontend_project should detect Angular from angular.json config."""
    (tmp_path / "angular.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "app", "dependencies": {}}), encoding="utf-8"
    )
    result = detect_frontend_project(tmp_path)
    assert result.has_frontend is True
    assert "angular" in result.frameworks


# ── analyze_accessibility ────────────────────────────────────────


def test_analyze_detects_axe_config(tmp_path: Path) -> None:
    """analyze_accessibility should detect existing .axerc config files."""
    package_data = {"name": "app", "dependencies": {"react": "^18.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(package_data), encoding="utf-8")
    (tmp_path / ".axerc").write_text("{}", encoding="utf-8")

    result = analyze_accessibility(tmp_path)
    assert result.has_frontend is True


def test_analyze_returns_result_for_frontend_project(react_project: Path) -> None:
    """analyze_accessibility should return analysis for a frontend project."""
    result = analyze_accessibility(react_project)
    assert result.has_frontend is True
    assert len(result.frameworks) > 0
    assert len(result.recommended_tools) > 0


def test_analyze_empty_for_non_frontend(empty_project: Path) -> None:
    """analyze_accessibility should return empty analysis for non-frontend project."""
    result = analyze_accessibility(empty_project)
    assert result.has_frontend is False
    assert result.routes == []
    assert result.frameworks == []


def test_analyze_discovers_nextjs_routes(nextjs_project: Path) -> None:
    """analyze_accessibility should discover routes from Next.js pages."""
    result = analyze_accessibility(nextjs_project)
    assert result.has_frontend is True
    assert len(result.routes) >= 2
    assert "/" in result.routes
    assert "/about" in result.routes


# ── AccessibilityTestBuilder ─────────────────────────────────────


def test_builder_generates_test_cases_for_routes() -> None:
    """AccessibilityTestBuilder should generate test cases for each route."""
    analysis = AccessibilityAnalysisResult(
        has_frontend=True,
        frameworks=["react"],
        routes=["/", "/about"],
        recommended_tools=["@axe-core/playwright"],
    )

    builder = AccessibilityTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    # 2 routes * 4 test types = 8 test cases
    assert len(test_cases) == 8


def test_builder_generates_all_test_types() -> None:
    """AccessibilityTestBuilder should generate all four test types per route."""
    analysis = AccessibilityAnalysisResult(
        has_frontend=True,
        frameworks=["react"],
        routes=["/dashboard"],
        recommended_tools=["@axe-core/playwright"],
    )

    builder = AccessibilityTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    test_types = {tc.test_type for tc in test_cases}
    assert test_types == {"axe_scan", "keyboard_nav", "aria_labels", "focus_management"}


def test_builder_handles_empty_analysis() -> None:
    """AccessibilityTestBuilder should return empty list for empty analysis."""
    analysis = AccessibilityAnalysisResult()
    builder = AccessibilityTestBuilder()
    test_cases = builder.generate_test_plan(analysis)
    assert test_cases == []


def test_builder_test_name_slugification() -> None:
    """AccessibilityTestBuilder should produce valid test names from routes."""
    analysis = AccessibilityAnalysisResult(
        has_frontend=True,
        frameworks=["react"],
        routes=["/users/:id/profile"],
        recommended_tools=["@axe-core/playwright"],
    )

    builder = AccessibilityTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    for tc in test_cases:
        # Test names should only contain valid identifier characters
        assert tc.test_name.replace("_", "").isalnum()
        assert tc.test_name.startswith("test_")


def test_builder_multiple_routes_generate_multiple_cases() -> None:
    """AccessibilityTestBuilder should generate cases for all routes."""
    analysis = AccessibilityAnalysisResult(
        has_frontend=True,
        frameworks=["next"],
        routes=["/", "/about", "/contact", "/dashboard"],
        recommended_tools=["@axe-core/playwright"],
    )

    builder = AccessibilityTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    # 4 routes * 4 test types = 16 test cases
    assert len(test_cases) == 16

    routes_in_cases = {tc.url_or_route for tc in test_cases}
    assert routes_in_cases == {"/", "/about", "/contact", "/dashboard"}


def test_builder_test_case_has_wcag_criteria() -> None:
    """AccessibilityTestBuilder should populate wcag_criteria on test cases."""
    analysis = AccessibilityAnalysisResult(
        has_frontend=True,
        frameworks=["react"],
        routes=["/"],
        recommended_tools=["@axe-core/playwright"],
    )

    builder = AccessibilityTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    for tc in test_cases:
        assert tc.wcag_criteria != ""


def test_builder_test_case_has_description() -> None:
    """AccessibilityTestBuilder should produce informative descriptions."""
    analysis = AccessibilityAnalysisResult(
        has_frontend=True,
        frameworks=["react"],
        routes=["/settings"],
        recommended_tools=["@axe-core/playwright"],
    )

    builder = AccessibilityTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    for tc in test_cases:
        assert "/settings" in tc.description


def test_builder_returns_accessibility_test_case_type() -> None:
    """AccessibilityTestBuilder should return AccessibilityTestCase instances."""
    analysis = AccessibilityAnalysisResult(
        has_frontend=True,
        frameworks=["react"],
        routes=["/"],
        recommended_tools=["@axe-core/playwright"],
    )

    builder = AccessibilityTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    for tc in test_cases:
        assert isinstance(tc, AccessibilityTestCase)
