"""Code parsing and AST extraction."""

from nit.parsing.languages import extract_from_file, extract_from_source, get_extractor
from nit.parsing.treesitter import (
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ParameterInfo,
    ParseResult,
    detect_language,
    parse_code,
    parse_file,
)

__all__ = [
    "ClassInfo",
    "FunctionInfo",
    "ImportInfo",
    "ParameterInfo",
    "ParseResult",
    "detect_language",
    "extract_from_file",
    "extract_from_source",
    "get_extractor",
    "parse_code",
    "parse_file",
]
