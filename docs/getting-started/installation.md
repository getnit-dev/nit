# Installation

## Requirements

- Python 3.14 or later
- An LLM API key (OpenAI, Anthropic, or a local Ollama instance)

## Install from PyPI

The recommended way to install nit:

```bash
pip install getnit
```

Or with [pipx](https://pypa.github.io/pipx/) for isolated installs:

```bash
pipx install getnit
```

## Install from source

```bash
git clone https://github.com/getnit-dev/nit.git
cd nit
pip install -e ".[dev]"
```

## Verify installation

```bash
nit --version
```

## Next steps

Once installed, head to the [Quickstart](quickstart.md) to generate your first tests.
