# Providers

nit supports multiple LLM providers through [LiteLLM](https://docs.litellm.ai/).

## OpenAI

```yaml
llm:
  provider: openai
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}
```

Or set the environment variable directly:

```bash
export OPENAI_API_KEY=sk-...
```

**Recommended models:** `gpt-4o` (best quality), `gpt-4o-mini` (faster, cheaper)

## Anthropic

```yaml
llm:
  provider: anthropic
  model: claude-sonnet-4-5-20250514
  api_key: ${ANTHROPIC_API_KEY}
```

**Recommended models:** `claude-sonnet-4-5-20250514` (best balance), `claude-opus-4-20250514` (highest quality)

## Ollama (local)

Run models locally with zero API costs:

```yaml
llm:
  mode: ollama
  model: llama3
  base_url: http://localhost:11434
```

No API key required. Install Ollama from [ollama.com](https://ollama.com/) and pull a model:

```bash
ollama pull llama3
```

**Recommended models:** `llama3` (general purpose), `codellama` (code-focused)

## AWS Bedrock

```yaml
llm:
  provider: bedrock
  model: anthropic.claude-3-sonnet-20240229-v1:0
```

Requires AWS credentials configured via environment variables or `~/.aws/credentials`.

## Google Vertex AI

```yaml
llm:
  provider: vertex_ai
  model: gemini-pro
```

Requires GCP credentials and project configuration.

## Azure OpenAI

```yaml
llm:
  provider: azure
  model: gpt-4o
  base_url: https://your-resource.openai.azure.com/
  api_key: ${AZURE_OPENAI_API_KEY}
```

## Custom base URL (proxy)

For custom API proxies or self-hosted endpoints:

```yaml
llm:
  provider: openai
  model: gpt-4o
  api_key: ${API_KEY}
  base_url: https://your-proxy.example.com/v1
```

## Environment variable fallbacks

If not set in `.nit.yml`, the LLM configuration falls back to:

| Variable | Config equivalent |
|----------|-------------------|
| `NIT_LLM_API_KEY` | `llm.api_key` |
| `NIT_LLM_MODEL` | `llm.model` |
| `NIT_LLM_PROVIDER` | `llm.provider` |
| `NIT_LLM_BASE_URL` | `llm.base_url` |

Provider-specific variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) are also supported through LiteLLM's built-in environment variable handling.
