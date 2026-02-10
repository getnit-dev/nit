"""Java AST extractor."""

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

_JAVA_TYPE_NODES = frozenset(
    {
        "void_type",
        "type_identifier",
        "generic_type",
        "integral_type",
        "boolean_type",
        "floating_point_type",
        "array_type",
        "scoped_type_identifier",
    }
)


class JavaExtractor(LanguageExtractor):
    language = "java"

    def extract_functions(self, root: tree_sitter.Node) -> list[FunctionInfo]:
        # Java has no top-level functions — everything is in classes
        del root
        return []

    def extract_classes(self, root: tree_sitter.Node) -> list[ClassInfo]:
        return [
            self._parse_class(child)
            for child in root.children
            if child.type in ("class_declaration", "interface_declaration")
        ]

    def extract_imports(self, root: tree_sitter.Node) -> list[ImportInfo]:
        return [
            self._parse_import(child)
            for child in root.children
            if child.type == "import_declaration"
        ]

    def _parse_class(self, node: tree_sitter.Node) -> ClassInfo:
        name_node = node.child_by_field_name("name")
        body_node = node.child_by_field_name("body")
        bases = self._extract_bases(node)
        methods = self._extract_methods(body_node)

        return ClassInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            methods=methods,
            bases=bases,
            body_text=_text(body_node),
        )

    def _extract_bases(self, node: tree_sitter.Node) -> list[str]:
        bases: list[str] = []
        for child in node.children:
            if child.type == "superclass":
                bases.extend(_text(sub) for sub in child.children if sub.type == "type_identifier")
            elif child.type == "super_interfaces":
                for sub in child.children:
                    if sub.type == "type_list":
                        bases.extend(
                            _text(iface)
                            for iface in sub.children
                            if iface.type == "type_identifier"
                        )
        return bases

    def _extract_methods(self, body_node: tree_sitter.Node | None) -> list[FunctionInfo]:
        if body_node is None:
            return []
        return [
            self._parse_method(child)
            for child in body_node.children
            if child.type in ("method_declaration", "constructor_declaration")
        ]

    def _parse_method(self, node: tree_sitter.Node) -> FunctionInfo:
        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")

        return_type = next(
            (_text(child) for child in node.children if child.type in _JAVA_TYPE_NODES),
            None,
        )

        return FunctionInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            parameters=self._parse_java_params(params_node),
            return_type=return_type,
            is_method=True,
            body_text=_text(body_node),
        )

    def _parse_java_params(self, node: tree_sitter.Node | None) -> list[ParameterInfo]:
        if node is None:
            return []
        return [
            ParameterInfo(
                name=_text(child.child_by_field_name("name")),
                type_annotation=(
                    _text(child.child_by_field_name("type"))
                    if child.child_by_field_name("type")
                    else None
                ),
            )
            for child in node.children
            if child.type == "formal_parameter"
        ]

    def _parse_import(self, node: tree_sitter.Node) -> ImportInfo:
        is_wildcard = False
        module = ""
        for child in node.children:
            if child.type == "scoped_identifier":
                module = _text(child)
            elif child.type == "asterisk":
                is_wildcard = True
        return ImportInfo(
            module=module,
            start_line=node.start_point.row + 1,
            is_wildcard=is_wildcard,
        )
