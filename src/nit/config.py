"""Configuration parsing from ``.nit.yml``."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")

_MIN_AUTH_TIMEOUT_MS = 1000


def _resolve_env_vars(value: str) -> str:
    """Replace ``${VAR_NAME}`` placeholders with environment variable values."""

    def _replace(match: re.Match[str]) -> str:
        var = match.group(1)
        resolved = os.environ.get(var)
        if resolved is None:
            logger.warning("Environment variable %s is not set (referenced in config)", var)
            return ""
        return resolved

    return _ENV_VAR_RE.sub(_replace, value)


def _resolve_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve environment variables in a dictionary."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = _resolve_env_vars(value)
        elif isinstance(value, dict):
            result[key] = _resolve_dict(value)
        elif isinstance(value, list):
            result[key] = [
                _resolve_env_vars(item) if isinstance(item, str) else item for item in value
            ]
        else:
            result[key] = value
    return result


@dataclass
class ProjectConfig:
    """Project-level configuration."""

    root: str
    """Project root directory."""

    primary_language: str = ""
    """Primary programming language of the project."""

    workspace_tool: str = "none"
    """Workspace/monorepo tool (turborepo, nx, pnpm, yarn, cargo, etc.)."""


@dataclass
class TestingConfig:
    """Testing framework configuration."""

    unit_framework: str = ""
    """Unit testing framework (pytest, vitest, jest, etc.)."""

    e2e_framework: str = ""
    """E2E testing framework (playwright, cypress, etc.)."""

    integration_framework: str = ""
    """Integration testing framework."""


@dataclass
class LLMConfig:
    """LLM configuration."""

    provider: str = "openai"
    """LLM provider name (openai, anthropic, ollama, etc.)."""

    model: str = ""
    """Model identifier (e.g. gpt-4o, claude-sonnet-4-5-20250514)."""

    api_key: str = ""
    """API key for the provider (supports ${ENV_VAR} expansion)."""

    base_url: str = ""
    """Custom base URL (useful for Ollama or proxied endpoints)."""

    mode: str = "builtin"
    """Execution mode: builtin (LiteLLM), cli, custom, or ollama."""

    temperature: float = 0.2
    """Default sampling temperature."""

    max_tokens: int = 4096
    """Default maximum tokens to generate."""

    requests_per_minute: int = 60
    """Rate limit: maximum requests per minute."""

    max_retries: int = 3
    """Maximum number of retry attempts on transient failures."""

    cli_command: str = ""
    """CLI command to execute in ``cli``/``custom`` mode."""

    cli_timeout: int = 300
    """Timeout in seconds for CLI command execution."""

    cli_extra_args: list[str] = field(default_factory=list)
    """Additional arguments for CLI mode commands."""

    token_budget: int = 0
    """Total token budget for the session (0 = unlimited)."""

    @property
    def is_configured(self) -> bool:
        """Return True when enough info is present for generation."""
        if self.mode == "ollama":
            return bool(self.model)
        if self.mode in {"cli", "custom"}:
            return bool(self.model and self.cli_command)
        return bool(self.model and self.api_key)


@dataclass
class GitConfig:
    """Git/PR/commit configuration."""

    auto_commit: bool = False
    """Automatically commit changes after generation/fixes."""

    auto_pr: bool = False
    """Automatically create PRs for generated tests/fixes."""

    create_issues: bool = False
    """Automatically create GitHub issues for detected bugs."""

    create_fix_prs: bool = False
    """Automatically create separate PRs for each bug fix."""

    branch_prefix: str = "nit/"
    """Prefix for auto-created branches (e.g., 'nit/fix-bug-123')."""

    commit_message_template: str = ""
    """Template for auto-commit messages (empty = use default)."""

    base_branch: str = ""
    """Default base branch for PRs (empty = auto-detect from git)."""


@dataclass
class ReportConfig:
    """Reporting and output configuration."""

    slack_webhook: str = ""
    """Slack webhook URL for notifications."""

    email_alerts: list[str] = field(default_factory=list)
    """Email addresses for alerts."""

    format: str = "terminal"
    """Default output format: terminal, json, html, markdown."""

    upload_to_platform: bool = True
    """Upload reports to platform (when platform is configured)."""

    html_output_dir: str = ".nit/reports"
    """Directory for HTML report output."""

    serve_port: int = 8080
    """Port for serving HTML reports (when using --serve)."""


@dataclass
class CoverageConfig:
    """Coverage thresholds and analysis configuration."""

    line_threshold: float = 80.0
    """Minimum acceptable line coverage percentage (default: 80%)."""

    branch_threshold: float = 75.0
    """Minimum acceptable branch coverage percentage (default: 75%)."""

    function_threshold: float = 85.0
    """Minimum acceptable function coverage percentage (default: 85%)."""

    complexity_threshold: int = 10
    """Cyclomatic complexity above which functions are high-priority (default: 10)."""

    undertested_threshold: float = 50.0
    """Coverage % below which functions are considered undertested (default: 50%)."""


@dataclass
class PlatformConfig:
    """Platform integration configuration."""

    url: str = ""
    """Platform base URL (e.g., https://platform.getnit.dev)."""

    api_key: str = ""
    """Platform virtual API key for proxy/reporting."""

    mode: str = ""
    """Platform mode: platform | byok | disabled."""

    user_id: str = ""
    """Optional user ID for usage metadata."""

    project_id: str = ""
    """Optional project ID for usage metadata/report uploads."""

    key_hash: str = ""
    """Optional key hash override for usage metadata."""

    @property
    def normalized_mode(self) -> str:
        """Resolve platform mode with defaults."""
        mode = self.mode.strip().lower()
        if mode in {"platform", "byok", "disabled"}:
            return mode
        if self.url and self.api_key:
            return "platform"
        return "disabled"


@dataclass
class AuthConfig:
    """E2E authentication configuration."""

    strategy: str = ""
    """Auth strategy: form, token, oauth, cookie, or custom."""

    login_url: str = ""
    """Login page URL (for form-based auth)."""

    username: str = ""
    """Username or email for login (supports ${ENV_VAR} expansion)."""

    password: str = ""
    """Password for login (supports ${ENV_VAR} expansion)."""

    token: str = ""
    """Bearer token or API key for token-based auth (supports ${ENV_VAR} expansion)."""

    auth_header_name: str = "Authorization"
    """HTTP header name for token-based auth."""

    auth_prefix: str = "Bearer"
    """Prefix for token value (e.g., 'Bearer' for 'Bearer <token>')."""

    success_indicator: str = ""
    """Selector or URL pattern indicating successful login."""

    cookie_name: str = ""
    """Cookie name for cookie-based auth."""

    cookie_value: str = ""
    """Cookie value (supports ${ENV_VAR} expansion)."""

    custom_script: str = ""
    """Path to custom auth setup script (for custom strategy)."""

    timeout: int = 30000
    """Timeout in milliseconds for auth operations."""


@dataclass
class E2EConfig:
    """E2E testing configuration."""

    enabled: bool = False
    """Whether E2E testing is enabled for this package."""

    base_url: str = ""
    """Base URL for E2E tests (e.g., http://localhost:3000)."""

    auth: AuthConfig = field(default_factory=AuthConfig)
    """Authentication configuration for E2E tests."""


@dataclass
class WorkspaceConfig:
    """Workspace/monorepo configuration."""

    auto_detect: bool = True
    """Whether to auto-detect workspace structure."""

    packages: list[str] = field(default_factory=list)
    """Explicit list of package paths (overrides auto-detection)."""


@dataclass
class SentryConfig:
    """Sentry error monitoring and observability configuration."""

    enabled: bool = False
    """Opt-in flag. No Sentry data sent unless True."""

    dsn: str = ""
    """Sentry DSN (Data Source Name). Configurable, not hardcoded."""

    traces_sample_rate: float = 0.0
    """Fraction of transactions sent for tracing (0.0-1.0). 0 = disabled."""

    profiles_sample_rate: float = 0.0
    """Fraction of profiled transactions (0.0-1.0). 0 = disabled."""

    enable_logs: bool = False
    """Send structured logs to Sentry."""

    environment: str = ""
    """Override environment tag (auto-detected if empty)."""

    send_default_pii: bool = False
    """Never enable by default. Kept False for privacy."""


@dataclass
class PipelineConfig:
    """Pipeline execution configuration."""

    max_fix_loops: int = 1
    """Maximum fix-rerun iterations (0 = unlimited, 1 = single pass)."""


@dataclass
class ExecutionConfig:
    """Test execution performance configuration."""

    parallel_shards: int = 4
    """Number of parallel shards for test execution."""

    min_files_for_sharding: int = 8
    """Minimum test files required to enable automatic sharding."""


@dataclass
class DocsConfig:
    """Documentation generation configuration."""

    enabled: bool = True
    """Enable documentation generation."""

    output_dir: str = ""
    """Output directory for generated docs (empty = inline docstrings only)."""

    style: str = ""
    """Docstring style preference (empty = auto-detect, 'google', 'numpy')."""

    framework: str = ""
    """Documentation framework override (empty = auto-detect)."""

    write_to_source: bool = False
    """Write generated docstrings back into source files."""

    check_mismatch: bool = True
    """Detect semantic doc/code mismatches via LLM."""

    exclude_patterns: list[str] = field(default_factory=list)
    """Glob patterns for files to exclude from documentation."""

    max_tokens: int = 4096
    """Token budget per file for LLM generation."""


@dataclass
class NitConfig:
    """Complete nit configuration from ``.nit.yml``."""

    project: ProjectConfig
    """Project configuration."""

    testing: TestingConfig = field(default_factory=TestingConfig)
    """Testing configuration."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    """LLM configuration."""

    git: GitConfig = field(default_factory=GitConfig)
    """Git/PR/commit configuration."""

    report: ReportConfig = field(default_factory=ReportConfig)
    """Reporting configuration."""

    platform: PlatformConfig = field(default_factory=PlatformConfig)
    """Platform integration configuration."""

    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    """Workspace configuration."""

    e2e: E2EConfig = field(default_factory=E2EConfig)
    """Global E2E configuration."""

    coverage: CoverageConfig = field(default_factory=CoverageConfig)
    """Coverage thresholds configuration."""

    docs: DocsConfig = field(default_factory=DocsConfig)
    """Documentation generation configuration."""

    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    """Pipeline execution configuration."""

    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    """Test execution performance configuration."""

    sentry: SentryConfig = field(default_factory=SentryConfig)
    """Sentry observability configuration."""

    packages: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Per-package configuration overrides."""

    raw: dict[str, Any] = field(default_factory=dict)
    """Raw parsed YAML for extension/debugging."""

    def get_package_e2e_config(self, package_path: str) -> E2EConfig:
        """Get E2E configuration for a specific package.

        Merges global config with package-specific overrides.
        """
        package_config = self.packages.get(package_path, {})
        e2e_raw = package_config.get("e2e", {})
        if not isinstance(e2e_raw, dict):
            return self.e2e

        # Start with global E2E config
        return _parse_e2e_config(e2e_raw, self.e2e)


def _parse_auth_config(auth_raw: dict[str, Any], default: AuthConfig | None = None) -> AuthConfig:
    """Parse authentication configuration from raw YAML."""
    if default is None:
        default = AuthConfig()

    return AuthConfig(
        strategy=str(auth_raw.get("strategy", default.strategy)),
        login_url=str(auth_raw.get("login_url", default.login_url)),
        username=str(
            auth_raw.get("username", default.username)
            or auth_raw.get("credentials", {}).get("username", default.username)
        ),
        password=str(
            auth_raw.get("password", default.password)
            or auth_raw.get("credentials", {}).get("password", default.password)
        ),
        token=str(auth_raw.get("token", default.token)),
        auth_header_name=str(auth_raw.get("token_header", default.auth_header_name)),
        auth_prefix=str(auth_raw.get("token_prefix", default.auth_prefix)),
        success_indicator=str(auth_raw.get("success_indicator", default.success_indicator)),
        cookie_name=str(auth_raw.get("cookie_name", default.cookie_name)),
        cookie_value=str(auth_raw.get("cookie_value", default.cookie_value)),
        custom_script=str(auth_raw.get("custom_script", default.custom_script)),
        timeout=int(auth_raw.get("timeout", default.timeout)),
    )


def _parse_e2e_config(e2e_raw: dict[str, Any], default: E2EConfig | None = None) -> E2EConfig:
    """Parse E2E configuration from raw YAML."""
    if default is None:
        default = E2EConfig()

    auth_raw = e2e_raw.get("auth", {})
    if not isinstance(auth_raw, dict):
        auth_raw = {}

    return E2EConfig(
        enabled=bool(e2e_raw.get("enabled", default.enabled)),
        base_url=str(e2e_raw.get("base_url", default.base_url)),
        auth=_parse_auth_config(auth_raw, default.auth),
    )


def _parse_coverage_config(raw: dict[str, Any]) -> CoverageConfig:
    """Parse coverage configuration from raw YAML."""
    coverage_raw = raw.get("coverage", {})
    if not isinstance(coverage_raw, dict):
        coverage_raw = {}

    return CoverageConfig(
        line_threshold=float(coverage_raw.get("line_threshold", 80.0)),
        branch_threshold=float(coverage_raw.get("branch_threshold", 75.0)),
        function_threshold=float(coverage_raw.get("function_threshold", 85.0)),
        complexity_threshold=int(coverage_raw.get("complexity_threshold", 10)),
        undertested_threshold=float(coverage_raw.get("undertested_threshold", 50.0)),
    )


def _parse_docs_config(raw: dict[str, Any]) -> DocsConfig:
    """Parse documentation generation configuration from raw YAML."""
    docs_raw = raw.get("docs", {})
    if not isinstance(docs_raw, dict):
        docs_raw = {}

    exclude_raw = docs_raw.get("exclude_patterns", [])
    exclude_patterns = [str(p) for p in exclude_raw] if isinstance(exclude_raw, list) else []

    return DocsConfig(
        enabled=bool(docs_raw.get("enabled", True)),
        output_dir=str(docs_raw.get("output_dir", "")),
        style=str(docs_raw.get("style", "")),
        framework=str(docs_raw.get("framework", "")),
        write_to_source=bool(docs_raw.get("write_to_source", False)),
        check_mismatch=bool(docs_raw.get("check_mismatch", True)),
        exclude_patterns=exclude_patterns,
        max_tokens=int(docs_raw.get("max_tokens", 4096)),
    )


def _parse_pipeline_config(raw: dict[str, Any]) -> PipelineConfig:
    """Parse pipeline configuration from raw YAML."""
    pipeline_raw = raw.get("pipeline", {})
    if not isinstance(pipeline_raw, dict):
        pipeline_raw = {}

    return PipelineConfig(
        max_fix_loops=int(pipeline_raw.get("max_fix_loops", 1)),
    )


def _parse_execution_config(raw: dict[str, Any]) -> ExecutionConfig:
    """Parse execution performance configuration from raw YAML."""
    exec_raw = raw.get("execution", {})
    if not isinstance(exec_raw, dict):
        exec_raw = {}

    return ExecutionConfig(
        parallel_shards=int(exec_raw.get("parallel_shards", 4)),
        min_files_for_sharding=int(exec_raw.get("min_files_for_sharding", 8)),
    )


def _parse_sentry_config(raw: dict[str, Any]) -> SentryConfig:
    """Parse Sentry configuration from raw YAML."""
    sentry_raw = raw.get("sentry", {})
    if not isinstance(sentry_raw, dict):
        sentry_raw = {}

    enabled_raw = sentry_raw.get("enabled", os.environ.get("NIT_SENTRY_ENABLED", ""))
    enabled = enabled_raw in {True, "true", "1", "yes"}

    return SentryConfig(
        enabled=enabled,
        dsn=str(sentry_raw.get("dsn", os.environ.get("NIT_SENTRY_DSN", ""))),
        traces_sample_rate=float(
            sentry_raw.get(
                "traces_sample_rate",
                os.environ.get("NIT_SENTRY_TRACES_SAMPLE_RATE", "0.0"),
            )
        ),
        profiles_sample_rate=float(
            sentry_raw.get(
                "profiles_sample_rate",
                os.environ.get("NIT_SENTRY_PROFILES_SAMPLE_RATE", "0.0"),
            )
        ),
        enable_logs=sentry_raw.get(
            "enable_logs",
            os.environ.get("NIT_SENTRY_ENABLE_LOGS", ""),
        )
        in {True, "true", "1", "yes"},
        environment=str(sentry_raw.get("environment", "")),
        send_default_pii=False,
    )


def load_config(root: str | Path) -> NitConfig:
    """Load and parse the complete ``.nit.yml`` configuration.

    Falls back to sensible defaults and environment variables when
    the YAML file is missing or incomplete.
    """
    root_path = Path(root).resolve()
    nit_yml = root_path / ".nit.yml"

    raw: dict[str, Any] = {}
    if nit_yml.is_file():
        text = nit_yml.read_text(encoding="utf-8")
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict):
            raw = _resolve_dict(parsed)

    # Parse project section
    project_raw = raw.get("project", {})
    if not isinstance(project_raw, dict):
        project_raw = {}

    project = ProjectConfig(
        root=str(project_raw.get("root", root_path)),
        primary_language=str(project_raw.get("primary_language", "")),
        workspace_tool=str(project_raw.get("workspace_tool", "none")),
    )

    # Parse testing section
    testing_raw = raw.get("testing", {})
    if not isinstance(testing_raw, dict):
        testing_raw = {}

    testing = TestingConfig(
        unit_framework=str(testing_raw.get("unit_framework", "")),
        e2e_framework=str(testing_raw.get("e2e_framework", "")),
        integration_framework=str(testing_raw.get("integration_framework", "")),
    )

    # Parse LLM section
    llm_raw = raw.get("llm", {})
    if not isinstance(llm_raw, dict):
        llm_raw = {}

    llm = LLMConfig(
        provider=str(llm_raw.get("provider", os.environ.get("NIT_LLM_PROVIDER", "openai"))),
        model=str(llm_raw.get("model", os.environ.get("NIT_LLM_MODEL", ""))),
        api_key=str(llm_raw.get("api_key", os.environ.get("NIT_LLM_API_KEY", ""))),
        base_url=str(llm_raw.get("base_url", os.environ.get("NIT_LLM_BASE_URL", ""))),
        mode=str(llm_raw.get("mode", "builtin")),
        temperature=float(llm_raw.get("temperature", 0.2)),
        max_tokens=int(llm_raw.get("max_tokens", 4096)),
        requests_per_minute=int(llm_raw.get("requests_per_minute", 60)),
        max_retries=int(llm_raw.get("max_retries", 3)),
        cli_command=str(llm_raw.get("cli_command", "")),
        cli_timeout=int(llm_raw.get("cli_timeout", 300)),
        cli_extra_args=(
            [str(arg) for arg in llm_raw.get("cli_extra_args", [])]
            if isinstance(llm_raw.get("cli_extra_args", []), list)
            else []
        ),
        token_budget=int(llm_raw.get("token_budget", 0)),
    )

    # Parse git section
    git_raw = raw.get("git", {})
    if not isinstance(git_raw, dict):
        git_raw = {}

    git = GitConfig(
        auto_commit=bool(git_raw.get("auto_commit", False)),
        auto_pr=bool(git_raw.get("auto_pr", False)),
        create_issues=bool(git_raw.get("create_issues", False)),
        create_fix_prs=bool(git_raw.get("create_fix_prs", False)),
        branch_prefix=str(git_raw.get("branch_prefix", "nit/")),
        commit_message_template=str(git_raw.get("commit_message_template", "")),
        base_branch=str(git_raw.get("base_branch", "")),
    )

    # Parse report section
    report_raw = raw.get("report", {})
    if not isinstance(report_raw, dict):
        report_raw = {}

    report = ReportConfig(
        slack_webhook=str(report_raw.get("slack_webhook", "")),
        email_alerts=list(report_raw.get("email_alerts", [])),
        format=str(report_raw.get("format", "terminal")),
        upload_to_platform=bool(report_raw.get("upload_to_platform", True)),
        html_output_dir=str(report_raw.get("html_output_dir", ".nit/reports")),
        serve_port=int(report_raw.get("serve_port", 8080)),
    )

    # Parse platform section
    platform_raw = raw.get("platform", {})
    if not isinstance(platform_raw, dict):
        platform_raw = {}

    platform = PlatformConfig(
        url=str(platform_raw.get("url", os.environ.get("NIT_PLATFORM_URL", ""))),
        api_key=str(platform_raw.get("api_key", os.environ.get("NIT_PLATFORM_API_KEY", ""))),
        mode=str(platform_raw.get("mode", os.environ.get("NIT_PLATFORM_MODE", ""))),
        user_id=str(platform_raw.get("user_id", os.environ.get("NIT_PLATFORM_USER_ID", ""))),
        project_id=str(
            platform_raw.get("project_id", os.environ.get("NIT_PLATFORM_PROJECT_ID", ""))
        ),
        key_hash=str(platform_raw.get("key_hash", os.environ.get("NIT_PLATFORM_KEY_HASH", ""))),
    )

    # Parse workspace section
    workspace_raw = raw.get("workspace", {})
    if not isinstance(workspace_raw, dict):
        workspace_raw = {}

    workspace = WorkspaceConfig(
        auto_detect=bool(workspace_raw.get("auto_detect", True)),
        packages=list(workspace_raw.get("packages", [])),
    )

    # Parse global E2E section
    e2e_raw = raw.get("e2e", {})
    if not isinstance(e2e_raw, dict):
        e2e_raw = {}
    e2e = _parse_e2e_config(e2e_raw)

    coverage = _parse_coverage_config(raw)

    docs = _parse_docs_config(raw)

    pipeline = _parse_pipeline_config(raw)

    execution = _parse_execution_config(raw)

    sentry = _parse_sentry_config(raw)

    packages_raw = raw.get("packages", {})
    if not isinstance(packages_raw, dict):
        packages_raw = {}

    return NitConfig(
        project=project,
        testing=testing,
        llm=llm,
        git=git,
        report=report,
        platform=platform,
        workspace=workspace,
        e2e=e2e,
        coverage=coverage,
        docs=docs,
        pipeline=pipeline,
        execution=execution,
        sentry=sentry,
        packages=packages_raw,
        raw=raw,
    )


