# Release Guide

This document describes the process for releasing `getnit` to PyPI.

## Prerequisites

### 1. PyPI Account Setup

1. Create an account on [PyPI](https://pypi.org/account/register/)
2. Enable two-factor authentication (required for trusted publishers)
3. Verify your email address

### 2. GitHub Trusted Publisher Setup

We use PyPI's [Trusted Publishers](https://docs.pypi.org/trusted-publishers/) feature, which allows GitHub Actions to publish without API tokens.

**First time setup (before v0.1.0):**

1. Go to [PyPI](https://pypi.org) and log in
2. Navigate to "Publishing" in your account settings
3. Click "Add a new pending publisher"
4. Fill in the form:
   - **PyPI Project Name**: `getnit`
   - **Owner**: `getnit` (or your GitHub org/username)
   - **Repository name**: `nit`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi`
5. Click "Add"

This creates a "pending publisher" that will be activated when the first release is published.

**For subsequent releases:** No action needed—trusted publishing is already configured.

## Release Process

### 1. Ensure Quality Gates Pass

Before releasing, ensure all quality checks pass locally:

```bash
# Format
.venv/bin/black src/ tests/

# Lint
.venv/bin/ruff check src/ tests/

# Type check
.venv/bin/mypy src/

# Tests
.venv/bin/pytest
```

All four must pass with zero errors.

### 2. Update Version

Update the version in [`pyproject.toml`](pyproject.toml):

```toml
[project]
name = "getnit"
version = "0.1.0"  # Update this
```

### 3. Update Changelog (if exists)

If you maintain a `CHANGELOG.md`, add an entry for the new version:

```markdown
## [0.1.0] - 2026-02-10

### Added
- Initial release
- Auto-detection of languages and frameworks
- Unit test generation for Vitest and pytest
- Coverage integration
- Memory system for learning project patterns
```

### 4. Commit and Tag

```bash
# Commit version bump
git add pyproject.toml CHANGELOG.md
git commit -m "Bump version to v0.1.0"

# Create and push tag
git tag v0.1.0
git push origin main
git push origin v0.1.0
```

### 5. Automated Release

The [`release.yml`](.github/workflows/release.yml) workflow will automatically:

1. **Build** the package using `python -m build`
2. **Check** the package with `twine check`
3. **Publish** to PyPI using trusted publishing
4. **Create** a GitHub Release with auto-generated release notes

Monitor the workflow at: https://github.com/getnit/nit/actions

### 6. Verify Release

After the workflow completes:

1. **Check PyPI**: Visit https://pypi.org/project/getnit/ to confirm the new version
2. **Test installation**:
   ```bash
   # In a fresh environment
   pip install getnit==0.1.0
   nit --version
   ```
3. **Check GitHub Release**: Visit https://github.com/getnit/nit/releases

## Manual Release (Fallback)

If the automated release fails, you can publish manually:

### 1. Build the package

```bash
.venv/bin/python -m pip install build twine
.venv/bin/python -m build
```

This creates:
- `dist/getnit-0.1.0.tar.gz` (source distribution)
- `dist/getnit-0.1.0-py3-none-any.whl` (wheel)

### 2. Check the package

```bash
.venv/bin/twine check dist/*
```

### 3. Test upload (optional)

Test with TestPyPI first:

```bash
.venv/bin/twine upload --repository testpypi dist/*
```

Then test installation:

```bash
pip install --index-url https://test.pypi.org/simple/ getnit==0.1.0
```

### 4. Upload to PyPI

```bash
.venv/bin/twine upload dist/*
```

You'll be prompted for your PyPI credentials or API token.

## Version Numbering

We follow [Semantic Versioning](https://semver.org/):

- **Major** (X.0.0): Breaking changes
- **Minor** (0.X.0): New features, backward compatible
- **Patch** (0.0.X): Bug fixes, backward compatible

Pre-release versions:
- `0.1.0-alpha.1`: Alpha releases
- `0.1.0-beta.1`: Beta releases
- `0.1.0-rc.1`: Release candidates

## Post-Release Checklist

After a successful release:

- [ ] Announce on GitHub Discussions / Discord / Slack
- [ ] Update documentation site (when available)
- [ ] Share on social media (Twitter, Reddit, Hacker News, etc.)
- [ ] Update the website (getnit.dev) if needed
- [ ] Close milestone on GitHub (if using milestones)

## Troubleshooting

### Trusted Publisher Not Working

If the GitHub Action fails with authentication errors:

1. Check that the trusted publisher is configured correctly on PyPI
2. Verify the workflow name matches exactly: `release.yml`
3. Verify the environment name matches: `pypi`
4. Ensure the tag was pushed (not just created locally)

### Build Fails

If the build step fails:

```bash
# Clean old builds
rm -rf dist/ build/ *.egg-info

# Ensure dependencies are up to date
.venv/bin/pip install --upgrade build

# Try building again
.venv/bin/python -m build
```

### Package Rejected

If PyPI rejects the package:

1. Check that the version doesn't already exist on PyPI
2. Run `twine check dist/*` to identify issues
3. Ensure all required metadata is in `pyproject.toml`:
   - `name`, `version`, `description`, `authors`, `license`, `readme`

## References

- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)
- [Python Packaging Guide](https://packaging.python.org/)
- [Semantic Versioning](https://semver.org/)
- [GitHub Actions: Publishing Python Packages](https://docs.github.com/en/actions/automating-builds-and-tests/building-and-testing-python#publishing-to-package-registries)
