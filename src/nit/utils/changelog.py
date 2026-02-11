"""Changelog generation from git history in Keep a Changelog format."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from nit.llm.prompts.changelog_prompt import build_changelog_polish_prompt
from nit.utils.git import CommitInfo, get_commits_between

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nit.llm.engine import LLMEngine

# Conventional commit type -> Keep a Changelog section
# https://keepachangelog.com/en/1.1.0/
# https://www.conventionalcommits.org/
_TYPE_TO_SECTION: dict[str, str] = {
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

# KAC section order
_SECTION_ORDER: tuple[str, ...] = (
    "Added",
    "Changed",
    "Deprecated",
    "Removed",
    "Fixed",
    "Security",
    "Other",
)


@dataclass
class ParsedCommit:
    """A commit parsed into conventional commit fields."""

    type: str
    """Conventional type (feat, fix, etc.)."""

    scope: str
    """Optional scope (e.g. api, cli)."""

    description: str
    """Short description."""

    breaking: bool
    """True if BREAKING CHANGE in body or ! after type(scope)."""

    raw_subject: str
    """Original subject line."""

    body: str
    """Full body."""


def parse_conventional_commit(subject: str, body: str = "") -> ParsedCommit:
    """Parse a commit subject (and optional body) into conventional commit fields.

    Supports: type(scope): description, type: description, and BREAKING CHANGE in body.
    """
    raw_subject = subject.strip()
    body = body.strip()

    # Optional ! after type(scope) for breaking change
    breaking_from_subject = False
    subject_stripped = raw_subject.strip()
    if "!:" in subject_stripped:
        breaking_from_subject = True
        subject_stripped = subject_stripped.replace("!:", ":", 1)
    elif subject_stripped.endswith("!") and ":" in subject_stripped:
        breaking_from_subject = True
        subject_stripped = subject_stripped[:-1].rstrip()

    # type(scope): description or type: description
    match = re.match(r"^(\w+)(?:\(([^)]*)\))?\s*:\s*(.+)$", subject_stripped)
    if match:
        ctype, scope, desc = match.groups()
        ctype = ctype.lower()
        scope = (scope or "").strip()
        description = desc.strip()
    else:
        ctype = "other"
        scope = ""
        description = raw_subject.strip()

    breaking = breaking_from_subject or "BREAKING CHANGE" in body.upper()

    return ParsedCommit(
        type=ctype,
        scope=scope,
        description=description,
        breaking=breaking,
        raw_subject=raw_subject,
        body=body,
    )


def group_commits_by_section(commits: list[CommitInfo]) -> dict[str, list[str]]:
    """Group parsed commits by Keep a Changelog section; each value is a list of entry lines."""
    grouped: dict[str, list[str]] = {s: [] for s in _SECTION_ORDER}

    for commit in commits:
        parsed = parse_conventional_commit(commit.subject, commit.body)
        section = _TYPE_TO_SECTION.get(parsed.type, "Other")
        if parsed.breaking:
            line = f"- **BREAKING:** {parsed.description}"
        elif parsed.scope:
            line = f"- **{parsed.scope}:** {parsed.description}"
        else:
            line = f"- {parsed.description}"
        grouped[section].append(line)

    # Drop empty sections
    return {k: v for k, v in grouped.items() if v}


def format_keep_a_changelog(
    version: str,
    date: datetime | None,
    grouped: dict[str, list[str]],
    *,
    unreleased: dict[str, list[str]] | None = None,
) -> str:
    """Produce Keep a Changelog markdown for a single version (and optional Unreleased)."""
    lines: list[str] = []

    if unreleased:
        lines.append("## [Unreleased]")
        lines.append("")
        for section in _SECTION_ORDER:
            entries = unreleased.get(section, [])
            if entries:
                lines.append(f"### {section}")
                lines.extend(entries)
                lines.append("")
        lines.append("")

    date_str = date.strftime("%Y-%m-%d") if date else ""

    lines.append(f"## [{version}] - {date_str}" if date_str else f"## [{version}]")
    lines.append("")
    for section in _SECTION_ORDER:
        entries = grouped.get(section, [])
        if entries:
            lines.append(f"### {section}")
            lines.extend(entries)
            lines.append("")

    return "\n".join(lines).rstrip()


@dataclass
class ChangelogGenerator:
    """Generate changelog from git history in Keep a Changelog format."""

    repo_path: Path | str
    """Repository root."""

    from_ref: str
    """Older ref (e.g. tag v1.0.0)."""

    to_ref: str = "HEAD"
    """Newer ref."""

    version: str = ""
    """Version label (e.g. 1.2.0). If empty, derived from to_ref (tag or 'Unreleased')."""

    use_llm: bool = True
    """Whether to use LLM to polish entry lines (when engine is provided)."""

    llm_engine: LLMEngine | None = field(default=None, repr=False)
    """Optional LLM engine for human-readable polish."""

    def _resolve_version(self) -> str:
        if self.version:
            return self.version
        ref = self.to_ref
        if "\n" in ref or "\0" in ref:
            return "Unreleased"
        path = Path(self.repo_path)
        git_cmd = shutil.which("git") or "git"
        try:
            result = subprocess.run(
                [git_cmd, "describe", "--tags", "--exact-match", ref],
                cwd=path,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            logger.debug("Could not resolve version for %s: %s", self.to_ref, e)
        return "Unreleased"

    def _get_release_date(self) -> datetime | None:
        ref = self.to_ref
        if "\n" in ref or "\0" in ref:
            return None
        path = Path(self.repo_path)
        git_cmd = shutil.which("git") or "git"
        try:
            result = subprocess.run(
                [git_cmd, "log", "-1", "--format=%ci", ref],
                cwd=path,
                capture_output=True,
                text=True,
                check=True,
            )
            date_str = result.stdout.strip()
            if date_str:
                return datetime.strptime(date_str.split()[0], "%Y-%m-%d").replace(tzinfo=UTC)
        except Exception as e:
            logger.debug("Could not get release date for %s: %s", self.to_ref, e)
        return None

    def generate(self) -> str:
        """Produce changelog markdown for commits between from_ref and to_ref."""
        path = Path(self.repo_path)
        commits = get_commits_between(path, self.from_ref, self.to_ref)
        grouped = group_commits_by_section(commits)
        version = self._resolve_version()
        date = self._get_release_date()

        if self.llm_engine and self.use_llm and grouped:
            grouped = self._polish_with_llm(grouped)

        return format_keep_a_changelog(version, date, grouped)

    def _polish_with_llm(self, grouped: dict[str, list[str]]) -> dict[str, list[str]]:
        """Use LLM to turn raw entry lines into human-readable bullets. Returns new grouped dict."""
        if not self.llm_engine:
            return grouped

        polished: dict[str, list[str]] = {}
        for section, entries in grouped.items():
            if not entries:
                continue
            prompt = build_changelog_polish_prompt(section, entries)
            try:
                text = asyncio.run(self.llm_engine.generate_text(prompt, context=""))
            except Exception:
                polished[section] = entries
                continue
            lines = [
                line.strip() for line in text.split("\n") if line.strip().startswith(("-", "*"))
            ]
            if lines:
                polished[section] = [
                    line if line.startswith("-") else f"-{line[1:]}".lstrip() for line in lines
                ]
            else:
                polished[section] = entries
        result: dict[str, list[str]] = {}
        for section in _SECTION_ORDER:
            if section in polished:
                result[section] = polished[section]
            elif section in grouped:
                result[section] = grouped[section]
        return result
