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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, Unpack

import click
import yaml
from rich.console import Console
from rich.table import Table
from rich.text import Text

from nit import __version__
from nit.adapters.base import CaseStatus, RunResult, TestFrameworkAdapter
from nit.adapters.registry import get_registry
from nit.agents.analyzers.diff import DiffAnalysisResult, DiffAnalysisTask, DiffAnalyzer
from nit.agents.base import TaskStatus
from nit.agents.builders.docs import DocBuilder, DocBuildTask
from nit.agents.builders.readme import ReadmeUpdater
from nit.agents.detectors.framework import detect_frameworks, needs_llm_fallback
from nit.agents.detectors.signals import FrameworkCategory, FrameworkProfile
from nit.agents.detectors.stack import detect_languages
from nit.agents.detectors.workspace import detect_workspace
from nit.agents.pipelines import PickPipeline, PickPipelineConfig, PickPipelineResult
from nit.agents.reporters.terminal import reporter
from nit.config import load_config, validate_config
from nit.llm.config import load_llm_config
from nit.llm.factory import create_engine
from nit.llm.usage_callback import get_session_usage_stats, get_usage_reporter
from nit.models.profile import ProjectProfile
from nit.models.store import is_profile_stale, load_profile, save_profile
from nit.utils.changelog import ChangelogGenerator
from nit.utils.ci_context import detect_ci_context
from nit.utils.git import GitOperationError
from nit.utils.platform_client import (
    PlatformClientError,
    PlatformRuntimeConfig,
    post_platform_bug,
    post_platform_report,
)
from nit.utils.readme import find_readme

logger = logging.getLogger(__name__)
console = Console()

# CLI display constants
MAX_CHANGED_FILES_DISPLAY = 20
MAX_FILE_MAPPINGS_DISPLAY = 15
MAX_MEMORY_PATTERNS_DISPLAY = 5
MAX_MEMORY_FEEDBACK_DISPLAY = 3

# Masking thresholds
_MIN_MASKED_VALUE_LENGTH = 8


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


def _config_to_dict(config: Any) -> dict[str, Any]:
    """Convert NitConfig to dictionary for display."""
    from dataclasses import asdict

    result = asdict(config)
    # Remove the raw field as it's redundant
    result.pop("raw", None)
    return result


