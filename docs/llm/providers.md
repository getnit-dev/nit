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

## Google Gemini

Use Google's Gemini API directly (Google AI Studio):

```yaml
llm:
  provider: gemini
  model: gemini-2.0-flash
  api_key: ${GEMINI_API_KEY}
```

```bash
export GEMINI_API_KEY=...
```

**Recommended models:** `gemini-2.0-flash` (fast, cost-effective), `gemini-1.5-pro` (higher quality)

For enterprise use with GCP credentials, see [Google Vertex AI](#google-vertex-ai) below.

## OpenRouter

[OpenRouter](https://openrouter.ai/) provides access to many models through a single API:

```yaml
llm:
  provider: openrouter
  model: openrouter/auto
  api_key: ${OPENROUTER_API_KEY}
  base_url: https://openrouter.ai/api/v1
```

```bash
export OPENROUTER_API_KEY=sk-or-...
```

OpenRouter routes to the best available model automatically with `openrouter/auto`, or you can specify a model directly (e.g., `anthropic/claude-3.5-sonnet`, `openai/gpt-4o`).

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

## LM Studio (local)

[LM Studio](https://lmstudio.ai/) provides an OpenAI-compatible local server:

```yaml
llm:
  provider: openai
  model: your-model-name
  base_url: http://localhost:1234/v1
```

No API key required. Download and run a model in LM Studio, then start the local server. nit connects via the OpenAI-compatible endpoint.

## AWS Bedrock

```yaml
llm:
  provider: bedrock
  model: anthropic.claude-3-sonnet-20240229-v1:0
```

Requires AWS credentials configured via environment variables or `~/.aws/credentials`. No `api_key` field needed.

## Google Vertex AI

```yaml
llm:
  provider: vertex_ai
  model: gemini-pro
```

Requires GCP credentials and project configuration. No `api_key` field needed.

## Azure OpenAI

```yaml
llm:
  provider: azure
  model: gpt-4o
  base_url: https://your-resource.openai.azure.com/
  api_key: ${AZURE_OPENAI_API_KEY}
```

## Custom / OpenAI-compatible endpoint

Any service that exposes an OpenAI-compatible API can be used:

```yaml
llm:
  provider: openai
  model: your-model
  api_key: ${API_KEY}
  base_url: https://your-endpoint.example.com/v1
```

This works with self-hosted inference servers (vLLM, TGI, LocalAI), corporate proxies, or any other OpenAI-compatible endpoint. Set `provider: openai` and point `base_url` at your server.

## Adding a custom provider

nit uses [LiteLLM](https://docs.litellm.ai/) under the hood, which supports 100+ LLM providers. Any provider supported by LiteLLM works with nit.

To configure an unsupported provider:

1. Check the [LiteLLM provider list](https://docs.litellm.ai/docs/providers) for the correct `provider` name and model format
2. Set `llm.provider` to the LiteLLM provider identifier
3. Set `llm.model` to the model name (with any required prefix)
4. Set `llm.api_key` and `llm.base_url` if required by the provider

Example for a hypothetical provider:

```yaml
llm:
  provider: my_provider
  model: my_provider/model-name
  api_key: ${MY_PROVIDER_API_KEY}
  base_url: https://api.myprovider.com/v1
```

## Environment variable fallbacks

If not set in `.nit.yml`, the LLM configuration falls back to:

| Variable | Config equivalent |
|----------|-------------------|
| `NIT_LLM_API_KEY` | `llm.api_key` |
| `NIT_LLM_MODEL` | `llm.model` |
| `NIT_LLM_PROVIDER` | `llm.provider` |
| `NIT_LLM_BASE_URL` | `llm.base_url` |

Provider-specific variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`) are also supported through LiteLLM's built-in environment variable handling.
