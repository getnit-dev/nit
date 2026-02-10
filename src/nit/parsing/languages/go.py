"""Go AST extractor."""

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


class GoExtractor(LanguageExtractor):
    language = "go"

    def extract_functions(self, root: tree_sitter.Node) -> list[FunctionInfo]:
        return [
            self._parse_function(child)
            for child in root.children
            if child.type == "function_declaration"
        ]

    def extract_classes(self, root: tree_sitter.Node) -> list[ClassInfo]:
        results: list[ClassInfo] = []
        for child in root.children:
            if child.type == "type_declaration":
                for sub in child.children:
                    if sub.type == "type_spec":
                        name_node = sub.child_by_field_name("name")
                        type_node = sub.child_by_field_name("type")
                        if type_node and type_node.type == "struct_type":
                            methods = self._find_methods(root, _text(name_node))
                            results.append(
                                ClassInfo(
                                    name=_text(name_node),
                                    start_line=sub.start_point.row + 1,
                                    end_line=sub.end_point.row + 1,
                                    methods=methods,
                                    body_text=_text(type_node),
                                )
                            )
        return results

    def extract_imports(self, root: tree_sitter.Node) -> list[ImportInfo]:
        results: list[ImportInfo] = []
        for child in root.children:
            if child.type == "import_declaration":
                for sub in child.children:
                    if sub.type == "import_spec":
                        results.append(self._parse_import_spec(sub, child))
                    elif sub.type == "import_spec_list":
                        results.extend(
                            self._parse_import_spec(spec, child)
                            for spec in sub.children
                            if spec.type == "import_spec"
                        )
        return results

    def _parse_function(self, node: tree_sitter.Node) -> FunctionInfo:
        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")
        result_node = node.child_by_field_name("result")

        return FunctionInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            parameters=self._parse_go_params(params_node),
            return_type=_text(result_node) if result_node else None,
            body_text=_text(body_node),
        )

    def _find_methods(self, root: tree_sitter.Node, struct_name: str) -> list[FunctionInfo]:
        methods: list[FunctionInfo] = []
        for child in root.children:
            if child.type == "method_declaration":
                receiver = None
                for sub in child.children:
                    if sub.type == "parameter_list":
                        receiver = sub
                        break
                if receiver and struct_name in _text(receiver):
                    name_node = child.child_by_field_name("name")
                    params_nodes = child.children_by_field_name("parameters")
                    body_node = child.child_by_field_name("body")
                    result_node = child.child_by_field_name("result")
                    actual_params = params_nodes[1] if len(params_nodes) > 1 else None
                    methods.append(
                        FunctionInfo(
                            name=_text(name_node),
                            start_line=child.start_point.row + 1,
                            end_line=child.end_point.row + 1,
                            parameters=self._parse_go_params(actual_params),
                            return_type=_text(result_node) if result_node else None,
                            is_method=True,
                            body_text=_text(body_node),
                        )
                    )
        return methods

    def _parse_go_params(self, node: tree_sitter.Node | None) -> list[ParameterInfo]:
        if node is None:
            return []
        params: list[ParameterInfo] = []
        for child in node.children:
            if child.type == "parameter_declaration":
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")
                params.append(
                    ParameterInfo(
                        name=_text(name_node),
                        type_annotation=_text(type_node) if type_node else None,
                    )
                )
        return params

    def _parse_import_spec(self, spec: tree_sitter.Node, parent: tree_sitter.Node) -> ImportInfo:
        path_node = spec.child_by_field_name("path")
        name_node = spec.child_by_field_name("name")
        module = _text(path_node).strip('"') if path_node else ""
        alias = _text(name_node) if name_node else None
        return ImportInfo(
            module=module,
            alias=alias,
            start_line=parent.start_point.row + 1,
        )
