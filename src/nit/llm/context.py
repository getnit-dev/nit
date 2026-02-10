"""Context Assembly Engine for LLM-based test generation.

Given a source file, collects source code, tree-sitter AST extracts,
import/dependency graph, related files, and existing test patterns
into a structured context suitable for LLM prompts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from nit.parsing.languages import extract_from_file
from nit.parsing.treesitter import (
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ParseResult,
    detect_language,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nit.config import AuthConfig
    from nit.models.route import RouteInfo

# ── Constants ────────────────────────────────────────────────────

DEFAULT_MAX_CONTEXT_TOKENS = 8000

# Priority weights for context sections (higher = kept first during truncation)
_PRIORITY_SOURCE = 100
_PRIORITY_SIGNATURES = 90
_PRIORITY_TEST_PATTERNS = 80
_PRIORITY_RELATED = 60
_PRIORITY_IMPORTS = 50

# Patterns for identifying test files by language
_TEST_FILE_PATTERNS: dict[str, list[str]] = {
    "python": ["test_*.py", "*_test.py"],
    "javascript": ["*.test.js", "*.spec.js", "*.test.jsx", "*.spec.jsx"],
    "typescript": ["*.test.ts", "*.spec.ts", "*.test.tsx", "*.spec.tsx"],
    "tsx": ["*.test.tsx", "*.spec.tsx"],
    "java": ["*Test.java", "*Tests.java", "*Spec.java"],
    "go": ["*_test.go"],
    "rust": [],  # Rust tests are inline (#[cfg(test)])
    "c": ["*_test.c", "test_*.c"],
    "cpp": ["*_test.cpp", "test_*.cpp", "*_test.cc", "test_*.cc"],
}

# Common test directory names
_TEST_DIR_NAMES = frozenset(
    {
        "test",
        "tests",
        "spec",
        "specs",
        "__tests__",
        "test_",
        "testing",
    }
)


# ── Data models ──────────────────────────────────────────────────


@dataclass
class ContextSection:
    """A single section of assembled context with priority metadata."""

    name: str
    content: str
    token_count: int
    priority: int


@dataclass
class DetectedTestPattern:
    """Conventions extracted from existing test files."""

    naming_style: str = "unknown"
    """Naming convention: 'function' (test_foo), 'class' (TestFoo), 'describe'."""

    assertion_style: str = "unknown"
    """Assertion convention: 'assert' (assert x), 'expect' (expect(x)), 'should' (x.should)."""

    mocking_patterns: list[str] = field(default_factory=list)
    """Detected mocking approaches (e.g. 'pytest.fixture', 'unittest.mock', 'vi.mock')."""

    imports: list[str] = field(default_factory=list)
    """Common test imports seen across test files."""

    sample_test: str = ""
    """A representative test function body used as a style reference."""


@dataclass
class RelatedFile:
    """A file related to the target source file (import, sibling, test)."""

    path: str
    relationship: str
    """One of 'import', 'test', 'sibling'."""

    content_snippet: str = ""
    """First portion of the file content (truncated)."""


@dataclass
class AssembledContext:
    """Complete context assembled for a source file."""

    source_path: str
    source_code: str
    language: str
    parse_result: ParseResult
    related_files: list[RelatedFile] = field(default_factory=list)
    test_patterns: DetectedTestPattern | None = None
    total_tokens: int = 0

    # E2E-specific optional fields
    route_info: RouteInfo | None = None
    auth_config: AuthConfig | None = None
    base_url: str = ""
    flow_description: str = ""

    @property
    def function_signatures(self) -> list[str]:
        """Formatted function signatures from the parse result."""
        return [_format_function_sig(f) for f in self.parse_result.functions]

    @property
    def class_signatures(self) -> list[str]:
        """Formatted class signatures from the parse result."""
        return [_format_class_sig(c) for c in self.parse_result.classes]


# ── ContextAssembler ─────────────────────────────────────────────


class ContextAssembler:
    """Assembles LLM context from a source file and its surroundings.

    Given a source file path and project root, this class:
    1. Reads and parses the source file with tree-sitter
    2. Resolves imports to locate related files
    3. Finds existing test files for the source
    4. Extracts test naming/assertion/mocking patterns
    5. Applies token windowing to fit the model's context limit
    """

    def __init__(
        self,
        root: Path,
        *,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        self._root = root
        self._max_tokens = max_context_tokens
        self._count_tokens = token_counter or _default_token_count

    def assemble(self, source_path: Path) -> AssembledContext:
        """Assemble full context for *source_path*.

        Args:
            source_path: Absolute or root-relative path to the source file.

        Returns:
            An ``AssembledContext`` with source, AST info, related files,
            and test patterns, windowed to fit within the configured token limit.
        """
        abs_path = self._resolve(source_path)
        source_code = abs_path.read_text(encoding="utf-8", errors="replace")
        language = detect_language(abs_path)
        if language is None:
            raise ValueError(f"Unsupported language for file: {abs_path}")

        parse_result = extract_from_file(str(abs_path))
        related = self._find_related_files(abs_path, parse_result, language)
        test_patterns = self._extract_test_patterns(abs_path, language)

        ctx = AssembledContext(
            source_path=str(abs_path.relative_to(self._root)),
            source_code=source_code,
            language=language,
            parse_result=parse_result,
            related_files=related,
            test_patterns=test_patterns,
        )

        self._apply_windowing(ctx)
        return ctx

    # ── Import resolution ────────────────────────────────────────

    def _find_related_files(
        self,
        source: Path,
        parse_result: ParseResult,
        language: str,
    ) -> list[RelatedFile]:
        """Find files related to *source* through imports and co-location."""
        related: list[RelatedFile] = []

        # 1. Resolve imports to real files
        for imp in parse_result.imports:
            resolved = self._resolve_import(source, imp, language)
            if resolved is not None and resolved != source:
                snippet = _read_snippet(resolved)
                related.append(
                    RelatedFile(
                        path=str(resolved.relative_to(self._root)),
                        relationship="import",
                        content_snippet=snippet,
                    )
                )

        # 2. Find existing test files for this source
        test_files = _find_test_files_for(source, self._root, language)
        for tf in test_files:
            snippet = _read_snippet(tf)
            related.append(
                RelatedFile(
                    path=str(tf.relative_to(self._root)),
                    relationship="test",
                    content_snippet=snippet,
                )
            )

        return related

    def _resolve_import(
        self,
        source: Path,
        imp: ImportInfo,
        language: str,
    ) -> Path | None:
        """Try to resolve an import to a file on disk."""
        module = imp.module
        if not module:
            return None

        if language == "python":
            return self._resolve_python_import(source, module)
        if language in {"javascript", "typescript", "tsx"}:
            return self._resolve_js_import(source, module)
        return None

    def _resolve_python_import(self, source: Path, module: str) -> Path | None:
        """Resolve a Python dotted import to a file."""
        parts = module.split(".")
        # Try relative to project root/src directories
        for base in [self._root, self._root / "src"]:
            candidate = base / Path(*parts)
            # Check package (dir/__init__.py)
            init = candidate / "__init__.py"
            if init.is_file():
                return init
            # Check module file
            py_file = candidate.with_suffix(".py")
            if py_file.is_file():
                return py_file

        # Try relative to source file's parent
        parent = source.parent
        candidate = parent / Path(*parts)
        py_file = candidate.with_suffix(".py")
        if py_file.is_file():
            return py_file

        return None

    def _resolve_js_import(self, source: Path, module: str) -> Path | None:
        """Resolve a JS/TS relative import to a file."""
        if not module.startswith("."):
            return None  # Skip node_modules imports

        parent = source.parent
        candidate = parent / module

        # Try direct file first
        if candidate.is_file():
            return candidate

        # Try with common extensions
        for ext in [".ts", ".tsx", ".js", ".jsx", ".mjs"]:
            with_ext = candidate.with_suffix(ext)
            if with_ext.is_file():
                return with_ext

        # Try index files in directory
        if candidate.is_dir():
            for idx in ["index.ts", "index.tsx", "index.js", "index.jsx"]:
                idx_path = candidate / idx
                if idx_path.is_file():
                    return idx_path

        return None

    # ── Test pattern extraction ──────────────────────────────────

    def _extract_test_patterns(
        self,
        source: Path,
        language: str,
    ) -> DetectedTestPattern | None:
        """Find existing test files and extract conventions from them."""
        test_files = _find_test_files_for(source, self._root, language)
        if not test_files:
            # Fall back to scanning any test file in the project
            test_files = _find_any_test_files(self._root, language, limit=5)

        if not test_files:
            return None

        return extract_test_patterns(test_files, language)

    # ── Context windowing ────────────────────────────────────────

    def _apply_windowing(self, ctx: AssembledContext) -> None:
        """Truncate context sections to fit within the token budget."""
        sections = self._build_sections(ctx)

        # Sort by priority descending — highest priority kept first
        sections.sort(key=lambda s: -s.priority)

        budget = self._max_tokens
        kept_names: set[str] = set()

        for section in sections:
            if section.token_count <= budget:
                budget -= section.token_count
                kept_names.add(section.name)
            else:
                # Partially include by truncating content
                if budget > 0 and section.name == "source":
                    # Always include at least partial source
                    ctx.source_code = _truncate_to_tokens(
                        ctx.source_code, budget, self._count_tokens
                    )
                    budget = 0
                    kept_names.add(section.name)
                break

        # Remove related files that didn't fit
        if "related" not in kept_names:
            ctx.related_files = []
        elif budget <= 0:
            # Trim related file snippets if we're tight on budget
            for rf in ctx.related_files:
                rf.content_snippet = ""

        # Remove test patterns if they didn't fit
        if "test_patterns" not in kept_names:
            ctx.test_patterns = None

        ctx.total_tokens = self._max_tokens - budget

    def _build_sections(self, ctx: AssembledContext) -> list[ContextSection]:
        """Break an AssembledContext into prioritized sections for windowing."""
        sections: list[ContextSection] = []

        # Source code — highest priority
        src_tokens = self._count_tokens(ctx.source_code)
        sections.append(ContextSection("source", ctx.source_code, src_tokens, _PRIORITY_SOURCE))

        # Function/class signatures
        sigs = "\n".join(ctx.function_signatures + ctx.class_signatures)
        if sigs:
            sig_tokens = self._count_tokens(sigs)
            sections.append(ContextSection("signatures", sigs, sig_tokens, _PRIORITY_SIGNATURES))

        # Test patterns
        if ctx.test_patterns is not None:
            tp_text = _format_test_pattern(ctx.test_patterns)
            tp_tokens = self._count_tokens(tp_text)
            sections.append(
                ContextSection("test_patterns", tp_text, tp_tokens, _PRIORITY_TEST_PATTERNS)
            )

        # Related files
        related_text = "\n---\n".join(
            f"# {rf.path} ({rf.relationship})\n{rf.content_snippet}" for rf in ctx.related_files
        )
        if related_text:
            rel_tokens = self._count_tokens(related_text)
            sections.append(ContextSection("related", related_text, rel_tokens, _PRIORITY_RELATED))

        # Import list
        imp_text = "\n".join(
            f"{imp.module}" + (f" ({', '.join(imp.names)})" if imp.names else "")
            for imp in ctx.parse_result.imports
        )
        if imp_text:
            imp_tokens = self._count_tokens(imp_text)
            sections.append(ContextSection("imports", imp_text, imp_tokens, _PRIORITY_IMPORTS))

        return sections

    # ── Helpers ───────────────────────────────────────────────────

    def _resolve(self, path: Path) -> Path:
        """Ensure *path* is absolute, resolving relative to root."""
        if path.is_absolute():
            return path
        return self._root / path


# ── Test pattern extraction (1.8.2) ──────────────────────────────


def extract_test_patterns(test_files: list[Path], language: str) -> DetectedTestPattern:
    """Analyse a set of test files and extract conventions.

    Reads up to 5 test files, detects:
    - Naming style (function-based, class-based, describe/it)
    - Assertion style (assert, expect, should)
    - Mocking patterns (pytest fixtures, unittest.mock, vi.mock, etc.)
    - Common test imports
    - A representative sample test body
    """
    naming_votes: dict[str, int] = {"function": 0, "class": 0, "describe": 0}
    assertion_votes: dict[str, int] = {"assert": 0, "expect": 0, "should": 0}
    mocking_patterns: set[str] = set()
    seen_imports: list[str] = []
    sample_test = ""

    for tf in test_files[:5]:
        try:
            content = tf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        _detect_naming(content, language, naming_votes)
        _detect_assertions(content, assertion_votes)
        mocking_patterns.update(_detect_mocking(content, language))
        seen_imports.extend(_extract_test_imports(content, language))

        if not sample_test:
            sample_test = _extract_sample_test(content, language)

    naming = max(naming_votes, key=lambda k: naming_votes[k])
    if naming_votes[naming] == 0:
        naming = "unknown"

    assertion = max(assertion_votes, key=lambda k: assertion_votes[k])
    if assertion_votes[assertion] == 0:
        assertion = "unknown"

    # Deduplicate imports preserving order
    unique_imports: list[str] = list(dict.fromkeys(seen_imports))

    return DetectedTestPattern(
        naming_style=naming,
        assertion_style=assertion,
        mocking_patterns=sorted(mocking_patterns),
        imports=unique_imports[:20],
        sample_test=sample_test,
    )


# ── Pattern detection helpers ────────────────────────────────────

_RE_DESCRIBE_BLOCK = re.compile(r"\bdescribe\s*\(")
_RE_IT_BLOCK = re.compile(r"\bit\s*\(")
_RE_TEST_FUNCTION = re.compile(r"^(?:def |async def )test_", re.MULTILINE)
_RE_TEST_CLASS = re.compile(r"^class Test\w+", re.MULTILINE)
_RE_ASSERT_STMT = re.compile(r"\bassert\b")
_RE_EXPECT_CALL = re.compile(r"\bexpect\s*\(")
_RE_SHOULD_CHAIN = re.compile(r"\.should\b")


def _detect_naming(content: str, language: str, votes: dict[str, int]) -> None:
    """Vote on naming convention based on file content."""
    if language in {"javascript", "typescript", "tsx"}:
        if _RE_DESCRIBE_BLOCK.search(content):
            votes["describe"] += 1
        if _RE_TEST_FUNCTION.search(content):
            votes["function"] += 1
    elif language == "python":
        if _RE_TEST_FUNCTION.search(content):
            votes["function"] += 1
        if _RE_TEST_CLASS.search(content):
            votes["class"] += 1
    elif language == "go":
        if re.search(r"^func Test\w+", content, re.MULTILINE):
            votes["function"] += 1


def _detect_assertions(content: str, votes: dict[str, int]) -> None:
    """Vote on assertion style based on file content."""
    if _RE_ASSERT_STMT.search(content):
        votes["assert"] += 1
    if _RE_EXPECT_CALL.search(content):
        votes["expect"] += 1
    if _RE_SHOULD_CHAIN.search(content):
        votes["should"] += 1


def _detect_mocking(content: str, language: str) -> list[str]:
    """Detect mocking patterns in test content."""
    if language == "python":
        return _detect_python_mocking(content)
    if language in {"javascript", "typescript", "tsx"}:
        return _detect_js_mocking(content)
    if language == "go":
        return _detect_go_mocking(content)
    return []


def _detect_python_mocking(content: str) -> list[str]:
    patterns: list[str] = []
    if "unittest.mock" in content or "from unittest import mock" in content:
        patterns.append("unittest.mock")
    if "@pytest.fixture" in content or "pytest.fixture" in content:
        patterns.append("pytest.fixture")
    if "monkeypatch" in content:
        patterns.append("monkeypatch")
    if "from unittest.mock import" in content and "patch" in content:
        patterns.append("unittest.mock.patch")
    return patterns


def _detect_js_mocking(content: str) -> list[str]:
    patterns: list[str] = []
    if "vi.mock(" in content or "vi.fn(" in content:
        patterns.append("vi.mock")
    if "jest.mock(" in content or "jest.fn(" in content:
        patterns.append("jest.mock")
    if "sinon." in content:
        patterns.append("sinon")
    if "nock(" in content:
        patterns.append("nock")
    return patterns


def _detect_go_mocking(content: str) -> list[str]:
    patterns: list[str] = []
    if "testify/mock" in content:
        patterns.append("testify.mock")
    if "gomock" in content:
        patterns.append("gomock")
    return patterns


def _extract_test_imports(content: str, language: str) -> list[str]:
    """Extract import statements from test file content."""
    if language == "python":
        return [
            m.group(0).strip()
            for m in re.finditer(r"^(?:from\s+\S+\s+)?import\s+.+$", content, re.MULTILINE)
        ]
    if language in {"javascript", "typescript", "tsx"}:
        return [m.group(0).strip() for m in re.finditer(r"^import\s+.+$", content, re.MULTILINE)]
    return []


_RE_PYTHON_TEST_FUNC = re.compile(
    r"^((?:async )?def test_\w+\([^)]*\).*?:.*?)(?=\n(?:def |class |$))",
    re.MULTILINE | re.DOTALL,
)

_RE_JS_IT_BLOCK = re.compile(
    r"(it\s*\(['\"].*?['\"]\s*,\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{.*?\}\s*\))",
    re.DOTALL,
)

_MAX_SAMPLE_LENGTH = 500


def _extract_sample_test(content: str, language: str) -> str:
    """Extract a representative test function body as a style sample."""
    if language == "python":
        m = _RE_PYTHON_TEST_FUNC.search(content)
        if m:
            return m.group(1)[:_MAX_SAMPLE_LENGTH]
    elif language in {"javascript", "typescript", "tsx"}:
        m = _RE_JS_IT_BLOCK.search(content)
        if m:
            return m.group(1)[:_MAX_SAMPLE_LENGTH]
    return ""


# ── File discovery helpers ───────────────────────────────────────


def _find_test_files_for(source: Path, root: Path, language: str) -> list[Path]:
    """Find test files that likely correspond to *source*."""
    stem = source.stem
    patterns = _TEST_FILE_PATTERNS.get(language, [])
    results: list[Path] = []

    # 1. Check sibling test files (same directory)
    parent = source.parent
    for p in patterns:
        # Replace wildcard with source stem
        specific = p.replace("*", stem)
        candidate = parent / specific
        if candidate.is_file() and candidate != source:
            results.append(candidate)

    # 2. Check common test directories relative to source
    for test_dir_name in ["tests", "test", "__tests__", "spec"]:
        # Sibling test directory
        test_dir = parent / test_dir_name
        if test_dir.is_dir():
            for p in patterns:
                specific = p.replace("*", stem)
                candidate = test_dir / specific
                if candidate.is_file():
                    results.append(candidate)

        # Project-root test directory mirroring source structure
        try:
            rel = source.relative_to(root / "src")
        except ValueError:
            try:
                rel = source.relative_to(root)
            except ValueError:
                continue
        test_mirror = root / test_dir_name / rel.parent
        if test_mirror.is_dir():
            for p in patterns:
                specific = p.replace("*", stem)
                candidate = test_mirror / specific
                if candidate.is_file():
                    results.append(candidate)

    return list(dict.fromkeys(results))  # dedupe, preserve order


def _find_any_test_files(root: Path, language: str, *, limit: int = 5) -> list[Path]:
    """Find any test files in the project for the given language."""
    patterns = _TEST_FILE_PATTERNS.get(language, [])
    results: list[Path] = []

    for pattern in patterns:
        for path in root.rglob(pattern):
            if _is_in_skip_dir(path):
                continue
            results.append(path)
            if len(results) >= limit:
                return results

    return results


def _is_in_skip_dir(path: Path) -> bool:
    """Check if path is inside a directory that should be skipped."""
    skip = {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        ".nit",
        "dist",
        "build",
    }
    return bool(skip & set(path.parts))


# ── Formatting helpers ───────────────────────────────────────────


def _format_function_sig(f: FunctionInfo) -> str:
    """Format a FunctionInfo as a human-readable signature."""
    params = ", ".join(
        p.name + (f": {p.type_annotation}" if p.type_annotation else "") for p in f.parameters
    )
    prefix = "async " if f.is_async else ""
    ret = f" -> {f.return_type}" if f.return_type else ""
    return f"{prefix}def {f.name}({params}){ret}"


def _format_class_sig(c: ClassInfo) -> str:
    """Format a ClassInfo as a human-readable signature."""
    bases = f"({', '.join(c.bases)})" if c.bases else ""
    methods = ", ".join(m.name for m in c.methods)
    return f"class {c.name}{bases}: [{methods}]"


def _format_test_pattern(tp: DetectedTestPattern) -> str:
    """Format DetectedTestPattern as a text block for context inclusion."""
    lines = [
        f"Naming: {tp.naming_style}",
        f"Assertions: {tp.assertion_style}",
    ]
    if tp.mocking_patterns:
        lines.append(f"Mocking: {', '.join(tp.mocking_patterns)}")
    if tp.sample_test:
        lines.append(f"Example:\n{tp.sample_test}")
    return "\n".join(lines)


# ── Windowing / truncation helpers ───────────────────────────────


def _default_token_count(text: str) -> int:
    """Rough token estimate: ~4 characters per token."""
    return len(text) // 4


def _truncate_to_tokens(
    text: str,
    max_tokens: int,
    counter: Callable[[str], int],
) -> str:
    """Truncate *text* to fit within *max_tokens*, keeping complete lines."""
    if counter(text) <= max_tokens:
        return text

    lines = text.splitlines(keepends=True)
    result: list[str] = []
    used = 0
    for line in lines:
        line_tokens = counter(line)
        if used + line_tokens > max_tokens:
            break
        result.append(line)
        used += line_tokens

    truncated = "".join(result)
    if truncated != text:
        truncated += "\n# ... (truncated)\n"
    return truncated


def _read_snippet(path: Path, max_lines: int = 50) -> str:
    """Read the first *max_lines* lines of a file."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = content.splitlines(keepends=True)
    return "".join(lines[:max_lines])
