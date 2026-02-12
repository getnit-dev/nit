# Platform Integration

The nit platform provides managed LLM proxy access, usage tracking, report storage, and a web dashboard.

## Modes

| Mode | Description |
|------|-------------|
| `platform` | Full platform integration. LLM requests are proxied through the platform. Requires platform URL and API key. |
| `byok` | Bring Your Own Key. Reports and usage are uploaded, but LLM requests go directly to your provider. |
| `disabled` | No platform integration. Fully local operation. |

## Configuration

```yaml
platform:
  url: https://platform.getnit.dev
  api_key: ${NIT_PLATFORM_API_KEY}
  mode: platform                    # platform, byok, disabled
  user_id: ""                       # Optional user ID
  project_id: ""                    # Optional project ID
  key_hash: ""                      # Optional key hash override
```

## Platform mode

In `platform` mode, LLM requests are routed through the nit platform:

```
nit CLI → platform proxy → LLM provider (OpenAI, Anthropic, etc.)
```

Benefits:

- **Virtual API keys** — use platform-issued keys instead of direct provider keys
- **Usage budgets** — set per-project or per-user token budgets
- **Rate limiting** — platform-enforced rate limits
- **Usage tracking** — all LLM usage is recorded for reporting

## BYOK mode

In `byok` (Bring Your Own Key) mode:

- LLM requests go directly to your provider using your own API key
- Reports, bugs, and drift data are still uploaded to the platform
- Usage events are sent for tracking (but not billed through the platform)

```yaml
platform:
  mode: byok
  url: https://platform.getnit.dev
  api_key: ${NIT_PLATFORM_API_KEY}
llm:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: gpt-4o
```

## Disabled mode

When platform integration is disabled (the default), nit operates fully locally:

- No data is sent to any external service
- LLM requests go directly to your configured provider
- Reports are written to local files only

## Report uploads

When `report.upload_to_platform` is `true` (and platform is configured), nit uploads:

- Test run results
- Coverage data
- Bug reports
- Drift snapshots

```yaml
report:
  upload_to_platform: true
```

Or upload explicitly via CLI:

```bash
nit pick --report
```

## Environment variables

All platform settings can be configured via environment variables:

| Variable | Config equivalent |
|----------|-------------------|
| `NIT_PLATFORM_URL` | `platform.url` |
| `NIT_PLATFORM_API_KEY` | `platform.api_key` |
| `NIT_PLATFORM_MODE` | `platform.mode` |
| `NIT_PLATFORM_USER_ID` | `platform.user_id` |
| `NIT_PLATFORM_PROJECT_ID` | `platform.project_id` |
| `NIT_PLATFORM_KEY_HASH` | `platform.key_hash` |