def validate_auth_config(auth: AuthConfig, prefix: str = "e2e.auth") -> list[str]:
    """Validate authentication configuration.

    Args:
        auth: The auth config to validate
        prefix: Prefix for error messages (e.g., "packages.my-app.e2e.auth")

    Returns:
        List of error messages (empty if valid)
    """
    errors: list[str] = []

    if not auth.strategy:
        return errors  # Strategy is optional

    valid_strategies = ("form", "token", "oauth", "cookie", "custom")
    if auth.strategy not in valid_strategies:
        errors.append(
            f"{prefix}.strategy must be one of: {', '.join(valid_strategies)} "
            f"(got: {auth.strategy})"
        )

    # Strategy-specific validation
    if auth.strategy == "form":
        if not auth.login_url:
            errors.append(f"{prefix}.login_url is required for form-based auth")
        if not auth.username or not auth.password:
            errors.append(
                f"{prefix}.username and {prefix}.password are required for form-based auth"
            )

    if auth.strategy == "token" and not auth.token:
        errors.append(f"{prefix}.token is required for token-based auth")

    if auth.strategy == "cookie" and (not auth.cookie_name or not auth.cookie_value):
        errors.append(
            f"{prefix}.cookie_name and {prefix}.cookie_value are required for cookie-based auth"
        )

    if auth.strategy == "custom" and not auth.custom_script:
        errors.append(f"{prefix}.custom_script is required for custom auth strategy")

    if auth.timeout < _MIN_AUTH_TIMEOUT_MS:
        errors.append(
            f"{prefix}.timeout should be at least {_MIN_AUTH_TIMEOUT_MS}ms "
            f"(got: {auth.timeout})"
        )

    return errors


