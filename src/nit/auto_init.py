"""Auto-detection engine for ``nit init --auto``.

Probes the local environment (API keys, CLI tools, running services,
package.json scripts) and returns a complete configuration dictionary
that can be passed directly to ``_write_comprehensive_nit_yml()``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

import httpx
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)
console = Console()

_OLLAMA_PROBE_TIMEOUT = 2  # seconds

# Framework keyword -> (default port, display name)
_FRAMEWORK_PORTS: dict[str, tuple[int, str]] = {
    "next": (3000, "Next.js"),
    "nuxt": (3000, "Nuxt"),
    "remix": (3000, "Remix"),
    "gatsby": (8000, "Gatsby"),
    "vite": (5173, "Vite"),
    "vue": (5173, "Vue CLI"),
    "angular": (4200, "Angular"),
    "svelte": (5173, "SvelteKit"),
    "webpack-dev-server": (8080, "webpack-dev-server"),
    "react-scripts": (3000, "Create React App"),
    "astro": (4321, "Astro"),
}

_DetectResult = tuple[dict[str, Any], str]


@dataclass
class _DetectionSummary:
    """Accumulates what the auto-detector found, for summary display."""

    llm_source: str = ""
    llm_config: dict[str, Any] = field(default_factory=dict)
    platform_source: str = ""
    platform_config: dict[str, Any] = field(default_factory=dict)
    e2e_source: str = ""
    e2e_config: dict[str, Any] = field(default_factory=dict)
    sentry_source: str = ""
    sentry_config: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# LLM detectors -- each returns (config_dict, human-readable source)
# ---------------------------------------------------------------------------


def _detect_anthropic_api_key() -> _DetectResult:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "mode": "builtin",
            "provider": "anthropic",
            "model": "claude-sonnet-4-5-20250514",
            "api_key": "${ANTHROPIC_API_KEY}",
            "base_url": "",
        }, "ANTHROPIC_API_KEY env var"
    return {}, ""


def _detect_openai_api_key() -> _DetectResult:
    if os.environ.get("OPENAI_API_KEY"):
        return {
            "mode": "builtin",
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "${OPENAI_API_KEY}",
            "base_url": "",
        }, "OPENAI_API_KEY env var"
    return {}, ""


def _detect_nit_llm_api_key() -> _DetectResult:
    if os.environ.get("NIT_LLM_API_KEY"):
        return {
            "mode": "builtin",
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "${NIT_LLM_API_KEY}",
            "base_url": "",
        }, "NIT_LLM_API_KEY env var"
    return {}, ""


def _detect_claude_project_dir(project_root: Path) -> _DetectResult:
    if (project_root / ".claude").is_dir():
        return {
            "mode": "cli",
            "provider": "anthropic",
            "model": "claude-sonnet-4-5-20250514",
            "cli_command": "claude",
            "cli_timeout": 300,
            "cli_extra_args": [],
        }, ".claude/ directory found"
    return {}, ""


def _detect_claude_cli() -> _DetectResult:
    if shutil.which("claude"):
        return {
            "mode": "cli",
            "provider": "anthropic",
            "model": "claude-sonnet-4-5-20250514",
            "cli_command": "claude",
            "cli_timeout": 300,
            "cli_extra_args": [],
        }, "claude CLI on PATH"
    return {}, ""


def _detect_codex_cli() -> _DetectResult:
    if shutil.which("codex"):
        return {
            "mode": "cli",
            "provider": "openai",
            "model": "gpt-4o",
            "cli_command": "codex",
            "cli_timeout": 300,
            "cli_extra_args": [],
        }, "codex CLI on PATH"
    return {}, ""


def _pick_best_ollama_model(model_names: list[str]) -> str:
    """Pick the best available Ollama model.

    Priority: llama3.1 > llama3 > mistral > codellama > first available.
    """
    preferences = ["llama3.1", "llama3", "mistral", "codellama"]
    for pref in preferences:
        for name in model_names:
            if pref in name:
                return name
    return model_names[0] if model_names else "llama3.1"


def _detect_ollama_running() -> _DetectResult:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"

    try:
        resp = httpx.get(f"{host}/api/tags", timeout=_OLLAMA_PROBE_TIMEOUT)
        data = resp.json()
    except Exception:
        return {}, ""

    models: list[dict[str, Any]] = data.get("models", [])
    if not models:
        return {}, ""

    model_names = [m["name"] for m in models if m.get("name")]
    best = _pick_best_ollama_model(model_names)
    is_default_host = host == "http://localhost:11434"

    return {
        "mode": "ollama",
        "provider": "ollama",
        "model": best,
        "api_key": "",
        "base_url": "" if is_default_host else host,
    }, f"Ollama running at {host} ({len(model_names)} model(s))"


def _detect_ollama_host_env() -> _DetectResult:
    host = os.environ.get("OLLAMA_HOST")
    if host:
        return {
            "mode": "ollama",
            "provider": "ollama",
            "model": "llama3.1",
            "api_key": "",
            "base_url": host,
        }, "OLLAMA_HOST env var"
    return {}, ""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _detect_llm(project_root: Path) -> _DetectResult:
    """Run LLM detection in priority order, return first match."""
    checks: list[Callable[[], _DetectResult]] = [
        _detect_anthropic_api_key,
        _detect_openai_api_key,
        _detect_nit_llm_api_key,
        partial(_detect_claude_project_dir, project_root),
        _detect_claude_cli,
        _detect_codex_cli,
        _detect_ollama_running,
        _detect_ollama_host_env,
    ]

    for check in checks:
        config, source = check()
        if config:
            return config, source

    return {
        "mode": "builtin",
        "provider": "openai",
        "model": "gpt-4o",
        "api_key": "",
        "base_url": "",
    }, "none (using defaults)"


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def _detect_platform() -> _DetectResult:
    api_key = os.environ.get("NIT_PLATFORM_API_KEY", "")
    url = os.environ.get("NIT_PLATFORM_URL", "")

    if api_key:
        mode = "platform" if url else "byok"
        return {
            "url": url or "",
            "api_key": "${NIT_PLATFORM_API_KEY}",
            "mode": mode,
            "user_id": os.environ.get("NIT_PLATFORM_USER_ID", ""),
            "project_id": os.environ.get("NIT_PLATFORM_PROJECT_ID", ""),
        }, f"NIT_PLATFORM_API_KEY env var (mode={mode})"

    return {
        "url": "",
        "api_key": "",
        "mode": "disabled",
        "user_id": "",
        "project_id": "",
    }, "none (disabled)"


# ---------------------------------------------------------------------------
# E2E base URL detection
# ---------------------------------------------------------------------------


def _extract_port_from_script(script_cmd: str) -> int | None:
    """Extract port number from patterns like --port 3000, -p=3000."""
    match = re.search(r"(?:--port|--PORT|-p)[=\s]+(\d{2,5})", script_cmd)
    if match:
        return int(match.group(1))
    return None


def _detect_e2e_base_url(project_root: Path) -> _DetectResult:
    """Detect E2E base URL from package.json dev scripts."""
    package_json = project_root / "package.json"
    if not package_json.is_file():
        return {"enabled": False, "base_url": ""}, ""

    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False, "base_url": ""}, ""

    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict):
        return {"enabled": False, "base_url": ""}, ""

    for script_name in ("dev", "start", "serve"):
        script_cmd = scripts.get(script_name, "")
        if not isinstance(script_cmd, str):
            continue

        port = _extract_port_from_script(script_cmd)
        if port:
            return {
                "enabled": True,
                "base_url": f"http://localhost:{port}",
            }, f"package.json scripts.{script_name} (port {port})"

        for keyword, (default_port, fw_name) in _FRAMEWORK_PORTS.items():
            if keyword in script_cmd:
                return {
                    "enabled": True,
                    "base_url": f"http://localhost:{default_port}",
                }, f"{fw_name} detected in scripts.{script_name}"

    return {"enabled": False, "base_url": ""}, ""


# ---------------------------------------------------------------------------
# Sentry detection
# ---------------------------------------------------------------------------


def _detect_sentry() -> _DetectResult:
    """Detect Sentry configuration from environment variables."""
    dsn = os.environ.get("NIT_SENTRY_DSN", "")
    if not dsn:
        return {
            "enabled": False,
            "dsn": "",
            "traces_sample_rate": 0.0,
            "profiles_sample_rate": 0.0,
            "enable_logs": False,
            "environment": "",
        }, "none (disabled)"

    enabled_raw = os.environ.get("NIT_SENTRY_ENABLED", "").strip().lower()
    enabled = enabled_raw in {"1", "true", "yes"}

    traces_rate = float(os.environ.get("NIT_SENTRY_TRACES_SAMPLE_RATE", "0.0"))
    profiles_rate = float(os.environ.get("NIT_SENTRY_PROFILES_SAMPLE_RATE", "0.0"))
    enable_logs_raw = os.environ.get("NIT_SENTRY_ENABLE_LOGS", "").strip().lower()
    enable_logs = enable_logs_raw in {"1", "true", "yes"}

    return {
        "enabled": enabled or True,
        "dsn": "${NIT_SENTRY_DSN}",
        "traces_sample_rate": traces_rate,
        "profiles_sample_rate": profiles_rate,
        "enable_logs": enable_logs,
        "environment": "",
    }, "NIT_SENTRY_DSN env var"


# ---------------------------------------------------------------------------
# Summary display
# ---------------------------------------------------------------------------


def _print_detection_summary(summary: _DetectionSummary) -> None:
    console.print()
    console.print("[bold cyan]Auto-detection results:[/bold cyan]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    table.add_column("Source", style="dim")

    llm = summary.llm_config
    llm_mode = llm.get("mode", "builtin")
    llm_provider = llm.get("provider", "openai")
    llm_model = llm.get("model", "")
    llm_display = f"{llm_mode}/{llm_provider} ({llm_model})"
    table.add_row("LLM", llm_display, summary.llm_source)

    table.add_row(
        "Platform",
        summary.platform_config.get("mode", "disabled"),
        summary.platform_source,
    )

    e2e = summary.e2e_config
    if e2e.get("enabled"):
        table.add_row("E2E base URL", e2e.get("base_url", ""), summary.e2e_source)
    else:
        table.add_row("E2E", "disabled", summary.e2e_source or "no dev server detected")

    sentry = summary.sentry_config
    if sentry.get("enabled"):
        table.add_row("Sentry", "enabled", summary.sentry_source)
    else:
        table.add_row("Sentry", "disabled", summary.sentry_source or "no DSN detected")

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_auto_config(project_root: Path) -> dict[str, Any]:
    """Auto-detect environment and build a complete config dict.

    Probes API keys, CLI tools, running services, and package.json
    to produce a zero-prompt configuration. Returns the same dict
    shape as ``_build_default_config()`` in ``cli.py``.
    """
    llm_config, llm_source = _detect_llm(project_root)
    platform_config, platform_source = _detect_platform()
    e2e_config, e2e_source = _detect_e2e_base_url(project_root)
    sentry_config, sentry_source = _detect_sentry()

    _print_detection_summary(
        _DetectionSummary(
            llm_source=llm_source,
            llm_config=llm_config,
            platform_source=platform_source,
            platform_config=platform_config,
            e2e_source=e2e_source,
            e2e_config=e2e_config,
            sentry_source=sentry_source,
            sentry_config=sentry_config,
        )
    )

    if "none" in llm_source:
        console.print(
            "[yellow]No API key detected.[/yellow] "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or install claude CLI."
        )

    return {
        "llm": llm_config,
        "platform": platform_config,
        "git": {
            "auto_commit": False,
            "auto_pr": False,
            "create_issues": False,
            "create_fix_prs": False,
            "branch_prefix": "nit/",
            "commit_message_template": "",
        },
        "report": {
            "slack_webhook": "",
            "email_alerts": [],
            "format": "terminal",
            "upload_to_platform": platform_config.get("mode", "disabled") != "disabled",
            "html_output_dir": ".nit/reports",
            "serve_port": 8080,
        },
        "e2e": e2e_config,
        "coverage": {
            "line_threshold": 80.0,
            "branch_threshold": 75.0,
            "function_threshold": 85.0,
            "complexity_threshold": 10,
            "undertested_threshold": 50.0,
        },
        "docs": {
            "enabled": True,
            "output_dir": "",
            "style": "",
            "framework": "",
            "write_to_source": False,
            "check_mismatch": True,
            "exclude_patterns": [],
            "max_tokens": 4096,
        },
        "sentry": sentry_config,
    }
