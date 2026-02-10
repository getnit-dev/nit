"""Tests for tree-sitter parsing and language-specific extraction."""

import pytest

from nit.parsing.languages import extract_from_source, get_extractor
from nit.parsing.treesitter import (
    SUPPORTED_LANGUAGES,
    detect_language,
    has_parse_errors,
    parse_code,
    query_ast,
)

# ---------------------------------------------------------------------------
# treesitter.py — core wrapper tests
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_python(self) -> None:
        assert detect_language("main.py") == "python"

    def test_javascript(self) -> None:
        assert detect_language("app.js") == "javascript"
        assert detect_language("app.mjs") == "javascript"
        assert detect_language("app.cjs") == "javascript"
        assert detect_language("app.jsx") == "javascript"

    def test_typescript(self) -> None:
        assert detect_language("app.ts") == "typescript"
        assert detect_language("app.mts") == "typescript"
        assert detect_language("app.cts") == "typescript"

    def test_tsx(self) -> None:
        assert detect_language("component.tsx") == "tsx"

    def test_c(self) -> None:
        assert detect_language("main.c") == "c"
        assert detect_language("header.h") == "c"

    def test_cpp(self) -> None:
        assert detect_language("main.cpp") == "cpp"
        assert detect_language("main.cc") == "cpp"
        assert detect_language("main.cxx") == "cpp"
        assert detect_language("header.hpp") == "cpp"

    def test_java(self) -> None:
        assert detect_language("Main.java") == "java"

    def test_go(self) -> None:
        assert detect_language("main.go") == "go"

    def test_rust(self) -> None:
        assert detect_language("lib.rs") == "rust"

    def test_unknown(self) -> None:
        assert detect_language("data.csv") is None
        assert detect_language("Makefile") is None

    def test_case_insensitive(self) -> None:
        assert detect_language("FILE.PY") == "python"
        assert detect_language("Main.JAVA") == "java"


class TestParseCode:
    def test_parse_produces_tree(self) -> None:
        tree = parse_code(b"def hello(): pass", "python")
        assert tree.root_node is not None
        assert tree.root_node.type == "module"

    def test_parse_error_detection(self) -> None:
        tree = parse_code(b"def (broken syntax", "python")
        assert has_parse_errors(tree.root_node)

    def test_parse_valid_code(self) -> None:
        tree = parse_code(b"def hello(): pass", "python")
        assert not has_parse_errors(tree.root_node)

    def test_unsupported_language(self) -> None:
        with pytest.raises(ValueError, match="Unsupported language"):
            parse_code(b"code", "cobol")


class TestQueryAST:
    def test_query_functions(self) -> None:
        tree = parse_code(b"def foo(): pass\ndef bar(): pass", "python")
        matches = query_ast(
            tree.root_node,
            "python",
            "(function_definition name: (identifier) @name)",
        )
        names = [
            node.text.decode()
            for _, captures in matches
            for nodes in captures.values()
            for node in nodes
            if node.text is not None
        ]
        assert names == ["foo", "bar"]


# ---------------------------------------------------------------------------
# Python extractor
# ---------------------------------------------------------------------------


