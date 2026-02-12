# LLM Overview

nit uses LLMs to generate tests, analyze code for bugs, produce documentation, and generate fixes. You bring your own LLM provider — nit supports any provider compatible with the OpenAI API format.

## Supported providers

| Provider | Models | Setup |
|----------|--------|-------|
| **OpenAI** | GPT-4o, GPT-4o-mini, o1, o3 | API key |
| **Anthropic** | Claude Sonnet 4.5, Claude Opus 4 | API key |
| **Ollama** | Llama 3, Mistral, CodeLlama, any local model | Local server |
| **AWS Bedrock** | Claude, Titan, Llama (via Bedrock) | AWS credentials |
| **Google Vertex AI** | Gemini models | GCP credentials |
| **Azure OpenAI** | GPT-4o (via Azure) | Azure credentials |

nit uses [LiteLLM](https://docs.litellm.ai/) under the hood, so any provider LiteLLM supports will work.

## Quick setup

=== "OpenAI"

    ```yaml
    llm:
      provider: openai
      model: gpt-4o
      api_key: ${OPENAI_API_KEY}
    ```

=== "Anthropic"

    ```yaml
    llm:
      provider: anthropic
      model: claude-sonnet-4-5-20250514
      api_key: ${ANTHROPIC_API_KEY}
    ```

=== "Ollama"

    ```yaml
    llm:
      mode: ollama
      model: llama3
      base_url: http://localhost:11434
    ```

## Execution modes

nit supports four execution modes for LLM calls. See [Modes](modes.md) for details.

| Mode | Description |
|------|-------------|
| `builtin` | Uses LiteLLM library (default) |
| `ollama` | Local Ollama instance |
| `cli` | Delegates to Claude CLI or Codex CLI |
| `custom` | Delegates to a custom command |

## How nit uses the LLM

nit makes LLM calls at several stages:

1. **Test generation** — source code + AST + patterns → test code
2. **Bug analysis** — code scanning for potential issues
3. **Root cause analysis** — analyzing failures and bugs
4. **Fix generation** — producing patches for detected bugs
5. **Documentation** — generating docstrings and docs
6. **Semantic gap detection** — identifying missing error handling

Each stage uses framework-specific prompts tailored to the detected language and testing framework.
