"""nit CLI — top-level command group."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, Unpack

import click
import yaml
from rich.console import Console
from rich.table import Table

from nit import __version__
from nit.adapters.base import CaseStatus, RunResult, TestFrameworkAdapter
from nit.adapters.registry import get_registry
from nit.agents.analyzers.diff import DiffAnalysisResult, DiffAnalysisTask, DiffAnalyzer
from nit.agents.base import TaskStatus
from nit.agents.builders.readme import ReadmeUpdater
from nit.agents.detectors.framework import detect_frameworks, needs_llm_fallback
from nit.agents.detectors.signals import FrameworkCategory, FrameworkProfile
from nit.agents.detectors.stack import detect_languages
from nit.agents.detectors.workspace import detect_workspace
from nit.agents.reporters.terminal import reporter
from nit.config import load_config, validate_config
from nit.llm.config import load_llm_config
from nit.llm.factory import create_engine
from nit.models.profile import ProjectProfile
from nit.models.store import is_profile_stale, load_profile, save_profile
from nit.utils.changelog import ChangelogGenerator
from nit.utils.git import GitOperationError
from nit.utils.platform_client import (
    PlatformClientError,
    PlatformRuntimeConfig,
    post_platform_report,
)
from nit.utils.readme import find_readme

logger = logging.getLogger(__name__)
console = Console()

# CLI display constants
MAX_CHANGED_FILES_DISPLAY = 20
MAX_FILE_MAPPINGS_DISPLAY = 15


def _load_nit_yml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}

    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(parsed, dict):
        return parsed
    return {}


def _set_nested_config_value(config: dict[str, Any], dotted_key: str, value: str) -> None:
    key_parts = [part.strip() for part in dotted_key.split(".") if part.strip()]
    if not key_parts:
        raise ValueError("Configuration key must not be empty.")

    cursor: dict[str, Any] = config
    for part in key_parts[:-1]:
        existing = cursor.get(part)
        if isinstance(existing, dict):
            cursor = existing
            continue

        next_node: dict[str, Any] = {}
        cursor[part] = next_node
        cursor = next_node

    cursor[key_parts[-1]] = value


def _is_llm_runtime_configured(config_obj: Any) -> bool:
    if config_obj.llm.is_configured:
        return True

    platform_mode = config_obj.platform.normalized_mode
    return (
        config_obj.llm.mode in {"builtin", "ollama"}
        and platform_mode == "platform"
        and bool(config_obj.llm.model and config_obj.platform.url and config_obj.platform.api_key)
    )


def _build_hunt_report_payload(
    *,
    config_obj: Any,
    test_type: str,
    target_file: str | None,
    coverage_target: int | None,
    fix: bool,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    full_report: dict[str, Any] = {
        "timestamp": now,
        "status": "pipeline_not_implemented",
        "mode": "hunt",
        "testType": test_type,
        "targetFile": target_file,
        "coverageTarget": coverage_target,
        "fixRequested": fix,
        "projectRoot": config_obj.project.root,
    }

    branch = os.environ.get("GITHUB_REF_NAME", "").strip() or None
    commit_sha = os.environ.get("GITHUB_SHA", "").strip() or None
    project_id = config_obj.platform.project_id.strip() or None

    payload: dict[str, Any] = {
        "projectId": project_id,
        "runId": str(uuid.uuid4()),
        "runMode": "hunt",
        "branch": branch,
        "commitSha": commit_sha,
        "unitCoverage": None,
        "integrationCoverage": None,
        "e2eCoverage": None,
        "overallCoverage": None,
        "testsGenerated": 0,
        "testsPassed": 0,
        "testsFailed": 0,
        "bugsFound": 0,
        "bugsFixed": 0,
        "fullReport": full_report,
    }

    return payload


def _upload_hunt_report(config_obj: Any, payload: dict[str, Any]) -> dict[str, Any]:
    platform = PlatformRuntimeConfig(
        url=config_obj.platform.url,
        api_key=config_obj.platform.api_key,
        mode=config_obj.platform.mode,
        user_id=config_obj.platform.user_id,
        project_id=config_obj.platform.project_id,
        key_hash=config_obj.platform.key_hash,
    )

    return post_platform_report(platform, payload)


def _build_profile(root: str) -> ProjectProfile:
    """Run all detectors and assemble a ``ProjectProfile``."""
    lang_profile = detect_languages(root)
    fw_profile = detect_frameworks(root)
    ws_profile = detect_workspace(root)

    return ProjectProfile(
        root=str(Path(root).resolve()),
        languages=lang_profile.languages,
        frameworks=fw_profile.frameworks,
        packages=ws_profile.packages,
        workspace_tool=ws_profile.tool,
    )


def _display_profile(profile: ProjectProfile) -> None:
    """Render a ``ProjectProfile`` to the terminal using Rich tables."""
    console.print()

    # ── Languages ──────────────────────────────────────────────────
    lang_table = Table(title="Languages", title_style="bold cyan")
    lang_table.add_column("Language", style="bold")
    lang_table.add_column("Files", justify="right")
    lang_table.add_column("Confidence", justify="right")
    lang_table.add_column("Extensions")

    for li in profile.languages:
        exts = ", ".join(f"{ext} ({cnt})" for ext, cnt in sorted(li.extensions.items()))
        lang_table.add_row(
            li.language,
            str(li.file_count),
            f"{li.confidence:.0%}",
            exts,
        )

    console.print(lang_table)
    console.print()

    # ── Frameworks ─────────────────────────────────────────────────
    fw_table = Table(title="Frameworks", title_style="bold cyan")
    fw_table.add_column("Name", style="bold")
    fw_table.add_column("Language")
    fw_table.add_column("Category")
    fw_table.add_column("Confidence", justify="right")

    for fw in profile.frameworks:
        fw_table.add_row(
            fw.name,
            fw.language,
            fw.category.value,
            f"{fw.confidence:.0%}",
        )

    if profile.frameworks:
        console.print(fw_table)
    else:
        console.print("[dim]No frameworks detected.[/dim]")
    console.print()

    # ── Workspace / Packages ───────────────────────────────────────
    pkg_table = Table(title="Packages", title_style="bold cyan")
    pkg_table.add_column("Name", style="bold")
    pkg_table.add_column("Path")
    pkg_table.add_column("Internal Deps")

    for pkg in profile.packages:
        deps = ", ".join(pkg.dependencies) if pkg.dependencies else "-"
        pkg_table.add_row(pkg.name, pkg.path, deps)

    console.print(pkg_table)
    console.print()

    # ── Summary line ───────────────────────────────────────────────
    primary = profile.primary_language or "unknown"
    console.print(
        f"[bold]Workspace:[/bold] {profile.workspace_tool}  "
        f"[bold]Primary language:[/bold] {primary}  "
        f"[bold]Packages:[/bold] {len(profile.packages)}"
    )


def _display_diff_result(diff_result: DiffAnalysisResult) -> None:
    """Display diff analysis result in the terminal using Rich tables."""

    console.print()

    # ── Summary ────────────────────────────────────────────────────
    console.print("[bold cyan]Change Summary[/bold cyan]")
    console.print(f"Total changed files: {len(diff_result.changed_files)}")
    console.print(f"Changed source files: {len(diff_result.changed_source_files)}")
    console.print(f"Changed test files: {len(diff_result.changed_test_files)}")
    console.print(f"Total affected source files: {len(diff_result.affected_source_files)}")
    console.print(
        f"Lines: [green]+{diff_result.total_lines_added}[/green] "
        f"[red]-{diff_result.total_lines_removed}[/red]"
    )
    console.print()

    # ── Changed Source Files ───────────────────────────────────────
    if diff_result.changed_source_files:
        src_table = Table(title="Changed Source Files", title_style="bold cyan")
        src_table.add_column("File", style="bold")

        for file in diff_result.changed_source_files[:MAX_CHANGED_FILES_DISPLAY]:
            src_table.add_row(file)

        remaining = len(diff_result.changed_source_files) - MAX_CHANGED_FILES_DISPLAY
        if remaining > 0:
            src_table.add_row(f"... and {remaining} more")

        console.print(src_table)
        console.print()

    # ── Changed Test Files ─────────────────────────────────────────
    if diff_result.changed_test_files:
        test_table = Table(title="Changed Test Files", title_style="bold cyan")
        test_table.add_column("File", style="bold")

        for file in diff_result.changed_test_files[:MAX_CHANGED_FILES_DISPLAY]:
            test_table.add_row(file)

        remaining = len(diff_result.changed_test_files) - MAX_CHANGED_FILES_DISPLAY
        if remaining > 0:
            test_table.add_row(f"... and {remaining} more")

        console.print(test_table)
        console.print()

    # ── File Mappings ──────────────────────────────────────────────
    if diff_result.file_mappings:
        mapping_table = Table(title="Source → Test Mappings", title_style="bold cyan")
        mapping_table.add_column("Source File", style="bold")
        mapping_table.add_column("Test File")
        mapping_table.add_column("Exists", justify="center")

        for mapping in diff_result.file_mappings[:MAX_FILE_MAPPINGS_DISPLAY]:
            exists_icon = "✓" if mapping.exists else "✗"
            exists_style = "green" if mapping.exists else "red"
            mapping_table.add_row(
                mapping.source_file,
                mapping.test_file,
                f"[{exists_style}]{exists_icon}[/{exists_style}]",
            )

        remaining = len(diff_result.file_mappings) - MAX_FILE_MAPPINGS_DISPLAY
        if remaining > 0:
            mapping_table.add_row(
                f"... and {remaining} more",
                "",
                "",
            )

        console.print(mapping_table)
        console.print()

    # ── Next Steps ─────────────────────────────────────────────────
    console.print("[green]✓ Diff analysis complete[/green]")
    console.print("[dim]Use these files to focus your test generation and coverage analysis.[/dim]")


def _load_and_validate_profile(path: str) -> ProjectProfile:
    """Load profile and validate it exists."""
    profile = load_profile(path)
    if profile is None:
        reporter.print_error("No profile found. Please run 'nit init' first.")
        raise click.Abort
    return profile


def _get_test_adapters(profile: ProjectProfile) -> list[TestFrameworkAdapter]:
    """Get test adapters for the given profile."""
    registry = get_registry()
    adapters_by_package = registry.select_adapters_for_profile(profile)

    # Get test adapters (filter out doc adapters)
    all_adapters = []
    for package_adapters in adapters_by_package.values():
        all_adapters.extend([a for a in package_adapters if isinstance(a, TestFrameworkAdapter)])

    if not all_adapters:
        reporter.print_error("No unit test framework detected")
        raise click.Abort

    return all_adapters


def _display_test_results_json(result: RunResult) -> None:
    """Display test results in JSON format for CI mode."""
    result_dict = {
        "success": result.failed == 0 and result.errors == 0,
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "skipped": result.skipped,
        "errors": result.errors,
        "duration_ms": result.duration_ms,
        "failed_tests": [
            {"name": tc.name, "message": tc.failure_message}
            for tc in result.test_cases
            if tc.status != CaseStatus.PASSED
        ],
    }
    click.echo(json.dumps(result_dict, indent=2))


def _display_test_results_console(result: RunResult) -> None:
    """Display test results in rich console format."""
    console.print()
    console.print("[bold]Test Results:[/bold]")
    reporter.print_info(f"Total: {result.total} tests")
    if result.passed > 0:
        reporter.print_success(f"✓ Passed: {result.passed}")
    if result.failed > 0:
        reporter.print_error(f"✗ Failed: {result.failed}")
    if result.skipped > 0:
        reporter.print_warning(f"⊘ Skipped: {result.skipped}")
    if result.errors > 0:
        reporter.print_error(f"✗ Errors: {result.errors}")

    console.print(f"Duration: {result.duration_ms / 1000:.2f}s")

    # Show failed test cases
    if result.failed > 0:
        failed_tests = [tc for tc in result.test_cases if tc.status != CaseStatus.PASSED]
        if failed_tests:
            console.print()
            console.print("[bold red]Failed Tests:[/bold red]")
            for test in failed_tests[:10]:  # Show first 10
                console.print(f"  • {test.name}", style="red")
                if test.failure_message:
                    console.print(f"    {test.failure_message[:200]}", style="dim red")


def _default_builtin_llm_init_config() -> dict[str, Any]:
    """Return default LLM config for non-interactive init flow."""
    return {
        "mode": "builtin",
        "provider": "openai",
        "model": "gpt-4o",
        "api_key": "",
        "base_url": "",
    }


def _claude_cli_llm_init_config() -> dict[str, Any]:
    return {
        "mode": "cli",
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250514",
        "cli_command": "claude",
        "cli_timeout": 300,
        "cli_extra_args": [],
    }


def _codex_cli_llm_init_config() -> dict[str, Any]:
    return {
        "mode": "cli",
        "provider": "openai",
        "model": "gpt-4o",
        "cli_command": "codex",
        "cli_timeout": 300,
        "cli_extra_args": [],
    }


def _ollama_llm_init_config() -> dict[str, Any]:
    return {
        "mode": "ollama",
        "provider": "ollama",
        "model": "llama3.1",
        "api_key": "",
        "base_url": "http://localhost:11434",
    }


def _custom_command_llm_init_config() -> dict[str, Any]:
    return {
        "mode": "custom",
        "provider": "openai",
        "model": "gpt-4o",
        "cli_command": (
            "my-ai-tool generate --context {context_file} "
            "--output {output_file} --prompt {prompt} --model {model}"
        ),
        "cli_timeout": 300,
        "cli_extra_args": [],
    }


def _is_interactive_terminal() -> bool:
    """Return True when running in an interactive terminal session."""
    ctx = click.get_current_context(silent=True)
    if ctx and ctx.obj and bool(ctx.obj.get("ci", False)):
        return False
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _check_selected_cli_tool(command: str) -> None:
    """Print CLI availability status for selected command."""
    resolved = shutil.which(command)
    if resolved:
        console.print(f"[green]Found {command} CLI at[/green] {resolved}")
        return

    console.print(
        f"[yellow]CLI tool '{command}' not found in PATH.[/yellow] "
        "Install it or update `llm.cli_command` before running generation."
    )


def _select_llm_init_config() -> dict[str, Any]:
    """Prompt for LLM setup choice in interactive mode."""
    if not _is_interactive_terminal():
        return _default_builtin_llm_init_config()

    choices: list[tuple[str, dict[str, Any]]] = [
        ("Built-in (API key) — Claude, GPT, Gemini, etc.", _default_builtin_llm_init_config()),
        ("Claude Code CLI — uses your installed `claude` command", _claude_cli_llm_init_config()),
        ("Codex CLI — uses OpenAI's `codex` command", _codex_cli_llm_init_config()),
        ("Ollama (local) — run models on your machine", _ollama_llm_init_config()),
        ("Custom command — specify your own tool", _custom_command_llm_init_config()),
    ]

    console.print()
    console.print("[bold]How would you like to power AI generation?[/bold]")
    console.print()
    for index, (label, _) in enumerate(choices, start=1):
        console.print(f"  {index}. {label}")
    console.print()

    selected = int(click.prompt("Select option", type=click.IntRange(1, len(choices)), default=1))
    _, config = choices[selected - 1]

    if config.get("mode") == "cli":
        cli_command = str(config.get("cli_command", "")).strip()
        if cli_command:
            _check_selected_cli_tool(cli_command)

    return config


def _format_yaml_string(value: str) -> str:
    """Format a value as a double-quoted YAML string."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_llm_section(llm_config: dict[str, Any]) -> list[str]:
    """Render mode-specific LLM config lines for ``.nit.yml``."""
    mode = str(llm_config.get("mode", "builtin"))
    provider = str(llm_config.get("provider", "openai"))
    model = str(llm_config.get("model", ""))
    api_key = str(llm_config.get("api_key", ""))
    base_url = str(llm_config.get("base_url", ""))
    cli_command = str(llm_config.get("cli_command", ""))
    cli_timeout = int(llm_config.get("cli_timeout", 300))
    cli_extra_args_raw = llm_config.get("cli_extra_args", [])
    cli_extra_args = (
        [str(value) for value in cli_extra_args_raw] if isinstance(cli_extra_args_raw, list) else []
    )

    lines = ["llm:", f"  mode: {mode}       # builtin | cli | custom | ollama"]

    if mode in {"builtin", "ollama"}:
        lines.append(f"  provider: {provider}   # openai | anthropic | ollama")
        lines.append(f"  model: {_format_yaml_string(model)}")
        lines.append(f"  api_key: {_format_yaml_string(api_key)}  # or set NIT_LLM_API_KEY env var")
        lines.append(f"  base_url: {_format_yaml_string(base_url)}")
        return lines

    lines.append(f"  provider: {provider}   # openai | anthropic | ollama")
    lines.append(f"  model: {_format_yaml_string(model)}")
    lines.append(f"  cli_command: {_format_yaml_string(cli_command)}")
    lines.append(f"  cli_timeout: {cli_timeout}")

    if cli_extra_args:
        lines.append("  cli_extra_args:")
        lines.extend(f"    - {_format_yaml_string(arg)}" for arg in cli_extra_args)
    else:
        lines.append("  cli_extra_args: []")

    return lines