class TestPythonExtractor:
    def test_simple_function(self) -> None:
        result = extract_from_source(
            b"def greet(name: str) -> str:\n    return 'hi'",
            "python",
        )
        assert len(result.functions) == 1
        fn = result.functions[0]
        assert fn.name == "greet"
        assert fn.return_type == "str"
        assert len(fn.parameters) == 1
        assert fn.parameters[0].name == "name"
        assert fn.parameters[0].type_annotation == "str"
        assert not fn.is_method
        assert not fn.is_async

    def test_async_function(self) -> None:
        result = extract_from_source(
            b"async def fetch(url: str) -> bytes:\n    pass",
            "python",
        )
        assert result.functions[0].is_async

    def test_decorated_function(self) -> None:
        result = extract_from_source(
            b"@app.route('/hello')\ndef hello():\n    pass",
            "python",
        )
        assert len(result.functions) == 1
        assert result.functions[0].decorators == ["app.route('/hello')"]

    def test_default_parameter(self) -> None:
        result = extract_from_source(
            b"def greet(name='world'):\n    pass",
            "python",
        )
        param = result.functions[0].parameters[0]
        assert param.name == "name"
        assert param.default_value == "'world'"

    def test_class_with_methods(self) -> None:
        result = extract_from_source(
            b"""
class MyService(Base):
    def get(self, id: int) -> str:
        pass

    async def fetch(self) -> None:
        pass
""",
            "python",
        )
        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls.name == "MyService"
        assert cls.bases == ["Base"]
        assert len(cls.methods) == 2
        assert cls.methods[0].name == "get"
        assert cls.methods[0].is_method
        assert cls.methods[1].name == "fetch"
        assert cls.methods[1].is_async

    def test_multiple_inheritance(self) -> None:
        result = extract_from_source(
            b"class Child(Base, Mixin):\n    pass",
            "python",
        )
        assert result.classes[0].bases == ["Base", "Mixin"]

    def test_import_statement(self) -> None:
        result = extract_from_source(b"import os", "python")
        assert len(result.imports) == 1
        assert result.imports[0].module == "os"

    def test_import_with_alias(self) -> None:
        result = extract_from_source(b"import numpy as np", "python")
        imp = result.imports[0]
        assert imp.module == "numpy"
        assert imp.alias == "np"

    def test_from_import(self) -> None:
        result = extract_from_source(b"from pathlib import Path", "python")
        imp = result.imports[0]
        assert imp.module == "pathlib"
        assert imp.names == ["Path"]

    def test_from_import_multiple(self) -> None:
        result = extract_from_source(
            b"from typing import Any, Optional",
            "python",
        )
        imp = result.imports[0]
        assert imp.module == "typing"
        assert imp.names == ["Any", "Optional"]

    def test_relative_import(self) -> None:
        result = extract_from_source(b"from . import utils", "python")
        assert result.imports[0].module == "."

    def test_no_errors(self) -> None:
        result = extract_from_source(b"x = 1", "python")
        assert not result.has_errors
        assert result.language == "python"

    def test_line_numbers(self) -> None:
        result = extract_from_source(
            b"# comment\ndef foo():\n    pass\n\ndef bar():\n    pass",
            "python",
        )
        assert result.functions[0].start_line == 2
        assert result.functions[1].start_line == 5


# ---------------------------------------------------------------------------
# JavaScript / TypeScript extractor
# ---------------------------------------------------------------------------


class TestJavaScriptExtractor:
    def test_function_declaration(self) -> None:
        result = extract_from_source(
            b"function greet(name) { return 'hi'; }",
            "javascript",
        )
        assert len(result.functions) == 1
        assert result.functions[0].name == "greet"

    def test_arrow_function(self) -> None:
        result = extract_from_source(
            b"const double = (x) => x * 2;",
            "javascript",
        )
        assert len(result.functions) == 1
        assert result.functions[0].name == "double"

    def test_exported_function(self) -> None:
        result = extract_from_source(
            b"export function main() {}",
            "javascript",
        )
        assert len(result.functions) == 1
        assert result.functions[0].name == "main"

    def test_class_with_methods(self) -> None:
        result = extract_from_source(
            b"""
class UserService {
    async getUser(id) {
        return {};
    }
}
""",
            "javascript",
        )
        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls.name == "UserService"
        assert len(cls.methods) == 1
        assert cls.methods[0].name == "getUser"
        assert cls.methods[0].is_async

    def test_named_import(self) -> None:
        result = extract_from_source(
            b"import { useState, useEffect } from 'react';",
            "javascript",
        )
        imp = result.imports[0]
        assert imp.module == "react"
        assert "useState" in imp.names
        assert "useEffect" in imp.names

    def test_default_import(self) -> None:
        result = extract_from_source(
            b"import axios from 'axios';",
            "javascript",
        )
        imp = result.imports[0]
        assert imp.module == "axios"
        assert imp.alias == "axios"

    def test_namespace_import(self) -> None:
        result = extract_from_source(
            b"import * as fs from 'fs';",
            "javascript",
        )
        imp = result.imports[0]
        assert imp.module == "fs"
        assert imp.is_wildcard
        assert imp.alias == "fs"


