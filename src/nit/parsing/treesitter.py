"""Tree-sitter wrapper for parsing source files and extracting code structures."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import tree_sitter
import tree_sitter_language_pack as tslp

from nit.utils.cache import FileContentCache, MemoryCache

if TYPE_CHECKING:
    from tree_sitter_language_pack import SupportedLanguage

logger = logging.getLogger(__name__)

# Map file extensions to tree-sitter language names
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".hh": "cpp",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
}

SUPPORTED_LANGUAGES = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "tsx",
        "c",
        "cpp",
        "java",
        "go",
        "rust",
        "csharp",
    }
)


@dataclass
class FunctionInfo:
    """Extracted function/method information."""

    name: str
    start_line: int
    end_line: int
    parameters: list[ParameterInfo] = field(default_factory=list)
    return_type: str | None = None
    decorators: list[str] = field(default_factory=list)
    is_method: bool = False
    is_async: bool = False
    body_text: str = ""


@dataclass
class ParameterInfo:
    """Extracted parameter information."""

    name: str
    type_annotation: str | None = None
    default_value: str | None = None


@dataclass
class ClassInfo:
    """Extracted class/struct information."""

    name: str
    start_line: int
    end_line: int
    methods: list[FunctionInfo] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    body_text: str = ""


@dataclass
class ImportInfo:
    """Extracted import statement information."""

    module: str
    names: list[str] = field(default_factory=list)
    alias: str | None = None
    start_line: int = 0
    is_wildcard: bool = False


@dataclass
class ParseResult:
    """Complete parse result for a source file."""

    language: str
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    has_errors: bool = False
    error_ranges: list[tuple[int, int]] = field(default_factory=list)


# ── Module-level caches ──────────────────────────────────────────
_parser_cache: dict[str, tree_sitter.Parser] = {}
_language_cache: dict[str, tree_sitter.Language] = {}
_file_ast_cache: FileContentCache[tree_sitter.Tree] = FileContentCache(max_size=512)
_code_ast_cache: MemoryCache[tree_sitter.Tree] = MemoryCache(max_size=256)


def detect_language(file_path: str | Path) -> str | None:
    """Detect language from file extension.

    Returns the tree-sitter language name, or None if unsupported.
    """
    ext = Path(file_path).suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


def get_parser(language: str) -> tree_sitter.Parser:
    """Get a (cached) tree-sitter parser for the given language."""
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    cached = _parser_cache.get(language)
    if cached is not None:
        return cached
    parser = tslp.get_parser(cast("SupportedLanguage", language))
    _parser_cache[language] = parser
    return parser


def get_language(language: str) -> tree_sitter.Language:
    """Get a (cached) tree-sitter Language object for the given language."""
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    cached = _language_cache.get(language)
    if cached is not None:
        return cached
    lang = tslp.get_language(cast("SupportedLanguage", language))
    _language_cache[language] = lang
    return lang


def parse_code(source: bytes, language: str) -> tree_sitter.Tree:
    """Parse source code bytes into a tree-sitter AST (cached by content hash)."""
    key = hashlib.sha256(source).hexdigest()[:16] + ":" + language
    cached = _code_ast_cache.get(key)
    if cached is not None:
        return cached
    parser = get_parser(language)
    tree = parser.parse(source)
    _code_ast_cache.put(key, tree)
    return tree


def parse_file(file_path: str | Path) -> tree_sitter.Tree:
    """Parse a source file into a tree-sitter AST (cached by file mtime).

    Raises ValueError if the language cannot be detected.
    """
    path = Path(file_path)
    cached = _file_ast_cache.get(path)
    if cached is not None:
        return cached
    language = detect_language(path)
    if language is None:
        raise ValueError(f"Cannot detect language for: {path}")
    source = path.read_bytes()
    parser = get_parser(language)
    tree = parser.parse(source)
    _file_ast_cache.put(path, tree)
    return tree


def query_ast(
    root: tree_sitter.Node,
    language: str,
    query_string: str,
) -> list[tuple[int, dict[str, list[tree_sitter.Node]]]]:
    """Run a tree-sitter query on an AST node.

    Returns a list of (pattern_index, {capture_name: [nodes]}) tuples.
    """
    lang = get_language(language)
    query = tree_sitter.Query(lang, query_string)
    cursor = tree_sitter.QueryCursor(query)
    return list(cursor.matches(root))


def has_parse_errors(root: tree_sitter.Node) -> bool:
    """Check if the AST contains any parse errors."""
    return root.has_error


def collect_error_ranges(root: tree_sitter.Node) -> list[tuple[int, int]]:
    """Collect line ranges of parse error nodes."""
    errors: list[tuple[int, int]] = []
    _walk_errors(root, errors)
    return errors


def _walk_errors(node: tree_sitter.Node, errors: list[tuple[int, int]]) -> None:
    if node.is_error or node.is_missing:
        errors.append((node.start_point.row + 1, node.end_point.row + 1))
    for child in node.children:
        _walk_errors(child, errors)


def _node_text(node: tree_sitter.Node) -> str:
    """Decode node text from bytes."""
    return node.text.decode("utf-8", errors="replace") if node.text else ""