def _mask_sensitive_values(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Recursively mask sensitive values in configuration dict."""
    import copy

    result = copy.deepcopy(config_dict)

    # List of sensitive keys to mask
    sensitive_keys = {
        "api_key",
        "password",
        "token",
        "cookie_value",
        "slack_webhook",
        "key_hash",
        "dsn",
    }

    def _mask_dict(data: dict[str, Any]) -> None:
        for key, value in data.items():
            if key in sensitive_keys and isinstance(value, str) and value:
                # Show first 4 chars, mask the rest
                if len(value) > _MIN_MASKED_VALUE_LENGTH:
                    data[key] = f"{value[:4]}...{value[-4:]}"
                else:
                    data[key] = "***"
            elif isinstance(value, dict):
                _mask_dict(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _mask_dict(item)

    _mask_dict(result)
    return result


def _is_llm_runtime_configured(config_obj: Any) -> bool:
    return bool(config_obj.llm.is_configured)


class _ScanKwargs(TypedDict):
    """Keyword arguments for the scan CLI command."""

    path: str
    force: bool
    as_json: bool
    diff: bool
    base_ref: str
    compare_ref: str | None


class _ReportKwargs(TypedDict):
    """Keyword arguments for the report CLI command."""

    path: str
    create_pr: bool
    create_issues: bool
    create_fix_prs: bool
    upload_platform: bool
    no_commit: bool
    html: bool
    serve: bool
    port: int
    days: int


@dataclass
class _PickOptions:
    """Options for pick command execution."""

    test_type: str
    target_file: str | None
    coverage_target: int | None
    fix: bool


def _build_pick_report_payload(
    config_obj: Any,
    options: _PickOptions,
    result: PickPipelineResult | None = None,
    start_time: datetime | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    full_report: dict[str, Any] = {
        "timestamp": now,
        "status": "completed" if result and result.success else "failed",
        "mode": "pick",
        "testType": options.test_type,
        "targetFile": options.target_file,
        "coverageTarget": options.coverage_target,
        "fixRequested": options.fix,
        "projectRoot": config_obj.project.root,
    }

    # Add result details if available
    if result:
        full_report["testsRun"] = result.tests_run
        full_report["testsPassed"] = result.tests_passed
        full_report["testsFailed"] = result.tests_failed
        full_report["testsErrors"] = result.tests_errors
        full_report["bugsFound"] = len(result.bugs_found)
        full_report["fixesApplied"] = len(result.fixes_applied)
        full_report["errors"] = result.errors

    # Detect CI context (supports GitHub Actions, GitLab, CircleCI, etc.)
    ci_context = detect_ci_context()

    # Get commit SHA from CI context, fallback to git if local
    commit_sha = ci_context.commit_sha
    if not commit_sha:
        # Try to get from local git
        try:
            import subprocess

            git_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            commit_sha = git_result.stdout.strip() or None
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            commit_sha = None

    # Get branch from CI context or fallback to git
    branch = ci_context.branch
    if not branch:
        try:
            import subprocess

            git_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            branch = git_result.stdout.strip() or None
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            branch = None

    # Note: Project ID is extracted from the API token on the backend

    # Get LLM config for provider and model info
    llm_provider = None
    llm_model = None
    if hasattr(config_obj, "llm"):
        llm_provider = getattr(config_obj.llm, "provider", None)
        llm_model = getattr(config_obj.llm, "model", None)

    # Get execution environment
    execution_environment = "local"
    if os.environ.get("GITHUB_ACTIONS"):
        execution_environment = "github-actions"
    elif os.environ.get("GITLAB_CI"):
        execution_environment = "gitlab-ci"
    elif os.environ.get("CI"):
        execution_environment = "ci"

    # Calculate execution time
    execution_time_ms = None
    if start_time:
        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000
        execution_time_ms = int(duration)

    # Get usage reporter and session stats
    usage_reporter = get_usage_reporter()
    session_stats = get_session_usage_stats()

    # Build metadata from session and environment
    run_metadata: dict[str, Any] = {
        "sessionId": getattr(usage_reporter, "session_id", None),
        "executionEnvironment": execution_environment,
        "llmRequestCount": session_stats.request_count,
    }

    payload: dict[str, Any] = {
        "runId": str(uuid.uuid4()),
        "runMode": "pick",
        "branch": branch,
        "commitSha": commit_sha,
        "unitCoverage": None,
        "integrationCoverage": None,
        "e2eCoverage": None,
        "overallCoverage": None,
        "testsGenerated": result.tests_run if result else 0,
        "testsPassed": result.tests_passed if result else 0,
        "testsFailed": result.tests_failed if result else 0,
        "bugsFound": len(result.bugs_found) if result else 0,
        "bugsFixed": len(result.fixes_applied) if result else 0,
        "llmProvider": llm_provider,
        "llmModel": llm_model,
        "llmPromptTokens": session_stats.prompt_tokens,
        "llmCompletionTokens": session_stats.completion_tokens,
        "llmTotalTokens": session_stats.total_tokens,
        "llmCostUsd": session_stats.total_cost_usd,
        "executionTimeMs": execution_time_ms,
        "executionEnvironment": execution_environment,
        "runMetadata": run_metadata,
        "fullReport": full_report,
    }

    return payload


def _upload_pick_report(config_obj: Any, payload: dict[str, Any]) -> dict[str, Any]:
    platform = PlatformRuntimeConfig(
        url=config_obj.platform.url,
        api_key=config_obj.platform.api_key,
        mode=config_obj.platform.mode,
        user_id=config_obj.platform.user_id,
        project_id=config_obj.platform.project_id,
        key_hash=config_obj.platform.key_hash,
    )

    return post_platform_report(platform, payload)


def _upload_bugs_to_platform(
    config_obj: Any,
    result: PickPipelineResult,
    issue_urls: dict[str, str] | None = None,
    pr_urls: dict[str, str] | None = None,
) -> list[str]:
    """Upload detected bugs to the platform API.

    Args:
        config_obj: Configuration object with platform settings.
        result: Pick pipeline result containing bugs.
        issue_urls: Optional mapping of bug titles to GitHub issue URLs.
        pr_urls: Optional mapping of bug titles to GitHub PR URLs.

    Returns:
        List of created bug IDs.

    Raises:
        PlatformClientError: If the API request fails.
    """
    if not result.bugs_found:
        return []

    platform_config = PlatformRuntimeConfig(
        url=config_obj.platform.url,
        api_key=config_obj.platform.api_key,
    )

    issue_map = issue_urls or {}
    pr_map = pr_urls or {}
    bug_ids: list[str] = []

    for bug in result.bugs_found:
        payload: dict[str, Any] = {
            "filePath": bug.location.file_path,
            "description": bug.description,
            "severity": (
                bug.severity.value if hasattr(bug.severity, "value") else str(bug.severity)
            ),
            "status": "open",
        }

        if bug.location.function_name:
            payload["functionName"] = bug.location.function_name

        if hasattr(bug, "root_cause") and bug.root_cause:
            payload["rootCause"] = bug.root_cause

        bug_key = bug.title
        if bug_key in issue_map:
            payload["githubIssueUrl"] = issue_map[bug_key]
        if bug_key in pr_map:
            payload["githubPrUrl"] = pr_map[bug_key]

        try:
            body = post_platform_bug(platform_config, payload)
            if "bugId" in body:
                bug_ids.append(body["bugId"])
                logger.info("Uploaded bug: %s (ID: %s)", bug.title, body["bugId"])
        except PlatformClientError as exc:
            logger.warning("Failed to upload bug '%s': %s", bug.title, exc)
            continue

    return bug_ids


def _try_pull_memory(config_obj: Any, project_root: Path, ci_mode: bool) -> None:
    """Pull memory from platform before generation. No-op if platform not configured."""
    if config_obj.platform.normalized_mode not in {"platform", "byok"}:
        return

    try:
        from nit.memory.sync import apply_pull_response, get_sync_version, set_sync_version
        from nit.utils.platform_client import pull_platform_memory

        platform = PlatformRuntimeConfig(
            url=config_obj.platform.url,
            api_key=config_obj.platform.api_key,
            mode=config_obj.platform.mode,
            user_id=config_obj.platform.user_id,
            project_id=config_obj.platform.project_id,
            key_hash=config_obj.platform.key_hash,
        )
        response = pull_platform_memory(platform, config_obj.platform.project_id)
        remote_version = response.get("version", 0)
        local_version = get_sync_version(project_root)

        if isinstance(remote_version, int) and remote_version > local_version:
            apply_pull_response(project_root, response)
            set_sync_version(project_root, remote_version)
            if not ci_mode:
                reporter.print_info(f"Pulled memory from platform (version {remote_version})")
    except Exception as exc:
        logger.warning("Memory pull from platform skipped: %s", exc)


def _try_push_memory(
    config_obj: Any,
    project_root: Path,
    ci_mode: bool,
    *,
    source: str = "local",
) -> None:
    """Push memory to platform after a run. No-op if platform not configured."""
    if config_obj.platform.normalized_mode not in {"platform", "byok"}:
        return

    try:
        from nit.memory.sync import build_push_payload, set_sync_version
        from nit.utils.platform_client import push_platform_memory

        platform = PlatformRuntimeConfig(
            url=config_obj.platform.url,
            api_key=config_obj.platform.api_key,
            mode=config_obj.platform.mode,
            user_id=config_obj.platform.user_id,
            project_id=config_obj.platform.project_id,
            key_hash=config_obj.platform.key_hash,
        )
        payload = build_push_payload(
            project_root,
            source=source,
            project_id=config_obj.platform.project_id,
        )
        result = push_platform_memory(platform, payload)

        new_version = result.get("version")
        if isinstance(new_version, int) and new_version > 0:
            set_sync_version(project_root, new_version)
            if not ci_mode:
                reporter.print_info(f"Synced memory to platform (version {new_version})")
    except Exception as exc:
        logger.warning("Memory push to platform failed: %s", exc)


def _build_profile(root: str) -> ProjectProfile:
    """Run all detectors and assemble a ``ProjectProfile``."""
    lang_profile = detect_languages(root)
    fw_profile = detect_frameworks(root)
    ws_profile = detect_workspace(root)

    profile = ProjectProfile(
        root=str(Path(root).resolve()),
        languages=lang_profile.languages,
        frameworks=fw_profile.frameworks,
        packages=ws_profile.packages,
        workspace_tool=ws_profile.tool,
    )

    # Detect LLM usage in the project
    try:
        from nit.agents.base import TaskInput
        from nit.agents.detectors.llm_usage import LLMUsageDetector

        detector = LLMUsageDetector()
        task = TaskInput(task_type="detect_llm_usage", target=str(Path(root).resolve()))
        result = asyncio.run(detector.run(task))
        if result.status == TaskStatus.COMPLETED:
            profile.llm_usage_count = result.result.get("total_usages", 0)
            providers_raw = result.result.get("providers", [])
            profile.llm_providers = [str(p) for p in providers_raw]
    except Exception as exc:
        logger.debug("LLM usage detection skipped: %s", exc)

    return profile


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

    # ── LLM Integrations ──────────────────────────────────────────
    if profile.llm_usage_count > 0:
        providers = ", ".join(profile.llm_providers) if profile.llm_providers else "unknown"
        console.print(
            f"[bold cyan]LLM Integrations:[/bold cyan] "
            f"{profile.llm_usage_count} usage(s) detected — providers: {providers}"
        )
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


def _get_slack_reporter(config: Any) -> Any:
    """Return a SlackReporter if a Slack webhook is configured, else None."""
    webhook = getattr(getattr(config, "report", None), "slack_webhook", "")
    if not webhook:
        return None
    from nit.agents.reporters.slack import SlackReporter

    return SlackReporter(webhook)


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
        "success": result.success,
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

    # Show raw output if test execution failed but no tests were found
    if not result.success and result.total == 0 and result.raw_output:
        console.print()
        console.print("[bold red]Test Framework Error:[/bold red]")
        # Show last 20 lines of output to help diagnose the issue
        output_lines = result.raw_output.strip().split("\n")
        for line in output_lines[-20:]:
            console.print(f"  {line}", style="dim red")


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


def _build_default_config() -> dict[str, Any]:
    """Build default configuration for quick/non-interactive mode."""
    return {
        "llm": _default_builtin_llm_init_config(),
        "platform": {
            "url": "",
            "api_key": "",
            "mode": "disabled",
            "user_id": "",
            "project_id": "",
        },
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
            "upload_to_platform": False,
            "html_output_dir": ".nit/reports",
            "serve_port": 8080,
        },
        "e2e": {
            "enabled": False,
            "base_url": "",
        },
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
        "sentry": {
            "enabled": False,
            "dsn": "",
            "traces_sample_rate": 0.0,
            "profiles_sample_rate": 0.0,
            "enable_logs": False,
            "environment": "",
        },
    }


def _interactive_config_setup() -> dict[str, Any]:
    """Interactive configuration setup with comprehensive prompts."""
    console.print()
    console.print("[bold cyan]═══ nit Configuration Setup ═══[/bold cyan]")
    console.print()

    # Platform Integration & Key Management (FIRST - determines if user needs own API key)
    platform_config = _prompt_platform_config()

    # LLM Configuration
    platform_mode = platform_config.get("mode", "disabled")
    llm_config = _prompt_llm_config()

    # Reporting Configuration (Slack/Email)
    report_config = _prompt_report_config()

    # E2E Configuration
    e2e_config = _prompt_e2e_config()

    # Git/PR/Commit Configuration
    git_config = _prompt_git_config()

    # Coverage Configuration
    coverage_config = _prompt_coverage_config()

    # Report Format Configuration
    platform_enabled = platform_mode == "byok"
    report_format_config = _prompt_report_format_config(platform_enabled)

    # Merge report configs
    full_report_config = {**report_config, **report_format_config}

    # Documentation Configuration
    docs_config = _prompt_docs_config()

    # Sentry Configuration
    sentry_config = _prompt_sentry_config()

    # Advanced LLM Settings (optional)
    if click.confirm(
        "\nConfigure advanced LLM settings? (temperature, max_tokens, etc.)", default=False
    ):
        llm_config = _prompt_advanced_llm_config(llm_config)

    return {
        "llm": llm_config,
        "platform": platform_config,
        "git": git_config,
        "report": full_report_config,
        "e2e": e2e_config,
        "coverage": coverage_config,
        "docs": docs_config,
        "sentry": sentry_config,
    }


def _prompt_llm_config() -> dict[str, Any]:
    """Prompt for LLM configuration."""
    console.print("[bold]2. LLM Provider Configuration[/bold]")
    console.print()

    # User configures their own LLM
    choices: list[tuple[str, dict[str, Any]]] = [
        ("Built-in (API key) — Claude, GPT, Gemini, OpenRouter, etc.", {}),
        ("Claude Code CLI — uses your installed `claude` command", _claude_cli_llm_init_config()),
        ("Codex CLI — uses OpenAI's `codex` command", _codex_cli_llm_init_config()),
        ("Ollama (local) — run models on your machine", _ollama_llm_init_config()),
        (
            "LM Studio (local) — OpenAI-compatible local server",
            {
                "mode": "builtin",
                "provider": "openai",
                "model": "",
                "api_key": "",
                "base_url": "http://localhost:1234/v1",
            },
        ),
        ("Custom command — specify your own tool", _custom_command_llm_init_config()),
    ]

    console.print("[bold]How would you like to power AI generation?[/bold]")
    console.print()
    for index, (label, _) in enumerate(choices, start=1):
        console.print(f"  {index}. {label}")
    console.print()

    selected = int(click.prompt("Select option", type=click.IntRange(1, len(choices)), default=1))
    _, config = choices[selected - 1]

    # Built-in mode: prompt for specific provider
    if not config:
        config = _prompt_builtin_provider()

    if config.get("mode") == "cli":
        cli_command = str(config.get("cli_command", "")).strip()
        if cli_command:
            _check_selected_cli_tool(cli_command)

    # Prompt for API key if needed (and not already set via env)
    needs_api_key = config.get("mode") in {"builtin"} and not config.get("_skip_api_key")
    if needs_api_key and not config.get("api_key"):
        console.print()
        if click.confirm("Configure API key now?", default=True):
            api_key = click.prompt(
                "API key (or leave empty to use environment variable)",
                default="",
                show_default=False,
                hide_input=True,
            )
            if api_key:
                config["api_key"] = api_key
        else:
            console.print("[dim]You can set it later via environment variable or .nit.yml[/dim]")

    config.pop("_skip_api_key", None)

    # Prompt for base_url if provider needs one and it's not set
    if config.get("_needs_base_url") and not config.get("base_url"):
        console.print()
        base_url = click.prompt("Base URL", default="")
        config["base_url"] = base_url
    config.pop("_needs_base_url", None)

    # Prompt for model if not set
    if not config.get("model"):
        suggested = _suggested_model_for_provider(config.get("provider", "openai"))
        model = click.prompt("Model name", default=suggested)
        config["model"] = model

    return config


def _prompt_builtin_provider() -> dict[str, Any]:
    """Prompt for a specific LLM provider when Built-in mode is selected."""
    providers: list[tuple[str, dict[str, Any]]] = [
        (
            "OpenAI (GPT-4o, etc.)",
            {
                "mode": "builtin",
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": "",
                "base_url": "",
            },
        ),
        (
            "Anthropic (Claude)",
            {
                "mode": "builtin",
                "provider": "anthropic",
                "model": "claude-sonnet-4-5-20250514",
                "api_key": "",
                "base_url": "",
            },
        ),
        (
            "Google Gemini",
            {
                "mode": "builtin",
                "provider": "gemini",
                "model": "gemini-2.0-flash",
                "api_key": "",
                "base_url": "",
            },
        ),
        (
            "OpenRouter (multi-provider routing)",
            {
                "mode": "builtin",
                "provider": "openrouter",
                "model": "openrouter/auto",
                "api_key": "",
                "base_url": "https://openrouter.ai/api/v1",
            },
        ),
        (
            "AWS Bedrock",
            {
                "mode": "builtin",
                "provider": "bedrock",
                "model": "anthropic.claude-3-sonnet-20240229-v1:0",
                "api_key": "",
                "base_url": "",
                "_skip_api_key": True,
            },
        ),
        (
            "Google Vertex AI",
            {
                "mode": "builtin",
                "provider": "vertex_ai",
                "model": "gemini-pro",
                "api_key": "",
                "base_url": "",
                "_skip_api_key": True,
            },
        ),
        (
            "Azure OpenAI",
            {
                "mode": "builtin",
                "provider": "azure",
                "model": "gpt-4o",
                "api_key": "",
                "base_url": "",
                "_needs_base_url": True,
            },
        ),
        (
            "Custom (any OpenAI-compatible endpoint)",
            {
                "mode": "builtin",
                "provider": "openai",
                "model": "",
                "api_key": "",
                "base_url": "",
                "_needs_base_url": True,
            },
        ),
    ]

    console.print()
    console.print("[bold]Select your LLM provider:[/bold]")
    console.print()
    for index, (label, _) in enumerate(providers, start=1):
        console.print(f"  {index}. {label}")
    console.print()

    selected = int(
        click.prompt("Select provider", type=click.IntRange(1, len(providers)), default=1)
    )
    _, config = providers[selected - 1]
    return config


def _suggested_model_for_provider(provider: str) -> str:
    """Return a sensible default model for a given provider."""
    defaults: dict[str, str] = {
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4-5-20250514",
        "gemini": "gemini-2.0-flash",
        "openrouter": "openrouter/auto",
        "bedrock": "anthropic.claude-3-sonnet-20240229-v1:0",
        "vertex_ai": "gemini-pro",
        "azure": "gpt-4o",
        "ollama": "llama3.1",
    }
    return defaults.get(provider, "gpt-4o")


def _prompt_platform_config() -> dict[str, Any]:
    """Prompt for platform configuration and key management."""
    console.print("[bold]1. Platform Integration & Key Management[/bold]")
    console.print()

    console.print("nit can operate in two modes:")
    console.print(
        "  1. [bold]BYOK (Bring Your Own Key)[/bold] - Use your LLM API keys + platform reporting"
    )
    console.print("  2. [bold]Disabled[/bold] - No platform integration (fully local)")
    console.print()

    mode_map = {
        "1": "byok",
        "2": "disabled",
        "byok": "byok",
        "disabled": "disabled",
    }

    while True:
        mode_input = (
            click.prompt(
                "Select mode (byok, disabled)",
                default="disabled",
                show_default=True,
            )
            .lower()
            .strip()
        )

        if mode_input in mode_map:
            mode_choice = mode_map[mode_input]
            break

        console.print(f"[red]Error: '{mode_input}' is not one of 'byok', 'disabled'.[/red]")

    platform_config: dict[str, Any] = {
        "mode": mode_choice,
        "url": "",
        "reporting_api_key": "",
        "user_id": "",
        "project_id": "",
    }

    if mode_choice == "byok":
        console.print()
        url = click.prompt(
            "Platform URL",
            default="https://platform.getnit.dev",
        )
        platform_config["url"] = url

        console.print()
        if click.confirm("Enable platform reporting (usage metrics, test results)?", default=True):
            reporting_api_key = click.prompt(
                "Platform reporting API key (or NIT_PLATFORM_REPORTING_API_KEY env var)",
                default="",
                show_default=False,
                hide_input=True,
            )
            platform_config["reporting_api_key"] = reporting_api_key

    return platform_config


def _prompt_report_config() -> dict[str, Any]:
    """Prompt for reporting configuration."""
    console.print()
    console.print("[bold]3. Reporting Configuration[/bold]")
    console.print()

    report_config: dict[str, Any] = {
        "slack_webhook": "",
        "email_alerts": [],
    }

    if click.confirm("Configure Slack notifications?", default=False):
        slack_webhook = click.prompt(
            "Slack webhook URL",
            default="",
        )
        report_config["slack_webhook"] = slack_webhook

    if click.confirm("Configure email alerts?", default=False):
        emails_str = click.prompt(
            "Email addresses (comma-separated)",
            default="",
        )
        if emails_str:
            report_config["email_alerts"] = [e.strip() for e in emails_str.split(",") if e.strip()]

    return report_config


def _prompt_e2e_config() -> dict[str, Any]:
    """Prompt for E2E testing configuration."""
    console.print()
    console.print("[bold]4. E2E Testing Configuration[/bold]")
    console.print()

    e2e_config: dict[str, Any] = {
        "enabled": False,
        "base_url": "",
        "auth": {},
    }

    if not click.confirm("Enable E2E testing?", default=False):
        return e2e_config

    e2e_config["enabled"] = True

    base_url = click.prompt(
        "E2E base URL (e.g., http://localhost:3000)",
        default="http://localhost:3000",
    )
    e2e_config["base_url"] = base_url

    if click.confirm("Configure authentication?", default=False):
        auth_config = _prompt_e2e_auth_config()
        e2e_config["auth"] = auth_config

    return e2e_config


def _prompt_e2e_auth_config() -> dict[str, Any]:
    """Prompt for E2E authentication configuration."""
    console.print()
    console.print("Authentication strategies:")
    console.print("  1. form   - Form-based login")
    console.print("  2. token  - Bearer token / API key")
    console.print("  3. cookie - Cookie-based auth")
    console.print("  4. oauth  - OAuth flow")
    console.print("  5. custom - Custom auth script")
    console.print()

    strategy = click.prompt(
        "Select strategy",
        type=click.Choice(["form", "token", "cookie", "oauth", "custom"]),
        default="form",
    )

    auth_config: dict[str, Any] = {"strategy": strategy}

    if strategy == "form":
        auth_config["login_url"] = click.prompt("Login URL")
        auth_config["username"] = click.prompt("Username (or env var like ${TEST_USER})")
        auth_config["password"] = click.prompt(
            "Password (or env var like ${TEST_PASSWORD})", hide_input=True
        )
        auth_config["success_indicator"] = click.prompt(
            "Success indicator (CSS selector or URL pattern)",
            default="",
        )

    elif strategy == "token":
        auth_config["token"] = click.prompt("Token (or env var like ${API_TOKEN})", hide_input=True)
        auth_config["token_header"] = click.prompt("Token header name", default="Authorization")
        auth_config["token_prefix"] = click.prompt("Token prefix", default="Bearer")

    elif strategy == "cookie":
        auth_config["cookie_name"] = click.prompt("Cookie name")
        auth_config["cookie_value"] = click.prompt("Cookie value (or env var)", hide_input=True)

    elif strategy == "custom":
        auth_config["custom_script"] = click.prompt("Path to custom auth script")

    return auth_config


def _prompt_git_config() -> dict[str, Any]:
    """Prompt for git/PR/commit configuration."""
    console.print()
    console.print("[bold]5. Git/PR/Commit Configuration[/bold]")
    console.print()

    git_config: dict[str, Any] = {
        "auto_commit": False,
        "auto_pr": False,
        "create_issues": False,
        "create_fix_prs": False,
        "branch_prefix": "nit/",
        "commit_message_template": "",
    }

    console.print("Configure default behaviors for git operations:")
    console.print("(These can be overridden with CLI flags)")
    console.print()

    git_config["auto_commit"] = click.confirm("Auto-commit generated tests/fixes?", default=False)

    git_config["auto_pr"] = click.confirm(
        "Auto-create PRs for generated tests/fixes?", default=False
    )

    git_config["create_issues"] = click.confirm(
        "Auto-create GitHub issues for detected bugs?", default=False
    )

    git_config["create_fix_prs"] = click.confirm(
        "Auto-create separate PRs for each bug fix?", default=False
    )

    if git_config["auto_pr"] or git_config["create_fix_prs"]:
        branch_prefix = click.prompt(
            "Branch prefix for auto-created branches",
            default="nit/",
        )
        git_config["branch_prefix"] = branch_prefix

    return git_config


def _prompt_coverage_config() -> dict[str, Any]:
    """Prompt for coverage threshold configuration."""
    console.print()
    console.print("[bold]6. Coverage Thresholds[/bold]")
    console.print()
    console.print("[dim]Configure quality gates for coverage analysis[/dim]")
    console.print()

    if not click.confirm("Configure coverage thresholds?", default=True):
        return {
            "line_threshold": 80.0,
            "branch_threshold": 75.0,
            "function_threshold": 85.0,
            "complexity_threshold": 10,
        }

    line_threshold = click.prompt(
        "Line coverage threshold (%)",
        type=float,
        default=80.0,
    )

    branch_threshold = click.prompt(
        "Branch coverage threshold (%)",
        type=float,
        default=75.0,
    )

    function_threshold = click.prompt(
        "Function coverage threshold (%)",
        type=float,
        default=85.0,
    )

    complexity_threshold = click.prompt(
        "Complexity threshold (for prioritization)",
        type=int,
        default=10,
    )

    return {
        "line_threshold": line_threshold,
        "branch_threshold": branch_threshold,
        "function_threshold": function_threshold,
        "complexity_threshold": complexity_threshold,
    }


def _prompt_docs_config() -> dict[str, Any]:
    """Prompt for documentation generation configuration."""
    console.print()
    console.print("[bold]7. Documentation Generation[/bold]")
    console.print()
    console.print("[dim]Configure how nit generates and manages documentation[/dim]")
    console.print()

    docs_config: dict[str, Any] = {
        "enabled": True,
        "output_dir": "",
        "style": "",
        "framework": "",
        "write_to_source": False,
        "check_mismatch": True,
        "exclude_patterns": [],
        "max_tokens": 4096,
    }

    if not click.confirm("Configure documentation generation?", default=True):
        return docs_config

    docs_config["write_to_source"] = click.confirm(
        "Write docstrings back to source files?", default=False
    )

    style = click.prompt(
        "Docstring style preference",
        type=click.Choice(["auto", "google", "numpy"], case_sensitive=False),
        default="auto",
    )
    docs_config["style"] = "" if style == "auto" else style

    framework = click.prompt(
        "Doc framework override",
        type=click.Choice(
            ["auto", "sphinx", "typedoc", "jsdoc", "doxygen", "godoc", "rustdoc", "mkdocs"],
            case_sensitive=False,
        ),
        default="auto",
    )
    docs_config["framework"] = "" if framework == "auto" else framework

    docs_config["check_mismatch"] = click.confirm(
        "Check for documentation/code mismatches?", default=True
    )

    output_dir = click.prompt(
        "Output directory for generated docs (empty for inline only)",
        default="",
    )
    docs_config["output_dir"] = output_dir

    return docs_config


def _prompt_sentry_config() -> dict[str, Any]:
    """Prompt for Sentry observability configuration."""
    console.print()
    console.print("[bold]8. Sentry Observability (optional)[/bold]")
    console.print()

    sentry_config: dict[str, Any] = {
        "enabled": False,
        "dsn": "",
        "traces_sample_rate": 0.0,
        "profiles_sample_rate": 0.0,
        "enable_logs": False,
        "environment": "",
    }

    if not click.confirm("Enable Sentry error tracking?", default=False):
        return sentry_config

    sentry_config["enabled"] = True

    dsn = click.prompt(
        "Sentry DSN (or env var like ${NIT_SENTRY_DSN})",
        default="",
    )
    sentry_config["dsn"] = dsn

    traces_rate = click.prompt(
        "Traces sample rate (0.0-1.0, 0 = disabled)",
        type=float,
        default=0.1,
    )
    sentry_config["traces_sample_rate"] = traces_rate

    profiles_rate = click.prompt(
        "Profiles sample rate (0.0-1.0, 0 = disabled)",
        type=float,
        default=0.0,
    )
    sentry_config["profiles_sample_rate"] = profiles_rate

    sentry_config["enable_logs"] = click.confirm("Send structured logs to Sentry?", default=False)

    environment = click.prompt(
        "Environment tag (leave empty for auto-detect)",
        default="",
    )
    sentry_config["environment"] = environment

    return sentry_config


def _prompt_report_format_config(platform_enabled: bool) -> dict[str, Any]:
    """Prompt for reporting format configuration.

    Args:
        platform_enabled: Whether platform integration is enabled.
    """
    console.print()
    console.print("[bold]6. Report Output Configuration[/bold]")
    console.print()

    report_format_config: dict[str, Any] = {
        "format": "terminal",
        "upload_to_platform": platform_enabled,
        "html_output_dir": ".nit/reports",
        "serve_port": 8080,
    }

    console.print("Configure default report output format:")
    console.print("  1. terminal - Rich terminal output (default)")
    console.print("  2. json     - JSON format")
    console.print("  3. html     - HTML reports")
    console.print("  4. markdown - Markdown format")
    console.print()

    format_choice = click.prompt(
        "Select default format",
        type=click.Choice(["terminal", "json", "html", "markdown"]),
        default="terminal",
    )
    report_format_config["format"] = format_choice

    if format_choice == "html":
        html_dir = click.prompt(
            "HTML output directory",
            default=".nit/reports",
        )
        report_format_config["html_output_dir"] = html_dir

        serve_port = click.prompt(
            "Port for serving HTML reports (--serve)",
            type=int,
            default=8080,
        )
        report_format_config["serve_port"] = serve_port

    if platform_enabled:
        console.print()
        console.print(
            "[dim]Platform integration is enabled - reports will be uploaded by default[/dim]"
        )
        upload = click.confirm(
            "Upload reports to platform by default?",
            default=True,
        )
        report_format_config["upload_to_platform"] = upload

    return report_format_config


def _prompt_advanced_llm_config(base_config: dict[str, Any]) -> dict[str, Any]:
    """Prompt for advanced LLM settings."""
    console.print()
    console.print("[bold]Advanced LLM Settings[/bold]")
    console.print()

    config = base_config.copy()

    temperature = click.prompt(
        "Temperature (0.0 = deterministic, 2.0 = creative)",
        type=float,
        default=0.2,
    )
    config["temperature"] = temperature

    max_tokens = click.prompt(
        "Max tokens per request",
        type=int,
        default=4096,
    )
    config["max_tokens"] = max_tokens

    requests_per_minute = click.prompt(
        "Rate limit (requests per minute)",
        type=int,
        default=60,
    )
    config["requests_per_minute"] = requests_per_minute

    max_retries = click.prompt(
        "Max retries on failure",
        type=int,
        default=3,
    )
    config["max_retries"] = max_retries

    return config


def _select_llm_init_config() -> dict[str, Any]:
    """Prompt for LLM setup choice in interactive mode (legacy function)."""
    if not _is_interactive_terminal():
        return _default_builtin_llm_init_config()

    choices: list[tuple[str, dict[str, Any]]] = [
        ("Built-in (API key) — Claude, GPT, Gemini, OpenRouter, etc.", {}),
        ("Claude Code CLI — uses your installed `claude` command", _claude_cli_llm_init_config()),
        ("Codex CLI — uses OpenAI's `codex` command", _codex_cli_llm_init_config()),
        ("Ollama (local) — run models on your machine", _ollama_llm_init_config()),
        (
            "LM Studio (local) — OpenAI-compatible local server",
            {
                "mode": "builtin",
                "provider": "openai",
                "model": "",
                "api_key": "",
                "base_url": "http://localhost:1234/v1",
            },
        ),
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

    if not config:
        config = _prompt_builtin_provider()

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
        lines.append(f"  provider: {provider}   # openai | anthropic | gemini | openrouter | ...")
        lines.append(f"  model: {_format_yaml_string(model)}")
        lines.append(f"  api_key: {_format_yaml_string(api_key)}  # or set NIT_LLM_API_KEY env var")
        lines.append(f"  base_url: {_format_yaml_string(base_url)}")

        # Add optional advanced settings if present
        if "temperature" in llm_config:
            lines.append(f"  temperature: {llm_config['temperature']}")
        if "max_tokens" in llm_config:
            lines.append(f"  max_tokens: {llm_config['max_tokens']}")
        if "requests_per_minute" in llm_config:
            lines.append(f"  requests_per_minute: {llm_config['requests_per_minute']}")
        if "max_retries" in llm_config:
            lines.append(f"  max_retries: {llm_config['max_retries']}")

        return lines

    lines.append(f"  provider: {provider}   # openai | anthropic | gemini | openrouter | ...")
    lines.append(f"  model: {_format_yaml_string(model)}")
    lines.append(f"  cli_command: {_format_yaml_string(cli_command)}")
    lines.append(f"  cli_timeout: {cli_timeout}")

    if cli_extra_args:
        lines.append("  cli_extra_args:")
        lines.extend(f"    - {_format_yaml_string(arg)}" for arg in cli_extra_args)
    else:
        lines.append("  cli_extra_args: []")

    return lines


def _render_platform_section(platform_config: dict[str, Any]) -> list[str]:
    """Render platform integration config lines for ``.nit.yml``."""
    mode = str(platform_config.get("mode", "disabled"))
    url = str(platform_config.get("url", ""))
    reporting_api_key = str(platform_config.get("reporting_api_key", ""))
    user_id = str(platform_config.get("user_id", ""))
    project_id = str(platform_config.get("project_id", ""))

    lines = [
        "platform:",
        f"  mode: {mode}  # byok | disabled",
        f"  url: {_format_yaml_string(url)}  # or set NIT_PLATFORM_URL env var",
    ]

    if reporting_api_key:
        lines.append(f"  reporting_api_key: {_format_yaml_string(reporting_api_key)}")
        lines.append("  # Platform reporting key")

    if project_id:
        lines.append(f"  project_id: {_format_yaml_string(project_id)}")

    if user_id:
        lines.append(f"  user_id: {_format_yaml_string(user_id)}")

    return lines


def _render_git_section(git_config: dict[str, Any]) -> list[str]:
    """Render git/PR/commit config lines for ``.nit.yml``."""
    auto_commit = str(git_config.get("auto_commit", False)).lower()
    auto_pr = str(git_config.get("auto_pr", False)).lower()
    create_issues = str(git_config.get("create_issues", False)).lower()
    create_fix_prs = str(git_config.get("create_fix_prs", False)).lower()
    branch_prefix = _format_yaml_string(git_config.get("branch_prefix", "nit/"))

    lines = [
        "git:",
        f"  auto_commit: {auto_commit}  # Auto-commit changes",
        f"  auto_pr: {auto_pr}  # Auto-create PRs",
        f"  create_issues: {create_issues}  # Auto-create issues",
        f"  create_fix_prs: {create_fix_prs}  # Auto-create fix PRs",
        f"  branch_prefix: {branch_prefix}  # Branch prefix",
    ]

    commit_template = str(git_config.get("commit_message_template", ""))
    if commit_template:
        lines.append(f"  commit_message_template: {_format_yaml_string(commit_template)}")

    return lines


def _render_report_section(report_config: dict[str, Any]) -> list[str]:
    """Render reporting config lines for ``.nit.yml``."""
    slack_webhook = str(report_config.get("slack_webhook", ""))
    email_alerts = report_config.get("email_alerts", [])
    format_type = str(report_config.get("format", "terminal"))
    upload_to_platform = bool(report_config.get("upload_to_platform", True))
    html_output_dir = str(report_config.get("html_output_dir", ".nit/reports"))
    serve_port = int(report_config.get("serve_port", 8080))

    upload_str = str(upload_to_platform).lower()
    lines = [
        "report:",
        f"  format: {format_type}  # terminal | json | html | markdown",
        f"  upload_to_platform: {upload_str}  # Upload when configured",
    ]

    if format_type == "html":
        lines.append(f"  html_output_dir: {_format_yaml_string(html_output_dir)}")
        lines.append(f"  serve_port: {serve_port}")

    if slack_webhook:
        lines.append(f"  slack_webhook: {_format_yaml_string(slack_webhook)}")

    if email_alerts:
        lines.append("  email_alerts:")
        lines.extend(f"    - {_format_yaml_string(email)}" for email in email_alerts)

    return lines


def _render_e2e_section(e2e_config: dict[str, Any]) -> list[str]:
    """Render E2E config lines for ``.nit.yml``."""
    enabled = bool(e2e_config.get("enabled", False))
    base_url = str(e2e_config.get("base_url", ""))
    auth = e2e_config.get("auth", {})

    lines = [
        "e2e:",
        f"  enabled: {str(enabled).lower()}",
    ]

    if base_url:
        lines.append(f"  base_url: {_format_yaml_string(base_url)}")

    if auth:
        lines.append("  auth:")
        strategy = str(auth.get("strategy", ""))
        if strategy:
            lines.append(f"    strategy: {strategy}")

        # Add strategy-specific fields
        if strategy == "form":
            if auth.get("login_url"):
                lines.append(f"    login_url: {_format_yaml_string(auth['login_url'])}")
            if auth.get("username"):
                lines.append(f"    username: {_format_yaml_string(auth['username'])}")
            if auth.get("password"):
                lines.append(f"    password: {_format_yaml_string(auth['password'])}")
            if auth.get("success_indicator"):
                lines.append(
                    f"    success_indicator: {_format_yaml_string(auth['success_indicator'])}"
                )

        elif strategy == "token":
            if auth.get("token"):
                lines.append(f"    token: {_format_yaml_string(auth['token'])}")
            if auth.get("token_header"):
                lines.append(f"    token_header: {_format_yaml_string(auth['token_header'])}")
            if auth.get("token_prefix"):
                lines.append(f"    token_prefix: {_format_yaml_string(auth['token_prefix'])}")

        elif strategy == "cookie":
            if auth.get("cookie_name"):
                lines.append(f"    cookie_name: {_format_yaml_string(auth['cookie_name'])}")
            if auth.get("cookie_value"):
                lines.append(f"    cookie_value: {_format_yaml_string(auth['cookie_value'])}")

        elif strategy == "custom":
            if auth.get("custom_script"):
                lines.append(f"    custom_script: {_format_yaml_string(auth['custom_script'])}")

    return lines


def _render_coverage_section(coverage_config: dict[str, Any]) -> list[str]:
    """Render coverage threshold config lines for ``.nit.yml``."""
    lines = ["coverage:"]

    line_threshold = float(coverage_config.get("line_threshold", 80.0))
    branch_threshold = float(coverage_config.get("branch_threshold", 75.0))
    function_threshold = float(coverage_config.get("function_threshold", 85.0))
    complexity_threshold = int(coverage_config.get("complexity_threshold", 10))
    undertested_threshold = float(coverage_config.get("undertested_threshold", 50.0))

    lines.append(f"  line_threshold: {line_threshold}")
    lines.append(f"  branch_threshold: {branch_threshold}")
    lines.append(f"  function_threshold: {function_threshold}")
    lines.append(f"  complexity_threshold: {complexity_threshold}")
    lines.append(f"  undertested_threshold: {undertested_threshold}")

    return lines


def _render_docs_section(docs_config: dict[str, Any]) -> list[str]:
    """Render documentation generation config lines for ``.nit.yml``."""
    enabled = bool(docs_config.get("enabled", True))
    output_dir = str(docs_config.get("output_dir", ""))
    style = str(docs_config.get("style", ""))
    framework = str(docs_config.get("framework", ""))
    write_to_source = bool(docs_config.get("write_to_source", False))
    check_mismatch = bool(docs_config.get("check_mismatch", True))
    exclude_patterns = docs_config.get("exclude_patterns", [])
    max_tokens = int(docs_config.get("max_tokens", 4096))

    write_str = str(write_to_source).lower()
    mismatch_str = str(check_mismatch).lower()
    lines = [
        "docs:",
        f"  enabled: {str(enabled).lower()}",
        f"  write_to_source: {write_str}  # Write docstrings back to source",
        f"  check_mismatch: {mismatch_str}  # Detect doc/code mismatches",
    ]

    if style:
        lines.append(f"  style: {_format_yaml_string(style)}  # google | numpy | (empty for auto)")
    else:
        lines.append('  style: ""  # google | numpy | (empty for auto-detect)')

    if framework:
        lines.append(
            f"  framework: {_format_yaml_string(framework)}"
            "  # sphinx | typedoc | jsdoc | doxygen | godoc | rustdoc | mkdocs"
        )
    else:
        lines.append('  framework: ""  # auto-detect from language')

    if output_dir:
        lines.append(f"  output_dir: {_format_yaml_string(output_dir)}  # Output directory")
    else:
        lines.append('  output_dir: ""  # Empty = inline docstrings only')

    lines.append(f"  max_tokens: {max_tokens}  # Token budget per file")

    if exclude_patterns and isinstance(exclude_patterns, list):
        lines.append("  exclude_patterns:")
        lines.extend(f"    - {_format_yaml_string(pat)}" for pat in exclude_patterns)
    else:
        lines.append("  exclude_patterns: []")

    return lines


def _render_sentry_section(sentry_config: dict[str, Any]) -> list[str]:
    """Render Sentry observability config lines for ``.nit.yml``."""
    enabled = bool(sentry_config.get("enabled", False))
    dsn = str(sentry_config.get("dsn", ""))
    traces_rate = float(sentry_config.get("traces_sample_rate", 0.0))
    profiles_rate = float(sentry_config.get("profiles_sample_rate", 0.0))
    enable_logs = bool(sentry_config.get("enable_logs", False))
    environment = str(sentry_config.get("environment", ""))

    lines = [
        "sentry:",
        f"  enabled: {str(enabled).lower()}",
    ]

    if dsn:
        lines.append(f"  dsn: {_format_yaml_string(dsn)}")

    lines.append(f"  traces_sample_rate: {traces_rate}")
    lines.append(f"  profiles_sample_rate: {profiles_rate}")
    lines.append(f"  enable_logs: {str(enable_logs).lower()}")

    if environment:
        lines.append(f"  environment: {_format_yaml_string(environment)}")

    return lines


def _write_comprehensive_nit_yml(profile: ProjectProfile, config_dict: dict[str, Any]) -> Path:
    """Write a comprehensive ``.nit.yml`` configuration file with all sections."""
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
    llm_config = config_dict.get("llm", _default_builtin_llm_init_config())
    lines.extend(_render_llm_section(llm_config))
    lines.append("")

    # Platform configuration
    platform_config = config_dict.get("platform", {})
    if platform_config.get("mode") and platform_config["mode"] != "disabled":
        lines.extend(_render_platform_section(platform_config))
        lines.append("")

    # Git configuration
    git_config = config_dict.get("git", {})
    if git_config:
        lines.extend(_render_git_section(git_config))
        lines.append("")

    # Report configuration
    report_config = config_dict.get("report", {})
    if report_config:
        lines.extend(_render_report_section(report_config))
        lines.append("")

    # E2E configuration
    e2e_config = config_dict.get("e2e", {})
    if e2e_config.get("enabled"):
        lines.extend(_render_e2e_section(e2e_config))
        lines.append("")

    # Coverage configuration
    coverage_config = config_dict.get("coverage", {})
    if coverage_config:
        lines.extend(_render_coverage_section(coverage_config))
        lines.append("")

    # Documentation configuration
    docs_config = config_dict.get("docs", {})
    if docs_config:
        lines.extend(_render_docs_section(docs_config))
        lines.append("")

    # Sentry configuration
    sentry_config = config_dict.get("sentry", {})
    if sentry_config.get("enabled"):
        lines.extend(_render_sentry_section(sentry_config))
        lines.append("")

    nit_yml.write_text("\n".join(lines), encoding="utf-8")
    return nit_yml


def _write_nit_yml(profile: ProjectProfile, llm_config: dict[str, Any] | None = None) -> Path:
    """Write a minimal ``.nit.yml`` configuration file (legacy function)."""
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


def _init_sentry_from_env() -> None:
    """Initialize Sentry from environment variables (pre-config-load).

    Provides early error capture even before ``.nit.yml`` is parsed.
    Full config-based init happens when ``load_config()`` runs in commands.
    """
    from nit.config import SentryConfig
    from nit.telemetry.sentry_integration import init_sentry

    enabled_raw = os.environ.get("NIT_SENTRY_ENABLED", "").strip().lower()
    if enabled_raw not in {"1", "true", "yes"}:
        return

    dsn = os.environ.get("NIT_SENTRY_DSN", "").strip()
    if not dsn:
        return

    config = SentryConfig(
        enabled=True,
        dsn=dsn,
        traces_sample_rate=float(os.environ.get("NIT_SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        profiles_sample_rate=float(os.environ.get("NIT_SENTRY_PROFILES_SAMPLE_RATE", "0.0")),
        enable_logs=os.environ.get("NIT_SENTRY_ENABLE_LOGS", "").strip().lower()
        in {"1", "true", "yes"},
    )
    init_sentry(config)


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
    _init_sentry_from_env()


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
      nit config set platform.url https://platform.getnit.dev
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


@config_group.command("show")
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--json-output",
    "as_json",
    is_flag=True,
    help="Output as JSON instead of YAML.",
)
@click.option(
    "--no-mask",
    is_flag=True,
    help="Show sensitive values unmasked (use with caution).",
)
def config_show(path: str, *, as_json: bool, no_mask: bool) -> None:
    """Display resolved configuration with masked sensitive values.

    Shows the complete configuration with environment variables resolved.
    Sensitive fields (API keys, passwords, tokens) are masked by default.

    Example:
      nit config show
      nit config show --json-output
      nit config show --no-mask  # Show unmasked values
    """
    try:
        config = load_config(path)
    except Exception as e:
        reporter.print_error(f"Failed to load configuration: {e}")
        raise click.Abort from e

    # Convert to dict
    config_dict = _config_to_dict(config)

    # Mask sensitive values unless --no-mask is specified
    if not no_mask:
        config_dict = _mask_sensitive_values(config_dict)

    # Output format
    if as_json:
        click.echo(json.dumps(config_dict, indent=2))
    else:
        console.print()
        console.print("[bold cyan]Configuration:[/bold cyan]")
        console.print()
        click.echo(yaml.safe_dump(config_dict, sort_keys=False, default_flow_style=False))


@config_group.command("validate")
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
def config_validate(path: str) -> None:
    """Validate `.nit.yml` configuration against schema.

    Checks for missing required fields, invalid values, and configuration errors.

    Example:
      nit config validate
    """
    try:
        config = load_config(path)
    except Exception as e:
        reporter.print_error(f"Failed to load configuration: {e}")
        raise click.Abort from e

    # Validate configuration
    errors = validate_config(config)

    if not errors:
        reporter.print_success("Configuration is valid!")
        console.print()
        console.print("[dim]All configuration checks passed.[/dim]")
        return

    # Display errors
    reporter.print_error(f"Found {len(errors)} configuration error(s):")
    console.print()

    for idx, error in enumerate(errors, start=1):
        console.print(f"  {idx}. [red]{error}[/red]")

    console.print()
    console.print("[dim]Fix these errors in .nit.yml and run 'nit config validate' again.[/dim]")
    raise click.Abort


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--quick",
    is_flag=True,
    help="Quick mode: use defaults without prompting (for CI/automation).",
)
@click.option(
    "--linear",
    is_flag=True,
    help="Use classic linear prompt mode instead of modern TUI.",
)
@click.option(
    "--auto",
    is_flag=True,
    help="Auto-detect environment (API keys, CLI tools, services) with zero prompts.",
)
def init(path: str, *, quick: bool, linear: bool, auto: bool) -> None:
    """Detect stack, create .nit.yml config and .nit/profile.json.

    Interactive setup that configures:
    - Project detection (languages, frameworks, workspace)
    - LLM provider and model
    - API key management (BYOK vs platform-managed)
    - Platform integration and reporting
    - Reporting preferences (Slack, email)
    - E2E testing configuration
    - Advanced LLM settings

    Default: Modern TUI interface with all options visible at once.
    Use --linear for classic sequential prompts.
    Use --quick for non-interactive mode with sensible defaults.
    """
    console.print(f"[bold]Scanning[/bold] {path} ...")

    profile = _build_profile(path)
    saved = save_profile(profile)

    _display_profile(profile)

    # Comprehensive interactive configuration
    if auto:
        from nit.auto_init import build_auto_config

        config_dict = build_auto_config(Path(path))
    elif quick or not _is_interactive_terminal():
        # Quick mode: use defaults
        config_dict = _build_default_config()
    elif linear:
        # Linear mode: classic sequential prompts
        config_dict = _interactive_config_setup()
    else:
        # TUI mode (DEFAULT): modern 2D interface
        from nit.tui_init import run_tui_init

        console.print()
        console.print("[bold cyan]Launching interactive configuration panel...[/bold cyan]")
        console.print("[dim]Tip: Use Tab/Arrow keys to navigate, Enter to select[/dim]")
        console.print()

        result = run_tui_init(Path(path))
        if result is None:
            # User cancelled
            reporter.print_warning("Configuration cancelled by user")
            raise click.Abort
        config_dict = result

    nit_yml = _write_comprehensive_nit_yml(profile, config_dict)
    console.print()
    console.print(f"[green]Config written to[/green]  {nit_yml}")
    console.print(f"[green]Profile saved to[/green]  {saved}")

    # Auto-generate drift test skeleton if LLM usage is detected
    if profile.llm_usage_count > 0:
        try:
            from nit.agents.detectors.llm_usage import LLMUsageDetector, LLMUsageProfile

            detector = LLMUsageDetector()
            llm_profile = LLMUsageProfile(
                total_usages=profile.llm_usage_count,
                providers=set(profile.llm_providers),
            )
            # Re-scan to get full location data for drift test generation
            from nit.agents.base import TaskInput

            task = TaskInput(task_type="detect_llm_usage", target=str(Path(path).resolve()))
            det_result = asyncio.run(detector.run(task))
            if det_result.status == TaskStatus.COMPLETED:
                locations = det_result.result.get("locations", [])
                for loc in locations:
                    from nit.agents.detectors.llm_usage import LLMUsageLocation

                    llm_profile.add_location(
                        LLMUsageLocation(
                            file_path=Path(loc["file_path"]),
                            line_number=loc["line_number"],
                            usage_type=loc["usage_type"],
                            provider=loc["provider"],
                            function_name=loc.get("function_name"),
                            endpoint_url=loc.get("endpoint_url"),
                            context=loc.get("context", ""),
                        )
                    )
                candidates = detector.generate_drift_test_candidates(llm_profile)
                if candidates:
                    drift_tests_path = Path(path) / ".nit" / "drift-tests.yml"
                    if not drift_tests_path.exists():
                        detector.generate_drift_test_skeleton(candidates, drift_tests_path)
                        console.print(
                            f"\n[green]Generated drift test skeleton:[/green] {drift_tests_path}"
                        )
                        console.print(
                            f"  Found {len(candidates)} LLM integration(s) — "
                            "edit the skeleton to configure baselines"
                        )
        except Exception as exc:
            logger.debug("Drift test skeleton generation skipped: %s", exc)

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
def scan(**kwargs: Unpack[_ScanKwargs]) -> None:
    """Detect languages, frameworks, and workspace structure.

    Creates/updates .nit/profile.json with project metadata.
    Use --force to ignore cache and re-scan from scratch.

    Alias: pick (as in "nitpick through the codebase")

    Next: Run 'nit analyze' to see coverage gaps and bugs
    """
    path = kwargs["path"]
    force = kwargs["force"]
    as_json = kwargs["as_json"]
    diff = kwargs["diff"]
    base_ref = kwargs["base_ref"]
    compare_ref = kwargs["compare_ref"]

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
    """Generate tests for coverage gaps identified by 'nit analyze'.

    Run 'nit analyze' first to see what will be generated.

    Options:
      --type unit/e2e/integration/all
      --file PATH        Generate for specific file
      --coverage-target N  Target coverage percentage

    Note: Currently a stub - implementation pending.
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

    asyncio.run(
        _run_generate(
            path=path,
            profile=profile,
            test_type=test_type,
            target_file=target_file,
            coverage_target=coverage_target,
            ci_mode=ci_mode,
        )
    )


async def _run_generate(**kwargs: Any) -> None:
    """Run the test generation pipeline.

    Analyzes coverage gaps and generates tests using UnitBuilder,
    E2EBuilder, and IntegrationBuilder agents.
    """
    from nit.agents.analyzers.coverage import CoverageAnalysisTask, CoverageAnalyzer
    from nit.agents.builders.infra import BootstrapTask, InfraBuilder
    from nit.agents.builders.integration import IntegrationBuilder, IntegrationBuildTask
    from nit.agents.builders.unit import BuildTask, UnitBuilder

    path: str = kwargs["path"]
    profile: ProjectProfile = kwargs["profile"]
    test_type: str = kwargs["test_type"]
    target_file: str | None = kwargs.get("target_file")
    coverage_target: int | None = kwargs.get("coverage_target")
    ci_mode: bool = kwargs.get("ci_mode", False)

    project_root = Path(path).resolve()

    # Get adapters
    adapters = _get_test_adapters(profile)
    primary_adapter = adapters[0]
    framework_name = primary_adapter.name

    # Check if test infrastructure exists; if not, bootstrap it
    if not primary_adapter.detect(project_root):
        reporter.print_info(f"No {framework_name} infrastructure detected — bootstrapping...")
        infra_builder = InfraBuilder(project_root)
        language = profile.primary_language or "unknown"
        bootstrap_task = BootstrapTask(
            framework=framework_name,
            language=language,
            project_path=str(project_root),
        )
        bootstrap_result = await infra_builder.run(bootstrap_task)
        if bootstrap_result.status == TaskStatus.COMPLETED:
            actions = bootstrap_result.result.get("actions", [])
            reporter.print_success(f"Bootstrapped {framework_name} with {len(actions)} action(s)")
        else:
            reporter.print_error(f"Bootstrap failed: {bootstrap_result.errors}")
            return

    # Create LLM engine
    llm_config = load_llm_config(str(project_root))
    engine = create_engine(llm_config)

    # Run coverage analysis to identify gaps
    reporter.print_info("Analyzing coverage gaps...")
    analyzer = CoverageAnalyzer(project_root)
    analysis_task = CoverageAnalysisTask(
        project_root=str(project_root),
        coverage_threshold=float(coverage_target or 80),
    )
    analysis_output = await analyzer.run(analysis_task)

    if analysis_output.status != TaskStatus.COMPLETED:
        reporter.print_warning(
            "Coverage analysis could not run (no coverage adapter detected). "
            "Generating tests for all source files."
        )
        build_tasks: list[BuildTask] = []
    else:
        build_tasks = analysis_output.result.get("build_tasks", [])
        gap_report = analysis_output.result.get("gap_report")
        if gap_report:
            reporter.print_info(
                f"Found {len(gap_report.untested_files)} untested file(s), "
                f"{len(gap_report.function_gaps)} function gap(s)"
            )

    # Filter by target_file if specified
    if target_file:
        build_tasks = [t for t in build_tasks if target_file in t.source_file]
        reporter.print_info(f"Filtered to {len(build_tasks)} task(s) matching {target_file}")

    if not build_tasks:
        reporter.print_success("No coverage gaps found — nothing to generate!")
        return

    # Generate tests
    generated_files: list[str] = []
    failed_count = 0
    unit_builder = UnitBuilder(engine, project_root, enable_memory=True)

    integration_builder: IntegrationBuilder | None = None
    if test_type in ("integration", "all"):
        integration_builder = IntegrationBuilder(engine, project_root, enable_memory=True)

    for task in build_tasks:
        # Set framework on the task
        if not task.framework:
            task.framework = framework_name

        # Determine output path
        output_path = _determine_test_output_path(task.source_file, primary_adapter, project_root)
        task.output_file = str(output_path)

        if test_type == "integration" and integration_builder:
            # Run integration builder
            int_task = IntegrationBuildTask(
                source_file=task.source_file,
                framework=task.framework,
                output_file=task.output_file,
            )
            result = await integration_builder.run(int_task)
        elif test_type in ("unit", "all"):
            result = await unit_builder.run(task)
        else:
            result = await unit_builder.run(task)

        if result.status == TaskStatus.COMPLETED:
            test_code = result.result.get("test_code", "")
            if test_code:
                out = Path(task.output_file)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(test_code, encoding="utf-8")
                generated_files.append(str(out.relative_to(project_root)))
                if not ci_mode:
                    reporter.print_success(f"Generated: {out.relative_to(project_root)}")
        else:
            failed_count += 1
            errors = result.errors or ["Unknown error"]
            if not ci_mode:
                reporter.print_warning(
                    f"Failed to generate test for {task.source_file}: {errors[0]}"
                )

    # Summary
    console.print()
    reporter.print_info(f"Generated {len(generated_files)} test file(s), {failed_count} failed")
    for f in generated_files:
        console.print(f"  [green]✓[/green] {f}")


def _determine_test_output_path(
    source_file: str, adapter: TestFrameworkAdapter, project_root: Path
) -> Path:
    """Compute the test file path from a source file path using adapter conventions."""
    source_path = Path(source_file)
    source_name = source_path.stem
    source_dir = source_path.parent

    # Get file extension/pattern from adapter
    patterns = adapter.get_test_pattern()
    if patterns:
        pattern = patterns[0]
        if pattern.endswith(".py"):
            test_name = f"test_{source_name}.py"
        elif pattern.endswith(".test.ts"):
            test_name = f"{source_name}.test.ts"
        elif pattern.endswith(".spec.ts"):
            test_name = f"{source_name}.spec.ts"
        elif pattern.endswith(".test.js"):
            test_name = f"{source_name}.test.js"
        elif pattern.endswith(".test.jsx"):
            test_name = f"{source_name}.test.jsx"
        elif pattern.endswith(".test.tsx"):
            test_name = f"{source_name}.test.tsx"
        else:
            test_name = f"test_{source_name}.py"
    else:
        test_name = f"test_{source_name}.py"

    # Place test files in a parallel tests/ directory or alongside source
    # Check if there's already a tests/ directory
    tests_dir = project_root / "tests"
    if tests_dir.exists():
        return tests_dir / test_name

    # Otherwise place alongside the source file
    return project_root / source_dir / test_name


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
@click.option(
    "--shard-index",
    type=int,
    default=None,
    help="Zero-based shard index for parallel test execution (requires --shard-count).",
)
@click.option(
    "--shard-count",
    type=int,
    default=None,
    help="Total number of shards for parallel test execution.",
)
@click.option(
    "--shard-output",
    type=click.Path(dir_okay=False),
    default=None,
    help="Path to write shard result JSON (default: .nit/shard-result-{index}.json).",
)
@click.option(
    "--parallel/--no-parallel",
    default=True,
    help="Automatically shard tests for parallel execution.",
)
def run(**kwargs: Any) -> None:
    """Run full test suite via detected adapter(s).

    Executes tests using the detected testing framework(s) and displays
    results with optional coverage reporting.  Use --shard-index and
    --shard-count for parallel sharded execution.
    """
    path: str = kwargs["path"]
    coverage: bool = kwargs["coverage"]
    package_path: str | None = kwargs.get("package_path")
    shard_index: int | None = kwargs.get("shard_index")
    shard_count: int | None = kwargs.get("shard_count")
    shard_output: str | None = kwargs.get("shard_output")
    parallel: bool = kwargs.get("parallel", True)

    ctx = click.get_current_context()
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    # Validate shard options
    if (shard_index is None) != (shard_count is None):
        raise click.UsageError("--shard-index and --shard-count must be used together.")

    if not ci_mode:
        reporter.print_header("nit run")

    # Load configuration
    try:
        load_config(path)
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

    # Check prerequisites before running tests
    from nit.cli_helpers import check_and_install_prerequisites

    prereqs_ok = asyncio.run(
        check_and_install_prerequisites(adapter, project_path, ci_mode=ci_mode)
    )
    if not prereqs_ok:
        reporter.print_error("Prerequisites not satisfied. Please install required dependencies.")
        raise click.Abort

    # Determine test files for this shard (if sharding enabled)
    test_files: list[Path] | None = None
    if shard_index is not None and shard_count is not None:
        from nit.sharding.splitter import discover_test_files, split_into_shards

        try:
            all_test_files = discover_test_files(project_path, adapter.get_test_pattern())
            test_files = split_into_shards(all_test_files, shard_index, shard_count)
        except ValueError as e:
            raise click.UsageError(str(e)) from e

        reporter.print_info(
            f"Shard {shard_index}/{shard_count}: running {len(test_files)} of "
            f"{len(all_test_files)} test files"
        )

    try:
        # Use parallel runner when --parallel is set and no manual sharding
        if parallel and shard_index is None and test_files is None:
            from nit.sharding.parallel_runner import run_tests_parallel

            result = asyncio.run(run_tests_parallel(adapter, project_path))
        else:
            result = asyncio.run(adapter.run_tests(project_path, test_files=test_files))

        # Write shard result if sharding is enabled
        if shard_index is not None and shard_count is not None:
            from nit.sharding.shard_result import write_shard_result

            output_path = Path(shard_output or f".nit/shard-result-{shard_index}.json")
            write_shard_result(result, output_path, shard_index, shard_count, adapter.name)
            reporter.print_info(f"Shard result written to {output_path}")

        # Display results
        if ci_mode:
            _display_test_results_json(result)
        else:
            _display_test_results_console(result)

        # Exit with appropriate code
        if not result.success:
            if not ci_mode:
                console.print()
                # Show diagnostic info if no tests ran but execution failed
                if result.total == 0 and result.raw_output:
                    reporter.print_error("Test execution failed with no tests run.")
                    reporter.print_info("Check the output above for errors.")
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
@click.argument(
    "shard_files",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False),
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Path to write combined result JSON.",
)
def combine(shard_files: tuple[str, ...], output_path: str | None) -> None:
    """Combine shard results from parallel test runs.

    Reads shard result JSON files produced by 'nit run --shard-index/--shard-count',
    merges test results and coverage reports, and outputs the combined report.
    """
    from nit.sharding.merger import merge_run_results
    from nit.sharding.shard_result import read_shard_result, write_shard_result

    reporter.print_header("nit combine")

    results: list[RunResult] = []
    adapter_names: set[str] = set()

    for sf in shard_files:
        try:
            result, metadata = read_shard_result(Path(sf))
            results.append(result)
            adapter_names.add(metadata["adapter_name"])
            reporter.print_info(
                f"Loaded shard {metadata['shard_index']}/{metadata['shard_count']} "
                f"from {sf} ({result.total} tests)"
            )
        except Exception as e:
            reporter.print_error(f"Failed to read shard file {sf}: {e}")
            raise click.Abort from e

    if len(adapter_names) > 1:
        reporter.print_warning(
            f"Warning: shards used different adapters: {', '.join(sorted(adapter_names))}"
        )

    merged = merge_run_results(results)

    # Write combined result if output path specified
    if output_path is not None:
        write_shard_result(
            merged,
            Path(output_path),
            shard_index=0,
            shard_count=len(results),
            adapter_name=next(iter(adapter_names)),
        )
        reporter.print_info(f"Combined result written to {output_path}")

    # Display combined results
    _display_test_results_console(merged)

    if merged.coverage is not None:
        reporter.print_info(
            f"Combined coverage: {merged.coverage.overall_line_coverage:.1f}% lines"
        )

    if not merged.success:
        reporter.print_error(
            f"Combined result: {merged.failed} failed, {merged.errors} errors "
            f"out of {merged.total} tests"
        )
        raise click.Abort

    reporter.print_success(f"All {merged.total} tests passed across {len(results)} shards!")


