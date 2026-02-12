# Sentry Integration

nit includes opt-in Sentry integration for error monitoring, performance tracing, and structured logging.

!!! warning "Opt-in only"
    No Sentry data is ever sent unless you explicitly set `sentry.enabled: true`. This is a strict opt-in — there is no default DSN hardcoded into nit.

## Configuration

```yaml
sentry:
  enabled: true                     # Must be true to send any data
  dsn: ${SENTRY_DSN}               # Your Sentry DSN
  traces_sample_rate: 0.1          # 10% of transactions traced
  profiles_sample_rate: 0.1        # 10% profiled
  enable_logs: false               # Structured log forwarding
  environment: production          # Environment tag (auto-detected if empty)
  send_default_pii: false          # Never sends PII by default
```

## What gets sent

When enabled, Sentry receives:

| Data type | Description | Controlled by |
|-----------|-------------|---------------|
| **Errors** | Unhandled exceptions with stack traces | `enabled` |
| **Transactions** | Performance traces for nit operations | `traces_sample_rate` |
| **Profiles** | CPU profiles for performance analysis | `profiles_sample_rate` |
| **Logs** | Structured log entries | `enable_logs` |

## Privacy scrubbing

nit scrubs all Sentry events before they are sent. The following data is **always removed**:

- API keys (LLM, platform, Sentry DSN)
- Passwords and tokens
- Slack webhook URLs
- Cookie values
- File paths containing usernames (replaced with `~`)
- Environment variables containing sensitive keys

This scrubbing happens locally before any data leaves your machine.

## Environment variables

All Sentry settings can be set via environment variables (useful in CI):

| Variable | Config equivalent |
|----------|-------------------|
| `NIT_SENTRY_ENABLED` | `sentry.enabled` |
| `NIT_SENTRY_DSN` | `sentry.dsn` |
| `NIT_SENTRY_TRACES_SAMPLE_RATE` | `sentry.traces_sample_rate` |
| `NIT_SENTRY_PROFILES_SAMPLE_RATE` | `sentry.profiles_sample_rate` |
| `NIT_SENTRY_ENABLE_LOGS` | `sentry.enable_logs` |

## GitHub Action

The nit GitHub Action includes Sentry inputs:

```yaml
- uses: getnit-dev/nit@v1
  with:
    llm_provider: openai
    llm_api_key: ${{ secrets.OPENAI_API_KEY }}
    sentry_enabled: 'true'
    sentry_dsn: ${{ secrets.SENTRY_DSN }}
    sentry_traces_sample_rate: '0.1'
```
