"""C# AST extractor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.parsing.languages.base import LanguageExtractor, _text
from nit.parsing.treesitter import (
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ParameterInfo,
)

if TYPE_CHECKING:
    import tree_sitter


class CSharpExtractor(LanguageExtractor):
    """Extract classes, methods, and using directives from C# source."""

    language = "csharp"

    def extract_functions(self, _root: tree_sitter.Node) -> list[FunctionInfo]:
        # C# has no top-level functions — everything is in classes/structs
        return []

    def extract_classes(self, root: tree_sitter.Node) -> list[ClassInfo]:
        return [
            self._parse_class(child)
            for child in root.children
            if child.type in ("class_declaration", "struct_declaration")
        ]

    def extract_imports(self, root: tree_sitter.Node) -> list[ImportInfo]:
        return [
            self._parse_using(child) for child in root.children if child.type == "using_directive"
        ]

    def _parse_class(self, node: tree_sitter.Node) -> ClassInfo:
        name_node = node.child_by_field_name("name")
        body_node = node.child_by_field_name("body")
        methods = self._extract_methods(body_node) if body_node else []
        return ClassInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            methods=methods,
            bases=[],
            body_text=_text(body_node),
        )

    def _extract_methods(self, body_node: tree_sitter.Node) -> list[FunctionInfo]:
        return [
            self._parse_method(child)
            for child in body_node.children
            if child.type in ("method_declaration", "constructor_declaration")
        ]

    def _parse_method(self, node: tree_sitter.Node) -> FunctionInfo:
        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")
        return FunctionInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            parameters=self._parse_params(params_node),
            return_type=None,
            is_method=True,
            body_text=_text(body_node),
        )

    def _parse_params(self, node: tree_sitter.Node | None) -> list[ParameterInfo]:
        if node is None:
            return []
        return [
            ParameterInfo(
                name=_text(child.child_by_field_name("name")),
                type_annotation=None,
            )
            for child in node.children
            if child.type == "parameter"
        ]

    def _parse_using(self, node: tree_sitter.Node) -> ImportInfo:
        # using_directive: "using" (identifier | scoped_identifier) ";"
        module = ""
        for child in node.children:
            if child.type in ("identifier", "scoped_identifier"):
                module = _text(child)
                break
        return ImportInfo(
            module=module,
            start_line=node.start_point.row + 1,
            is_wildcard=False,
        )