class TestTypeScriptExtractor:
    def test_typed_function(self) -> None:
        result = extract_from_source(
            b"function greet(name: string): string { return 'hi'; }",
            "typescript",
        )
        fn = result.functions[0]
        assert fn.name == "greet"
        assert fn.return_type == "string"

    def test_typed_parameters(self) -> None:
        result = extract_from_source(
            b"function add(a: number, b: number): number { return a + b; }",
            "typescript",
        )
        fn = result.functions[0]
        assert len(fn.parameters) == 2
        assert fn.parameters[0].name == "a"
        assert fn.parameters[0].type_annotation == "number"

    def test_exported_class(self) -> None:
        result = extract_from_source(
            b"""
export class ApiClient {
    async get(url: string): Promise<Response> {
        return fetch(url);
    }
}
""",
            "typescript",
        )
        assert len(result.classes) == 1
        assert result.classes[0].name == "ApiClient"


# ---------------------------------------------------------------------------
# C extractor
# ---------------------------------------------------------------------------


class TestCExtractor:
    def test_function(self) -> None:
        result = extract_from_source(
            b"int add(int a, int b) { return a + b; }",
            "c",
        )
        fn = result.functions[0]
        assert fn.name == "add"
        assert fn.return_type == "int"
        assert len(fn.parameters) == 2
        assert fn.parameters[0].name == "a"
        assert fn.parameters[0].type_annotation == "int"

    def test_struct(self) -> None:
        result = extract_from_source(
            b"struct Point { int x; int y; };",
            "c",
        )
        assert len(result.classes) == 1
        assert result.classes[0].name == "Point"

    def test_include(self) -> None:
        result = extract_from_source(
            b'#include <stdio.h>\n#include "myheader.h"',
            "c",
        )
        assert len(result.imports) == 2
        assert result.imports[0].module == "stdio.h"
        assert result.imports[1].module == "myheader.h"


# ---------------------------------------------------------------------------
# C++ extractor
# ---------------------------------------------------------------------------


class TestCppExtractor:
    def test_function(self) -> None:
        result = extract_from_source(
            b"int add(int a, int b) { return a + b; }",
            "cpp",
        )
        assert result.functions[0].name == "add"

    def test_class_with_methods(self) -> None:
        result = extract_from_source(
            b"""
class Calculator {
public:
    int add(int a, int b) { return a + b; }
};
""",
            "cpp",
        )
        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls.name == "Calculator"
        assert len(cls.methods) == 1
        assert cls.methods[0].name == "add"

    def test_inheritance(self) -> None:
        result = extract_from_source(
            b"class Derived : public Base { };",
            "cpp",
        )
        assert result.classes[0].bases == ["Base"]

    def test_struct_also_detected(self) -> None:
        result = extract_from_source(
            b"struct Vec2 { float x; float y; };",
            "cpp",
        )
        assert any(c.name == "Vec2" for c in result.classes)


# ---------------------------------------------------------------------------
# Java extractor
# ---------------------------------------------------------------------------


class TestJavaExtractor:
    def test_no_top_level_functions(self) -> None:
        result = extract_from_source(
            b"public class Main { public static void main(String[] args) {} }",
            "java",
        )
        assert len(result.functions) == 0

    def test_class_with_methods(self) -> None:
        result = extract_from_source(
            b"""
public class UserService {
    public String getUser(int id) {
        return "user";
    }
    private void helper() {}
}
""",
            "java",
        )
        cls = result.classes[0]
        assert cls.name == "UserService"
        assert len(cls.methods) == 2
        assert cls.methods[0].name == "getUser"
        assert cls.methods[0].return_type == "String"

    def test_method_parameters(self) -> None:
        result = extract_from_source(
            b"public class Calc { public int add(int a, int b) { return a+b; } }",
            "java",
        )
        method = result.classes[0].methods[0]
        assert len(method.parameters) == 2
        assert method.parameters[0].name == "a"
        assert method.parameters[0].type_annotation == "int"

    def test_imports(self) -> None:
        result = extract_from_source(
            b"import java.util.List;\nimport java.util.Map;",
            "java",
        )
        assert len(result.imports) == 2
        assert result.imports[0].module == "java.util.List"
        assert result.imports[1].module == "java.util.Map"

    def test_inheritance(self) -> None:
        result = extract_from_source(
            b"public class Child extends Parent { }",
            "java",
        )
        assert "Parent" in result.classes[0].bases


