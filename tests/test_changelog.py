"""Tests for the changelog utility (utils/changelog.py).

Covers conventional commit parsing, Keep a Changelog section grouping,
markdown formatting, and the ChangelogGenerator class (version resolution,
date extraction, LLM polishing, and end-to-end generate flow).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.utils.changelog import (
    ChangelogGenerator,
    ParsedCommit,
    format_keep_a_changelog,
    group_commits_by_section,
    parse_conventional_commit,
)
from nit.utils.git import CommitInfo, GitOperationError, get_commits_between

if TYPE_CHECKING:
    from pathlib import Path


# ── Helpers ────────────────────────────────────────────────────────


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
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


def _ensure_git_repo(tmp_path: Path) -> None:
    """Initialize a git repo; skip test if git not available or sandbox blocks it."""
    try:
        _git_init(tmp_path)
    except subprocess.CalledProcessError as e:
        if "Operation not permitted" in (e.stderr or b"").decode(errors="replace"):
            pytest.skip("Git write not permitted (e.g. sandbox)")
        raise


def _git_commit(path: Path, message: str) -> None:
    f = path / "f"
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
    subprocess.run(["git", "tag", tag], cwd=path, capture_output=True, check=True)


def _git_rev(path: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# ── parse_conventional_commit ──────────────────────────────────────


class TestParseConventionalCommit:
    """Tests for parse_conventional_commit()."""

    def test_simple_feat(self) -> None:
        result = parse_conventional_commit("feat: add new button")
        assert result.type == "feat"
        assert result.scope == ""
        assert result.description == "add new button"
        assert result.breaking is False
        assert result.raw_subject == "feat: add new button"
        assert result.body == ""

    def test_feat_with_scope(self) -> None:
        result = parse_conventional_commit("feat(api): add /users endpoint")
        assert result.type == "feat"
        assert result.scope == "api"
        assert result.description == "add /users endpoint"
        assert result.breaking is False

    def test_fix_commit(self) -> None:
        result = parse_conventional_commit("fix: resolve null pointer in parser")
        assert result.type == "fix"
        assert result.description == "resolve null pointer in parser"

    def test_docs_commit(self) -> None:
        result = parse_conventional_commit("docs: update README")
        assert result.type == "docs"
        assert result.description == "update README"

    def test_type_is_lowercased(self) -> None:
        result = parse_conventional_commit("FEAT: uppercase type")
        assert result.type == "feat"
        assert result.description == "uppercase type"

    def test_breaking_change_bang_before_colon(self) -> None:
        result = parse_conventional_commit("feat!: drop support for Node 14")
        assert result.breaking is True
        assert result.type == "feat"
        assert result.description == "drop support for Node 14"

    def test_breaking_change_bang_with_scope(self) -> None:
        result = parse_conventional_commit("feat(api)!: drop v1 support")
        assert result.breaking is True
        assert result.type == "feat"
        assert result.scope == "api"
        assert result.description == "drop v1 support"

    def test_breaking_change_in_body_keyword(self) -> None:
        result = parse_conventional_commit(
            "feat: remove deprecated API",
            body="BREAKING CHANGE: use new API instead.",
        )
        assert result.breaking is True
        assert result.description == "remove deprecated API"
        assert "BREAKING CHANGE" in result.body

    def test_breaking_change_body_case_insensitive(self) -> None:
        result = parse_conventional_commit(
            "feat: update",
            body="breaking change: something changed",
        )
        assert result.breaking is True

    def test_no_breaking_when_absent(self) -> None:
        result = parse_conventional_commit("feat: normal change", body="just a note")
        assert result.breaking is False

    def test_non_conventional_commit(self) -> None:
        result = parse_conventional_commit("random commit message")
        assert result.type == "other"
        assert result.scope == ""
        assert result.description == "random commit message"
        assert result.breaking is False

    def test_non_conventional_merge_commit(self) -> None:
        result = parse_conventional_commit("Merge branch 'main' into develop")
        assert result.type == "other"
        assert result.description == "Merge branch 'main' into develop"

    def test_body_is_preserved(self) -> None:
        result = parse_conventional_commit("fix: something", body="detailed explanation here")
        assert result.body == "detailed explanation here"

    def test_empty_body_default(self) -> None:
        result = parse_conventional_commit("fix: something")
        assert result.body == ""

    def test_whitespace_in_subject_is_stripped(self) -> None:
        result = parse_conventional_commit("  feat(cli):  add flag  ")
        assert result.type == "feat"
        assert result.scope == "cli"
        assert result.description == "add flag"

    def test_whitespace_in_body_is_stripped(self) -> None:
        result = parse_conventional_commit("fix: bug", body="  some body  \n  ")
        assert result.body == "some body"

    def test_chore_type(self) -> None:
        result = parse_conventional_commit("chore: bump deps")
        assert result.type == "chore"
        assert result.description == "bump deps"

    def test_refactor_type(self) -> None:
        result = parse_conventional_commit("refactor(core): simplify logic")
        assert result.type == "refactor"
        assert result.scope == "core"

    def test_returns_parsed_commit_dataclass(self) -> None:
        result = parse_conventional_commit("feat: something")
        assert isinstance(result, ParsedCommit)

    def test_raw_subject_preserves_original_for_breaking(self) -> None:
        result = parse_conventional_commit("feat!: breaking thing")
        assert result.raw_subject == "feat!: breaking thing"

    def test_scope_with_spaces_is_trimmed(self) -> None:
        result = parse_conventional_commit("feat( cli ): something")
        assert result.scope == "cli"

    def test_empty_scope_parentheses(self) -> None:
        result = parse_conventional_commit("feat(): something")
        assert result.scope == ""
        assert result.description == "something"

    def test_both_bang_and_body_breaking(self) -> None:
        """Both ! and BREAKING CHANGE in body should still yield breaking=True."""
        result = parse_conventional_commit(
            "feat!: big change",
            body="BREAKING CHANGE: details here",
        )
        assert result.breaking is True

    def test_style_type(self) -> None:
        result = parse_conventional_commit("style: fix whitespace")
        assert result.type == "style"

    def test_perf_type(self) -> None:
        result = parse_conventional_commit("perf: optimize query")
        assert result.type == "perf"

    def test_test_type(self) -> None:
        result = parse_conventional_commit("test: add unit tests")
        assert result.type == "test"

    def test_build_type(self) -> None:
        result = parse_conventional_commit("build: update webpack config")
        assert result.type == "build"

    def test_ci_type(self) -> None:
        result = parse_conventional_commit("ci: add github action")
        assert result.type == "ci"


# ── group_commits_by_section ───────────────────────────────────────


class TestGroupCommitsBySection:
    """Tests for group_commits_by_section()."""

    def test_feat_goes_to_added(self) -> None:
        commits = [CommitInfo(sha="aaa", subject="feat: new widget", body="")]
        grouped = group_commits_by_section(commits)
        assert "Added" in grouped
        assert len(grouped["Added"]) == 1
        assert "new widget" in grouped["Added"][0]

    def test_fix_goes_to_fixed(self) -> None:
        commits = [CommitInfo(sha="bbb", subject="fix: crash on startup", body="")]
        grouped = group_commits_by_section(commits)
        assert "Fixed" in grouped
        assert "crash on startup" in grouped["Fixed"][0]

    def test_docs_goes_to_changed(self) -> None:
        commits = [CommitInfo(sha="ccc", subject="docs: update guide", body="")]
        grouped = group_commits_by_section(commits)
        assert "Changed" in grouped

    def test_refactor_goes_to_changed(self) -> None:
        commits = [CommitInfo(sha="ddd", subject="refactor: simplify", body="")]
        grouped = group_commits_by_section(commits)
        assert "Changed" in grouped

    def test_chore_goes_to_other(self) -> None:
        commits = [CommitInfo(sha="eee", subject="chore: cleanup", body="")]
        grouped = group_commits_by_section(commits)
        assert "Other" in grouped

    def test_unknown_type_goes_to_other(self) -> None:
        commits = [CommitInfo(sha="fff", subject="random commit", body="")]
        grouped = group_commits_by_section(commits)
        assert "Other" in grouped

    def test_breaking_change_gets_breaking_prefix(self) -> None:
        commits = [CommitInfo(sha="ggg", subject="feat!: remove old api", body="")]
        grouped = group_commits_by_section(commits)
        assert any("**BREAKING:**" in line for line in grouped["Added"])

    def test_scope_gets_bold_prefix(self) -> None:
        commits = [CommitInfo(sha="hhh", subject="feat(cli): add flag", body="")]
        grouped = group_commits_by_section(commits)
        assert any("**cli:**" in line for line in grouped["Added"])

    def test_no_scope_plain_bullet(self) -> None:
        commits = [CommitInfo(sha="iii", subject="feat: plain feature", body="")]
        grouped = group_commits_by_section(commits)
        line = grouped["Added"][0]
        assert line.startswith("- ")
        assert "**" not in line

    def test_empty_sections_are_dropped(self) -> None:
        commits = [CommitInfo(sha="jjj", subject="feat: only feature", body="")]
        grouped = group_commits_by_section(commits)
        assert "Fixed" not in grouped
        assert "Deprecated" not in grouped
        assert "Removed" not in grouped
        assert "Security" not in grouped

    def test_empty_commits_returns_empty(self) -> None:
        grouped = group_commits_by_section([])
        assert grouped == {}

    def test_multiple_commits_same_section(self) -> None:
        commits = [
            CommitInfo(sha="k1", subject="feat: one", body=""),
            CommitInfo(sha="k2", subject="feat: two", body=""),
            CommitInfo(sha="k3", subject="feat: three", body=""),
        ]
        grouped = group_commits_by_section(commits)
        assert len(grouped["Added"]) == 3

    def test_multiple_sections(self) -> None:
        commits = [
            CommitInfo(sha="l1", subject="feat: add thing", body=""),
            CommitInfo(sha="l2", subject="fix: fix thing", body=""),
            CommitInfo(sha="l3", subject="docs: document thing", body=""),
        ]
        grouped = group_commits_by_section(commits)
        assert "Added" in grouped
        assert "Fixed" in grouped
        assert "Changed" in grouped

    def test_breaking_in_body_gets_prefix(self) -> None:
        commits = [
            CommitInfo(
                sha="m1",
                subject="feat: new auth",
                body="BREAKING CHANGE: old tokens invalid",
            ),
        ]
        grouped = group_commits_by_section(commits)
        assert any("**BREAKING:**" in line for line in grouped["Added"])

    def test_perf_goes_to_changed(self) -> None:
        commits = [CommitInfo(sha="n1", subject="perf: optimize queries", body="")]
        grouped = group_commits_by_section(commits)
        assert "Changed" in grouped

    def test_ci_goes_to_changed(self) -> None:
        commits = [CommitInfo(sha="o1", subject="ci: update pipeline", body="")]
        grouped = group_commits_by_section(commits)
        assert "Changed" in grouped

    def test_build_goes_to_changed(self) -> None:
        commits = [CommitInfo(sha="p1", subject="build: update config", body="")]
        grouped = group_commits_by_section(commits)
        assert "Changed" in grouped

    def test_style_goes_to_changed(self) -> None:
        commits = [CommitInfo(sha="q1", subject="style: fix formatting", body="")]
        grouped = group_commits_by_section(commits)
        assert "Changed" in grouped

    def test_test_goes_to_changed(self) -> None:
        commits = [CommitInfo(sha="r1", subject="test: add unit tests", body="")]
        grouped = group_commits_by_section(commits)
        assert "Changed" in grouped

    def test_breaking_overrides_scope_in_prefix(self) -> None:
        """When both breaking and scope are present, BREAKING prefix wins."""
        commits = [
            CommitInfo(sha="s1", subject="feat(api)!: drop endpoint", body=""),
        ]
        grouped = group_commits_by_section(commits)
        line = grouped["Added"][0]
        assert "**BREAKING:**" in line
        # Scope should NOT appear as a separate bold prefix alongside BREAKING
        assert "**api:**" not in line


# ── format_keep_a_changelog ────────────────────────────────────────


class TestFormatKeepAChangelog:
    """Tests for format_keep_a_changelog()."""

    def test_basic_format_with_date(self) -> None:
        grouped = {"Added": ["- new feature"]}
        date = datetime(2024, 6, 15, tzinfo=UTC)
        result = format_keep_a_changelog("1.0.0", date, grouped)
        assert "## [1.0.0] - 2024-06-15" in result
        assert "### Added" in result
        assert "- new feature" in result

    def test_format_without_date(self) -> None:
        grouped = {"Added": ["- something"]}
        result = format_keep_a_changelog("1.0.0", None, grouped)
        assert "## [1.0.0]" in result
        # No date should appear
        assert " - " not in result.split("\n")[0] or result.split("\n")[0] == "## [1.0.0]"

    def test_multiple_sections_in_correct_order(self) -> None:
        grouped = {
            "Fixed": ["- fix a bug"],
            "Added": ["- new feature"],
            "Changed": ["- refactored module"],
        }
        date = datetime(2024, 1, 1, tzinfo=UTC)
        result = format_keep_a_changelog("2.0.0", date, grouped)
        added_pos = result.index("### Added")
        changed_pos = result.index("### Changed")
        fixed_pos = result.index("### Fixed")
        assert added_pos < changed_pos < fixed_pos

    def test_empty_grouped_produces_header_only(self) -> None:
        result = format_keep_a_changelog("0.1.0", None, {})
        assert "## [0.1.0]" in result
        assert "### " not in result

    def test_unreleased_section_above_version(self) -> None:
        grouped = {"Added": ["- new feature"]}
        unreleased = {"Fixed": ["- pending fix"]}
        date = datetime(2024, 3, 1, tzinfo=UTC)
        result = format_keep_a_changelog("1.0.0", date, grouped, unreleased=unreleased)
        assert "## [Unreleased]" in result
        assert "## [1.0.0]" in result
        unreleased_pos = result.index("## [Unreleased]")
        version_pos = result.index("## [1.0.0]")
        assert unreleased_pos < version_pos

    def test_unreleased_sections_formatted(self) -> None:
        unreleased = {"Added": ["- something upcoming"], "Fixed": ["- a fix"]}
        grouped = {"Added": ["- released feature"]}
        result = format_keep_a_changelog("1.0.0", None, grouped, unreleased=unreleased)
        # Unreleased should contain its own section headers
        assert "## [Unreleased]" in result
        # Both Added sections should appear (one under Unreleased, one under version)
        assert result.count("### Added") == 2

    def test_no_unreleased_when_none(self) -> None:
        grouped = {"Added": ["- feature"]}
        result = format_keep_a_changelog("1.0.0", None, grouped, unreleased=None)
        assert "Unreleased" not in result

    def test_no_unreleased_when_empty_dict(self) -> None:
        grouped = {"Added": ["- feature"]}
        result = format_keep_a_changelog("1.0.0", None, grouped, unreleased={})
        assert "Unreleased" not in result

    def test_multiple_entries_per_section(self) -> None:
        grouped = {"Added": ["- one", "- two", "- three"]}
        result = format_keep_a_changelog("1.0.0", None, grouped)
        assert "- one" in result
        assert "- two" in result
        assert "- three" in result

    def test_result_stripped_no_trailing_newlines(self) -> None:
        grouped = {"Added": ["- feature"]}
        result = format_keep_a_changelog("1.0.0", None, grouped)
        assert result == result.rstrip()

    def test_other_section_present(self) -> None:
        grouped = {"Other": ["- chore task"]}
        result = format_keep_a_changelog("1.0.0", None, grouped)
        assert "### Other" in result
        assert "- chore task" in result

    def test_single_section_with_two_entries(self) -> None:
        grouped = {"Added": ["- new feature A", "- new feature B"]}
        out = format_keep_a_changelog("1.2.0", datetime(2024, 1, 15, tzinfo=UTC), grouped)
        assert "## [1.2.0] - 2024-01-15" in out
        assert "### Added" in out
        assert "- new feature A" in out
        assert "- new feature B" in out


# ── ChangelogGenerator._resolve_version ────────────────────────────


class TestChangelogGeneratorResolveVersion:
    """Tests for ChangelogGenerator._resolve_version()."""

    def test_explicit_version_returned_directly(self, tmp_path: Path) -> None:
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="HEAD",
            version="2.0.0",
        )
        assert gen._resolve_version() == "2.0.0"

    def test_newline_in_to_ref_returns_unreleased(self, tmp_path: Path) -> None:
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="bad\nref",
        )
        assert gen._resolve_version() == "Unreleased"

    def test_null_in_to_ref_returns_unreleased(self, tmp_path: Path) -> None:
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="bad\0ref",
        )
        assert gen._resolve_version() == "Unreleased"

    @patch("nit.utils.changelog.subprocess.run")
    def test_tag_found_by_git_describe(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="v1.5.0\n")
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="some-sha",
        )
        assert gen._resolve_version() == "v1.5.0"

    @patch("nit.utils.changelog.subprocess.run")
    def test_git_describe_fails_returns_unreleased(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="some-sha",
        )
        assert gen._resolve_version() == "Unreleased"

    @patch("nit.utils.changelog.subprocess.run")
    def test_git_describe_exception_returns_unreleased(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.side_effect = OSError("git not found")
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="some-sha",
        )
        assert gen._resolve_version() == "Unreleased"

    @patch("nit.utils.changelog.subprocess.run")
    def test_git_describe_empty_stdout_returns_unreleased(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="  \n")
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="some-sha",
        )
        assert gen._resolve_version() == "Unreleased"


# ── ChangelogGenerator._get_release_date ───────────────────────────


class TestChangelogGeneratorGetReleaseDate:
    """Tests for ChangelogGenerator._get_release_date()."""

    def test_newline_in_to_ref_returns_none(self, tmp_path: Path) -> None:
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="bad\nref",
        )
        assert gen._get_release_date() is None

    def test_null_in_to_ref_returns_none(self, tmp_path: Path) -> None:
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="bad\0ref",
        )
        assert gen._get_release_date() is None

    @patch("nit.utils.changelog.subprocess.run")
    def test_valid_date_parsed(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(
            stdout="2024-07-04 12:00:00 -0500\n",
            returncode=0,
        )
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="v1.1.0",
        )
        date = gen._get_release_date()
        assert date is not None
        assert date.year == 2024
        assert date.month == 7
        assert date.day == 4
        assert date.tzinfo == UTC

    @patch("nit.utils.changelog.subprocess.run")
    def test_git_log_failure_returns_none(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="v1.1.0",
        )
        assert gen._get_release_date() is None

    @patch("nit.utils.changelog.subprocess.run")
    def test_empty_stdout_returns_none(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            to_ref="v1.1.0",
        )
        assert gen._get_release_date() is None


# ── ChangelogGenerator.generate ────────────────────────────────────


class TestChangelogGeneratorGenerate:
    """Tests for ChangelogGenerator.generate() end-to-end flow."""

    @patch("nit.utils.changelog.ChangelogGenerator._get_release_date")
    @patch("nit.utils.changelog.ChangelogGenerator._resolve_version")
    @patch("nit.utils.changelog.get_commits_between")
    def test_generate_basic_flow(
        self,
        mock_commits: MagicMock,
        mock_version: MagicMock,
        mock_date: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_commits.return_value = [
            CommitInfo(sha="a1b2c3", subject="feat: add login", body=""),
            CommitInfo(sha="d4e5f6", subject="fix: fix crash", body=""),
        ]
        mock_version.return_value = "1.0.0"
        mock_date.return_value = datetime(2024, 8, 10, tzinfo=UTC)

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0.9.0",
            to_ref="v1.0.0",
            use_llm=False,
        )
        result = gen.generate()

        assert "## [1.0.0] - 2024-08-10" in result
        assert "### Added" in result
        assert "add login" in result
        assert "### Fixed" in result
        assert "fix crash" in result

    @patch("nit.utils.changelog.ChangelogGenerator._get_release_date")
    @patch("nit.utils.changelog.ChangelogGenerator._resolve_version")
    @patch("nit.utils.changelog.get_commits_between")
    def test_generate_no_commits(
        self,
        mock_commits: MagicMock,
        mock_version: MagicMock,
        mock_date: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_commits.return_value = []
        mock_version.return_value = "Unreleased"
        mock_date.return_value = None

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v1.0.0",
            use_llm=False,
        )
        result = gen.generate()
        assert "## [Unreleased]" in result

    @patch("nit.utils.changelog.ChangelogGenerator._get_release_date")
    @patch("nit.utils.changelog.ChangelogGenerator._resolve_version")
    @patch("nit.utils.changelog.get_commits_between")
    def test_generate_uses_llm_when_enabled(
        self,
        mock_commits: MagicMock,
        mock_version: MagicMock,
        mock_date: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_commits.return_value = [
            CommitInfo(sha="aaa", subject="feat: add widget", body=""),
        ]
        mock_version.return_value = "1.0.0"
        mock_date.return_value = None

        engine = MagicMock()
        engine.generate_text = AsyncMock(return_value="- Add a new widget component")

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0.9.0",
            to_ref="v1.0.0",
            use_llm=True,
            llm_engine=engine,
        )
        result = gen.generate()

        assert "Add a new widget component" in result
        engine.generate_text.assert_called()

    @patch("nit.utils.changelog.ChangelogGenerator._get_release_date")
    @patch("nit.utils.changelog.ChangelogGenerator._resolve_version")
    @patch("nit.utils.changelog.get_commits_between")
    def test_generate_skips_llm_when_disabled(
        self,
        mock_commits: MagicMock,
        mock_version: MagicMock,
        mock_date: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_commits.return_value = [
            CommitInfo(sha="aaa", subject="feat: add thing", body=""),
        ]
        mock_version.return_value = "1.0.0"
        mock_date.return_value = None

        engine = MagicMock()
        engine.generate_text = AsyncMock()

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0.9.0",
            use_llm=False,
            llm_engine=engine,
        )
        gen.generate()
        engine.generate_text.assert_not_called()

    @patch("nit.utils.changelog.ChangelogGenerator._get_release_date")
    @patch("nit.utils.changelog.ChangelogGenerator._resolve_version")
    @patch("nit.utils.changelog.get_commits_between")
    def test_generate_skips_llm_when_no_engine(
        self,
        mock_commits: MagicMock,
        mock_version: MagicMock,
        mock_date: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_commits.return_value = [
            CommitInfo(sha="aaa", subject="feat: add thing", body=""),
        ]
        mock_version.return_value = "1.0.0"
        mock_date.return_value = None

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0.9.0",
            use_llm=True,
            llm_engine=None,
        )
        result = gen.generate()
        assert "add thing" in result

    @patch("nit.utils.changelog.ChangelogGenerator._get_release_date")
    @patch("nit.utils.changelog.ChangelogGenerator._resolve_version")
    @patch("nit.utils.changelog.get_commits_between")
    def test_generate_skips_llm_when_grouped_empty(
        self,
        mock_commits: MagicMock,
        mock_version: MagicMock,
        mock_date: MagicMock,
        tmp_path: Path,
    ) -> None:
        """LLM should not be called when there are no commits (grouped is empty)."""
        mock_commits.return_value = []
        mock_version.return_value = "1.0.0"
        mock_date.return_value = None

        engine = MagicMock()
        engine.generate_text = AsyncMock()

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0.9.0",
            use_llm=True,
            llm_engine=engine,
        )
        gen.generate()
        engine.generate_text.assert_not_called()


# ── ChangelogGenerator._polish_with_llm ───────────────────────────


class TestChangelogGeneratorPolishWithLLM:
    """Tests for ChangelogGenerator._polish_with_llm()."""

    def test_polish_replaces_entries(self, tmp_path: Path) -> None:
        engine = MagicMock()
        engine.generate_text = AsyncMock(return_value="- Polished entry one\n- Polished entry two")

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0",
            llm_engine=engine,
        )
        grouped = {"Added": ["- raw entry one", "- raw entry two"]}
        result = gen._polish_with_llm(grouped)

        assert "- Polished entry one" in result["Added"]
        assert "- Polished entry two" in result["Added"]

    def test_polish_falls_back_on_llm_error(self, tmp_path: Path) -> None:
        engine = MagicMock()
        engine.generate_text = AsyncMock(side_effect=RuntimeError("LLM failed"))

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0",
            llm_engine=engine,
        )
        original_entries = ["- original entry"]
        grouped = {"Added": original_entries}
        result = gen._polish_with_llm(grouped)

        assert result["Added"] == original_entries

    def test_polish_falls_back_when_no_bullets_returned(self, tmp_path: Path) -> None:
        engine = MagicMock()
        engine.generate_text = AsyncMock(return_value="No bullets here, just text.")

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0",
            llm_engine=engine,
        )
        original_entries = ["- keep this"]
        grouped = {"Fixed": original_entries}
        result = gen._polish_with_llm(grouped)

        assert result["Fixed"] == original_entries

    def test_polish_returns_original_when_no_engine(self, tmp_path: Path) -> None:
        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0",
            llm_engine=None,
        )
        grouped = {"Added": ["- entry"]}
        result = gen._polish_with_llm(grouped)
        assert result == grouped

    def test_polish_handles_asterisk_bullets(self, tmp_path: Path) -> None:
        engine = MagicMock()
        engine.generate_text = AsyncMock(return_value="* star bullet one\n* star bullet two")

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0",
            llm_engine=engine,
        )
        grouped = {"Added": ["- raw"]}
        result = gen._polish_with_llm(grouped)

        # Asterisk bullets get normalized to dash bullets
        for line in result["Added"]:
            assert line.startswith("-")

    def test_polish_preserves_section_order(self, tmp_path: Path) -> None:
        engine = MagicMock()
        engine.generate_text = AsyncMock(return_value="- polished")

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0",
            llm_engine=engine,
        )
        # Provide in reverse order: Fixed before Added
        grouped = {"Fixed": ["- fix"], "Added": ["- add"]}
        result = gen._polish_with_llm(grouped)

        keys = list(result.keys())
        assert keys.index("Added") < keys.index("Fixed")

    def test_polish_skips_empty_sections_for_llm_call(self, tmp_path: Path) -> None:
        """Empty sections are not sent to the LLM but are preserved from grouped."""
        engine = MagicMock()
        engine.generate_text = AsyncMock(return_value="- polished")

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0",
            llm_engine=engine,
        )
        grouped = {"Added": ["- entry"], "Fixed": []}
        result = gen._polish_with_llm(grouped)

        # LLM should only be called once (for Added, not for empty Fixed)
        assert engine.generate_text.call_count == 1
        # Empty "Fixed" is still preserved from grouped (pass-through)
        assert result["Fixed"] == []
        # Added was polished
        assert result["Added"] == ["- polished"]

    def test_polish_calls_llm_per_nonempty_section(self, tmp_path: Path) -> None:
        engine = MagicMock()
        engine.generate_text = AsyncMock(return_value="- polished")

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0",
            llm_engine=engine,
        )
        grouped = {"Added": ["- a"], "Fixed": ["- b"], "Changed": ["- c"]}
        gen._polish_with_llm(grouped)

        assert engine.generate_text.call_count == 3

    def test_polish_mixed_dash_and_asterisk(self, tmp_path: Path) -> None:
        engine = MagicMock()
        engine.generate_text = AsyncMock(return_value="- dash line\n* star line\n- another dash")

        gen = ChangelogGenerator(
            repo_path=tmp_path,
            from_ref="v0",
            llm_engine=engine,
        )
        grouped = {"Added": ["- raw"]}
        result = gen._polish_with_llm(grouped)

        assert len(result["Added"]) == 3
        for line in result["Added"]:
            assert line.startswith("-")


# ── get_commits_between (with real git) ────────────────────────────


class TestGetCommitsBetween:
    """Tests for get_commits_between using a real git repo."""

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


# ── ChangelogGenerator with real git ───────────────────────────────


class TestChangelogGeneratorWithGit:
    """Integration tests for ChangelogGenerator using a real git repo."""

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


# ── Integration-style tests ───────────────────────────────────────


class TestChangelogIntegration:
    """Integration-level tests combining parse + group + format."""

    def test_full_pipeline_without_llm(self) -> None:
        commits = [
            CommitInfo(sha="aaa", subject="feat(auth): add SSO login", body=""),
            CommitInfo(
                sha="bbb",
                subject="feat!: rewrite config format",
                body="BREAKING CHANGE: old config files are not supported",
            ),
            CommitInfo(sha="ccc", subject="fix: memory leak in cache", body=""),
            CommitInfo(sha="ddd", subject="docs: add migration guide", body=""),
            CommitInfo(sha="eee", subject="chore: bump dependencies", body=""),
            CommitInfo(sha="fff", subject="Merge pull request #42", body=""),
        ]

        grouped = group_commits_by_section(commits)
        date = datetime(2024, 12, 25, tzinfo=UTC)
        result = format_keep_a_changelog("3.0.0", date, grouped)

        assert "## [3.0.0] - 2024-12-25" in result
        assert "### Added" in result
        assert "**auth:** add SSO login" in result
        assert "**BREAKING:** rewrite config format" in result
        assert "### Fixed" in result
        assert "memory leak in cache" in result
        assert "### Changed" in result
        assert "add migration guide" in result
        assert "### Other" in result
        assert "bump dependencies" in result
        assert "Merge pull request #42" in result

    def test_full_pipeline_with_unreleased(self) -> None:
        released_commits = [
            CommitInfo(sha="r1", subject="feat: initial release", body=""),
        ]
        unreleased_commits = [
            CommitInfo(sha="u1", subject="fix: hotfix pending", body=""),
        ]

        grouped = group_commits_by_section(released_commits)
        unreleased = group_commits_by_section(unreleased_commits)
        date = datetime(2024, 1, 1, tzinfo=UTC)
        result = format_keep_a_changelog("1.0.0", date, grouped, unreleased=unreleased)

        assert "## [Unreleased]" in result
        assert "## [1.0.0] - 2024-01-01" in result
        assert "hotfix pending" in result
        assert "initial release" in result

    def test_all_conventional_types_covered(self) -> None:
        """Verify that every type in _TYPE_TO_SECTION maps to a section correctly."""
        type_map = {
            "feat": "Added",
            "fix": "Fixed",
            "docs": "Changed",
            "style": "Changed",
            "refactor": "Changed",
            "perf": "Changed",
            "test": "Changed",
            "build": "Changed",
            "ci": "Changed",
            "chore": "Other",
        }
        for ctype, expected_section in type_map.items():
            commits = [CommitInfo(sha="x", subject=f"{ctype}: test", body="")]
            grouped = group_commits_by_section(commits)
            assert expected_section in grouped, f"{ctype} should map to {expected_section}"
