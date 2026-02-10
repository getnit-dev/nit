"""Stack detector — scan a directory to identify languages and their prevalence."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.parsing.treesitter import (
    EXTENSION_TO_LANGUAGE,
    SUPPORTED_LANGUAGES,
    get_parser,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    import tree_sitter

logger = logging.getLogger(__name__)

# Extensions that map to multiple possible languages.
# For each ambiguous extension we list the candidate languages and a
# tree-sitter query that, if it matches, confirms the *second* candidate
# (the non-default one).  The first candidate is the default fallback.
AMBIGUOUS_EXTENSIONS: dict[str, list[str]] = {
    ".h": ["c", "cpp"],
    ".hpp": ["cpp"],
    ".hxx": ["cpp"],
    ".hh": ["cpp"],
}

# C++ indicators in a .h file that tree-sitter for C would *not* parse:
# class declarations, namespaces, templates, access specifiers, etc.
_CPP_INDICATOR_NODE_TYPES = frozenset(
    {
        "class_specifier",
        "namespace_definition",
        "template_declaration",
        "access_specifier",
        "using_declaration",
    }
)

# Default directories to skip during scanning.
DEFAULT_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".nit",
        ".next",
        "target",
        "vendor",
    }
)

MAX_DISAMBIGUATION_FILES = 5
MAX_DISAMBIGUATION_BYTES = 64 * 1024  # 64 KiB per sample


@dataclass
class LanguageInfo:
    """Per-language detection result."""

    language: str
    file_count: int
    confidence: float
    extensions: dict[str, int] = field(default_factory=dict)


@dataclass
class LanguageProfile:
    """Detected language profile for a project directory."""

    languages: list[LanguageInfo] = field(default_factory=list)
    total_files: int = 0
    root: str = ""

    @property
    def primary_language(self) -> str | None:
        """Return the language with the most files, or None if empty."""
        if not self.languages:
            return None
        return self.languages[0].language


def _iter_source_files(
    root: Path,
    skip_dirs: frozenset[str],
) -> Iterable[Path]:
    """Yield source files under *root*, skipping common non-source dirs."""
    for child in sorted(root.iterdir()):
        if child.is_dir():
            if child.name in skip_dirs:
                continue
            yield from _iter_source_files(child, skip_dirs)
        elif child.is_file() and child.suffix.lower() in EXTENSION_TO_LANGUAGE:
            yield child


def _disambiguate_header(file_path: Path) -> str:
    """Use tree-sitter to decide whether a .h file is C or C++.

    Parse the file with the C++ parser.  If the AST contains C++-specific
    node types (classes, namespaces, templates, …), classify as ``cpp``;
    otherwise fall back to ``c``.
    """
    try:
        source = file_path.read_bytes()[:MAX_DISAMBIGUATION_BYTES]
    except OSError:
        return "c"

    parser = get_parser("cpp")
    tree = parser.parse(source)
    if _has_cpp_indicators(tree.root_node):
        return "cpp"
    return "c"


def _has_cpp_indicators(node: tree_sitter.Node) -> bool:
    """Walk the AST looking for C++-only constructs."""
    if node.type in _CPP_INDICATOR_NODE_TYPES:
        return True
    return any(_has_cpp_indicators(child) for child in node.children)


def _compute_confidence(file_count: int, total_files: int) -> float:
    """Compute a 0-1 confidence score for a language.

    The score is the proportion of matching files, with a small bonus
    for having more than a handful of files (reduces noise from stray
    single-file artefacts).
    """
    if total_files == 0:
        return 0.0
    ratio = file_count / total_files
    # Small projects with only 1 file get a slight penalty.
    if file_count == 1:
        ratio *= 0.9
    return round(min(ratio, 1.0), 4)


def detect_languages(
    root: str | Path,
    *,
    skip_dirs: frozenset[str] | None = None,
) -> LanguageProfile:
    """Scan *root* for source files, count by language, rank by frequency.

    For ambiguous extensions (e.g. ``.h`` which could be C or C++),
    tree-sitter is used to parse a sample file and confirm the language.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f"Not a directory: {root_path}")

    effective_skip = skip_dirs if skip_dirs is not None else DEFAULT_SKIP_DIRS

    # Pass 1: count extensions
    ext_files: dict[str, list[Path]] = {}
    for path in _iter_source_files(root_path, effective_skip):
        ext = path.suffix.lower()
        ext_files.setdefault(ext, []).append(path)

    # Pass 2: resolve ambiguous extensions via tree-sitter
    lang_ext_counts: dict[str, dict[str, int]] = {}

    for ext, files in ext_files.items():
        if ext in AMBIGUOUS_EXTENSIONS:
            resolved = _resolve_ambiguous(ext, files)
            for lang, count in resolved.items():
                lang_ext_counts.setdefault(lang, {})
                lang_ext_counts[lang][ext] = lang_ext_counts[lang].get(ext, 0) + count
        else:
            detected_lang = EXTENSION_TO_LANGUAGE.get(ext)
            if detected_lang and detected_lang in SUPPORTED_LANGUAGES:
                lang_ext_counts.setdefault(detected_lang, {})
                lang_ext_counts[detected_lang][ext] = len(files)

    total_files = sum(count for ext_map in lang_ext_counts.values() for count in ext_map.values())

    # Build LanguageInfo entries sorted by file count descending
    infos: list[LanguageInfo] = []
    for lang, ext_map in lang_ext_counts.items():
        file_count = sum(ext_map.values())
        infos.append(
            LanguageInfo(
                language=lang,
                file_count=file_count,
                confidence=_compute_confidence(file_count, total_files),
                extensions=dict(ext_map),
            )
        )

    infos.sort(key=lambda li: (-li.file_count, li.language))

    return LanguageProfile(
        languages=infos,
        total_files=total_files,
        root=str(root_path),
    )