async def _run_pick_pipeline(config: PickPipelineConfig) -> None:
    """Execute the full pick pipeline using the refactored PickPipeline class.

    Args:
        config: Pick pipeline configuration.
    """
    pipeline = PickPipeline(config)
    result = await pipeline.run()

    # Display results
    if not config.ci_mode:
        _display_pick_results(result, config.fix_enabled)

    if not result.success:
        raise click.Abort


async def _run_pick_pipeline_with_result(config: PickPipelineConfig) -> PickPipelineResult:
    """Execute the full pick pipeline and return the result.

    Args:
        config: Pick pipeline configuration.

    Returns:
        The pipeline execution result.
    """
    pipeline = PickPipeline(config)
    result = await pipeline.run()

    # Display results
    if not config.ci_mode:
        _display_pick_results(result, config.fix_enabled)

    if not result.success:
        raise click.Abort

    return result


def _display_pick_results(result: PickPipelineResult, fix_enabled: bool) -> None:
    """Display pick pipeline results in console format."""
    console.print()
    console.print("[bold cyan]── Results ─────────────────────────────────────[/bold cyan]")
    console.print()

    # Test results summary bar
    total = result.tests_run
    skipped = total - result.tests_passed - result.tests_failed - result.tests_errors
    reporter.print_test_summary_bar(
        result.tests_passed,
        result.tests_failed,
        max(skipped, 0),
        result.tests_errors,
        0.0,  # duration already shown during pipeline
    )

    # Bug results
    if result.bugs_found:
        bug_table = Table(
            title=f"Bugs Found ({len(result.bugs_found)})",
            title_style="bold red",
            show_edge=False,
            pad_edge=False,
        )
        bug_table.add_column("Bug", style="bold")
        bug_table.add_column("Severity", justify="center")
        max_display = 8
        for bug in result.bugs_found[:max_display]:
            sev = bug.severity.value
            sev_color = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "dim"}.get(sev, "yellow")
            bug_table.add_row(bug.title, f"[{sev_color}]{sev}[/{sev_color}]")
        if len(result.bugs_found) > max_display:
            bug_table.add_row(f"[dim]... and {len(result.bugs_found) - max_display} more[/dim]", "")
        console.print(bug_table)
        console.print()
    else:
        reporter.print_success("No bugs found")
        console.print()

    # Coverage gap analysis
    if result.gap_report:
        reporter.print_semantic_gap_analysis(result.gap_report)
        console.print()

    # Fix results
    if fix_enabled:
        if result.fixes_applied:
            console.print(f"[bold green]Fixes Applied:[/bold green] {len(result.fixes_applied)}")
            max_display = 5
            for file_path in result.fixes_applied[:max_display]:
                console.print(f"  [green]✓[/green] {file_path}")
            if len(result.fixes_applied) > max_display:
                console.print(
                    f"  [dim]... and {len(result.fixes_applied) - max_display} more[/dim]"
                )
            console.print()
        else:
            console.print("[dim]No fixes applied[/dim]")
            console.print()

    # PR result
    if result.pr_created and result.pr_url:
        console.print(f"[bold]Pull Request:[/bold] {result.pr_url}")
        console.print()

    # Final status
    if result.success:
        if result.bugs_found or result.fixes_applied:
            reporter.print_success("Pick pipeline completed successfully")
        else:
            reporter.print_success("Pick completed - no bugs found")
    else:
        reporter.print_error("Pick pipeline failed")
        for error in result.errors:
            reporter.print_error(f"  {error}")


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
    "--fix/--no-fix",
    default=None,
    help="Generate and apply fixes for found bugs (uses config default if not specified).",
)
@click.option(
    "--report/--no-report",
    "upload_report",
    default=None,
    help="Upload pick run summary to platform (default: auto based on platform config).",
)
@click.option(
    "--pr/--no-pr",
    "create_pr",
    default=None,
    help="Create GitHub PR with generated tests (uses config default).",
)
@click.option(
    "--create-issues/--no-create-issues",
    "create_issues",
    default=None,
    help="Create GitHub issues for detected bugs (uses config default if not specified).",
)
@click.option(
    "--create-fix-prs/--no-create-fix-prs",
    "create_fix_prs",
    default=None,
    help="Create GitHub pull requests with bug fixes (uses config default if not specified).",
)
@click.option(
    "--auto-commit/--no-auto-commit",
    "auto_commit",
    default=None,
    help="Automatically commit changes (uses config default if not specified).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["terminal", "json", "html", "markdown"]),
    default=None,
    help="Report output format (uses config default if not specified).",
)
@click.option(
    "--max-loops",
    "max_loops",
    type=click.IntRange(0),
    default=None,
    help="Maximum fix-rerun iterations (0=unlimited, uses config default if not specified).",
)
@click.option(
    "--token-budget",
    "token_budget",
    type=click.IntRange(0),
    default=None,
    help="Maximum total LLM tokens for this run (0=unlimited, config default if omitted).",
)
@click.option(
    "--no-sync",
    "no_sync",
    is_flag=True,
    default=False,
    help="Skip memory sync with platform.",
)
def pick(**kwargs: Any) -> None:
    """Full pipeline: scan → run → analyze bugs → debug → report

    Individual steps available as separate commands:
      nit scan     - detect project structure
      nit run      - run tests with coverage
      nit analyze  - find bugs and coverage gaps
      nit debug    - generate and apply fixes
      nit report   - create PR/issues

    Configuration:
      All flags use defaults from .nit.yml [git] and [report] sections.
      CLI flags override config defaults.
      Use --no-X to explicitly disable a feature.
    """
    # Extract parameters from kwargs
    path: str = kwargs["path"]
    test_type: str = kwargs["test_type"]
    target_file: str | None = kwargs.get("target_file")
    coverage_target: int | None = kwargs.get("coverage_target")

    ctx = click.get_current_context()
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    if not ci_mode:
        reporter.print_header("nit pick")

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

    # Initialize Sentry from config (idempotent — no-op if already init from env)
    from nit.telemetry.sentry_integration import init_sentry as _init_sentry

    _init_sentry(config.sentry)

    # Check if LLM is configured
    if not _is_llm_runtime_configured(config):
        reporter.print_error("LLM is not configured. Please run 'nit init' or set up .nit.yml")
        raise click.Abort

    # Resolve options: CLI flags override config defaults
    # For boolean flags: None = use config default, True/False = explicit override
    auto_commit_flag: bool | None = kwargs.get("auto_commit")
    auto_commit = auto_commit_flag if auto_commit_flag is not None else config.git.auto_commit

    fix_flag: bool | None = kwargs.get("fix")
    fix = fix_flag if fix_flag is not None else False  # No config default for --fix yet

    create_pr_flag: bool | None = kwargs.get("create_pr")
    create_pr = create_pr_flag if create_pr_flag is not None else config.git.auto_pr

    create_issues_flag: bool | None = kwargs.get("create_issues")
    create_issues = (
        create_issues_flag if create_issues_flag is not None else config.git.create_issues
    )

    create_fix_prs_flag: bool | None = kwargs.get("create_fix_prs")
    create_fix_prs = (
        create_fix_prs_flag if create_fix_prs_flag is not None else config.git.create_fix_prs
    )

    # Upload report: default to True when platform is configured
    platform_enabled = config.platform.normalized_mode in {"platform", "byok"}
    upload_report_flag: bool | None = kwargs.get("upload_report")
    if upload_report_flag is not None:
        upload_report = upload_report_flag
    else:
        upload_report = platform_enabled and config.report.upload_to_platform

    # Output format
    output_format_flag: str | None = kwargs.get("output_format")
    output_format = output_format_flag if output_format_flag else config.report.format

    # Pipeline loop settings (local only — CI always uses single pass)
    max_loops_flag: int | None = kwargs.get("max_loops")
    max_loops = max_loops_flag if max_loops_flag is not None else config.pipeline.max_fix_loops

    token_budget_flag: int | None = kwargs.get("token_budget")
    token_budget = token_budget_flag if token_budget_flag is not None else config.llm.token_budget

    reporter.print_info(f"Running full pipeline for {test_type} tests...")
    if target_file:
        reporter.print_info(f"Target file: {target_file}")
    if coverage_target:
        reporter.print_info(f"Target coverage: {coverage_target}%")
    if auto_commit:
        reporter.print_info("Auto-commit enabled: will commit changes automatically")
    if fix:
        reporter.print_info("Fix mode enabled: will generate code fixes for bugs")
    if create_pr:
        reporter.print_info("PR mode enabled: will create GitHub PR with generated tests")
    if create_issues:
        reporter.print_info("Issue creation enabled: will create GitHub issues for detected bugs")
    if create_fix_prs:
        reporter.print_info("Fix PR creation enabled: will create GitHub PRs with bug fixes")
    if upload_report:
        reporter.print_info("Platform reporting enabled: will upload results to platform")
    if output_format != "terminal":
        reporter.print_info(f"Output format: {output_format}")
    if not ci_mode and max_loops != 1:
        loop_label = "unlimited" if max_loops == 0 else str(max_loops)
        reporter.print_info(f"Fix loop: up to {loop_label} iteration(s)")
    if not ci_mode and token_budget > 0:
        reporter.print_info(f"Token budget: {token_budget:,} tokens")

    # Memory sync: pull from platform before running pipeline
    no_sync = kwargs.get("no_sync", False)
    sync_enabled = platform_enabled and not no_sync
    if sync_enabled:
        _try_pull_memory(config, Path(path).resolve(), ci_mode)

    # Run the full pick pipeline
    pipeline_config = PickPipelineConfig(
        project_root=Path(path).resolve(),
        test_type=test_type,
        target_file=target_file,
        coverage_target=coverage_target,
        fix_enabled=fix,
        create_pr=create_pr,
        create_issues=create_issues,
        create_fix_prs=create_fix_prs,
        commit_changes=auto_commit,
        ci_mode=ci_mode,
        max_fix_loops=max_loops,
        token_budget=token_budget,
    )

    # Track execution time
    start_time = datetime.now(UTC)
    result = asyncio.run(_run_pick_pipeline_with_result(pipeline_config))

    if upload_report:
        pick_options = _PickOptions(
            test_type=test_type,
            target_file=target_file,
            coverage_target=coverage_target,
            fix=fix,
        )
        report_payload = _build_pick_report_payload(
            config,
            pick_options,
            result=result,
            start_time=start_time,
        )
        try:
            upload_result = _upload_pick_report(config, report_payload)
        except PlatformClientError as exc:
            reporter.print_error(str(exc))
            raise click.Abort from exc

        report_id = upload_result.get("reportId")
        if isinstance(report_id, str) and report_id:
            reporter.print_success(f"Uploaded pick report: {report_id}")
        else:
            reporter.print_success("Uploaded pick report.")

        # Upload bugs to platform (if bugs were found and issues/PRs were created)
        if result.bugs_found and upload_report:
            try:
                # Build mappings of bug titles to GitHub URLs
                issue_map: dict[str, str] = {}
                pr_map: dict[str, str] = {}

                # Map issues (assumes same order as bugs_found)
                for i, bug in enumerate(result.bugs_found):
                    if i < len(result.created_issues):
                        issue_map[bug.title] = result.created_issues[i]
                    if i < len(result.created_fix_prs):
                        pr_map[bug.title] = result.created_fix_prs[i]

                bug_ids = _upload_bugs_to_platform(config, result, issue_map, pr_map)
                if bug_ids and not ci_mode:
                    reporter.print_success(f"Uploaded {len(bug_ids)} bugs to platform")
            except PlatformClientError as exc:
                logger.warning("Failed to upload bugs to platform: %s", exc)
                # Don't abort here, bugs upload is supplementary
            except Exception as exc:
                logger.warning("Unexpected error uploading bugs: %s", exc)

    # Memory sync: push to platform after report upload (non-fatal)
    if sync_enabled:
        _try_push_memory(
            config,
            Path(path).resolve(),
            ci_mode,
            source="ci" if ci_mode else "local",
        )

    # Send Slack notification for bugs found
    if result.bugs_found:
        slack = _get_slack_reporter(config)
        if slack:
            try:
                from nit.agents.reporters.slack import BugEvent

                bug_events = [
                    BugEvent(
                        file_path=bug.location.file_path,
                        function_name=bug.location.function_name,
                        bug_type=bug.bug_type.value if hasattr(bug.bug_type, "value") else "",
                        description=bug.description or bug.title,
                        severity=bug.severity.value if hasattr(bug.severity, "value") else "medium",
                    )
                    for bug in result.bugs_found
                ]
                slack.send_bug_alert(bug_events)
            except Exception as exc:
                logger.warning("Failed to send Slack bug alert: %s", exc)


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--package",
    "package_path",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Specific package to analyze (for monorepos).",
)
@click.option(
    "--json-output",
    "as_json",
    is_flag=True,
    help="Output results in JSON format.",
)
@click.option(
    "--type",
    "test_type",
    type=click.Choice(["unit", "e2e", "integration", "all"], case_sensitive=False),
    default="all",
    help="Filter by test type.",
)
@click.option(
    "--file",
    "target_file",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    help="Analyze specific file only.",
)
def analyze(
    path: str,
    package_path: str | None,
    as_json: bool,
    test_type: str,
    target_file: str | None,
) -> None:
    """Analyze coverage gaps and detect bugs from test failures.

    Shows what tests are missing and what bugs were found WITHOUT generating them.
    Uses the same pipeline as 'pick' but with fix generation disabled.

    Auto-runs 'scan' and 'run' if needed.
    """
    # Note: package_path is not yet fully implemented
    _ = package_path

    ctx = click.get_current_context()
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    if not ci_mode:
        reporter.print_header("nit analyze")

    # Load configuration
    try:
        _ = load_config(path)
    except Exception as e:
        reporter.print_error(f"Failed to load configuration: {e}")
        raise click.Abort from e

    # Run analysis using PickPipeline with fix disabled
    pipeline_config = PickPipelineConfig(
        project_root=Path(path).resolve(),
        test_type=test_type,
        target_file=target_file,
        fix_enabled=False,  # Analysis only, no fix generation
        create_pr=False,
        create_issues=False,
        create_fix_prs=False,
        commit_changes=False,
        ci_mode=ci_mode,
    )

    pipeline = PickPipeline(pipeline_config)

    try:
        result = asyncio.run(pipeline.run())

        # Display results
        if as_json:
            output = {
                "bugs_found": len(result.bugs_found),
                "bugs": [
                    {
                        "title": bug.title,
                        "severity": bug.severity.value,
                        "file": bug.location.file_path,
                        "line": bug.location.line_number,
                        "type": bug.bug_type.value,
                    }
                    for bug in result.bugs_found
                ],
                "coverage": (
                    {
                        "overall_line": (
                            result.coverage_report.overall_line_coverage
                            if hasattr(result, "coverage_report") and result.coverage_report
                            else 0.0
                        ),
                        "overall_function": (
                            result.coverage_report.overall_function_coverage
                            if hasattr(result, "coverage_report") and result.coverage_report
                            else 0.0
                        ),
                        "uncovered_files": (
                            result.coverage_report.get_uncovered_files()
                            if hasattr(result, "coverage_report") and result.coverage_report
                            else []
                        ),
                    }
                ),
                "gap_report": (
                    {
                        "overall_coverage": result.gap_report.overall_coverage,
                        "target_coverage": result.gap_report.target_coverage,
                        "function_gaps": [
                            {
                                "file_path": gap.file_path,
                                "function_name": gap.function_name,
                                "priority": gap.priority.value,
                                "complexity": gap.complexity,
                                "coverage_percentage": gap.coverage_percentage,
                                "is_public": gap.is_public,
                            }
                            for gap in result.gap_report.function_gaps
                        ],
                        "untested_files": result.gap_report.untested_files,
                        "stale_tests": [
                            {
                                "test_file": stale.test_file,
                                "reason": stale.reason,
                            }
                            for stale in result.gap_report.stale_tests
                        ],
                    }
                    if hasattr(result, "gap_report") and result.gap_report
                    else None
                ),
                "tests_run": result.tests_run,
                "tests_passed": result.tests_passed,
                "tests_failed": result.tests_failed,
                "risk_report": (
                    {
                        "critical_files": result.risk_report.critical_files,
                        "high_risk_files": result.risk_report.high_risk_files,
                        "total_files": len(result.risk_report.file_risks),
                    }
                    if result.risk_report
                    else None
                ),
                "code_analysis": (
                    {"files_analyzed": len(result.code_maps)} if result.code_maps else None
                ),
                "integration_deps": [
                    {
                        "file": str(r.source_path),
                        "dependencies": [d.dependency_type.value for d in r.dependencies],
                    }
                    for r in result.integration_deps
                ],
                "semantic_gaps": [
                    {
                        "function": g.function_name,
                        "file": g.file_path,
                        "category": g.category.value,
                        "severity": g.severity,
                    }
                    for g in result.semantic_gaps
                ],
                "route_discovery": (
                    {
                        "framework": result.route_discovery.framework,
                        "routes_found": len(result.route_discovery.routes),
                    }
                    if result.route_discovery
                    else None
                ),
            }
            console.print_json(data=output)
        else:
            # Terminal output
            console.print()

            # Show bugs
            if result.bugs_found:
                reporter.print_bug_analysis(result.bugs_found)
                console.print()

            # Show coverage
            uncovered_files = []
            if hasattr(result, "coverage_report") and result.coverage_report:
                uncovered_files = result.coverage_report.get_uncovered_files()

                # Prefer semantic gap analysis if available
                if hasattr(result, "gap_report") and result.gap_report:
                    reporter.print_semantic_gap_analysis(
                        result.gap_report,
                        has_llm_gaps=bool(result.semantic_gaps),
                    )
                    console.print()
                elif uncovered_files:
                    # Fall back to simple coverage gaps display
                    reporter.print_coverage_gaps(
                        {
                            file: {
                                "coverage": result.coverage_report.files[
                                    file
                                ].line_coverage_percentage,
                                "risk_level": (
                                    "HIGH"
                                    if result.coverage_report.files[file].line_coverage_percentage
                                    == 0
                                    else "MEDIUM"
                                ),
                                "uncovered_functions": len(
                                    [
                                        f
                                        for f in result.coverage_report.files[file].functions
                                        if not f.is_covered
                                    ]
                                ),
                            }
                            for file in uncovered_files[:10]  # Top 10
                        }
                    )
                    console.print()

            # Show deep analysis results
            if result.code_maps:
                reporter.print_code_analysis_summary(result.code_maps)
            if result.convention_profile:
                reporter.print_pattern_profile(result.convention_profile)
            if result.risk_report:
                reporter.print_risk_report(result.risk_report)
            if result.semantic_gaps:
                reporter.print_semantic_gaps(result.semantic_gaps)
            if result.integration_deps:
                reporter.print_integration_deps(result.integration_deps)
            if result.route_discovery and result.route_discovery.routes:
                reporter.print_route_flows(result.route_discovery, result.flow_mapping)

            # Next steps (no redundant summary - info is already shown above)
            has_issues = (
                result.bugs_found
                or uncovered_files
                or (result.gap_report and result.gap_report.function_gaps)
                or (result.gap_report and result.gap_report.stale_tests)
                or result.risk_report
                or result.semantic_gaps
            )

            if result.bugs_found:
                reporter.print_info("Next: Run 'nit pick --fix' to generate and apply fixes")
            elif has_issues:
                reporter.print_info("Next: Run 'nit generate' to create tests for coverage gaps")
            else:
                reporter.print_success("No issues found!")

    except Exception as e:
        reporter.print_error(f"Analysis failed: {e}")
        if not ci_mode:
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
    "--file",
    "target_file",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    help="Debug specific file only.",
)
@click.option(
    "--bug-id",
    help="Debug specific bug by ID (from analyze output).",
)
@click.option(
    "--no-verify",
    is_flag=True,
    help="Skip fix verification step (faster but risky).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be fixed without applying changes.",
)
def debug(
    path: str,
    target_file: str | None,
    bug_id: str | None,
    no_verify: bool,
    dry_run: bool,
) -> None:
    """Generate and apply fixes for detected bugs.

    Runs the debug pipeline from pick: verify bugs → root cause analysis →
    generate fixes → verify fixes → apply fixes.

    Auto-runs 'analyze' if no bugs have been found yet.
    """
    # Note: bug_id and no_verify are not yet implemented
    # They will be used in the full implementation
    _ = bug_id
    _ = no_verify

    ctx = click.get_current_context()
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    if not ci_mode:
        reporter.print_header("nit debug")

    # Load configuration
    try:
        config = load_config(path)
    except Exception as e:
        reporter.print_error(f"Failed to load configuration: {e}")
        raise click.Abort from e

    # Check if LLM is configured
    if not _is_llm_runtime_configured(config):
        reporter.print_error("LLM is not configured. Please run 'nit init' or set up .nit.yml")
        raise click.Abort

    # Delegate to pick with --fix flag
    if not ci_mode:
        reporter.print_info("Debug command is currently implemented via 'pick --fix'")
        reporter.print_info("Running pick pipeline with fix mode enabled...")

    ctx.invoke(
        pick,
        path=path,
        test_type="all",
        target_file=target_file,
        coverage_target=None,
        fix=not dry_run,  # Don't apply fixes in dry-run mode
        upload_report=False,
        create_pr=False,
        create_issues=False,
        create_fix_prs=False,
    )


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--pr",
    "create_pr",
    is_flag=True,
    help="Create GitHub PR with fixes.",
)
@click.option(
    "--create-issues",
    is_flag=True,
    help="Create GitHub issues for bugs.",
)
@click.option(
    "--create-fix-prs",
    is_flag=True,
    help="Create separate PRs for each fix.",
)
@click.option(
    "--platform",
    "upload_platform",
    is_flag=True,
    help="Upload report to platform (if configured).",
)
@click.option(
    "--no-commit",
    is_flag=True,
    help="Skip committing changes.",
)
@click.option(
    "--html",
    is_flag=True,
    help="Generate HTML dashboard.",
)
@click.option(
    "--serve",
    is_flag=True,
    help="Serve dashboard on localhost (implies --html).",
)
@click.option(
    "--port",
    default=4040,
    type=int,
    help="Server port for --serve (default: 4040).",
)
@click.option(
    "--days",
    default=30,
    type=int,
    help="Days of history to show in dashboard (default: 30).",
)
def report(**kwargs: Unpack[_ReportKwargs]) -> None:
    """Create GitHub PR/issues, upload to platform, or generate HTML dashboard.

    Available actions:
    - Generate HTML dashboard (--html)
    - Serve dashboard locally (--serve, implies --html)
    - Create GitHub PR with fixes (--pr)
    - Create GitHub issues for bugs (--create-issues)
    - Create separate PRs for each fix (--create-fix-prs)
    - Upload to platform (--platform)

    Examples:
        nit report --html               # Generate dashboard
        nit report --html --serve       # Generate and serve dashboard
        nit report --pr                 # Create GitHub PR
    """
    path = kwargs["path"]
    create_pr = kwargs["create_pr"]
    create_issues = kwargs["create_issues"]
    create_fix_prs = kwargs["create_fix_prs"]
    upload_platform = kwargs["upload_platform"]
    no_commit = kwargs["no_commit"]
    html = kwargs["html"]
    serve = kwargs["serve"]
    port = kwargs["port"]
    days = kwargs["days"]

    ctx = click.get_current_context()
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    # Handle HTML dashboard generation
    if html or serve:
        from nit.agents.reporters.dashboard import DashboardReporter

        if not ci_mode:
            reporter.print_header("nit report --html")

        project_root = Path(path).resolve()

        dashboard = DashboardReporter(project_root, days=days)

        try:
            dashboard_path = dashboard.generate_html()
            reporter.print_success(f"Dashboard generated: {dashboard_path}")

            if serve:
                reporter.print_info(f"Starting dashboard server on port {port}...")
                dashboard.serve(port=port, open_browser=not ci_mode)

        except Exception as e:
            reporter.print_error(f"Failed to generate dashboard: {e}")
            raise click.Abort from e

        return

    # Otherwise, handle PR/issue creation via pick pipeline
    if not ci_mode:
        reporter.print_header("nit report")

    # Load configuration (for validation only - not used in delegation to pick)
    try:
        _ = load_config(path)
    except Exception as e:
        reporter.print_error(f"Failed to load configuration: {e}")
        raise click.Abort from e

    # Delegate to pick with appropriate flags
    if not ci_mode:
        reporter.print_info("Report command is currently implemented via 'pick --fix'")
        reporter.print_info("Running pick pipeline with reporting enabled...")

    ctx.invoke(
        pick,
        path=path,
        test_type="all",
        target_file=None,
        coverage_target=None,
        fix=not no_commit,  # Apply fixes unless --no-commit
        upload_report=upload_platform,
        create_pr=create_pr,
        create_issues=create_issues,
        create_fix_prs=create_fix_prs,
    )


