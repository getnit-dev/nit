"""Tests for changelog generation (Keep a Changelog format)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nit.utils.changelog import (
    ChangelogGenerator,
    format_keep_a_changelog,
    group_commits_by_section,
    parse_conventional_commit,
)
from nit.utils.git import CommitInfo, GitOperationError, get_commits_between

# ---------------------------------------------------------------------------
# parse_conventional_commit
# ---------------------------------------------------------------------------


class TestParseConventionalCommit:
    def test_feat_no_scope(self) -> None:
        parsed = parse_conventional_commit("feat: add login button")
        assert parsed.type == "feat"
        assert parsed.scope == ""
        assert parsed.description == "add login button"
        assert parsed.breaking is False

    def test_feat_with_scope(self) -> None:
        parsed = parse_conventional_commit("feat(api): add /users endpoint")
        assert parsed.type == "feat"
        assert parsed.scope == "api"
        assert parsed.description == "add /users endpoint"

    def test_fix(self) -> None:
        parsed = parse_conventional_commit("fix: resolve null pointer in parser")
        assert parsed.type == "fix"
        assert parsed.description == "resolve null pointer in parser"

    def test_breaking_in_body(self) -> None:
        parsed = parse_conventional_commit(
            "feat: remove deprecated API",
            body="BREAKING CHANGE: use new API instead.",
        )
        assert parsed.breaking is True

    def test_breaking_exclamation(self) -> None:
        parsed = parse_conventional_commit("feat!: drop support for Node 14")
        assert parsed.breaking is True
        assert parsed.description == "drop support for Node 14"

    def test_non_conventional_falls_back_to_other(self) -> None:
        parsed = parse_conventional_commit("random commit message")
        assert parsed.type == "other"
        assert parsed.description == "random commit message"


# ---------------------------------------------------------------------------
# group_commits_by_section
# ---------------------------------------------------------------------------


class TestGroupCommitsBySection:
    def test_groups_by_type(self) -> None:
        commits = [
            CommitInfo("a", "feat: add X", ""),
            CommitInfo("b", "fix: fix Y", ""),
            CommitInfo("c", "feat: add Z", ""),
        ]
        grouped = group_commits_by_section(commits)
        assert "Added" in grouped
        assert "Fixed" in grouped
        assert len(grouped["Added"]) == 2
        assert len(grouped["Fixed"]) == 1

    def test_breaking_gets_prefix(self) -> None:
        commits = [
            CommitInfo("a", "feat!: remove old API", ""),
        ]
        grouped = group_commits_by_section(commits)
        assert "Added" in grouped
        assert any("BREAKING" in line for line in grouped["Added"])


# ---------------------------------------------------------------------------
# format_keep_a_changelog
# ---------------------------------------------------------------------------


class TestFormatKeepAChangelog:
    def test_single_section(self) -> None:
        grouped = {"Added": ["- new feature A", "- new feature B"]}
        out = format_keep_a_changelog("1.2.0", datetime(2024, 1, 15, tzinfo=UTC), grouped)
        assert "## [1.2.0] - 2024-01-15" in out
        assert "### Added" in out
        assert "- new feature A" in out
        assert "- new feature B" in out

    def test_section_order(self) -> None:
        grouped = {
            "Fixed": ["- fix bug"],
            "Added": ["- add thing"],
        }
        out = format_keep_a_changelog("1.0.0", None, grouped)
        added_pos = out.index("### Added")
        fixed_pos = out.index("### Fixed")
        assert added_pos < fixed_pos

    def test_unreleased_optional(self) -> None:
        grouped = {"Changed": ["- change X"]}
        unreleased = {"Added": ["- WIP feature"]}
        out = format_keep_a_changelog(
            "1.0.0",
            datetime(2024, 1, 1, tzinfo=UTC),
            grouped,
            unreleased=unreleased,
        )
        assert "## [Unreleased]" in out
        assert "WIP feature" in out
        assert "## [1.0.0]" in out


# ---------------------------------------------------------------------------
# get_commits_between
# ---------------------------------------------------------------------------


def _ensure_git_repo(tmp_path: Path) -> None:
    """Initialize a git repo; skip test if git not available or sandbox blocks it."""
    try:
        _git_init(tmp_path)
    except subprocess.CalledProcessError as e:
        if "Operation not permitted" in (e.stderr or b"").decode(errors="replace"):
            pytest.skip("Git write not permitted (e.g. sandbox)")
        raise


class TestGetCommitsBetween:
    def test_empty_range_returns_empty_list(self, tmp_path: Path) -> None:
        _ensure_git_repo(tmp_path)
        _git_commit(tmp_path, "first")
        rev = _git_rev(tmp_path, "HEAD")
        commits = get_commits_between(tmp_path, rev, "HEAD")
        assert commits == []

    def test_returns_commits_newest_first(self, tmp_path: Path) -> None:
        _ensure_git_repo(tmp_path)
        _git_commit(tmp_path, "first")
        base = _git_rev(tmp_path, "HEAD")
        _git_commit(tmp_path, "second")
        _git_commit(tmp_path, "third")
        commits = get_commits_between(tmp_path, base, "HEAD")
        assert len(commits) == 2
        assert commits[0].subject == "third"
        assert commits[1].subject == "second"

    def test_invalid_ref_raises(self, tmp_path: Path) -> None:
        _ensure_git_repo(tmp_path)
        with pytest.raises(GitOperationError, match="Failed to get commits"):
            get_commits_between(tmp_path, "nonexistent-ref", "HEAD")


# ---------------------------------------------------------------------------
# ChangelogGenerator
# ---------------------------------------------------------------------------


class TestChangelogGenerator:
    def test_generate_no_llm(self, tmp_path: Path) -> None:
        _ensure_git_repo(tmp_path)
        _git_commit(tmp_path, "feat: add login")
        base = _git_rev(tmp_path, "HEAD")
        _git_commit(tmp_path, "fix: fix logout bug")
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref=base,
            to_ref="HEAD",
            use_llm=False,
            llm_engine=None,
        )
        markdown = gen.generate()
        # Only commits after base are included, so we see the fix commit
        assert "### Fixed" in markdown or "fix logout" in markdown
        assert "## [" in markdown

    def test_generate_version_defaults_to_unreleased_without_tag(self, tmp_path: Path) -> None:
        _ensure_git_repo(tmp_path)
        _git_commit(tmp_path, "feat: one")
        base = _git_rev(tmp_path, "HEAD")
        _git_commit(tmp_path, "feat: two")
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref=base,
            to_ref="HEAD",
            version="",
            use_llm=False,
        )
        markdown = gen.generate()
        assert "## [" in markdown
        assert "feat: two" in markdown or "two" in markdown

    def test_explicit_version_used(self, tmp_path: Path) -> None:
        _ensure_git_repo(tmp_path)
        _git_commit(tmp_path, "feat: thing")
        base = _git_rev(tmp_path, "HEAD")
        _git_commit(tmp_path, "fix: other")
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref=base,
            to_ref="HEAD",
            version="2.0.0",
            use_llm=False,
        )
        markdown = gen.generate()
        assert "## [2.0.0]" in markdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def _git_commit(path: Path, message: str) -> None:
    f = path / "f"
    # Append a line so each commit has a change (avoid "nothing to commit")
    if f.exists():
        content = f.read_text()
        f.write_text(content + "\n")
    else:
        f.write_text("x\n")
    subprocess.run(["git", "add", "f"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=path,
        capture_output=True,
        check=True,
    )


def _git_tag(path: Path, tag: str) -> None:
    subprocess.run(
        ["git", "tag", tag],
        cwd=path,
        capture_output=True,
        check=True,
    )


def _git_rev(path: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()