def _write_nit_yml(profile: ProjectProfile, llm_config: dict[str, Any] | None = None) -> Path:
    """Write a minimal ``.nit.yml`` configuration file."""
    root = Path(profile.root)
    nit_yml = root / ".nit.yml"

    lines: list[str] = ["# nit configuration", "# https://github.com/nit-ai/nit", ""]

    # Project section
    lines.append("project:")
    lines.append(f"  root: {profile.root}")
    if profile.primary_language:
        lines.append(f"  primary_language: {profile.primary_language}")
    lines.append(f"  workspace_tool: {profile.workspace_tool}")
    lines.append("")

    # Detected frameworks
    unit_fws = profile.frameworks_by_category(FrameworkCategory.UNIT_TEST)
    e2e_fws = profile.frameworks_by_category(FrameworkCategory.E2E_TEST)

    if unit_fws or e2e_fws:
        lines.append("testing:")
        if unit_fws:
            lines.append(f"  unit_framework: {unit_fws[0].name}")
        if e2e_fws:
            lines.append(f"  e2e_framework: {e2e_fws[0].name}")
        lines.append("")

    # LLM configuration
    selected_llm = llm_config or _default_builtin_llm_init_config()
    lines.extend(_render_llm_section(selected_llm))
    lines.append("")

    nit_yml.write_text("\n".join(lines), encoding="utf-8")
    return nit_yml