@cli.command()
@click.option(
    "--path",
    default=".",
    help="Path to project root",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
)
@click.option(
    "--baseline",
    is_flag=True,
    help="Update baselines instead of running drift tests",
)
@click.option(
    "--watch",
    is_flag=True,
    help="Run drift tests continuously on a schedule",
)
@click.option(
    "--interval",
    default=3600,
    help="Interval in seconds for watch mode (default: 3600 = 1 hour)",
    type=int,
)
@click.option(
    "--tests-file",
    default=".nit/drift-tests.yml",
    help="Path to drift tests YAML file",
)
def drift(path: str, baseline: bool, watch: bool, interval: int, tests_file: str) -> None:
    """Check LLM endpoints for drift (tasks 3.11.7, 3.11.8, 3.11.9).

    Monitors LLM output drift by comparing test outputs against baselines.

    Examples:
        nit drift                     # Run all drift tests
        nit drift --baseline          # Update baselines from current outputs
        nit drift --watch             # Continuously monitor drift (1 hour interval)
        nit drift --watch --interval 1800  # Monitor every 30 minutes
    """
    from nit.agents.watchers.drift import DriftWatcher

    project_root = Path(path).resolve()

    # Initialize drift watcher
    watcher = DriftWatcher(project_root)

    if watch:
        # Continuous monitoring mode (task 3.11.9)
        _drift_watch(watcher, tests_file, interval, baseline)
    elif baseline:
        # Update baselines mode (task 3.11.8)
        _drift_baseline(watcher, tests_file)
    else:
        # Run drift tests mode (task 3.11.7)
        _drift_test(watcher, tests_file)


