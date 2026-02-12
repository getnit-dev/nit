"""Tests for the C# AST extractor using real tree-sitter parsing."""

from __future__ import annotations

from nit.parsing.languages import extract_from_source, get_extractor
from nit.parsing.languages.csharp import CSharpExtractor
from nit.parsing.treesitter import ClassInfo, FunctionInfo, ImportInfo, ParseResult

# ── Helper ──────────────────────────────────────────────────────────


def _parse(code: str) -> ParseResult:
    """Parse C# source code and return a ParseResult."""
    return extract_from_source(code.encode("utf-8"), "csharp")


# ── Tests: Extractor registration ──────────────────────────────────


def test_get_extractor_returns_csharp() -> None:
    """get_extractor('csharp') returns a CSharpExtractor instance."""
    ext = get_extractor("csharp")
    assert isinstance(ext, CSharpExtractor)


def test_language_property() -> None:
    """CSharpExtractor.language is 'csharp'."""
    ext = CSharpExtractor()
    assert ext.language == "csharp"


# ── Tests: extract_functions (always empty for C#) ──────────────────


def test_extract_functions_returns_empty_list() -> None:
    """C# has no top-level functions; extract_functions always returns []."""
    result = _parse("""\
using System;

class Foo {
    void Bar() {}
}
""")
    assert result.functions == []


def test_extract_functions_empty_source() -> None:
    """Empty source produces empty functions list."""
    result = _parse("")
    assert result.functions == []


# ── Tests: extract_classes ──────────────────────────────────────────


def test_extract_single_class() -> None:
    """Parses a single class declaration."""
    result = _parse("""\
class Calculator {
    int Add(int a, int b) {
        return a + b;
    }
}
""")
    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls.name == "Calculator"
    assert cls.start_line == 1
    assert isinstance(cls, ClassInfo)


def test_extract_multiple_classes() -> None:
    """Parses multiple class declarations."""
    result = _parse("""\
class Foo {}
class Bar {}
class Baz {}
""")
    names = [c.name for c in result.classes]
    assert names == ["Foo", "Bar", "Baz"]


def test_extract_struct_declaration() -> None:
    """Parses struct declarations alongside classes."""
    result = _parse("""\
struct Point {
    int X;
    int Y;
}

class Shape {
    void Draw() {}
}
""")
    names = [c.name for c in result.classes]
    assert "Point" in names
    assert "Shape" in names
    assert len(result.classes) == 2


def test_class_start_and_end_lines() -> None:
    """Class start_line and end_line are 1-indexed."""
    result = _parse("""\
class Alpha {
    void M() {}
}

class Beta {
    void N() {}
}
""")
    alpha = result.classes[0]
    beta = result.classes[1]
    assert alpha.start_line == 1
    assert alpha.end_line == 3
    assert beta.start_line == 5


def test_class_body_text_not_empty() -> None:
    """ClassInfo.body_text is populated for non-empty classes."""
    result = _parse("""\
class Greeter {
    void Hello() {}
}
""")
    cls = result.classes[0]
    assert cls.body_text != ""
    assert "Hello" in cls.body_text


def test_class_bases_always_empty() -> None:
    """CSharpExtractor always sets bases=[] (not parsed)."""
    result = _parse("""\
class Derived {
    void Foo() {}
}
""")
    assert result.classes[0].bases == []


def test_empty_class() -> None:
    """An empty class body produces zero methods."""
    result = _parse("class Empty {}\n")
    assert len(result.classes) == 1
    assert result.classes[0].methods == []


# ── Tests: methods inside classes ───────────────────────────────────


def test_class_methods_extracted() -> None:
    """Methods inside a class are extracted."""
    result = _parse("""\
class Service {
    void Start() {}
    void Stop() {}
}
""")
    cls = result.classes[0]
    method_names = [m.name for m in cls.methods]
    assert "Start" in method_names
    assert "Stop" in method_names
    assert len(cls.methods) == 2


def test_constructor_extracted_as_method() -> None:
    """constructor_declaration nodes are extracted."""
    result = _parse("""\
class Person {
    Person(string name) {}
    void Greet() {}
}
""")
    cls = result.classes[0]
    method_names = [m.name for m in cls.methods]
    assert "Person" in method_names
    assert "Greet" in method_names


def test_method_is_method_flag() -> None:
    """All extracted methods have is_method=True."""
    result = _parse("""\
class Ops {
    int Compute(int x) { return x * 2; }
}
""")
    for method in result.classes[0].methods:
        assert method.is_method is True


def test_method_return_type_is_none() -> None:
    """CSharpExtractor sets return_type=None for all methods."""
    result = _parse("""\
class Math {
    int Add(int a, int b) { return a + b; }
}
""")
    method = result.classes[0].methods[0]
    assert method.return_type is None


def test_method_body_text() -> None:
    """Method body_text is populated."""
    result = _parse("""\
class Calc {
    int Double(int n) { return n * 2; }
}
""")
    method = result.classes[0].methods[0]
    assert isinstance(method, FunctionInfo)
    assert method.body_text != ""
    assert "return" in method.body_text


def test_method_line_numbers() -> None:
    """Method start_line and end_line are accurate."""
    result = _parse("""\
class A {
    void First() {}
    void Second() {
        int x = 1;
    }
}
""")
    methods = result.classes[0].methods
    first = next(m for m in methods if m.name == "First")
    second = next(m for m in methods if m.name == "Second")
    assert first.start_line == 2
    assert second.start_line == 3
    assert second.end_line == 5


# ── Tests: parameter extraction ─────────────────────────────────────