@click.group()
@click.option(
    "--ci",
    is_flag=True,
    help="CI mode: machine-readable JSON output, non-interactive, exit codes for pass/fail.",
)
@click.version_option(version=__version__, prog_name="nit")
@click.pass_context
def cli(ctx: click.Context, *, ci: bool) -> None:
    """nit — Open-source AI testing, documentation & quality agent."""
    ctx.ensure_object(dict)
    ctx.obj["ci"] = ci


@cli.group("config")
def config_group() -> None:
    """Manage `.nit.yml` configuration values."""


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
def config_set(key: str, value: str, path: str) -> None:
    """Set a configuration key in `.nit.yml` using dotted paths.

    Example:
      nit config set platform.url https://api.getnit.dev
    """
    root_path = Path(path)
    nit_yml = root_path / ".nit.yml"
    config_data = _load_nit_yml(nit_yml)
    _set_nested_config_value(config_data, key, value)

    nit_yml.write_text(
        yaml.safe_dump(config_data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    reporter.print_success(f"Updated {key} in {nit_yml}")


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
def init(path: str) -> None:
    """Detect stack, create .nit.yml config and .nit/profile.json."""
    console.print(f"[bold]Scanning[/bold] {path} ...")

    profile = _build_profile(path)
    saved = save_profile(profile)

    _display_profile(profile)
    llm_config = _select_llm_init_config()
    nit_yml = _write_nit_yml(profile, llm_config)
    console.print()
    console.print(f"[green]Config written to[/green]  {nit_yml}")
    console.print(f"[green]Profile saved to[/green]  {saved}")

    # Warn about low-confidence frameworks that may need LLM fallback
    fw_profile = FrameworkProfile(frameworks=profile.frameworks, root=profile.root)
    ambiguous = needs_llm_fallback(fw_profile)
    if ambiguous:
        names = ", ".join(fw.name for fw in ambiguous)
        console.print(
            f"\n[yellow]Low-confidence detections ({names}) — "
            "consider configuring an LLM provider for better results.[/yellow]"
        )


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option("--force", is_flag=True, help="Re-scan even if the cached profile is fresh.")
@click.option("--json-output", "as_json", is_flag=True, help="Output raw JSON instead of tables.")
@click.option(
    "--diff",
    is_flag=True,
    help="Analyze only changed files (PR mode). Requires git repository.",
)
@click.option(
    "--base-ref",
    default="HEAD",
    help="Base git ref to compare against (default: HEAD).",
)
@click.option(
    "--compare-ref",
    default=None,
    help="Git ref to compare (default: working directory).",
)
def scan(  # noqa: PLR0913
    path: str,
    *,
    force: bool,
    as_json: bool,
    diff: bool,
    base_ref: str,
    compare_ref: str | None,
) -> None:
    """Re-run detectors, update profile, display results."""
    ctx = click.get_current_context()
    ci_mode = (ctx.obj.get("ci", False) if ctx.obj else False) or as_json

    # If diff mode is enabled, run DiffAnalyzer instead
    if diff:
        _scan_diff_mode(path, base_ref, compare_ref, ci_mode=ci_mode)
        return

    if not force and not is_profile_stale(path):
        cached = load_profile(path)
        if cached is not None:
            if ci_mode:
                click.echo(json.dumps(cached.to_dict(), indent=2))
            else:
                console.print("[dim]Using cached profile (use --force to re-scan).[/dim]")
                _display_profile(cached)
            return

    if not ci_mode:
        console.print(f"[bold]Scanning[/bold] {path} ...")

    profile = _build_profile(path)
    save_profile(profile)

    if ci_mode:
        click.echo(json.dumps(profile.to_dict(), indent=2))
    else:
        _display_profile(profile)
        console.print("\n[green]Profile updated.[/green]")


def _scan_diff_mode(path: str, base_ref: str, compare_ref: str | None, *, ci_mode: bool) -> None:
    """Run scan in diff mode (PR mode) to analyze only changed files."""
    if not ci_mode:
        console.print(f"[bold]Analyzing changes[/bold] in {path} ...")
        console.print(f"Base: {base_ref}, Compare: {compare_ref or 'working directory'}")

    # Run DiffAnalyzer
    analyzer = DiffAnalyzer(Path(path))
    task = DiffAnalysisTask(
        project_root=path,
        base_ref=base_ref,
        compare_ref=compare_ref,
    )

    # Run async analysis
    result = asyncio.run(analyzer.run(task))

    if result.status != TaskStatus.COMPLETED:
        reporter.print_error(f"Diff analysis failed: {', '.join(result.errors)}")
        raise click.Abort

    diff_result = result.result["diff_result"]

    if ci_mode:
        # Output JSON for CI mode
        output = {
            "changed_files": len(diff_result.changed_files),
            "changed_source_files": diff_result.changed_source_files,
            "changed_test_files": diff_result.changed_test_files,
            "affected_source_files": diff_result.affected_source_files,
            "total_lines_added": diff_result.total_lines_added,
            "total_lines_removed": diff_result.total_lines_removed,
            "file_mappings": [
                {
                    "source": m.source_file,
                    "test": m.test_file,
                    "exists": m.exists,
                }
                for m in diff_result.file_mappings
            ],
        }
        click.echo(json.dumps(output, indent=2))
    else:
        # Display results in console
        _display_diff_result(diff_result)


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--type",
    "test_type",
    type=click.Choice(["unit", "e2e", "integration", "all"], case_sensitive=False),
    default="all",
    help="Type of tests to generate.",
)
@click.option(
    "--file",
    "target_file",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    help="Generate tests for a specific file only.",
)
@click.option(
    "--coverage-target",
    type=click.IntRange(0, 100),
    help="Keep generating until this coverage percentage is reached.",
)
@click.option(
    "--package",
    "package_path",
    type=str,
    help="Generate tests for a specific package only (monorepo).",
)
def generate(
    path: str,
    test_type: str,
    target_file: str | None,
    coverage_target: int | None,
    package_path: str | None,
) -> None:
    """Generate tests for uncovered code.

    This command analyzes your codebase, identifies gaps in test coverage,
    and generates tests to fill those gaps.
    """
    ctx = click.get_current_context()
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    if not ci_mode:
        reporter.print_header("nit generate")

    # Load configuration
    try:
        config = load_config(path)
        errors = validate_config(config)
        if errors:
            for error in errors:
                reporter.print_error(error)
            raise click.Abort
    except Exception as e:
        reporter.print_error(f"Failed to load configuration: {e}")
        raise click.Abort from e

    # Check if LLM is configured
    if not _is_llm_runtime_configured(config):
        reporter.print_error("LLM is not configured. Please run 'nit init' or set up .nit.yml")
        raise click.Abort

    # Load or build profile
    profile = load_profile(path)
    if profile is None or is_profile_stale(path):
        reporter.print_info("Profile is stale, re-scanning...")
        profile = _build_profile(path)
        save_profile(profile)

    # Display what we're generating
    reporter.print_info(f"Generating {test_type} tests...")
    if package_path:
        reporter.print_info(f"Target package: {package_path}")
    if target_file:
        reporter.print_info(f"Target file: {target_file}")
    if coverage_target:
        reporter.print_info(f"Target coverage: {coverage_target}%")

    # TODO: Implement actual generation logic
    # This will involve:
    # 1. Running CoverageAnalyzer to identify gaps
    # 2. Creating BuildTasks for each gap
    # 3. Running UnitBuilder/E2EBuilder/IntegrationBuilder
    # 4. Validating generated tests
    # 5. Writing test files
    reporter.print_warning("Test generation not yet implemented")
    reporter.print_info(
        "This will run analyzers → create build tasks → run builders → write test files"
    )


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--coverage/--no-coverage",
    default=True,
    help="Run with coverage reporting.",
)
@click.option(
    "--package",
    "package_path",
    type=str,
    help="Run tests for a specific package only (monorepo).",
)
def run(path: str, *, coverage: bool, package_path: str | None) -> None:
    """Run full test suite via detected adapter(s).

    Executes tests using the detected testing framework(s) and displays
    results with optional coverage reporting.
    """
    ctx = click.get_current_context()
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    if not ci_mode:
        reporter.print_header("nit run")

    # Load configuration
    try:
        config = load_config(path)  # noqa: F841
    except Exception as e:
        reporter.print_error(f"Failed to load configuration: {e}")
        raise click.Abort from e

    # Load profile and get adapters
    profile = _load_and_validate_profile(path)
    all_adapters = _get_test_adapters(profile)

    if package_path:
        reporter.print_info(f"Running tests for package: {package_path}")
    else:
        reporter.print_info("Running all tests...")

    if coverage:
        reporter.print_info("Coverage reporting enabled")

    # Run tests with the first adapter (primary framework)
    adapter = all_adapters[0]
    reporter.print_info(f"Running tests with {adapter.name}...")

    project_path = Path(path)

    try:
        result = asyncio.run(adapter.run_tests(project_path))

        # Display results
        if ci_mode:
            _display_test_results_json(result)
        else:
            _display_test_results_console(result)

        # Exit with appropriate code
        if result.failed > 0 or result.errors > 0:
            if not ci_mode:
                console.print()
            raise click.Abort

        if not ci_mode:
            reporter.print_success("All tests passed!")

    except click.Abort:
        raise
    except Exception as e:
        reporter.print_error(f"Test execution failed: {e}")
        traceback.print_exc()
        raise click.Abort from e


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--type",
    "test_type",
    type=click.Choice(["unit", "e2e", "integration", "all"], case_sensitive=False),
    default="all",
    help="Type of tests to generate.",
)
@click.option(
    "--file",
    "target_file",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    help="Generate tests for a specific file only.",
)
@click.option(
    "--coverage-target",
    type=click.IntRange(0, 100),
    help="Keep generating until this coverage percentage is reached.",
)
@click.option(
    "--fix",
    is_flag=True,
    help="Also generate and apply fixes for found bugs.",
)
@click.option(
    "--report",
    "upload_report",
    is_flag=True,
    help="Upload hunt run summary to platform /api/v1/reports.",
)
@click.option(
    "--pr",
    "create_pr",
    is_flag=True,
    help="Create a GitHub pull request with generated tests.",
)
def hunt(  # noqa: PLR0912, PLR0913
    path: str,
    test_type: str,
    target_file: str | None,
    coverage_target: int | None,
    *,
    fix: bool,
    upload_report: bool,
    create_pr: bool,
) -> None:
    """Hunt for bugs: scan → analyze → generate → run → debug → report.

    This is the full pipeline that:
    - Scans your codebase
    - Analyzes coverage gaps
    - Generates tests
    - Runs tests to find bugs
    - Reports findings

    Use --fix to also generate code fixes for discovered bugs.
    Use --pr to create a GitHub PR with the generated tests.
    """
    ctx = click.get_current_context()
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    if not ci_mode:
        reporter.print_header("nit hunt")

    # Load configuration
    try:
        config = load_config(path)
        errors = validate_config(config)
        if errors:
            for error in errors:
                reporter.print_error(error)
            raise click.Abort
    except Exception as e:
        reporter.print_error(f"Failed to load configuration: {e}")
        raise click.Abort from e

    # Check if LLM is configured
    if not _is_llm_runtime_configured(config):
        reporter.print_error("LLM is not configured. Please run 'nit init' or set up .nit.yml")
        raise click.Abort

    reporter.print_info(f"Running full pipeline for {test_type} tests...")
    if target_file:
        reporter.print_info(f"Target file: {target_file}")
    if coverage_target:
        reporter.print_info(f"Target coverage: {coverage_target}%")
    if fix:
        reporter.print_info("Fix mode enabled: will generate code fixes for bugs")
    if create_pr:
        reporter.print_info("PR mode enabled: will create GitHub PR with generated tests")

    # TODO: Implement the full hunt pipeline
    # 1. Scan (update profile)
    # 2. Analyze (coverage, code, risk)
    # 3. Generate tests
    # 4. Run tests
    # 5. Identify bugs
    # 6. Optionally generate fixes
    # 7. Report findings
    # 8. If create_pr: Use GitHubPRReporter to create PR with generated tests
    reporter.print_warning("Hunt pipeline not yet implemented")
    reporter.print_info("This will run the full testing + debugging pipeline")

    if upload_report:
        report_payload = _build_hunt_report_payload(
            config_obj=config,
            test_type=test_type,
            target_file=target_file,
            coverage_target=coverage_target,
            fix=fix,
        )
        try:
            upload_result = _upload_hunt_report(config, report_payload)
        except PlatformClientError as exc:
            reporter.print_error(str(exc))
            raise click.Abort from exc

        report_id = upload_result.get("reportId")
        if isinstance(report_id, str) and report_id:
            reporter.print_success(f"Uploaded hunt report: {report_id}")
        else:
            reporter.print_success("Uploaded hunt report.")


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option("--force", is_flag=True, help="Re-scan even if the cached profile is fresh.")
@click.option("--json-output", "as_json", is_flag=True, help="Output raw JSON instead of tables.")
def pick(path: str, *, force: bool, as_json: bool) -> None:
    """Pick through the codebase: scan and analyze the project structure.

    This is an alias for 'nit scan' - it runs detectors and updates the profile.
    """
    # This is just an alias for scan - invoke the scan command
    ctx = click.get_current_context()
    ctx.invoke(scan, path=path, force=force, as_json=as_json)