def _drift_test(watcher: Any, tests_file: str) -> None:
    """Run drift tests and report results."""
    console.print("[bold cyan]Running drift tests...[/bold cyan]\n")

    # Run tests
    report = asyncio.run(watcher.run_drift_tests(tests_file))

    # Display results
    _display_drift_report(report)

    # Send Slack alert if drift detected
    if report.drift_detected:
        try:
            config = load_config(".")
            slack = _get_slack_reporter(config)
            if slack:
                from nit.agents.reporters.slack import DriftEvent

                drift_events = [
                    DriftEvent(
                        test_name=r.test_name,
                        endpoint=getattr(r, "endpoint", ""),
                        similarity_score=r.similarity_score or 0.0,
                        threshold=getattr(r, "threshold", 0.85),
                        baseline_output=getattr(r, "baseline_output", ""),
                        actual_output=getattr(r, "actual_output", ""),
                    )
                    for r in report.results
                    if not r.passed and not r.error
                ]
                if drift_events:
                    slack.send_drift_alert(drift_events)
        except Exception as exc:
            logger.warning("Failed to send Slack drift alert: %s", exc)

    # Exit with error code if drift detected
    if report.drift_detected:
        sys.exit(1)


def _drift_baseline(watcher: Any, tests_file: str) -> None:
    """Update baselines from current test outputs."""
    console.print("[bold cyan]Updating drift test baselines...[/bold cyan]\n")

    # Update baselines
    report = asyncio.run(watcher.update_baselines(tests_file))

    # Display results
    console.print(f"[green]✓[/green] Updated {report.passed_tests} baselines")

    if report.skipped_tests > 0:
        console.print(f"[yellow]![/yellow] Skipped {report.skipped_tests} tests due to errors")

    # Show details
    for result in report.results:
        if result.error:
            console.print(f"  [red]✗[/red] {result.test_name}: {result.error}")
        else:
            console.print(f"  [green]✓[/green] {result.test_name}")


