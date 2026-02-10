"""JavaScript / TypeScript / TSX AST extractors."""

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


class JavaScriptExtractor(LanguageExtractor):
    language = "javascript"

    def extract_functions(self, root: tree_sitter.Node) -> list[FunctionInfo]:
        results: list[FunctionInfo] = []
        for child in root.children:
            if child.type == "function_declaration":
                results.append(self._parse_function_decl(child))
            elif child.type == "export_statement":
                for sub in child.children:
                    if sub.type == "function_declaration":
                        results.append(self._parse_function_decl(sub))
                    elif sub.type == "lexical_declaration":
                        results.extend(self._extract_arrow_functions(sub))
            elif child.type == "lexical_declaration":
                results.extend(self._extract_arrow_functions(child))
        return results

    def extract_classes(self, root: tree_sitter.Node) -> list[ClassInfo]:
        results: list[ClassInfo] = []
        for child in root.children:
            node = child
            if child.type == "export_statement":
                for sub in child.children:
                    if sub.type == "class_declaration":
                        node = sub
                        break
                else:
                    continue
            if node.type == "class_declaration":
                results.append(self._parse_class(node))
        return results

    def extract_imports(self, root: tree_sitter.Node) -> list[ImportInfo]:
        return [
            self._parse_import(child) for child in root.children if child.type == "import_statement"
        ]

    # -- helpers --

    def _parse_function_decl(self, node: tree_sitter.Node) -> FunctionInfo:
        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")
        return_type = self._get_return_type(node)
        is_async = any(c.type == "async" for c in node.children)

        return FunctionInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            parameters=self._parse_params(params_node),
            return_type=return_type,
            is_async=is_async,
            body_text=_text(body_node),
        )

    def _extract_arrow_functions(self, node: tree_sitter.Node) -> list[FunctionInfo]:
        results: list[FunctionInfo] = []
        for child in node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")
                if value_node and value_node.type == "arrow_function":
                    params_node = value_node.child_by_field_name("parameters")
                    body_node = value_node.child_by_field_name("body")
                    return_type = self._get_return_type(value_node)
                    results.append(
                        FunctionInfo(
                            name=_text(name_node),
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            parameters=self._parse_params(params_node),
                            return_type=return_type,
                            body_text=_text(body_node),
                        )
                    )
        return results

    def _parse_class(self, node: tree_sitter.Node) -> ClassInfo:
        name_node = node.child_by_field_name("name")
        body_node = node.child_by_field_name("body")

        bases: list[str] = [
            _text(sub)
            for child in node.children
            if child.type == "class_heritage"
            for sub in child.children
            if sub.type in ("identifier", "member_expression")
        ]

        methods: list[FunctionInfo] = []
        if body_node:
            methods = [
                self._parse_method(child)
                for child in body_node.children
                if child.type == "method_definition"
            ]

        return ClassInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            methods=methods,
            bases=bases,
            body_text=_text(body_node),
        )

    def _parse_method(self, node: tree_sitter.Node) -> FunctionInfo:
        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")
        return_type = self._get_return_type(node)
        is_async = any(c.type == "async" for c in node.children)

        return FunctionInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            parameters=self._parse_params(params_node),
            return_type=return_type,
            is_method=True,
            is_async=is_async,
            body_text=_text(body_node),
        )

    def _parse_params(self, node: tree_sitter.Node | None) -> list[ParameterInfo]:
        if node is None:
            return []
        params: list[ParameterInfo] = []
        for child in node.children:
            if child.type == "identifier":
                params.append(ParameterInfo(name=_text(child)))
            elif child.type == "required_parameter":
                name = _text(child.child_by_field_name("pattern") or child.children[0])
                type_ann = self._get_type_annotation(child)
                params.append(ParameterInfo(name=name, type_annotation=type_ann))
            elif child.type == "optional_parameter":
                name = _text(child.child_by_field_name("pattern") or child.children[0])
                type_ann = self._get_type_annotation(child)
                default = _text(child.child_by_field_name("value"))
                params.append(
                    ParameterInfo(
                        name=name, type_annotation=type_ann, default_value=default or None
                    )
                )
        return params

    def _get_type_annotation(self, node: tree_sitter.Node) -> str | None:
        for child in node.children:
            if child.type == "type_annotation":
                for sub in child.children:
                    if sub.type != ":":
                        return _text(sub)
        return None

    def _get_return_type(self, node: tree_sitter.Node) -> str | None:
        for child in node.children:
            if child.type in ("return_type", "type_annotation"):
                for sub in child.children:
                    if sub.type != ":":
                        return _text(sub)
        return None

    def _parse_import(self, node: tree_sitter.Node) -> ImportInfo:
        source = ""
        names: list[str] = []
        alias = None
        is_wildcard = False

        for child in node.children:
            if child.type == "string":
                source = _text(child).strip("'\"")
            elif child.type == "import_clause":
                for sub in child.children:
                    if sub.type == "identifier":
                        alias = _text(sub)
                    elif sub.type == "named_imports":
                        for spec in sub.children:
                            if spec.type == "import_specifier":
                                name_node = spec.child_by_field_name("name")
                                if name_node:
                                    names.append(_text(name_node))
                    elif sub.type == "namespace_import":
                        is_wildcard = True
                        for ns_child in sub.children:
                            if ns_child.type == "identifier":
                                alias = _text(ns_child)

        return ImportInfo(
            module=source,
            names=names,
            alias=alias,
            start_line=node.start_point.row + 1,
            is_wildcard=is_wildcard,
        )


class TypeScriptExtractor(JavaScriptExtractor):
    language = "typescript"


class TSXExtractor(JavaScriptExtractor):
    language = "tsx"