@cli.command()
def drift() -> None:
    """Check LLM endpoints for drift."""
    click.echo("nit drift — not yet implemented")


def _docs_changelog(
    path: str,
    from_tag: str,
    output_path: str | None,
    *,
    use_llm: bool,
) -> None:
    """Generate CHANGELOG.md from git history since the given tag."""
    root = Path(path).resolve()
    out_file = Path(output_path) if output_path else root / "CHANGELOG.md"

    llm_engine = None
    if use_llm:
        try:
            config = load_config(path)
            if _is_llm_runtime_configured(config):
                llm_config = load_llm_config(path)
                llm_engine = create_engine(llm_config)
        except Exception as e:
            logger.debug("LLM not available for changelog polish: %s", e)

    generator = ChangelogGenerator(
        repo_path=root,
        from_ref=from_tag,
        to_ref="HEAD",
        use_llm=use_llm,
        llm_engine=llm_engine,
    )
    markdown = generator.generate()
    out_file.write_text(markdown, encoding="utf-8")
    reporter.print_success(f"Wrote {out_file}")


class DocsOptions(TypedDict):
    """Options for the docs command (Click passes these as keyword args)."""

    path: str
    changelog_tag: str | None
    changelog_output: str | None
    changelog_no_llm: bool
    readme: bool
    write: bool


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--changelog",
    "changelog_tag",
    type=str,
    default=None,
    metavar="TAG",
    help="Generate CHANGELOG.md from git history since tag (e.g. v1.0.0).",
)
@click.option(
    "--output",
    "changelog_output",
    type=click.Path(dir_okay=False, resolve_path=True),
    default=None,
    help="Output file for changelog (default: CHANGELOG.md in project root).",
)
@click.option(
    "--no-llm",
    "changelog_no_llm",
    is_flag=True,
    help="Skip LLM polish for changelog entries (use raw commit messages).",
)
@click.option(
    "--readme",
    is_flag=True,
    help="Update README (installation, project structure, usage) via LLM.",
)
@click.option(
    "--write",
    is_flag=True,
    help="Write generated README content to the README file (use with --readme).",
)
def docs(**opts: Unpack[DocsOptions]) -> None:
    """Generate/update documentation.

    Use --changelog <tag> to generate CHANGELOG.md from git history since that tag.
    Use --readme to generate README section updates from project structure.
    Use --write with --readme to write the result to the README file.
    """
    path = opts["path"]
    changelog_tag = opts["changelog_tag"]
    changelog_output = opts["changelog_output"]
    changelog_no_llm = opts["changelog_no_llm"]
    readme = opts["readme"]
    write = opts["write"]
    if changelog_tag is not None:
        try:
            _docs_changelog(
                path,
                changelog_tag,
                changelog_output,
                use_llm=not changelog_no_llm,
            )
        except GitOperationError as e:
            reporter.print_error(str(e))
            raise click.Abort from e
        return
    if not readme:
        click.echo("nit docs — use --changelog <tag> or --readme, or run another doc target.")
        return
    _docs_readme(path, write=write)