def _drift_watch(watcher: Any, tests_file: str, interval: int, baseline: bool) -> None:
    """Continuously monitor drift on a schedule."""
    import time

    console.print(f"[bold cyan]Starting drift monitoring (interval: {interval}s)...[/bold cyan]\n")
    console.print("Press Ctrl+C to stop\n")

    try:
        iteration = 0
        while True:
            iteration += 1
            console.print(f"[bold]Iteration {iteration}[/bold] — {datetime.now(UTC).isoformat()}")

            if baseline:
                # Update baselines mode
                _drift_baseline(watcher, tests_file)
            else:
                # Test mode
                _drift_test(watcher, tests_file)

            console.print(f"\nNext run in {interval}s...\n")
            time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Drift monitoring stopped[/yellow]")


def _display_drift_report(report: Any) -> None:
    """Display drift test results in a table."""
    # Summary
    console.print("[bold]Drift Test Results[/bold]\n")
    console.print(f"Total tests: {report.total_tests}")
    console.print(f"Passed: [green]{report.passed_tests}[/green]")
    console.print(f"Failed: [red]{report.failed_tests}[/red]")

    if report.skipped_tests > 0:
        console.print(f"Skipped: [yellow]{report.skipped_tests}[/yellow]")

    console.print()

    # Create results table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Test", style="white")
    table.add_column("Status", justify="center")
    table.add_column("Similarity", justify="right")
    table.add_column("Details", style="dim")

    for result in report.results:
        # Status icon
        if result.error:
            status = "[yellow]⊗[/yellow]"
            similarity = "—"
            details = result.error[:50]
        elif not result.baseline_exists:
            status = "[yellow]?[/yellow]"
            similarity = "—"
            details = "No baseline"
        elif result.passed:
            status = "[green]✓[/green]"
            similarity = (
                f"{result.similarity_score:.3f}" if result.similarity_score is not None else "—"
            )
            details = "Passed"
        else:
            status = "[red]✗[/red]"
            similarity = (
                f"{result.similarity_score:.3f}" if result.similarity_score is not None else "—"
            )
            details = "Drift detected"

        table.add_row(
            result.test_name,
            status,
            similarity,
            details,
        )

    console.print(table)
    console.print()

    # Drift warning
    if report.drift_detected:
        console.print("[bold red]⚠ Drift detected in one or more tests[/bold red]")


