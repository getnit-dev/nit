# Execution Modes

nit supports four modes for making LLM calls, giving you flexibility in how and where AI inference runs.

## builtin (default)

Uses the [LiteLLM](https://docs.litellm.ai/) library to call LLM APIs directly from Python.

```yaml
llm:
  mode: builtin
  provider: openai
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}
```

**Best for:** most users. Supports all providers, has built-in rate limiting and retries.

## ollama

Connects to a local [Ollama](https://ollama.com/) instance for fully local, offline inference.

```yaml
llm:
  mode: ollama
  model: llama3
  base_url: http://localhost:11434
```

**Best for:** privacy-sensitive environments, offline use, cost-free experimentation.

No API key is needed. Start Ollama and pull a model:

```bash
ollama serve
ollama pull llama3
```

## cli

Delegates LLM calls to an external CLI tool like Claude Code or Codex.

```yaml
llm:
  mode: cli
  model: claude-sonnet-4-5-20250514
  cli_command: claude
  cli_timeout: 300
  cli_extra_args: []
```

**Supported CLI tools:**

| Tool | Command | Notes |
|------|---------|-------|
| Claude Code | `claude` | Anthropic's CLI |
| Codex | `codex` | OpenAI's CLI |

**Best for:** users who already have a CLI tool configured with authentication.

## custom

Delegates to any custom command or script.

```yaml
llm:
  mode: custom
  model: my-model
  cli_command: /path/to/my-llm-script.sh
  cli_timeout: 600
```

The custom command receives a prompt via stdin and should output the response to stdout.

**Best for:** custom model hosting, internal tools, specialized inference pipelines.

## Configuration reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | `builtin` | Execution mode |
| `provider` | `openai` | LLM provider (builtin mode) |
| `model` | — | Model identifier (required) |
| `api_key` | — | API key (builtin mode) |
| `base_url` | — | Custom base URL |
| `cli_command` | — | CLI command (cli/custom mode) |
| `cli_timeout` | `300` | CLI timeout in seconds |
| `cli_extra_args` | `[]` | Additional CLI arguments |

## Mode selection guide

| Scenario | Recommended mode |
|----------|-----------------|
| Standard cloud LLM usage | `builtin` |
| Local/private inference | `ollama` |
| Already using Claude CLI or Codex | `cli` |
| Custom model hosting | `custom` |
