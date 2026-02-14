# Homebrew Formula (source)

This is the source copy of the Homebrew formula for nit. The live formula lives in
[getnit-dev/homebrew-getnit](https://github.com/getnit-dev/homebrew-getnit) and is
automatically updated by the release pipeline.

The `update-homebrew` job in `.github/workflows/release.yml` dispatches a
`repository_dispatch` event to the tap repo with the new version and sha256.
The tap repo's `update-formula.yml` workflow applies the update automatically.
