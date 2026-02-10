"""Base class and utilities for language-specific AST extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from nit.parsing.treesitter import (
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ParseResult,
    collect_error_ranges,
    get_parser,
    has_parse_errors,
)

if TYPE_CHECKING:
    import tree_sitter


def _text(node: tree_sitter.Node | None) -> str:
    """Decode node text from bytes, returning empty string for None."""
    if node is None:
        return ""
    return node.text.decode("utf-8", errors="replace") if node.text else ""


class LanguageExtractor(ABC):
    """Base class for language-specific AST extractors."""

    @property
    @abstractmethod
    def language(self) -> str:
        """Tree-sitter language name."""

    def extract(self, source: bytes) -> ParseResult:
        """Parse source and extract all code structures."""
        parser = get_parser(self.language)
        tree = parser.parse(source)
        root = tree.root_node

        return ParseResult(
            language=self.language,
            functions=self.extract_functions(root),
            classes=self.extract_classes(root),
            imports=self.extract_imports(root),
            has_errors=has_parse_errors(root),
            error_ranges=collect_error_ranges(root),
        )

    @abstractmethod
    def extract_functions(self, root: tree_sitter.Node) -> list[FunctionInfo]:
        """Extract top-level function definitions."""

    @abstractmethod
    def extract_classes(self, root: tree_sitter.Node) -> list[ClassInfo]:
        """Extract class/struct definitions with their methods."""

    @abstractmethod
    def extract_imports(self, root: tree_sitter.Node) -> list[ImportInfo]:
        """Extract import/include statements."""
