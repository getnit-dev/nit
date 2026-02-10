"""C and C++ AST extractors."""

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


class CExtractor(LanguageExtractor):
    language = "c"

    def extract_functions(self, root: tree_sitter.Node) -> list[FunctionInfo]:
        return [
            self._parse_function(child)
            for child in root.children
            if child.type == "function_definition"
        ]

    def extract_classes(self, root: tree_sitter.Node) -> list[ClassInfo]:
        results: list[ClassInfo] = []
        for child in root.children:
            if child.type == "struct_specifier":
                info = self._parse_struct(child)
                if info:
                    results.append(info)
            elif child.type == "type_definition":
                for sub in child.children:
                    if sub.type == "struct_specifier":
                        info = self._parse_struct(sub)
                        if info:
                            results.append(info)
        return results

    def extract_imports(self, root: tree_sitter.Node) -> list[ImportInfo]:
        return [
            self._parse_include(child) for child in root.children if child.type == "preproc_include"
        ]

    def _parse_function(self, node: tree_sitter.Node) -> FunctionInfo:
        return_type = None
        name = ""
        params: list[ParameterInfo] = []
        body_node = None

        for child in node.children:
            if child.type in ("primitive_type", "type_identifier", "sized_type_specifier"):
                return_type = _text(child)
            elif child.type == "function_declarator":
                decl_name = child.child_by_field_name("declarator")
                if decl_name:
                    name = _text(decl_name)
                param_list = child.child_by_field_name("parameters")
                if param_list:
                    params = self._parse_c_params(param_list)
            elif child.type == "compound_statement":
                body_node = child

        return FunctionInfo(
            name=name,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            parameters=params,
            return_type=return_type,
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

    def _parse_c_params(self, node: tree_sitter.Node) -> list[ParameterInfo]:
        params: list[ParameterInfo] = []
        for child in node.children:
            if child.type == "parameter_declaration":
                type_part = child.child_by_field_name("type")
                decl_part = child.child_by_field_name("declarator")
                params.append(
                    ParameterInfo(
                        name=_text(decl_part) if decl_part else "",
                        type_annotation=_text(type_part) if type_part else None,
                    )
                )
        return params

    def _parse_include(self, node: tree_sitter.Node) -> ImportInfo:
        path = ""
        for child in node.children:
            if child.type in ("system_lib_string", "string_literal"):
                path = _text(child).strip('<>"/')
        return ImportInfo(module=path, start_line=node.start_point.row + 1)


class CppExtractor(CExtractor):
    language = "cpp"

    def extract_classes(self, root: tree_sitter.Node) -> list[ClassInfo]:
        results = super().extract_classes(root)
        for child in root.children:
            if child.type == "class_specifier":
                info = self._parse_cpp_class(child)
                if info:
                    results.append(info)
        return results

    def _parse_cpp_class(self, node: tree_sitter.Node) -> ClassInfo | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        body_node = node.child_by_field_name("body")

        bases: list[str] = [
            _text(sub)
            for child in node.children
            if child.type == "base_class_clause"
            for sub in child.children
            if sub.type == "type_identifier"
        ]

        methods: list[FunctionInfo] = []
        if body_node:
            for child in body_node.children:
                if child.type == "function_definition":
                    func = self._parse_function(child)
                    func.is_method = True
                    methods.append(func)
                elif child.type == "declaration":
                    for sub in child.children:
                        if sub.type == "function_declarator":
                            decl_name = sub.child_by_field_name("declarator")
                            if decl_name:
                                methods.append(
                                    FunctionInfo(
                                        name=_text(decl_name),
                                        start_line=child.start_point.row + 1,
                                        end_line=child.end_point.row + 1,
                                        is_method=True,
                                    )
                                )

        return ClassInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            methods=methods,
            bases=bases,
            body_text=_text(body_node),
        )