# ── nit watch ─────────────────────────────────────────────────────


@cli.command()
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--interval",
    default=3600,
    type=int,
    help="Interval in seconds between runs (default: 3600 = 1 hour).",
)
@click.option(
    "--coverage/--no-coverage",
    "enable_coverage",
    default=False,
    help="Enable coverage trend monitoring.",
)
@click.option(
    "--coverage-threshold",
    default=80.0,
    type=float,
    help="Minimum acceptable coverage percentage (default: 80).",
)
@click.option(
    "--drop-threshold",
    default=5.0,
    type=float,
    help="Alert if coverage drops by more than N percentage points (default: 5).",
)
@click.option(
    "--test-command",
    default=None,
    type=str,
    help="Test command to run (auto-detected if not specified).",
)
@click.option(
    "--timeout",
    default=600,
    type=int,
    help="Timeout in seconds for test execution (default: 600).",
)
@click.option(
    "--max-runs",
    default=None,
    type=int,
    help="Maximum number of runs before stopping (default: unlimited).",
)
def watch(**kwargs: Any) -> None:
    """Run tests on a schedule and optionally monitor coverage trends.

    Examples:
        nit watch                               # Run tests every hour
        nit watch --interval 1800               # Run every 30 minutes
        nit watch --coverage                    # Include coverage monitoring
        nit watch --max-runs 5                  # Stop after 5 runs
        nit watch --test-command "pytest -x"    # Custom test command
    """
    import time as time_mod

    from nit.agents.watchers.schedule import ScheduleWatcher

    path: str = kwargs["path"]
    interval: int = kwargs["interval"]
    enable_coverage: bool = kwargs.get("enable_coverage", False)
    coverage_threshold: float = kwargs.get("coverage_threshold", 80.0)
    drop_threshold: float = kwargs.get("drop_threshold", 5.0)
    test_command: str | None = kwargs.get("test_command")
    timeout: int = kwargs.get("timeout", 600)
    max_runs: int | None = kwargs.get("max_runs")

    project_root = Path(path).resolve()

    schedule_watcher = ScheduleWatcher(
        project_root,
        test_command=test_command,
        timeout=float(timeout),
    )

    coverage_watcher = None
    if enable_coverage:
        from nit.agents.watchers.coverage import CoverageWatcher

        coverage_watcher = CoverageWatcher(
            project_root,
            coverage_threshold=coverage_threshold,
            drop_threshold=drop_threshold,
        )

    console.print("[bold cyan]Starting watch mode[/bold cyan]")
    console.print(f"  Interval: {interval}s")
    console.print(f"  Test command: {schedule_watcher._test_command}")
    if coverage_watcher:
        console.print(f"  Coverage threshold: {coverage_threshold}%")
        console.print(f"  Drop threshold: {drop_threshold}pp")
    if max_runs:
        console.print(f"  Max runs: {max_runs}")
    console.print("\nPress Ctrl+C to stop\n")

    try:
        run_count = 0
        while max_runs is None or run_count < max_runs:
            run_count += 1
            console.print(f"[bold]Run {run_count}[/bold] — {datetime.now(UTC).isoformat()}")

            # Execute tests
            run_result = asyncio.run(schedule_watcher.run_once())
            _display_watch_run(run_result)

            # Coverage monitoring
            if coverage_watcher:
                try:
                    trend_report = asyncio.run(coverage_watcher.collect_and_analyze())
                    _display_coverage_trend(trend_report)

                    # Slack alert for coverage issues
                    if trend_report.alerts:
                        try:
                            watch_config = load_config(path)
                            slack = _get_slack_reporter(watch_config)
                            if slack:
                                from nit.agents.reporters.slack import CoverageEvent

                                cov_events = [
                                    CoverageEvent(
                                        package=str(project_root.name),
                                        before=a.previous_coverage,
                                        after=a.current_coverage,
                                        threshold=a.threshold,
                                    )
                                    for a in trend_report.alerts
                                ]
                                slack.send_coverage_alert(cov_events)
                        except Exception as slack_exc:
                            logger.warning("Failed to send Slack coverage alert: %s", slack_exc)
                except Exception as exc:
                    reporter.print_warning(f"Coverage collection failed: {exc}")

            if max_runs is None or run_count < max_runs:
                console.print(f"\nNext run in {interval}s...\n")
                time_mod.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Watch mode stopped[/yellow]")


def _display_watch_run(run_result: Any) -> None:
    """Display results of a single scheduled test run."""
    if run_result.success:
        console.print(f"  [green]✓[/green] Tests passed ({run_result.duration_seconds:.1f}s)")
    else:
        console.print(
            f"  [red]✗[/red] Tests failed (exit code {run_result.exit_code}, "
            f"{run_result.duration_seconds:.1f}s)"
        )
        if run_result.error:
            console.print(f"  Error: {run_result.error}")


def _display_coverage_trend(trend_report: Any) -> None:
    """Display coverage trend information."""
    snapshot = trend_report.current_snapshot
    console.print(
        f"  Coverage: {snapshot.overall_line_coverage:.1f}% line, "
        f"{snapshot.overall_function_coverage:.1f}% function"
    )
    console.print(f"  Trend: {trend_report.trend}")

    for alert in trend_report.alerts:
        severity_style = "red" if alert.severity == "critical" else "yellow"
        console.print(f"  [{severity_style}]Alert: {alert.message}[/{severity_style}]")


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
    check: bool
    files: tuple[str, ...]
    all_files: bool
    write_to_source: bool
    output_dir: str | None
    style: str | None
    framework: str | None
    check_mismatch: bool


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
@click.option(
    "--check",
    is_flag=True,
    help="Check for outdated docstrings without generating (task 4.1.5).",
)
@click.option(
    "--file",
    "files",
    multiple=True,
    type=str,
    help="Specific file(s) to document (can be used multiple times).",
)
@click.option(
    "--all",
    "all_files",
    is_flag=True,
    help="Generate documentation for all source files (task 4.1.4).",
)
@click.option(
    "--write-to-source",
    is_flag=True,
    help="Write generated docstrings back into source files.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Output directory for generated documentation files.",
)
@click.option(
    "--style",
    type=click.Choice(["google", "numpy"], case_sensitive=False),
    default=None,
    help="Docstring style preference (e.g., google, numpy).",
)
@click.option(
    "--framework",
    type=click.Choice(
        ["sphinx", "typedoc", "jsdoc", "doxygen", "godoc", "rustdoc", "mkdocs"],
        case_sensitive=False,
    ),
    default=None,
    help="Documentation framework override.",
)
@click.option(
    "--check-mismatch/--no-check-mismatch",
    default=True,
    help="Check for documentation/code semantic mismatches.",
)
def docs(**opts: Unpack[DocsOptions]) -> None:
    """Generate/update documentation.

    Use --changelog <tag> to generate CHANGELOG.md from git history since that tag.
    Use --readme to generate README section updates from project structure.
    Use --write with --readme to write the result to the README file.
    Use --all to generate docstrings for all source files.
    Use --check to report outdated docs without generating.
    Use --file <path> to target specific files.
    """
    path = opts["path"]
    changelog_tag = opts["changelog_tag"]
    changelog_output = opts["changelog_output"]
    changelog_no_llm = opts["changelog_no_llm"]
    readme = opts["readme"]
    write = opts["write"]
    check = opts["check"]
    files = opts["files"]
    all_files = opts["all_files"]
    write_to_source = opts["write_to_source"]
    output_dir = opts["output_dir"]
    style = opts["style"]
    framework = opts["framework"]
    check_mismatch = opts["check_mismatch"]

    # Handle changelog mode
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

    # Handle README mode
    if readme:
        _docs_readme(path, write=write)
        return

    # Handle docstring generation mode (task 4.1.4, 4.1.5)
    if all_files or files or check:
        _docs_docstrings(
            path,
            files=list(files),
            check_only=check,
            overrides={
                "write_to_source": write_to_source,
                "output_dir": output_dir,
                "style": style,
                "framework": framework,
                "check_mismatch": check_mismatch,
            },
        )
        return

    # No mode specified
    click.echo("nit docs — use --changelog <tag>, --readme, --all, --file <path>, or --check.")
    return


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


def _docs_docstrings(
    path: str,
    *,
    files: list[str] | None = None,
    check_only: bool = False,
    overrides: dict[str, Any] | None = None,
) -> None:
    """Generate or check docstrings for source files.

    Args:
        path: Project root path.
        files: Specific files to document (None for all).
        check_only: If True, only report outdated docs without generating.
        overrides: CLI overrides for docs config (write_to_source, output_dir,
            style, framework, check_mismatch).
    """
    cli_overrides = overrides or {}

    # Load config
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

    if not check_only and not _is_llm_runtime_configured(config):
        reporter.print_error("LLM is not configured. Run 'nit init' or set up .nit.yml")
        raise click.Abort

    # Create LLM engine (only if not check-only)
    engine = None
    if not check_only:
        llm_config = load_llm_config(path)
        engine = create_engine(llm_config)

    # Build docs config from .nit.yml with CLI overrides
    docs_config = config.docs
    if cli_overrides.get("write_to_source"):
        docs_config.write_to_source = True
    if cli_overrides.get("output_dir"):
        docs_config.output_dir = cli_overrides["output_dir"]
    if cli_overrides.get("style"):
        docs_config.style = cli_overrides["style"]
    if cli_overrides.get("framework"):
        docs_config.framework = cli_overrides["framework"]
    if "check_mismatch" in cli_overrides:
        docs_config.check_mismatch = cli_overrides["check_mismatch"]

    framework = cli_overrides.get("framework")

    # Create DocBuilder
    root = Path(path).resolve()
    if engine is None and not check_only:
        reporter.print_error("LLM engine not initialized")
        raise click.Abort
    builder = DocBuilder(
        llm_engine=engine,  # type: ignore[arg-type]
        project_root=root,
        docs_config=docs_config,
    )

    # Build task
    source_files = files if files else []
    task = DocBuildTask(
        source_files=source_files,
        check_only=check_only,
        doc_framework=framework,
    )

    # Run DocBuilder
    mode_str = "Checking" if check_only else "Generating"
    if files:
        reporter.print_info(f"{mode_str} documentation for {len(files)} file(s)...")
    else:
        reporter.print_info(f"{mode_str} documentation for all source files...")

    try:
        result = asyncio.run(builder.run(task))
    except Exception as e:
        reporter.print_error(f"Documentation generation failed: {e}")
        raise click.Abort from e

    if result.status == TaskStatus.FAILED:
        for error in result.errors:
            reporter.print_error(error)
        raise click.Abort

    # Display results
    results = result.result.get("results", [])
    _display_doc_results(results, check_only=check_only)