def _resolve_ambiguous(ext: str, files: list[Path]) -> dict[str, int]:
    """For an ambiguous extension, sample files with tree-sitter and tally."""
    candidates = AMBIGUOUS_EXTENSIONS[ext]
    if len(candidates) == 1:
        return {candidates[0]: len(files)}

    # Sample up to MAX_DISAMBIGUATION_FILES files to decide the split.
    sample = files[:MAX_DISAMBIGUATION_FILES]
    tally: dict[str, int] = {}
    for path in sample:
        resolved = _disambiguate_header(path)
        tally[resolved] = tally.get(resolved, 0) + 1

    if not tally:
        # Fallback to default candidate
        return {candidates[0]: len(files)}

    # If all samples agree, assign all files to that language.
    if len(tally) == 1:
        lang = next(iter(tally))
        return {lang: len(files)}

    # Mixed: extrapolate proportions to the full file set.
    sample_total = sum(tally.values())
    result: dict[str, int] = {}
    assigned = 0
    sorted_langs = sorted(tally, key=lambda lang_key: -tally[lang_key])
    for lang in sorted_langs[:-1]:
        count = round(len(files) * tally[lang] / sample_total)
        result[lang] = count
        assigned += count
    # Last language gets the remainder to avoid rounding drift.
    result[sorted_langs[-1]] = len(files) - assigned
    return result


class StackDetector(BaseAgent):
    """Agent that detects the programming language stack of a project."""

    @property
    def name(self) -> str:
        return "stack-detector"

    @property
    def description(self) -> str:
        return "Scan a project directory to identify languages and their prevalence."

    async def run(self, task: TaskInput) -> TaskOutput:
        """Run stack detection on the target directory.

        ``task.target`` should be the path to a project root directory.
        Optional ``task.context["skip_dirs"]`` overrides default skip dirs.
        """
        target = Path(task.target)
        skip_raw = task.context.get("skip_dirs")
        skip_dirs = frozenset(skip_raw) if skip_raw is not None else None

        try:
            profile = detect_languages(target, skip_dirs=skip_dirs)
        except ValueError as exc:
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[str(exc)],
            )

        return TaskOutput(
            status=TaskStatus.COMPLETED,
            result={
                "root": profile.root,
                "total_files": profile.total_files,
                "primary_language": profile.primary_language,
                "languages": [
                    {
                        "language": li.language,
                        "file_count": li.file_count,
                        "confidence": li.confidence,
                        "extensions": li.extensions,
                    }
                    for li in profile.languages
                ],
            },
        )
