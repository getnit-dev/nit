# Publishing the nit GitHub Action

This guide explains how to publish the nit GitHub Action so users can reference it as `getnit-dev/nit@v1`.

## Prerequisites

- Repository at `https://github.com/getnit-dev/nit`
- Push access to the repository
- Action definition file (`action.yml`) in the repository root ✅ (already created)

## Publishing Steps

### 1. Verify Action Definition

The `action.yml` file is already created in the repository root. Verify it's correct:

```bash
cat action.yml
```

### 2. Commit the Action Files

```bash
git add action.yml .github/ACTION.md PUBLISHING_ACTION.md
git commit -m "feat: add GitHub Action definition

- Add action.yml with composite action
- Add action documentation
- Enable usage as getnit-dev/nit@v1"
```

### 3. Push to Main Branch

```bash
git push origin main
```

### 4. Create a Release Tag

GitHub Actions are versioned using Git tags. Create a `v1` tag:

```bash
# Create and push the v1 tag
git tag -a v1 -m "Release v1.0.0 - Initial GitHub Action"
git push origin v1

# Optionally, also create a semantic version tag
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

**Versioning Strategy:**
- `v1` - Major version tag (moves with updates, e.g., v1.1.0, v1.2.0)
- `v1.0.0` - Specific version tag (immutable)
- Users can reference either:
  - `getnit-dev/nit@v1` (auto-updates to latest v1.x)
  - `getnit-dev/nit@v1.0.0` (pinned to specific version)

### 5. Test the Action

Create a test repository and add this workflow:

```yaml
name: Test nit Action
on: [push]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run nit
        uses: getnit-dev/nit@v1
        with:
          mode: run
          llm_provider: anthropic
          llm_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

### 6. Publish to GitHub Marketplace (Optional)

To make the action discoverable in the GitHub Marketplace:

1. **Go to the repository on GitHub**
   - Navigate to `https://github.com/getnit-dev/nit`

2. **Click "Releases"** in the right sidebar

3. **Click "Draft a new release"**

4. **Fill in the release form:**
   - **Tag**: `v1.0.0` (select existing or create new)
   - **Title**: `nit v1.0.0 - AI Testing & Quality Agent`
   - **Description**: Copy from the release notes template below
   - **☑️ Publish this Action to the GitHub Marketplace**
     - **Primary Category**: Testing
     - **Secondary Category**: Code Quality

5. **Click "Publish release"**

### Release Notes Template

```markdown
## 🎉 nit v1.0.0 - Initial GitHub Action Release

### What's New

This is the first release of the nit GitHub Action! Now you can easily integrate AI-powered test generation into your CI/CD pipeline.

### Features

- 🤖 **Auto-detection** of your project's languages and frameworks
- ✅ **Test generation** using OpenAI, Anthropic, or Ollama models
- 📊 **Coverage tracking** with before/after comparison
- 🔄 **LLM drift monitoring** for AI-powered features
- 📝 **Documentation generation** for your codebase

### Quick Start

```yaml
- uses: getnit-dev/nit@v1
  with:
    mode: hunt
    llm_provider: anthropic
    llm_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Documentation

- [Action Documentation](.github/ACTION.md)
- [Example Workflows](.github/workflows/nit.yml.example)
- [Full Documentation](https://getnit.dev)

### Installation

```bash
pip install getnit
```

**Full Changelog**: https://github.com/getnit-dev/nit/commits/v1.0.0
```

## Updating the Action

When you make changes to the action:

### Minor Updates (v1.x.x)

```bash
# Make your changes to action.yml
git add action.yml
git commit -m "fix: update action configuration"
git push origin main

# Update the v1 tag to point to the new commit
git tag -fa v1 -m "Update v1 to include latest changes"
git push origin v1 --force

# Create a new specific version tag
git tag -a v1.1.0 -m "Release v1.1.0"
git push origin v1.1.0
```

### Major Updates (v2.0.0)

```bash
# Make breaking changes
git add action.yml
git commit -m "feat!: breaking change description"
git push origin main

# Create new major version tags
git tag -a v2.0.0 -m "Release v2.0.0"
git push origin v2.0.0

git tag -a v2 -m "Major version v2"
git push origin v2
```

## Testing Changes

Before pushing tags, test the action locally using [act](https://github.com/nektos/act):

```bash
# Install act
brew install act  # macOS
# or
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash

# Test the workflow
act -j test-action -s ANTHROPIC_API_KEY=your-key-here
```

## Troubleshooting

### Action Not Found

If users get "Unable to resolve action", check:

1. Repository is public
2. `action.yml` is in the repository root
3. Tag `v1` exists: `git ls-remote --tags origin`

### Action Not Running

If the action doesn't execute:

1. Check the action logs in GitHub UI
2. Verify all required inputs are provided
3. Check that secrets are configured correctly

### Force Update v1 Tag

If users are getting old versions with `@v1`:

```bash
# Delete the old tag
git tag -d v1
git push origin :refs/tags/v1

# Create new tag
git tag -a v1 -m "Update v1 to latest"
git push origin v1
```

## Best Practices

1. **Semantic Versioning**: Use semver (v1.0.0, v1.1.0, v2.0.0)
2. **Major Version Tags**: Maintain `v1`, `v2` etc. for users who want auto-updates
3. **Changelog**: Keep CHANGELOG.md up to date
4. **Testing**: Test thoroughly before moving major version tags
5. **Security**: Never commit API keys or secrets to the repository
6. **Documentation**: Update ACTION.md when adding new inputs/outputs

## Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions/creating-actions)
- [Publishing Actions to Marketplace](https://docs.github.com/en/actions/creating-actions/publishing-actions-in-github-marketplace)
- [Action Versioning](https://github.com/actions/toolkit/blob/master/docs/action-versioning.md)
