"""Accessibility analyzer -- detects frontend projects and a11y testing opportunities.

This analyzer:
1. Scans for frontend frameworks (React, Vue, Angular, Next.js, Svelte)
2. Detects HTML files and existing accessibility configurations
3. Identifies routes for accessibility testing
4. Recommends appropriate accessibility testing tools
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Data models ──────────────────────────────────────────────────


@dataclass
class AccessibilityViolation:
    """A single accessibility violation detected during analysis."""

    rule_id: str
    """Identifier for the accessibility rule (e.g., 'color-contrast')."""

    impact: str
    """Impact level: critical, serious, moderate, or minor."""

    description: str
    """Human-readable description of the violation."""

    help_url: str = ""
    """URL to documentation about fixing this violation."""

    nodes: list[str] = field(default_factory=list)
    """CSS selectors or descriptions of affected DOM nodes."""


@dataclass
class AccessibilityReport:
    """Accessibility scan report for a single URL or page."""

    url: str = ""
    """URL or route that was scanned."""

    violations: list[AccessibilityViolation] = field(default_factory=list)
    """List of accessibility violations found."""

    passes: int = 0
    """Number of accessibility rules that passed."""

    wcag_level: str = "AA"
    """WCAG conformance level targeted (A, AA, or AAA)."""

    score: float = 100.0
    """Accessibility score (0.0-100.0)."""


@dataclass
class AccessibilityAnalysisResult:
    """Aggregated result of accessibility analysis for a project."""

    has_frontend: bool = False
    """Whether the project contains frontend code."""

    frameworks: list[str] = field(default_factory=list)
    """Detected frontend frameworks (e.g., 'react', 'vue', 'angular')."""

    routes: list[str] = field(default_factory=list)
    """Discovered routes or pages suitable for accessibility testing."""

    reports: list[AccessibilityReport] = field(default_factory=list)
    """Accessibility reports from existing scans (if any)."""

    recommended_tools: list[str] = field(default_factory=list)
    """Recommended accessibility testing tools based on detected stack."""


# ── Framework detection helpers ──────────────────────────────────


def _read_package_json_deps(project_root: Path) -> dict[str, str]:
    """Read all dependencies from package.json.

    Args:
        project_root: Root directory of the project.

    Returns:
        Merged dictionary of dependencies and devDependencies.
    """
    package_json = project_root / "package.json"
    if not package_json.is_file():
        return {}

    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
        all_deps: dict[str, str] = {}
        for key in ("dependencies", "devDependencies"):
            deps = data.get(key)
            if isinstance(deps, dict):
                all_deps.update(deps)
        return all_deps
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Could not parse package.json: %s", exc)
        return {}


def _detect_frameworks(deps: dict[str, str], project_root: Path) -> list[str]:
    """Detect frontend frameworks from package.json dependencies and config files.

    Args:
        deps: Merged dependencies from package.json.
        project_root: Root directory of the project.

    Returns:
        List of detected framework names.
    """
    frameworks: list[str] = []

    # Check package.json dependencies
    framework_indicators: dict[str, list[str]] = {
        "react": ["react", "react-dom"],
        "vue": ["vue"],
        "angular": ["@angular/core"],
        "next": ["next"],
        "svelte": ["svelte"],
    }

    for framework, packages in framework_indicators.items():
        if any(pkg in deps for pkg in packages):
            frameworks.append(framework)

    # Check for config files as fallback
    config_indicators: dict[str, list[str]] = {
        "next": ["next.config.js", "next.config.mjs", "next.config.ts"],
        "angular": ["angular.json", ".angular-cli.json"],
        "vue": ["vue.config.js", "vite.config.ts", "vite.config.js"],
        "svelte": ["svelte.config.js"],
    }

    for framework, config_files in config_indicators.items():
        if framework not in frameworks and any(
            (project_root / cfg).is_file() for cfg in config_files
        ):
            frameworks.append(framework)

    return sorted(set(frameworks))


def _recommend_tools(frameworks: list[str]) -> list[str]:
    """Recommend accessibility testing tools based on detected frameworks.

    Args:
        frameworks: List of detected frontend frameworks.

    Returns:
        List of recommended tool package names.
    """
    tools: list[str] = []

    # Always recommend axe-core for any frontend project
    tools.append("@axe-core/playwright")

    if any(fw in frameworks for fw in ("react", "next")):
        tools.append("jest-axe")

    if any(fw in frameworks for fw in ("vue", "svelte")):
        tools.append("jest-axe")

    # Cypress-axe for projects that might use Cypress
    tools.append("cypress-axe")

    return sorted(set(tools))


def _detect_html_files(project_root: Path) -> bool:
    """Check if the project contains HTML files.

    Args:
        project_root: Root directory of the project.

    Returns:
        True if HTML files are found outside of node_modules.
    """
    exclude_dirs = {"node_modules", ".git", "dist", "build", ".venv", "venv"}

    for html_file in project_root.rglob("*.html"):
        if not any(part in exclude_dirs for part in html_file.relative_to(project_root).parts):
            return True

    return False


def _scan_routes(project_root: Path, frameworks: list[str]) -> list[str]:
    """Scan for route definitions in the project.

    Args:
        project_root: Root directory of the project.
        frameworks: Detected frontend frameworks.

    Returns:
        List of discovered route paths.
    """
    routes: list[str] = []

    # Next.js file-based routing
    if "next" in frameworks:
        for route_dir in ("pages", "app"):
            pages_dir = project_root / route_dir
            if pages_dir.is_dir():
                routes.extend(_discover_nextjs_routes(pages_dir))

    # Scan for React Router / Vue Router route definitions
    exclude_dirs = {"node_modules", ".git", "dist", "build", ".venv", "venv"}
    route_patterns = ["route", "path:"]
    extensions = {".tsx", ".ts", ".jsx", ".js"}

    for src_file in project_root.rglob("*"):
        if not src_file.is_file():
            continue
        if src_file.suffix not in extensions:
            continue
        rel = src_file.relative_to(project_root)
        if any(part in exclude_dirs for part in rel.parts):
            continue

        try:
            content = src_file.read_text(encoding="utf-8")
            if any(pattern in content.lower() for pattern in route_patterns):
                # Extract route paths from common patterns
                routes.extend(_extract_route_paths(content))
        except (OSError, UnicodeDecodeError):
            continue

    return sorted(set(routes))


def _discover_nextjs_routes(pages_dir: Path) -> list[str]:
    """Discover routes from Next.js pages/app directory.

    Args:
        pages_dir: The pages/ or app/ directory.

    Returns:
        List of route paths.
    """
    routes: list[str] = []
    page_extensions = {".tsx", ".ts", ".jsx", ".js"}

    for page_file in pages_dir.rglob("*"):
        if not page_file.is_file():
            continue
        if page_file.suffix not in page_extensions:
            continue
        if page_file.name.startswith("_"):
            continue

        rel = page_file.relative_to(pages_dir)
        route = "/" + str(rel.with_suffix("")).replace("\\", "/")

        # Clean up index routes
        if route.endswith("/index"):
            route = route[: -len("/index")] or "/"

        routes.append(route)

    return routes


def _extract_route_paths(content: str) -> list[str]:
    """Extract route paths from file content.

    Looks for common route definition patterns like:
    - path: '/some/route'
    - path="/some/route"
    - Route path="/some/route"

    Args:
        content: File content to search.

    Returns:
        List of extracted route paths.
    """
    routes: list[str] = []
    # Match path="/route" or path: "/route" or path='/route' or path: '/route'
    pattern = r"""(?:path)\s*[:=]\s*["'](/[^"']*?)["']"""
    for match in re.finditer(pattern, content):
        route = match.group(1)
        if route and not route.startswith("//"):
            routes.append(route)

    return routes


def _detect_axe_configs(project_root: Path) -> list[str]:
    """Detect existing accessibility configuration files.

    Args:
        project_root: Root directory of the project.

    Returns:
        List of found accessibility config file names.
    """
    config_files = [
        ".axerc",
        ".axerc.json",
        "axe.config.js",
        "axe.config.ts",
        ".pa11yrc",
        "pa11y.json",
        ".pa11yci",
    ]

    return [cfg for cfg in config_files if (project_root / cfg).is_file()]


# ── Public API ───────────────────────────────────────────────────


def detect_frontend_project(project_root: Path) -> AccessibilityAnalysisResult:
    """Scan a project for frontend frameworks and accessibility testing opportunities.

    Checks package.json dependencies, common config files, and HTML files
    to determine if the project has a frontend component. Populates
    ``has_frontend``, ``frameworks``, and ``recommended_tools``.

    Args:
        project_root: Root directory of the project.

    Returns:
        AccessibilityAnalysisResult with detection results.
    """
    result = AccessibilityAnalysisResult()

    # Read package.json dependencies
    deps = _read_package_json_deps(project_root)

    # Detect frameworks
    frameworks = _detect_frameworks(deps, project_root)
    if frameworks:
        result.has_frontend = True
        result.frameworks = frameworks
        result.recommended_tools = _recommend_tools(frameworks)
        logger.info("Detected frontend frameworks: %s", ", ".join(frameworks))

    # Check for HTML files
    if not result.has_frontend and _detect_html_files(project_root):
        result.has_frontend = True
        result.recommended_tools = ["@axe-core/playwright", "cypress-axe"]
        logger.info("Detected HTML files in project")

    return result


def analyze_accessibility(project_root: Path) -> AccessibilityAnalysisResult:
    """Analyze a project for accessibility testing opportunities.

    Calls :func:`detect_frontend_project`, then scans for existing
    accessibility configs and discovers routes suitable for testing.

    Args:
        project_root: Root directory of the project.

    Returns:
        AccessibilityAnalysisResult with full analysis.
    """
    result = detect_frontend_project(project_root)

    # Detect existing accessibility configs
    axe_configs = _detect_axe_configs(project_root)
    if axe_configs:
        logger.info("Found existing accessibility configs: %s", ", ".join(axe_configs))

    # Discover routes for testing
    if result.has_frontend:
        result.routes = _scan_routes(project_root, result.frameworks)
        logger.info(
            "Accessibility analysis: %d frameworks, %d routes, %d recommended tools",
            len(result.frameworks),
            len(result.routes),
            len(result.recommended_tools),
        )

    return result
