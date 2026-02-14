"""Dashboard reporter for generating local HTML analytics dashboard.

Generates a self-contained HTML dashboard with analytics visualizations.
"""

from __future__ import annotations

import http.server
import logging
import os
import socketserver
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nit.memory.analytics_queries import AnalyticsQueries

logger = logging.getLogger(__name__)

# Coverage thresholds
_COVERAGE_THRESHOLD_SUCCESS = 80
_COVERAGE_THRESHOLD_WARNING = 60

# Test health thresholds
_PASS_RATE_THRESHOLD_SUCCESS = 95
_PASS_RATE_THRESHOLD_WARNING = 80


class DashboardReporter:
    """Reporter that generates HTML analytics dashboard.

    Creates a self-contained HTML file with:
    - Coverage trends
    - Bug discovery timeline
    - Test health overview
    - Drift monitoring results
    - LLM usage and costs
    - Memory insights
    """

    def __init__(self, project_root: Path, *, days: int = 30) -> None:
        """Initialize the dashboard reporter.

        Args:
            project_root: Root directory of the project.
            days: Number of days of history to show (default: 30).
        """
        self._project_root = project_root
        self._queries = AnalyticsQueries(project_root)
        self._days = days

    def generate_html(self) -> Path:
        """Generate HTML dashboard at .nit/dashboard/index.html.

        Returns:
            Path to the generated HTML file.
        """
        logger.info("Generating dashboard with %d days of history", self._days)

        # Collect all dashboard data
        data = self._collect_dashboard_data()

        # Render HTML
        html = self._render_html(data)

        # Write to file
        dashboard_path = self._project_root / ".nit" / "dashboard" / "index.html"
        dashboard_path.parent.mkdir(parents=True, exist_ok=True)
        dashboard_path.write_text(html, encoding="utf-8")

        logger.info("Dashboard generated at %s", dashboard_path)
        return dashboard_path

    def serve(self, *, port: int = 4040, open_browser: bool = True) -> None:
        """Start local HTTP server for dashboard.

        Args:
            port: Server port (default: 4040).
            open_browser: Whether to open browser automatically.
        """
        dashboard_dir = self._project_root / ".nit" / "dashboard"

        if not (dashboard_dir / "index.html").exists():
            logger.error("Dashboard not found. Generate it first with generate_html()")
            return

        # Change to dashboard directory
        original_dir = Path.cwd()
        os.chdir(dashboard_dir)

        try:
            handler = http.server.SimpleHTTPRequestHandler
            with socketserver.TCPServer(("", port), handler) as httpd:
                url = f"http://localhost:{port}"
                logger.info("Dashboard serving at %s", url)
                logger.info("Press Ctrl+C to stop")

                if open_browser:
                    webbrowser.open(url)

                httpd.serve_forever()

        except KeyboardInterrupt:
            logger.info("Stopping dashboard server...")
        finally:
            os.chdir(original_dir)

    def _collect_dashboard_data(self) -> dict[str, Any]:
        """Collect all data for dashboard.

        Returns:
            Dictionary with all dashboard sections.
        """
        return {
            "coverage_trend": self._queries.get_coverage_trend(self._days),
            "bug_timeline": self._queries.get_bug_timeline(self._days),
            "test_health": self._queries.get_test_health(),
            "drift_summary": self._queries.get_drift_summary(self._days),
            "llm_usage": self._queries.get_llm_usage_summary(self._days),
            "memory_insights": self._queries.get_memory_insights(),
            "generated_at": datetime.now(UTC).isoformat(),
            "days": self._days,
        }

    def _render_html(self, data: dict[str, Any]) -> str:
        """Render HTML dashboard.

        Args:
            data: Dashboard data from _collect_dashboard_data().

        Returns:
            Complete HTML string.
        """
        # Extract key metrics
        coverage_latest = data["coverage_trend"][-1] if data["coverage_trend"] else None
        test_health = data["test_health"]
        llm_usage = data["llm_usage"]
        memory_insights = data["memory_insights"]

        # Build HTML
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>nit Analytics Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            padding: 2rem;
            line-height: 1.6;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 0.5rem;
            color: #58a6ff;
        }}
        .subtitle {{
            color: #8b949e;
            margin-bottom: 2rem;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}
        .card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 1.5rem;
        }}
        .card h2 {{
            font-size: 1.25rem;
            margin-bottom: 1rem;
            color: #58a6ff;
            border-bottom: 1px solid #30363d;
            padding-bottom: 0.5rem;
        }}
        .metric {{
            display: flex;
            justify-content: space-between;
            padding: 0.75rem 0;
            border-bottom: 1px solid #21262d;
        }}
        .metric:last-child {{ border-bottom: none; }}
        .metric-label {{ color: #8b949e; }}
        .metric-value {{
            font-weight: 600;
            color: #58a6ff;
        }}
        .metric-value.success {{ color: #3fb950; }}
        .metric-value.warning {{ color: #d29922; }}
        .metric-value.error {{ color: #f85149; }}
        .list-item {{
            padding: 0.5rem 0;
            border-bottom: 1px solid #21262d;
        }}
        .list-item:last-child {{ border-bottom: none; }}
        .empty-state {{
            color: #8b949e;
            font-style: italic;
            text-align: center;
            padding: 2rem;
        }}
        .tag {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.875rem;
            margin-right: 0.5rem;
        }}
        .tag.success {{ background: #1a4d2e; color: #56d364; }}
        .tag.error {{ background: #4d1a1a; color: #ff7b72; }}
        footer {{
            text-align: center;
            color: #8b949e;
            margin-top: 3rem;
            padding-top: 1rem;
            border-top: 1px solid #30363d;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 nit Analytics Dashboard</h1>
        <p class="subtitle">
            Generated: {data['generated_at'].split('T')[0]} |
            Showing last {data['days']} days
        </p>

        <!-- Summary Cards -->
        <div class="grid">
            <!-- Coverage Card -->
            <div class="card">
                <h2>📊 Coverage</h2>
                {self._render_coverage_card(coverage_latest)}
            </div>

            <!-- Test Health Card -->
            <div class="card">
                <h2>🧪 Test Health</h2>
                {self._render_test_health_card(test_health)}
            </div>

            <!-- LLM Usage Card -->
            <div class="card">
                <h2>🤖 LLM Usage</h2>
                {self._render_llm_usage_card(llm_usage)}
            </div>
        </div>

        <!-- Bug Timeline -->
        <div class="card" style="margin-bottom: 2rem;">
            <h2>🐛 Bug Timeline</h2>
            {self._render_bug_timeline(data['bug_timeline'])}
        </div>

        <!-- Memory Insights -->
        <div class="card" style="margin-bottom: 2rem;">
            <h2>🧠 Memory Insights</h2>
            {self._render_memory_insights(memory_insights)}
        </div>

        <!-- Drift Summary -->
        <div class="card">
            <h2>📉 Drift Monitoring</h2>
            {self._render_drift_summary(data['drift_summary'])}
        </div>

        <footer>
            <p>Generated by <strong>nit</strong> | Local-first analytics</p>
        </footer>
    </div>
</body>
</html>"""

    def _render_coverage_card(self, latest: dict[str, Any] | None) -> str:
        """Render coverage metrics card."""
        if not latest:
            return '<p class="empty-state">No coverage data available</p>'

        line_pct = latest["overall_line"] * 100
        branch_pct = latest["overall_branch"] * 100
        function_pct = latest["overall_function"] * 100

        def _get_coverage_class(pct: float) -> str:
            if pct >= _COVERAGE_THRESHOLD_SUCCESS:
                return "success"
            if pct >= _COVERAGE_THRESHOLD_WARNING:
                return "warning"
            return "error"

        line_class = _get_coverage_class(line_pct)
        branch_class = _get_coverage_class(branch_pct)
        function_class = _get_coverage_class(function_pct)

        return f"""
        <div class="metric">
            <span class="metric-label">Line Coverage</span>
            <span class="metric-value {line_class}">{line_pct:.1f}%</span>
        </div>
        <div class="metric">
            <span class="metric-label">Branch Coverage</span>
            <span class="metric-value {branch_class}">{branch_pct:.1f}%</span>
        </div>
        <div class="metric">
            <span class="metric-label">Function Coverage</span>
            <span class="metric-value {function_class}">{function_pct:.1f}%</span>
        </div>
        """

    def _render_test_health_card(self, health: dict[str, Any]) -> str:
        """Render test health metrics card."""
        if not health or health["total_tests"] == 0:
            return '<p class="empty-state">No test data available</p>'

        pass_rate = health["pass_rate"]
        flaky_count = len(health["flaky_tests"])

        if pass_rate >= _PASS_RATE_THRESHOLD_SUCCESS:
            rate_css_class = "success"
        elif pass_rate >= _PASS_RATE_THRESHOLD_WARNING:
            rate_css_class = "warning"
        else:
            rate_css_class = "error"

        flaky_class = "error" if flaky_count > 0 else "success"

        return f"""
        <div class="metric">
            <span class="metric-label">Total Tests</span>
            <span class="metric-value">{health['total_tests']}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Pass Rate</span>
            <span class="metric-value {rate_css_class}">{pass_rate:.1f}%</span>
        </div>
        <div class="metric">
            <span class="metric-label">Flaky Tests</span>
            <span class="metric-value {flaky_class}">{flaky_count}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Avg Duration</span>
            <span class="metric-value">{health['avg_duration_ms'] / 1000:.1f}s</span>
        </div>
        """

    def _render_llm_usage_card(self, usage: dict[str, Any]) -> str:
        """Render LLM usage metrics card."""
        if not usage or usage["total_tokens"] == 0:
            return '<p class="empty-state">No LLM usage data available</p>'

        cost_str = f"${usage['total_cost_usd']:.2f}" if usage["total_cost_usd"] > 0 else "Free"

        # Top model
        top_model = (
            max(usage["by_model"].items(), key=lambda x: x[1]["tokens"])[0]
            if usage["by_model"]
            else "None"
        )

        return f"""
        <div class="metric">
            <span class="metric-label">Total Tokens</span>
            <span class="metric-value">{usage['total_tokens']:,}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Total Cost</span>
            <span class="metric-value">{cost_str}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Top Model</span>
            <span class="metric-value" style="font-size: 0.875rem;">{top_model}</span>
        </div>
        """

    def _render_bug_timeline(self, timeline: list[dict[str, Any]]) -> str:
        """Render bug timeline."""
        if not timeline:
            return '<p class="empty-state">No bug data available</p>'

        return "\n".join(f"""
            <div class="metric">
                <span class="metric-label">{entry['date']}</span>
                <span class="metric-value">
                    <span class="tag error">{entry['discovered']} found</span>
                    <span class="tag success">{entry['fixed']} fixed</span>
                </span>
            </div>
            """ for entry in timeline[-10:])  # Last 10 days

    def _render_memory_insights(self, insights: dict[str, Any]) -> str:
        """Render memory insights."""
        stats = insights.get("stats", {})
        known_count = len(insights.get("known_patterns", []))
        failed_count = len(insights.get("failed_patterns", []))

        if stats.get("total_runs", 0) == 0:
            return '<p class="empty-state">No memory data available</p>'

        return f"""
        <div class="metric">
            <span class="metric-label">Total Runs</span>
            <span class="metric-value">{stats.get('total_runs', 0)}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Tests Generated</span>
            <span class="metric-value">{stats.get('total_tests_generated', 0)}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Known Patterns</span>
            <span class="metric-value success">{known_count}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Failed Patterns</span>
            <span class="metric-value error">{failed_count}</span>
        </div>
        """

    def _render_drift_summary(self, drift_tests: list[dict[str, Any]]) -> str:
        """Render drift monitoring summary."""
        if not drift_tests:
            return '<p class="empty-state">No drift monitoring data available</p>'

        return "\n".join(f"""
            <div class="list-item">
                <strong>{test['test_name']}</strong><br>
                <small style="color: #8b949e;">
                    {len(test['results'])} runs |
                    Latest similarity: {test['results'][-1]['similarity']:.2f}
                </small>
            </div>
            """ for test in drift_tests[:10])  # Top 10 tests
