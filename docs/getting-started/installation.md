# Installation

## Requirements

- Python 3.11 or later
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

## Install via npm

```bash
npm install -g getnit
```

Or run without installing:

```bash
npx getnit@latest --version
```

## Install via Homebrew (macOS)

```bash
brew install getnit-dev/getnit/nit
```

## Standalone binary

=== "macOS / Linux"

    ```bash
    curl -fsSL https://raw.githubusercontent.com/getnit-dev/nit/main/release/scripts/install.sh | sh
    ```

=== "Windows (PowerShell)"

    ```powershell
    irm https://raw.githubusercontent.com/getnit-dev/nit/main/release/scripts/install.ps1 | iex
    ```

The install script detects your OS and architecture, downloads the correct binary from
[GitHub Releases](https://github.com/getnit-dev/nit/releases), and adds it to your PATH.

## Docker

```bash
docker run --rm -v $(pwd):/workspace ghcr.io/getnit-dev/nit:latest --version
```

For multi-language test execution (Node.js + Python + Java):

```bash
docker run --rm -v $(pwd):/workspace ghcr.io/getnit-dev/nit:test hunt
```

## Install from source

```bash
git clone https://github.com/getnit-dev/nit.git
cd nit
pip install -e ".[dev]"
```

## Optional extras

Semantic drift comparison (embedding-based) requires `sentence-transformers`:

```bash
pip install 'getnit[semantic]'
```

## Verify installation

```bash
nit --version
```

## Next steps

Once installed, head to the [Quickstart](quickstart.md) to generate your first tests.
