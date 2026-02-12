# Monorepo Support

nit supports monorepo and workspace structures, with per-package detection, configuration, and memory.

## Workspace detection

nit auto-detects workspace structures from:

| Tool | Detection signal |
|------|-----------------|
| **Turborepo** | `turbo.json` |
| **Nx** | `nx.json` |
| **pnpm** | `pnpm-workspace.yaml` |
| **Yarn** | `package.json` with `workspaces` field |
| **Cargo** | `Cargo.toml` with `[workspace]` |

## Configuration

### Auto-detection (default)

```yaml
workspace:
  auto_detect: true
```

nit scans for workspace configuration files and discovers package boundaries automatically.

### Explicit packages

Override auto-detection with explicit package paths:

```yaml
workspace:
  auto_detect: false
  packages:
    - packages/web-app
    - packages/api-server
    - packages/shared-lib
```

## Per-package configuration

Override settings for individual packages:

```yaml
packages:
  packages/web-app:
    e2e:
      enabled: true
      base_url: http://localhost:3000
      auth:
        strategy: form
        login_url: http://localhost:3000/login
        username: ${WEB_USER}
        password: ${WEB_PASSWORD}

  packages/api-server:
    e2e:
      enabled: true
      base_url: http://localhost:4000
      auth:
        strategy: token
        token: ${API_TOKEN}
```

## Running nit on a specific package

Use the `--path` flag to target a specific package:

```bash
# Scan only the web-app package
nit scan --path packages/web-app

# Generate tests for the API server
nit generate --path packages/api-server

# Full pipeline for a specific package
nit pick --path packages/shared-lib
```

## Per-package memory

In monorepos, nit maintains separate memory for each package:

```
.nit/memory/
  global_memory.json           # Project-wide patterns
  packages/
    web-app/memory.json        # web-app specific patterns
    api-server/memory.json     # api-server specific patterns
```

Each package builds its own pattern library over time. The Package Memory Manager merges global and package-specific patterns when generating tests.

```bash
# View memory for a specific package
nit memory show --package packages/web-app

# Reset memory for one package
nit memory reset --package packages/api-server
```

## CI with monorepo

### GitHub Action with path targeting

```yaml
- uses: getnit-dev/nit@v1
  with:
    llm_provider: openai
    llm_api_key: ${{ secrets.OPENAI_API_KEY }}
    path: packages/web-app
```

### Matrix strategy for all packages

```yaml
jobs:
  test:
    strategy:
      matrix:
        package: [packages/web-app, packages/api-server, packages/shared-lib]
    steps:
      - uses: actions/checkout@v4
      - uses: getnit-dev/nit@v1
        with:
          llm_provider: openai
          llm_api_key: ${{ secrets.OPENAI_API_KEY }}
          path: ${{ matrix.package }}
```

## Workspace tool configuration

Explicitly set your workspace tool if auto-detection doesn't work:

```yaml
project:
  workspace_tool: turborepo  # turborepo, nx, pnpm, yarn, cargo
```
