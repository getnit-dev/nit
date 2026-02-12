# Configuration

nit is configured via a `.nit.yml` file at the root of your project. All sections are optional — nit uses sensible defaults and auto-detection when values are not specified.

## Full configuration reference

```yaml
# Project settings
project:
  root: .                          # Project root directory
  primary_language: python         # Primary language (auto-detected if empty)
  workspace_tool: none             # Monorepo tool: turborepo, nx, pnpm, yarn, cargo

# Testing framework overrides
testing:
  unit_framework: pytest           # Unit test framework (auto-detected)
  e2e_framework: playwright        # E2E framework (auto-detected)
  integration_framework: ""        # Integration test framework

# LLM provider configuration
llm:
  provider: openai                 # openai, anthropic, gemini, openrouter, bedrock, vertex_ai, azure
  model: gpt-4o                    # Model identifier
  api_key: ${OPENAI_API_KEY}       # Supports ${ENV_VAR} expansion
  base_url: ""                     # Custom base URL (Ollama, proxy)
  mode: builtin                    # builtin, cli, custom, ollama
  temperature: 0.2                 # Sampling temperature (0.0-2.0)
  max_tokens: 4096                 # Max output tokens
  requests_per_minute: 60          # Rate limit
  max_retries: 3                   # Retry attempts on failure
  cli_command: ""                  # Command for cli/custom mode
  cli_timeout: 300                 # CLI timeout in seconds
  cli_extra_args: []               # Additional CLI arguments
  token_budget: 0                  # Session token budget (0 = unlimited)

# Git and PR automation
git:
  auto_commit: false               # Auto-commit generated tests
  auto_pr: false                   # Auto-create PRs
  create_issues: false             # Create GitHub issues for bugs
  create_fix_prs: false            # Create PRs for bug fixes
  branch_prefix: "nit/"            # Branch name prefix
  commit_message_template: ""      # Custom commit message template
  base_branch: ""                  # Base branch (auto-detected)

# Reporting and output
report:
  slack_webhook: ""                # Slack webhook URL
  email_alerts: []                 # Email addresses for alerts
  format: terminal                 # terminal, json, html, markdown
  upload_to_platform: true         # Upload to nit platform
  html_output_dir: .nit/reports    # HTML report output directory
  serve_port: 8080                 # Port for HTML report server

# Coverage thresholds
coverage:
  line_threshold: 80.0             # Minimum line coverage %
  branch_threshold: 75.0           # Minimum branch coverage %
  function_threshold: 85.0         # Minimum function coverage %
  complexity_threshold: 10         # Cyclomatic complexity threshold
  undertested_threshold: 50.0      # "Undertested" cutoff %

# Platform integration
platform:
  url: ""                          # Platform base URL
  api_key: ""                      # Platform API key
  mode: ""                         # byok, disabled
  user_id: ""                      # User ID for usage metadata
  project_id: ""                   # Project ID for reports
  key_hash: ""                     # Key hash override

# Workspace / monorepo
workspace:
  auto_detect: true                # Auto-detect workspace structure
  packages: []                     # Explicit package paths

# E2E testing
e2e:
  enabled: false                   # Enable E2E test generation
  base_url: ""                     # Base URL for E2E tests
  auth:
    strategy: ""                   # form, token, oauth, cookie, custom
    login_url: ""                  # Login page URL
    username: ${E2E_USERNAME}       # Username (env var expansion)
    password: ${E2E_PASSWORD}       # Password (env var expansion)
    token: ""                      # Bearer token
    auth_header_name: Authorization # HTTP header name
    auth_prefix: Bearer            # Token prefix
    success_indicator: ""          # Login success selector/URL
    cookie_name: ""                # Cookie name
    cookie_value: ""               # Cookie value
    custom_script: ""              # Custom auth script path
    timeout: 30000                 # Auth timeout (ms)

# Documentation generation
docs:
  enabled: true                    # Enable documentation generation
  output_dir: ""                   # Output directory (empty = inline only)
  style: ""                        # Docstring style: google, numpy (auto-detect)
  framework: ""                    # Framework override (auto-detect if empty)
  write_to_source: false           # Write docstrings back into source files
  check_mismatch: true             # Detect doc/code semantic mismatches
  exclude_patterns: []             # Glob patterns to exclude from docs
  max_tokens: 4096                 # Token budget per file

# Pipeline execution
pipeline:
  max_fix_loops: 1                 # Max fix-rerun iterations (0 = unlimited)

# Test execution performance
execution:
  parallel_shards: 4               # Number of parallel shards
  min_files_for_sharding: 8        # Min files to enable sharding

# Security analysis
security:
  enabled: true                    # Enable security scanning (default: true)
  llm_validation: true             # Validate findings via LLM (default: true)
  confidence_threshold: 0.7        # Min confidence to report (0.0-1.0)
  severity_threshold: medium       # Min severity: critical, high, medium, low, info
  exclude_patterns: []             # Glob patterns to skip (e.g., "vendor/*")

# Sentry observability (opt-in)
sentry:
  enabled: false                   # No data sent unless true
  dsn: ""                          # Sentry DSN
  traces_sample_rate: 0.0          # Tracing sample rate (0.0-1.0)
  profiles_sample_rate: 0.0        # Profiling sample rate (0.0-1.0)
  enable_logs: false               # Send structured logs
  environment: ""                  # Environment tag override
  send_default_pii: false          # Never sends PII by default

# Per-package overrides (monorepo)
packages:
  packages/web-app:
    e2e:
      enabled: true
      base_url: http://localhost:3000
      auth:
        strategy: form
        login_url: http://localhost:3000/login
        username: ${E2E_USERNAME}
        password: ${E2E_PASSWORD}
```

