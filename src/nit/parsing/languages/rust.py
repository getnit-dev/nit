"""Rust AST extractor."""

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


class RustExtractor(LanguageExtractor):
    language = "rust"

    def extract_functions(self, root: tree_sitter.Node) -> list[FunctionInfo]:
        return [
            self._parse_function(child) for child in root.children if child.type == "function_item"
        ]

    def extract_classes(self, root: tree_sitter.Node) -> list[ClassInfo]:
        results: list[ClassInfo] = []
        structs: dict[str, ClassInfo] = {}
        for child in root.children:
            if child.type == "struct_item":
                info = self._parse_struct(child)
                if info:
                    structs[info.name] = info
                    results.append(info)

        for child in root.children:
            if child.type == "impl_item":
                type_node = child.child_by_field_name("type")
                type_name = _text(type_node)
                body_node = child.child_by_field_name("body")
                if body_node and type_name in structs:
                    for sub in body_node.children:
                        if sub.type == "function_item":
                            func = self._parse_function(sub)
                            func.is_method = True
                            structs[type_name].methods.append(func)

        return results

    def extract_imports(self, root: tree_sitter.Node) -> list[ImportInfo]:
        results: list[ImportInfo] = []
        for child in root.children:
            if child.type == "use_declaration":
                results.extend(self._parse_use(child))
        return results

    def _parse_function(self, node: tree_sitter.Node) -> FunctionInfo:
        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")
        return_type = node.child_by_field_name("return_type")
        is_async = any(
            c.type == "async" or (c.type == "function_modifiers" and "async" in _text(c))
            for c in node.children
        )

        return FunctionInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            parameters=self._parse_rust_params(params_node),
            return_type=_text(return_type) if return_type else None,
            is_async=is_async,
            body_text=_text(body_node),
        )

    def _parse_struct(self, node: tree_sitter.Node) -> ClassInfo | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        body_node = node.child_by_field_name("body")
        return ClassInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            body_text=_text(body_node),
        )

    def _parse_rust_params(self, node: tree_sitter.Node | None) -> list[ParameterInfo]:
        if node is None:
            return []
        params: list[ParameterInfo] = []
        for child in node.children:
            if child.type == "parameter":
                name_node = child.child_by_field_name("pattern")
                type_node = child.child_by_field_name("type")
                params.append(
                    ParameterInfo(
                        name=_text(name_node),
                        type_annotation=_text(type_node) if type_node else None,
                    )
                )
            elif child.type == "self_parameter":
                params.append(ParameterInfo(name=_text(child)))
        return params

    def _parse_use(self, node: tree_sitter.Node) -> list[ImportInfo]:
        results: list[ImportInfo] = []
        for child in node.children:
            if child.type == "scoped_identifier":
                results.append(ImportInfo(module=_text(child), start_line=node.start_point.row + 1))
            elif child.type == "use_as_clause":
                path_node = child.child_by_field_name("path")
                alias_node = child.child_by_field_name("alias")
                results.append(
                    ImportInfo(
                        module=_text(path_node),
                        alias=_text(alias_node) if alias_node else None,
                        start_line=node.start_point.row + 1,
                    )
                )
            elif child.type == "scoped_use_list":
                path = _text(child)
                results.append(ImportInfo(module=path, start_line=node.start_point.row + 1))
            elif child.type == "use_wildcard":
                results.append(
                    ImportInfo(
                        module=_text(child),
                        start_line=node.start_point.row + 1,
                        is_wildcard=True,
                    )
                )
        return results