def test_method_with_no_parameters() -> None:
    """A method with no parameters has an empty parameters list."""
    result = _parse("""\
class C {
    void NoArgs() {}
}
""")
    method = result.classes[0].methods[0]
    assert method.parameters == []


def test_method_with_single_parameter() -> None:
    """A method with one parameter extracts it correctly."""
    result = _parse("""\
class C {
    void Act(string name) {}
}
""")
    method = result.classes[0].methods[0]
    assert len(method.parameters) == 1
    assert method.parameters[0].name == "name"


def test_method_with_multiple_parameters() -> None:
    """A method with multiple parameters extracts all of them."""
    result = _parse("""\
class C {
    int Add(int a, int b, int c) { return a + b + c; }
}
""")
    method = result.classes[0].methods[0]
    assert len(method.parameters) == 3
    param_names = [p.name for p in method.parameters]
    assert param_names == ["a", "b", "c"]


def test_parameter_type_annotation_is_none() -> None:
    """CSharpExtractor sets type_annotation=None for parameters."""
    result = _parse("""\
class C {
    void F(int x, string y) {}
}
""")
    for param in result.classes[0].methods[0].parameters:
        assert param.type_annotation is None


def test_constructor_parameters() -> None:
    """Constructor parameters are extracted properly."""
    result = _parse("""\
class Widget {
    Widget(int width, int height) {}
}
""")
    ctor = result.classes[0].methods[0]
    assert len(ctor.parameters) == 2
    names = [p.name for p in ctor.parameters]
    assert names == ["width", "height"]


# ── Tests: extract_imports (using directives) ───────────────────────


def test_single_using_directive() -> None:
    """Parses a single using directive."""
    result = _parse("using System;\n")
    assert len(result.imports) == 1
    imp = result.imports[0]
    assert isinstance(imp, ImportInfo)
    assert imp.module == "System"
    assert imp.is_wildcard is False


def test_multiple_using_directives() -> None:
    """Parses multiple using directives."""
    result = _parse("""\
using System;
using System.Collections.Generic;
using System.Linq;
""")
    assert len(result.imports) == 3
    modules = [i.module for i in result.imports]
    assert "System" in modules
    assert "System.Collections.Generic" in modules
    assert "System.Linq" in modules


def test_using_directive_start_line() -> None:
    """Using directive start_line is 1-indexed."""
    result = _parse("""\
using System;
using System.IO;
""")
    assert result.imports[0].start_line == 1
    assert result.imports[1].start_line == 2


def test_using_is_never_wildcard() -> None:
    """CSharpExtractor always sets is_wildcard=False for using directives."""
    result = _parse("""\
using System;
using System.Collections.Generic;
""")
    for imp in result.imports:
        assert imp.is_wildcard is False


def test_scoped_namespace_in_using() -> None:
    """Deeply nested namespace in using directive is captured fully."""
    result = _parse("using Microsoft.Extensions.DependencyInjection;\n")
    assert result.imports[0].module == "Microsoft.Extensions.DependencyInjection"


def test_no_using_directives() -> None:
    """Source without using directives produces empty imports list."""
    result = _parse("class Foo {}\n")
    assert result.imports == []


# ── Tests: full extract() pipeline ──────────────────────────────────


def test_full_extract_combines_all() -> None:
    """extract() produces functions, classes, and imports together."""
    result = _parse("""\
using System;
using System.Text;

class Logger {
    Logger(string path) {}
    void Log(string message) {}
    void Flush() {}
}

struct Config {
    void Load() {}
}
""")
    assert result.language == "csharp"
    assert result.functions == []
    assert len(result.imports) == 2
    assert len(result.classes) == 2

    logger_cls = next(c for c in result.classes if c.name == "Logger")
    assert len(logger_cls.methods) == 3

    config_cls = next(c for c in result.classes if c.name == "Config")
    assert len(config_cls.methods) == 1


def test_parse_result_has_errors_false_for_valid_code() -> None:
    """Valid C# code produces has_errors=False."""
    result = _parse("""\
using System;

class Hello {
    void World() {}
}
""")
    assert result.has_errors is False
    assert result.error_ranges == []


def test_parse_result_language_is_csharp() -> None:
    """ParseResult.language is always 'csharp'."""
    result = _parse("class X {}\n")
    assert result.language == "csharp"


# ── Tests: edge cases ──────────────────────────────────────────────


def test_class_with_fields_only() -> None:
    """A class with only fields (no methods) produces zero methods."""
    result = _parse("""\
class Record {
    int Id;
    string Name;
}
""")
    cls = result.classes[0]
    assert cls.name == "Record"
    assert cls.methods == []


def test_multiple_structs() -> None:
    """Multiple struct declarations are all extracted."""
    result = _parse("""\
struct Vec2 { }
struct Vec3 { }
""")
    names = [c.name for c in result.classes]
    assert "Vec2" in names
    assert "Vec3" in names


def test_class_and_using_together() -> None:
    """Both using directives and classes in same file parse correctly."""
    result = _parse("""\
using System;

class App {
    void Run() {}
}
""")
    assert len(result.imports) == 1
    assert len(result.classes) == 1
    assert result.imports[0].module == "System"
    assert result.classes[0].name == "App"


def test_method_with_complex_body() -> None:
    """A method with a multi-line body is parsed without errors."""
    result = _parse("""\
class Processor {
    int Process(int input) {
        int result = input * 2;
        if (result > 100) {
            result = 100;
        }
        return result;
    }
}
""")
    assert result.has_errors is False
    method = result.classes[0].methods[0]
    assert method.name == "Process"
    assert len(method.parameters) == 1
    assert "return" in method.body_text