# ---------------------------------------------------------------------------
# Go extractor
# ---------------------------------------------------------------------------


class TestGoExtractor:
    def test_function(self) -> None:
        result = extract_from_source(
            b"package main\nfunc Add(a int, b int) int { return a + b }",
            "go",
        )
        fn = result.functions[0]
        assert fn.name == "Add"
        assert fn.return_type == "int"
        assert len(fn.parameters) == 2

    def test_struct(self) -> None:
        result = extract_from_source(
            b"package main\ntype Point struct { X int; Y int }",
            "go",
        )
        assert len(result.classes) == 1
        assert result.classes[0].name == "Point"

    def test_method_attached_to_struct(self) -> None:
        result = extract_from_source(
            b"""package main
type Point struct { X int; Y int }
func (p *Point) String() string { return "" }
""",
            "go",
        )
        assert len(result.classes) == 1
        assert len(result.classes[0].methods) == 1
        assert result.classes[0].methods[0].name == "String"
        assert result.classes[0].methods[0].is_method

    def test_imports(self) -> None:
        result = extract_from_source(
            b'package main\nimport (\n\t"fmt"\n\t"os"\n)',
            "go",
        )
        assert len(result.imports) == 2
        modules = {i.module for i in result.imports}
        assert "fmt" in modules
        assert "os" in modules

    def test_single_import(self) -> None:
        result = extract_from_source(
            b'package main\nimport "fmt"',
            "go",
        )
        assert len(result.imports) == 1
        assert result.imports[0].module == "fmt"


# ---------------------------------------------------------------------------
# Rust extractor
# ---------------------------------------------------------------------------


class TestRustExtractor:
    def test_function(self) -> None:
        result = extract_from_source(
            b"fn add(a: i32, b: i32) -> i32 { a + b }",
            "rust",
        )
        fn = result.functions[0]
        assert fn.name == "add"
        assert fn.return_type == "i32"
        assert len(fn.parameters) == 2
        assert fn.parameters[0].name == "a"
        assert fn.parameters[0].type_annotation == "i32"

    def test_async_function(self) -> None:
        result = extract_from_source(
            b"async fn fetch() -> Result<(), Error> { Ok(()) }",
            "rust",
        )
        assert result.functions[0].is_async

    def test_struct_with_impl(self) -> None:
        result = extract_from_source(
            b"""
pub struct Point { pub x: f64, pub y: f64 }
impl Point {
    pub fn new(x: f64, y: f64) -> Self { Point { x, y } }
    pub fn distance(&self) -> f64 { 0.0 }
}
""",
            "rust",
        )
        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls.name == "Point"
        assert len(cls.methods) == 2
        assert cls.methods[0].name == "new"
        assert cls.methods[1].name == "distance"
        assert cls.methods[1].is_method

    def test_use_import(self) -> None:
        result = extract_from_source(
            b"use std::collections::HashMap;",
            "rust",
        )
        assert len(result.imports) == 1
        assert result.imports[0].module == "std::collections::HashMap"

    def test_use_group_import(self) -> None:
        result = extract_from_source(
            b"use std::io::{self, Read};",
            "rust",
        )
        assert len(result.imports) == 1
        assert "std::io" in result.imports[0].module


# ---------------------------------------------------------------------------
# Cross-language: error handling
# ---------------------------------------------------------------------------


class TestParseErrors:
    def test_python_syntax_error(self) -> None:
        result = extract_from_source(b"def (broken", "python")
        assert result.has_errors

    def test_valid_code_no_errors(self) -> None:
        result = extract_from_source(b"x = 1", "python")
        assert not result.has_errors

    def test_unsupported_language(self) -> None:
        with pytest.raises(ValueError, match="No extractor"):
            get_extractor("cobol")


# ---------------------------------------------------------------------------
# Extractor registry
# ---------------------------------------------------------------------------


class TestExtractorRegistry:
    @pytest.mark.parametrize("lang", list(SUPPORTED_LANGUAGES))
    def test_all_supported_languages_have_extractors(self, lang: str) -> None:
        extractor = get_extractor(lang)
        assert extractor.language == lang