def _validate_llm_config(llm: LLMConfig) -> list[str]:
    """Validate LLM configuration fields."""
    errors: list[str] = []

    if llm.mode not in ("builtin", "cli", "custom", "ollama"):
        errors.append(f"llm.mode must be one of: builtin, cli, custom, ollama (got: {llm.mode})")

    if llm.mode in {"cli", "custom"} and not llm.cli_command:
        errors.append(f"llm.cli_command is required when llm.mode is {llm.mode}")

    if llm.mode in {"cli", "custom"} and llm.cli_timeout < 1:
        errors.append("llm.cli_timeout must be >= 1 for cli/custom mode")

    if llm.provider not in ("openai", "anthropic", "ollama"):
        errors.append(
            f"llm.provider not recognized: {llm.provider} "
            "(should be openai, anthropic, or ollama)"
        )

    max_temperature = 2.0
    if llm.temperature < 0 or llm.temperature > max_temperature:
        errors.append(
            f"llm.temperature should be between 0 and {max_temperature} "
            f"(got: {llm.temperature})"
        )

    if llm.max_tokens < 1:
        errors.append(f"llm.max_tokens must be positive (got: {llm.max_tokens})")

    return errors


def _validate_platform_config(platform: PlatformConfig) -> list[str]:
    """Validate platform integration settings."""
    errors: list[str] = []
    platform_mode = platform.normalized_mode

    if platform_mode not in {"platform", "byok", "disabled"}:
        errors.append(
            f"platform.mode must be one of: platform, byok, disabled (got: {platform.mode})"
        )

    if platform_mode in {"platform", "byok"}:
        if not platform.url:
            errors.append("platform.url is required when platform.mode is platform or byok")
        if not platform.api_key:
            errors.append("platform.api_key is required when platform.mode is platform or byok")

    return errors