def _display_doc_results(results: list[dict[str, Any]], *, check_only: bool) -> None:
    """Display documentation generation results.

    Args:
        results: List of DocBuildResult dicts.
        check_only: Whether this was a check-only run.
    """
    # Display limit for function names
    max_display_functions = 5

    total_files = len(results)
    outdated_files = sum(1 for r in results if r["outdated"])
    total_changes = sum(len(r["changes"]) for r in results)

    if check_only:
        # Check mode: report outdated docs
        if outdated_files == 0:
            reporter.print_success("All documentation is up to date!")
            return

        reporter.print_warning(
            f"Found {outdated_files}/{total_files} file(s) with outdated documentation"
        )

        table = Table(title="Outdated Documentation")
        table.add_column("File", style="cyan")
        table.add_column("Changes", justify="right", style="yellow")
        table.add_column("Functions", style="dim")

        for r in results:
            if not r["outdated"]:
                continue

            changes = r["changes"]
            file_path = r["file_path"]
            function_names = ", ".join(c["function_name"] for c in changes[:max_display_functions])
            if len(changes) > max_display_functions:
                function_names += f", ... ({len(changes) - max_display_functions} more)"

            table.add_row(file_path, str(len(changes)), function_names)

        console.print(table)
        reporter.print_info("Run 'nit docs --all' to generate missing documentation for all files")

    else:
        # Generation mode: report what was generated
        if total_changes == 0:
            reporter.print_success("All documentation is up to date!")
            return

        reporter.print_success(
            f"Generated documentation for {total_changes} function(s) "
            f"across {outdated_files} file(s)"
        )

        table = Table(title="Generated Documentation")
        table.add_column("File", style="cyan")
        table.add_column("Generated", justify="right", style="green")
        table.add_column("Functions", style="dim")

        for r in results:
            if not r["outdated"]:
                continue

            generated_docs = r["generated_docs"]
            file_path = r["file_path"]
            function_names = ", ".join(list(generated_docs.keys())[:max_display_functions])
            if len(generated_docs) > max_display_functions:
                excess = len(generated_docs) - max_display_functions
                function_names += f", ... ({excess} more)"

            table.add_row(file_path, str(len(generated_docs)), function_names)

        console.print(table)

        # Display sample generated doc
        if results and results[0]["generated_docs"]:
            first_result = next((r for r in results if r["generated_docs"]), None)
            if first_result:
                sample_func = next(iter(first_result["generated_docs"].keys()))
                sample_doc = first_result["generated_docs"][sample_func]
                reporter.print_info(f"\nSample generated documentation for {sample_func}:")
                click.echo(f"\n{sample_doc}\n")

        # Display files written
        all_written: list[str] = []
        for r in results:
            all_written.extend(r.get("files_written", []))
        if all_written:
            reporter.print_success(f"Wrote documentation to {len(all_written)} file(s)")

    # Display mismatches (both check and generation modes)
    all_mismatches: list[dict[str, Any]] = []
    for r in results:
        all_mismatches.extend(r.get("mismatches", []))

    if all_mismatches:
        reporter.print_warning(f"Found {len(all_mismatches)} doc/code mismatch(es)")

        mismatch_table = Table(title="Documentation Mismatches")
        mismatch_table.add_column("File", style="cyan")
        mismatch_table.add_column("Function", style="yellow")
        mismatch_table.add_column("Type", style="red")
        mismatch_table.add_column("Description", style="dim")
        mismatch_table.add_column("Severity")

        for m in all_mismatches:
            severity_style = "red bold" if m["severity"] == "error" else "yellow"
            mismatch_table.add_row(
                m["file_path"],
                m["function_name"],
                m["mismatch_type"],
                m["description"],
                Text(m["severity"], style=severity_style),
            )

        console.print(mismatch_table)


@cli.group("memory")
def memory_group() -> None:
    """Manage nit's memory system (conventions, patterns, statistics)."""


@memory_group.command("show")
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--package",
    "package_name",
    type=str,
    default=None,
    help="Show memory for a specific package (monorepo).",
)
@click.option(
    "--json-output",
    "as_json",
    is_flag=True,
    help="Output as JSON instead of human-readable format.",
)
def memory_show(path: str, package_name: str | None, *, as_json: bool) -> None:
    """Display memory contents in human-readable format (task U.2.1, U.2.2).

    Shows global memory (conventions, patterns, statistics) by default.
    Use --package to show package-specific memory.

    Examples:
        nit memory show                    # Show global memory
        nit memory show --package api      # Show memory for 'api' package
        nit memory show --json-output      # Output as JSON
    """
    from pathlib import Path

    from nit.memory.global_memory import GlobalMemory
    from nit.memory.package_memory_manager import PackageMemoryManager

    root = Path(path).resolve()

    if package_name:
        # Show package-specific memory (task U.2.2)
        manager = PackageMemoryManager(root)
        pkg_memory = manager.get_package_memory(package_name)

        if as_json:
            click.echo(json.dumps(pkg_memory.to_dict(), indent=2))
        else:
            console.print()
            console.print(f"[bold cyan]Package Memory: {package_name}[/bold cyan]")
            console.print()
            _display_package_memory(pkg_memory)
    else:
        # Show global memory (task U.2.1)
        global_memory = GlobalMemory(root)

        if as_json:
            click.echo(json.dumps(global_memory.to_dict(), indent=2))
        else:
            console.print()
            console.print("[bold cyan]Global Memory[/bold cyan]")
            console.print()
            _display_global_memory(global_memory)


@memory_group.command("reset")
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--package",
    "package_name",
    type=str,
    default=None,
    help="Reset memory for a specific package only.",
)
@click.option(
    "--confirm",
    is_flag=True,
    help="Skip confirmation prompt.",
)
def memory_reset(path: str, package_name: str | None, *, confirm: bool) -> None:
    """Clear all memory (start fresh) (task U.2.3).

    Clears global memory by default. Use --package to clear specific package memory.
    This action cannot be undone.

    Examples:
        nit memory reset --confirm                # Clear global memory
        nit memory reset --package api --confirm  # Clear 'api' package memory
    """
    from pathlib import Path

    from nit.memory.global_memory import GlobalMemory
    from nit.memory.package_memory_manager import PackageMemoryManager

    root = Path(path).resolve()

    # Confirm deletion unless --confirm is passed
    if not confirm:
        if package_name:
            message = f"Clear memory for package '{package_name}'?"
        else:
            message = "Clear ALL global memory?"

        if not click.confirm(message):
            reporter.print_info("Reset cancelled")
            return

    if package_name:
        # Clear package memory
        manager = PackageMemoryManager(root)
        # Load package memory first to ensure it's in the cache
        manager.get_package_memory(package_name)
        manager.clear_package_memory(package_name)
        reporter.print_success(f"Cleared memory for package: {package_name}")
    else:
        # Clear global memory
        memory = GlobalMemory(root)
        memory.clear()
        reporter.print_success("Cleared global memory")


@memory_group.command("export")
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
@click.option(
    "--package",
    "package_name",
    type=str,
    default=None,
    help="Export memory for a specific package.",
)
@click.option(
    "--output",
    "output_file",
    type=click.Path(dir_okay=False, resolve_path=True),
    default=None,
    help="Output file path (default: print to stdout).",
)
def memory_export(path: str, package_name: str | None, output_file: str | None) -> None:
    """Export memory as readable markdown report (task U.2.4).

    Exports global memory by default. Use --package to export specific package memory.
    Prints to stdout unless --output is specified.

    Examples:
        nit memory export                           # Print global memory as markdown
        nit memory export --output memory.md        # Save to file
        nit memory export --package api             # Export package memory
    """
    from pathlib import Path

    from nit.memory.global_memory import GlobalMemory
    from nit.memory.package_memory_manager import PackageMemoryManager

    root = Path(path).resolve()

    if package_name:
        # Export package memory
        manager = PackageMemoryManager(root)
        pkg_memory = manager.get_package_memory(package_name)
        markdown = pkg_memory.to_markdown()
    else:
        # Export global memory
        global_memory = GlobalMemory(root)
        markdown = global_memory.to_markdown()

    if output_file:
        # Write to file
        out_path = Path(output_file)
        out_path.write_text(markdown, encoding="utf-8")
        reporter.print_success(f"Exported memory to {out_path}")
    else:
        # Print to stdout
        click.echo(markdown)


@memory_group.command("pull")
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
def memory_pull(path: str) -> None:
    """Pull memory from platform and update local state.

    Downloads the latest merged memory from the platform and updates
    local .nit/memory/ files. Requires platform configuration.

    Examples:
        nit memory pull
    """
    from pathlib import Path

    root = Path(path).resolve()
    config = load_config(str(root))

    if config.platform.normalized_mode not in {"platform", "byok"}:
        reporter.print_error(
            "Platform not configured. Run `nit init` to set up platform integration."
        )
        raise SystemExit(1)

    from nit.memory.sync import apply_pull_response, get_sync_version, set_sync_version
    from nit.utils.platform_client import PlatformRuntimeConfig, pull_platform_memory

    platform = PlatformRuntimeConfig(
        url=config.platform.url,
        api_key=config.platform.api_key,
        mode=config.platform.mode,
        user_id=config.platform.user_id,
        project_id=config.platform.project_id,
        key_hash=config.platform.key_hash,
    )

    reporter.print_info("Pulling memory from platform...")
    response = pull_platform_memory(platform, config.platform.project_id)
    remote_version = response.get("version", 0)
    local_version = get_sync_version(root)

    if not isinstance(remote_version, int) or remote_version <= 0:
        reporter.print_info("No memory on platform yet.")
        return

    if remote_version <= local_version:
        reporter.print_info(f"Local memory is up to date (version {local_version}).")
        return

    apply_pull_response(root, response)
    set_sync_version(root, remote_version)
    reporter.print_success(f"Pulled memory from platform (version {remote_version}).")


@memory_group.command("push")
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
def memory_push(path: str) -> None:
    """Push local memory to platform for merging.

    Uploads local memory to the platform where it is merged with
    existing memory from other sources (CI, other developers).
    Requires platform configuration.

    Examples:
        nit memory push
    """
    from pathlib import Path

    root = Path(path).resolve()
    config = load_config(str(root))

    if config.platform.normalized_mode not in {"platform", "byok"}:
        reporter.print_error(
            "Platform not configured. Run `nit init` to set up platform integration."
        )
        raise SystemExit(1)

    from nit.memory.sync import build_push_payload, set_sync_version
    from nit.utils.platform_client import PlatformRuntimeConfig, push_platform_memory

    platform = PlatformRuntimeConfig(
        url=config.platform.url,
        api_key=config.platform.api_key,
        mode=config.platform.mode,
        user_id=config.platform.user_id,
        project_id=config.platform.project_id,
        key_hash=config.platform.key_hash,
    )

    reporter.print_info("Pushing memory to platform...")
    payload = build_push_payload(
        root,
        source="local",
        project_id=config.platform.project_id,
    )
    result = push_platform_memory(platform, payload)

    new_version = result.get("version")
    if isinstance(new_version, int) and new_version > 0:
        set_sync_version(root, new_version)
        merged = result.get("merged", False)
        status = "merged with existing" if merged else "uploaded"
        reporter.print_success(f"Memory {status} (version {new_version}).")
    else:
        reporter.print_success("Memory pushed to platform.")


def _display_global_memory(memory: Any) -> None:
    """Display global memory in a human-readable format."""
    # Conventions
    conventions = memory.get_conventions()
    if conventions:
        console.print("[bold]Conventions:[/bold]")
        for key, value in conventions.items():
            console.print(f"  • {key}: {value}")
        console.print()
    else:
        console.print("[dim]No conventions recorded[/dim]")
        console.print()

    # Known patterns
    known_patterns = memory.get_known_patterns()
    if known_patterns:
        console.print(f"[bold]Known Patterns ({len(known_patterns)}):[/bold]")
        for pattern in known_patterns[:MAX_MEMORY_PATTERNS_DISPLAY]:
            console.print(f"  • {pattern.get('pattern', 'N/A')}")
            console.print(f"    Success count: {pattern.get('success_count', 0)}")
            console.print(f"    Last used: {pattern.get('last_used', 'Never')}")
        if len(known_patterns) > MAX_MEMORY_PATTERNS_DISPLAY:
            console.print(f"  ... and {len(known_patterns) - MAX_MEMORY_PATTERNS_DISPLAY} more")
        console.print()
    else:
        console.print("[dim]No known patterns recorded[/dim]")
        console.print()

    # Failed patterns
    failed_patterns = memory.get_failed_patterns()
    if failed_patterns:
        console.print(f"[bold]Failed Patterns ({len(failed_patterns)}):[/bold]")
        for pattern in failed_patterns[:MAX_MEMORY_PATTERNS_DISPLAY]:
            console.print(f"  • {pattern.get('pattern', 'N/A')}")
            console.print(f"    Reason: {pattern.get('reason', 'Unknown')}")
        if len(failed_patterns) > MAX_MEMORY_PATTERNS_DISPLAY:
            console.print(f"  ... and {len(failed_patterns) - MAX_MEMORY_PATTERNS_DISPLAY} more")
        console.print()
    else:
        console.print("[dim]No failed patterns recorded[/dim]")
        console.print()

    # Statistics
    stats = memory.get_stats()
    console.print("[bold]Statistics:[/bold]")
    console.print(f"  Total runs: {stats.get('total_runs', 0)}")
    console.print(f"  Successful generations: {stats.get('successful_generations', 0)}")
    console.print(f"  Failed generations: {stats.get('failed_generations', 0)}")
    console.print(f"  Tests generated: {stats.get('total_tests_generated', 0)}")
    console.print(f"  Tests passing: {stats.get('total_tests_passing', 0)}")
    console.print(f"  Last run: {stats.get('last_run', 'Never')}")
    console.print()


def _display_package_memory(memory: Any) -> None:
    """Display package memory in a human-readable format."""
    # Test patterns
    test_patterns = memory.get_test_patterns()
    if test_patterns:
        console.print("[bold]Test Patterns:[/bold]")
        for key, value in test_patterns.items():
            console.print(f"  • {key}: {value}")
        console.print()
    else:
        console.print("[dim]No test patterns recorded[/dim]")
        console.print()

    # Known issues
    known_issues = memory.get_known_issues()
    if known_issues:
        console.print(f"[bold]Known Issues ({len(known_issues)}):[/bold]")
        for issue in known_issues[:MAX_MEMORY_PATTERNS_DISPLAY]:
            console.print(f"  • {issue.get('issue', 'N/A')}")
            if issue.get("workaround"):
                console.print(f"    Workaround: {issue['workaround']}")
        if len(known_issues) > MAX_MEMORY_PATTERNS_DISPLAY:
            console.print(f"  ... and {len(known_issues) - MAX_MEMORY_PATTERNS_DISPLAY} more")
        console.print()
    else:
        console.print("[dim]No known issues recorded[/dim]")
        console.print()

    # Coverage history
    coverage_history = memory.get_coverage_history()
    if coverage_history:
        latest = coverage_history[-1]
        console.print("[bold]Coverage:[/bold]")
        console.print(f"  Latest: {latest.get('coverage_percent', 0):.1f}%")
        console.print(f"  History: {len(coverage_history)} snapshot(s)")
        console.print()
    else:
        console.print("[dim]No coverage history recorded[/dim]")
        console.print()

    # LLM feedback
    llm_feedback = memory.get_llm_feedback()
    if llm_feedback:
        console.print(f"[bold]LLM Feedback ({len(llm_feedback)}):[/bold]")
        for feedback in llm_feedback[:MAX_MEMORY_FEEDBACK_DISPLAY]:
            console.print(
                f"  • [{feedback.get('type', 'N/A')}] {feedback.get('content', 'N/A')[:80]}"
            )
        if len(llm_feedback) > MAX_MEMORY_FEEDBACK_DISPLAY:
            console.print(f"  ... and {len(llm_feedback) - MAX_MEMORY_FEEDBACK_DISPLAY} more")
        console.print()
    else:
        console.print("[dim]No LLM feedback recorded[/dim]")
        console.print()