def _docs_readme(path: str, *, write: bool) -> None:
    """Generate README updates and optionally write to file."""
    try:
        config = load_config(path)
        errors = validate_config(config)
        if errors:
            for error in errors:
                reporter.print_error(error)
            raise click.Abort
    except Exception as e:
        reporter.print_error(f"Failed to load configuration: {e}")
        raise click.Abort from e

    if not _is_llm_runtime_configured(config):
        reporter.print_error("LLM is not configured. Run 'nit init' or set up .nit.yml")
        raise click.Abort

    profile = load_profile(path)
    if profile is None or is_profile_stale(path):
        reporter.print_info("Profile is stale, re-scanning...")
        profile = _build_profile(path)
        save_profile(profile)

    readme_path = find_readme(path)
    if readme_path is None:
        reporter.print_error("No README file found. Create README.md (or readme.md) first.")
        raise click.Abort

    llm_config = load_llm_config(path)
    engine = create_engine(llm_config)
    updater = ReadmeUpdater(engine)

    reporter.print_info("Generating README updates...")
    try:
        content = asyncio.run(updater.update_readme(path, profile, readme_path))
    except FileNotFoundError as e:
        reporter.print_error(str(e))
        raise click.Abort from e
    except Exception as e:
        reporter.print_error(f"README generation failed: {e}")
        raise click.Abort from e

    if write:
        readme_path.write_text(content, encoding="utf-8")
        reporter.print_success(f"Updated {readme_path}")
    else:
        click.echo(content)