def _validate_coverage_config(coverage: CoverageConfig) -> list[str]:
    """Validate coverage threshold settings."""
    max_percentage = 100.0
    errors: list[str] = []

    if not 0.0 <= coverage.line_threshold <= max_percentage:
        errors.append(
            f"coverage.line_threshold must be between 0 and 100 "
            f"(got: {coverage.line_threshold})"
        )

    if not 0.0 <= coverage.branch_threshold <= max_percentage:
        errors.append(
            f"coverage.branch_threshold must be between 0 and 100 "
            f"(got: {coverage.branch_threshold})"
        )

    if not 0.0 <= coverage.function_threshold <= max_percentage:
        errors.append(
            f"coverage.function_threshold must be between 0 and 100 "
            f"(got: {coverage.function_threshold})"
        )

    if coverage.complexity_threshold < 1:
        errors.append(
            f"coverage.complexity_threshold must be at least 1 "
            f"(got: {coverage.complexity_threshold})"
        )

    if not 0.0 <= coverage.undertested_threshold <= max_percentage:
        errors.append(
            f"coverage.undertested_threshold must be between 0 and 100 "
            f"(got: {coverage.undertested_threshold})"
        )

    return errors


def _validate_pipeline_config(pipeline: PipelineConfig) -> list[str]:
    """Validate pipeline execution settings."""
    errors: list[str] = []

    if pipeline.max_fix_loops < 0:
        errors.append(
            f"pipeline.max_fix_loops must be non-negative (got: {pipeline.max_fix_loops})"
        )

    return errors


