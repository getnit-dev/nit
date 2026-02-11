"""Language-specific AST extractors.

Each supported language has its own module with an extractor class.
Use get_extractor(), extract_from_source(), or extract_from_file()
to work with them.
"""

from __future__ import annotations

from pathlib import Path

from nit.parsing.languages.base import LanguageExtractor
from nit.parsing.languages.c import CExtractor, CppExtractor
from nit.parsing.languages.csharp import CSharpExtractor
from nit.parsing.languages.go import GoExtractor
from nit.parsing.languages.java import JavaExtractor
from nit.parsing.languages.javascript import (
    JavaScriptExtractor,
    TSXExtractor,
    TypeScriptExtractor,
)
from nit.parsing.languages.python import PythonExtractor
from nit.parsing.languages.rust import RustExtractor
from nit.parsing.treesitter import ParseResult, detect_language

_EXTRACTORS: dict[str, type[LanguageExtractor]] = {
    "python": PythonExtractor,
    "javascript": JavaScriptExtractor,
    "typescript": TypeScriptExtractor,
    "tsx": TSXExtractor,
    "c": CExtractor,
    "cpp": CppExtractor,
    "csharp": CSharpExtractor,
    "java": JavaExtractor,
    "go": GoExtractor,
    "rust": RustExtractor,
}


def get_extractor(language: str) -> LanguageExtractor:
    """Get a language extractor instance for the given language."""
    cls = _EXTRACTORS.get(language)
    if cls is None:
        raise ValueError(f"No extractor for language: {language}")
    return cls()


def extract_from_source(source: bytes, language: str) -> ParseResult:
    """Parse source code and extract all code structures."""
    return get_extractor(language).extract(source)


def extract_from_file(file_path: str) -> ParseResult:
    """Parse a file and extract all code structures.

    Detects language from file extension.
    """
    path = Path(file_path)
    language = detect_language(path)
    if language is None:
        raise ValueError(f"Cannot detect language for: {path}")
    source = path.read_bytes()
    return extract_from_source(source, language)


__all__ = [
    "CExtractor",
    "CSharpExtractor",
    "CppExtractor",
    "GoExtractor",
    "JavaExtractor",
    "JavaScriptExtractor",
    "LanguageExtractor",
    "PythonExtractor",
    "RustExtractor",
    "TSXExtractor",
    "TypeScriptExtractor",
    "extract_from_file",
    "extract_from_source",
    "get_extractor",
]
