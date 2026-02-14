# Release Process

nit uses a fully automated release pipeline. Pushing a version tag triggers builds
and publishes to all distribution channels.

## Triggering a release

```bash
# Update version in pyproject.toml and src/nit/__init__.py
# Then tag and push:
git tag v0.2.0
git push origin v0.2.0
```

For pre-releases, include the pre-release suffix in the tag:

```bash
git tag v0.2.0-rc.1
git push origin v0.2.0-rc.1
```

Tags matching `v*-alpha*`, `v*-beta*`, or `v*-rc*` are automatically marked as
pre-releases on GitHub and PyPI.

## What the pipeline does

The [`release.yml`](https://github.com/getnit-dev/nit/blob/main/.github/workflows/release.yml)
workflow runs six jobs in dependency order:

```
build-binaries (5 platforms)
    |
    v
publish-pypi ──────────────────────────┐
    |                                  |
    v                                  v
create-release (GitHub)     publish-docker (GHCR)
    |                       update-homebrew (tap)
    v
publish-npm
```

### Job 1: Build binaries

Builds standalone PyInstaller binaries for five platforms:

| Platform      | Runner           | Asset                     |
|---------------|------------------|---------------------------|
| Linux x64     | ubuntu-latest    | `nit-linux-x64.tar.gz`    |
| Linux arm64   | ubuntu-24.04-arm | `nit-linux-arm64.tar.gz`  |
| macOS x64     | macos-13         | `nit-darwin-x64.tar.gz`   |
| macOS arm64   | macos-latest     | `nit-darwin-arm64.tar.gz` |
| Windows x64   | windows-latest   | `nit-windows-x64.zip`     |

Defined in
[`build-binaries.yml`](https://github.com/getnit-dev/nit/blob/main/.github/workflows/build-binaries.yml)
as a reusable workflow.

### Job 2: Publish to PyPI

Uses [trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) — no
API token needed. Builds sdist + wheel with `python -m build`, validates with
`twine check`, and publishes via `pypa/gh-action-pypi-publish`.

### Job 3: Create GitHub Release

Downloads all binary artifacts and Python packages, then creates a GitHub Release
with auto-generated release notes and all assets attached.

### Job 4: Publish to npm

Updates `release/npm/package.json` version from the git tag, then runs
`npm publish --provenance` using
[npm trusted publishing](https://docs.npmjs.com/generating-provenance-statements) (OIDC).

### Job 5: Publish Docker images

Builds and pushes two images to `ghcr.io/getnit-dev/nit`:

- **`:latest`** and **`:$version`** — Production image (Python 3.12-slim + nit)
- **`:test`** and **`:$version-test`** — Multi-language image (+ Node.js, Java)

### Job 6: Update Homebrew tap

Computes the sha256 of the PyPI sdist and dispatches a
[repository_dispatch](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#repository_dispatch)
event to `getnit-dev/homebrew-getnit` with the new version and hash.

## Required secrets

| Secret              | Where to configure                  | Purpose                              |
|---------------------|-------------------------------------|--------------------------------------|
| `NPM_TOKEN`         | GitHub repo secrets                 | npm publish authentication           |
| `HOMEBREW_TAP_PAT`  | GitHub repo secrets                 | Push updates to homebrew-tap repo    |
| `GITHUB_TOKEN`      | Automatic                           | GHCR Docker push, GitHub Release     |
| PyPI OIDC           | PyPI trusted publishers settings    | PyPI publish (no secret needed)      |

## Required environments

Create two [GitHub environments](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment):

- **`pypi`** — Used by the publish-pypi job (configure trusted publisher on pypi.org)
- **`npm`** — Used by the publish-npm job

## External setup (one-time)

1. **PyPI:** Configure trusted publisher at pypi.org/manage/project/getnit/settings/publishing/
   with repository `getnit-dev/nit`, workflow `release.yml`, environment `pypi`
2. **npm:** Register `getnit` on npmjs.com, add `NPM_TOKEN` to repo secrets
3. **Homebrew:** Create the `getnit-dev/homebrew-getnit` repo with `Formula/nit.rb`,
   add `HOMEBREW_TAP_PAT` secret (PAT with repo scope for `getnit-dev/homebrew-getnit`)
4. **GHCR:** Enable GitHub Container Registry for the `getnit-dev` org

## Directory layout

All release-related files live under `release/`:

```
release/
  npm/              # npm package (package.json, postinstall.js, bin wrappers)
  scripts/          # Install scripts (install.sh, install.ps1)
  homebrew/         # Homebrew formula source (synced to getnit-dev/homebrew-getnit)
```

Root-level files used by the pipeline:

```
Dockerfile          # Production Docker image
Dockerfile.test     # Multi-language test Docker image
nit.spec            # PyInstaller spec for standalone binaries
```

## Testing a release

Use a release candidate tag to test the full pipeline without affecting the
`latest` tag:

```bash
git tag v0.2.0-rc.1
git push origin v0.2.0-rc.1
```

This runs the full pipeline but marks everything as a pre-release.