def _validate_sentry_config(sentry: SentryConfig) -> list[str]:
    """Validate Sentry configuration."""
    errors: list[str] = []

    if sentry.enabled and not sentry.dsn:
        errors.append("sentry.dsn is required when sentry.enabled is true")

    if not 0.0 <= sentry.traces_sample_rate <= 1.0:
        errors.append(
            f"sentry.traces_sample_rate must be between 0.0 and 1.0 "
            f"(got: {sentry.traces_sample_rate})"
        )

    if not 0.0 <= sentry.profiles_sample_rate <= 1.0:
        errors.append(
            f"sentry.profiles_sample_rate must be between 0.0 and 1.0 "
            f"(got: {sentry.profiles_sample_rate})"
        )

    return errors


def validate_config(config: NitConfig) -> list[str]:
    """Validate the configuration and return a list of error messages.

    Returns an empty list if the configuration is valid.
    """
    errors: list[str] = []

    if not config.project.root:
        errors.append("project.root is required")

    errors.extend(_validate_llm_config(config.llm))
    errors.extend(_validate_platform_config(config.platform))
    errors.extend(_validate_coverage_config(config.coverage))
    errors.extend(_validate_pipeline_config(config.pipeline))
    errors.extend(_validate_sentry_config(config.sentry))

    # Validate global E2E auth config
    if config.e2e.auth.strategy:
        errors.extend(validate_auth_config(config.e2e.auth, "e2e.auth"))

    # Validate per-package E2E auth configs
    for package_path in config.packages:
        package_e2e = config.get_package_e2e_config(package_path)
        if package_e2e.auth.strategy:
            errors.extend(
                validate_auth_config(package_e2e.auth, f"packages.{package_path}.e2e.auth")
            )

    return errors
