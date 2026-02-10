"""Configuration parsing from ``.nit.yml``."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(value: str) -> str:
    """Replace ``${VAR_NAME}`` placeholders with environment variable values."""

    def _replace(match: re.Match[str]) -> str:
        var = match.group(1)
        return os.environ.get(var, "")

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

    @property
    def is_configured(self) -> bool:
        """Return True when enough info is present for generation."""
        if self.mode == "ollama":
            return bool(self.model)
        if self.mode in {"cli", "custom"}:
            return bool(self.model and self.cli_command)
        return bool(self.model and self.api_key)


@dataclass
class ReportConfig:
    """Reporting configuration."""

    slack_webhook: str = ""
    """Slack webhook URL for notifications."""

    email_alerts: list[str] = field(default_factory=list)
    """Email addresses for alerts."""


@dataclass
class PlatformConfig:
    """Platform integration configuration."""

    url: str = ""
    """Platform base URL (e.g., https://api.getnit.dev)."""

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

    token_header: str = "Authorization"  # noqa: S105
    """HTTP header name for token-based auth."""

    token_prefix: str = "Bearer"  # noqa: S105
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
class NitConfig:
    """Complete nit configuration from ``.nit.yml``."""

    project: ProjectConfig
    """Project configuration."""

    testing: TestingConfig = field(default_factory=TestingConfig)
    """Testing configuration."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    """LLM configuration."""

    report: ReportConfig = field(default_factory=ReportConfig)
    """Reporting configuration."""

    platform: PlatformConfig = field(default_factory=PlatformConfig)
    """Platform integration configuration."""

    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    """Workspace configuration."""

    e2e: E2EConfig = field(default_factory=E2EConfig)
    """Global E2E configuration."""

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
        token_header=str(auth_raw.get("token_header", default.token_header)),
        token_prefix=str(auth_raw.get("token_prefix", default.token_prefix)),
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
    )

    # Parse report section
    report_raw = raw.get("report", {})
    if not isinstance(report_raw, dict):
        report_raw = {}

    report = ReportConfig(
        slack_webhook=str(report_raw.get("slack_webhook", "")),
        email_alerts=list(report_raw.get("email_alerts", [])),
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

    # Parse per-package configurations
    packages_raw = raw.get("packages", {})
    if not isinstance(packages_raw, dict):
        packages_raw = {}

    return NitConfig(
        project=project,
        testing=testing,
        llm=llm,
        report=report,
        platform=platform,
        workspace=workspace,
        e2e=e2e,
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

    if auth.timeout < 1000:  # noqa: PLR2004
        errors.append(f"{prefix}.timeout should be at least 1000ms (got: {auth.timeout})")

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


def validate_config(config: NitConfig) -> list[str]:
    """Validate the configuration and return a list of error messages.

    Returns an empty list if the configuration is valid.
    """
    errors: list[str] = []

    if not config.project.root:
        errors.append("project.root is required")

    errors.extend(_validate_llm_config(config.llm))
    errors.extend(_validate_platform_config(config.platform))

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