## Environment variable expansion

Any string value in `.nit.yml` can reference environment variables using `${VAR_NAME}` syntax:

```yaml
llm:
  api_key: ${OPENAI_API_KEY}
e2e:
  auth:
    username: ${E2E_USERNAME}
    password: ${E2E_PASSWORD}
```

If the environment variable is not set, nit logs a warning and uses an empty string.

## Validating configuration

```bash
nit config validate
```

This checks all fields for type errors, missing required values, and invalid ranges. See [Config Commands](../cli/config-commands.md) for more details.

## Config management via CLI

```bash
# Set a value (using dotted keys)
nit config set llm.model gpt-4o

# Show current configuration (sensitive values masked)
nit config show

# Validate configuration
nit config validate
```

## Section reference

| Section | Description | Details |
|---------|-------------|---------|
| `project` | Project root, language, workspace tool | [Quickstart](quickstart.md) |
| `llm` | LLM provider, model, API key, mode | [LLM Overview](../llm/index.md) |
| `git` | Auto-commit, auto-PR, issue creation | [GitHub Integration](../integrations/github.md) |
| `report` | Output format, Slack webhook, platform upload | [Integrations](../integrations/slack.md) |
| `coverage` | Line, branch, function coverage thresholds | [Coverage Adapters](../adapters/coverage.md) |
| `docs` | Doc generation, style, mismatch detection, write-back | [Documentation Adapters](../adapters/documentation.md) |
| `platform` | Platform URL, API key, mode | [Platform Integration](../integrations/platform.md) |
| `workspace` | Auto-detect, explicit package paths | [Monorepo Support](../ci/monorepo.md) |
| `e2e` | E2E testing, auth strategies | [E2E Testing](../adapters/e2e.md) |
| `pipeline` | Fix loop limits | [Pipelines](../agents/pipelines.md) |
| `execution` | Parallel shards, sharding thresholds | [Sharding](../ci/sharding.md) |
| `sentry` | Error monitoring, tracing, profiling | [Sentry Integration](../integrations/sentry.md) |
| `packages` | Per-package overrides for monorepos | [Monorepo Support](../ci/monorepo.md) |
