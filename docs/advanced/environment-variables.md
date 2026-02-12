# Environment Variables

nit reads several environment variables as fallbacks for configuration values. Environment variables are useful in CI environments where you don't want to commit secrets to `.nit.yml`.

## LLM configuration

| Variable | Config equivalent | Description |
|----------|-------------------|-------------|
| `NIT_LLM_API_KEY` | `llm.api_key` | API key for the LLM provider |
| `NIT_LLM_MODEL` | `llm.model` | Model identifier |
| `NIT_LLM_PROVIDER` | `llm.provider` | Provider name |
| `NIT_LLM_BASE_URL` | `llm.base_url` | Custom base URL |

## Platform configuration

| Variable | Config equivalent | Description |
|----------|-------------------|-------------|
| `NIT_PLATFORM_URL` | `platform.url` | Platform base URL |
| `NIT_PLATFORM_API_KEY` | `platform.api_key` | Platform API key |
| `NIT_PLATFORM_MODE` | `platform.mode` | Platform mode (`byok` or `disabled`) |
| `NIT_PLATFORM_USER_ID` | `platform.user_id` | User ID for metadata |
| `NIT_PLATFORM_PROJECT_ID` | `platform.project_id` | Project ID for metadata |
| `NIT_PLATFORM_KEY_HASH` | `platform.key_hash` | Key hash override |

## Sentry configuration

| Variable | Config equivalent | Description |
|----------|-------------------|-------------|
| `NIT_SENTRY_ENABLED` | `sentry.enabled` | Enable Sentry (`true`/`false`) |
| `NIT_SENTRY_DSN` | `sentry.dsn` | Sentry DSN |
| `NIT_SENTRY_TRACES_SAMPLE_RATE` | `sentry.traces_sample_rate` | Tracing sample rate |
| `NIT_SENTRY_PROFILES_SAMPLE_RATE` | `sentry.profiles_sample_rate` | Profiling sample rate |
| `NIT_SENTRY_ENABLE_LOGS` | `sentry.enable_logs` | Send logs to Sentry |

## Provider-specific variables

These are read by LiteLLM directly:

| Variable | Provider |
|----------|----------|
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Google Gemini |
| `OPENROUTER_API_KEY` | OpenRouter |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | AWS Bedrock |
| `GOOGLE_APPLICATION_CREDENTIALS` | Google Vertex AI |
| `AZURE_API_KEY` | Azure OpenAI |

## GitHub integration

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | GitHub API token (auto-set in GitHub Actions) |

## Config file variable expansion

Any string value in `.nit.yml` supports `${VAR_NAME}` expansion:

```yaml
llm:
  api_key: ${OPENAI_API_KEY}
e2e:
  auth:
    username: ${E2E_USERNAME}
    password: ${E2E_PASSWORD}
report:
  slack_webhook: ${SLACK_WEBHOOK_URL}
```

If the referenced variable is not set, nit logs a warning and uses an empty string.

## Precedence

Configuration values are resolved in this order (first wins):

1. Explicit value in `.nit.yml`
2. Environment variable expansion in `.nit.yml` (e.g., `${VAR}`)
3. Environment variable fallback (e.g., `NIT_LLM_API_KEY`)
4. Provider-specific variable (e.g., `OPENAI_API_KEY` via LiteLLM)
5. Default value
