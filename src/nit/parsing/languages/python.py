"""Python AST extractor."""

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


class PythonExtractor(LanguageExtractor):
    language = "python"

    def extract_functions(self, root: tree_sitter.Node) -> list[FunctionInfo]:
        return [
            self._parse_function(child)
            for child in root.children
            if child.type in ("function_definition", "decorated_definition")
        ]

    def extract_classes(self, root: tree_sitter.Node) -> list[ClassInfo]:
        results: list[ClassInfo] = []
        for child in root.children:
            node = child
            if child.type == "decorated_definition":
                for sub in child.children:
                    if sub.type == "class_definition":
                        node = sub
                        break
                else:
                    continue
            if node.type == "class_definition":
                results.append(self._parse_class(node))
        return results

    def extract_imports(self, root: tree_sitter.Node) -> list[ImportInfo]:
        results: list[ImportInfo] = []
        for child in root.children:
            if child.type == "import_statement":
                results.append(self._parse_import(child))
            elif child.type == "import_from_statement":
                results.append(self._parse_from_import(child))
        return results

    # -- helpers --

    def _parse_function(self, node: tree_sitter.Node) -> FunctionInfo:
        decorators: list[str] = []
        func_node = node

        if node.type == "decorated_definition":
            for child in node.children:
                if child.type == "decorator":
                    decorators.append(_text(child).lstrip("@").strip())
                elif child.type == "function_definition":
                    func_node = child

        name_node = func_node.child_by_field_name("name")
        params_node = func_node.child_by_field_name("parameters")
        return_node = func_node.child_by_field_name("return_type")
        body_node = func_node.child_by_field_name("body")

        is_async = any(c.type == "async" for c in func_node.children)

        return FunctionInfo(
            name=_text(name_node),
            start_line=func_node.start_point.row + 1,
            end_line=func_node.end_point.row + 1,
            parameters=self._parse_parameters(params_node),
            return_type=_text(return_node) if return_node else None,
            decorators=decorators,
            is_method=False,
            is_async=is_async,
            body_text=_text(body_node),
        )

    def _parse_class(self, node: tree_sitter.Node) -> ClassInfo:
        name_node = node.child_by_field_name("name")
        bases_node = node.child_by_field_name("superclasses")
        body_node = node.child_by_field_name("body")

        bases: list[str] = [
            _text(child)
            for child in (bases_node.children if bases_node else [])
            if child.is_named and child.type != "comment"
        ]

        methods: list[FunctionInfo] = []
        if body_node:
            for child in body_node.children:
                if child.type in ("function_definition", "decorated_definition"):
                    func = self._parse_function(child)
                    func.is_method = True
                    methods.append(func)

        return ClassInfo(
            name=_text(name_node),
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            methods=methods,
            bases=bases,
            body_text=_text(body_node),
        )

    def _parse_parameters(self, node: tree_sitter.Node | None) -> list[ParameterInfo]:
        if node is None:
            return []
        params: list[ParameterInfo] = []
        for child in node.children:
            if child.type in ("identifier",):
                params.append(ParameterInfo(name=_text(child)))
            elif child.type == "typed_parameter":
                name = _text(child.children[0]) if child.children else ""
                type_ann = None
                for sub in child.children:
                    if sub.type == "type":
                        type_ann = _text(sub)
                params.append(ParameterInfo(name=name, type_annotation=type_ann))
            elif child.type == "default_parameter":
                name = _text(child.children[0]) if child.children else ""
                default = _text(child.children[-1]) if len(child.children) > 1 else None
                params.append(ParameterInfo(name=name, default_value=default))
            elif child.type == "typed_default_parameter":
                name = _text(child.children[0]) if child.children else ""
                type_ann = None
                default = None
                for sub in child.children:
                    if sub.type == "type":
                        type_ann = _text(sub)
                    elif sub.type not in ("identifier", ":", "=") and sub == child.children[-1]:
                        default = _text(sub)
                params.append(
                    ParameterInfo(name=name, type_annotation=type_ann, default_value=default)
                )
        return params

    def _parse_import(self, node: tree_sitter.Node) -> ImportInfo:
        names: list[str] = []
        alias = None
        for child in node.children:
            if child.type == "dotted_name":
                names.append(_text(child))
            elif child.type == "aliased_import":
                name_part = child.child_by_field_name("name")
                alias_part = child.child_by_field_name("alias")
                if name_part:
                    names.append(_text(name_part))
                if alias_part:
                    alias = _text(alias_part)
        module = names[0] if names else ""
        return ImportInfo(module=module, alias=alias, start_line=node.start_point.row + 1)

    def _parse_from_import(self, node: tree_sitter.Node) -> ImportInfo:
        module = ""
        names: list[str] = []
        is_wildcard = False
        found_import_keyword = False

        for child in node.children:
            if child.type == "import":
                found_import_keyword = True
            elif child.type in ("dotted_name", "relative_import") and not found_import_keyword:
                module = _text(child)
            elif child.type == "dotted_name" and found_import_keyword:
                names.append(_text(child))
            elif child.type == "wildcard_import":
                is_wildcard = True

        return ImportInfo(
            module=module,
            names=names,
            start_line=node.start_point.row + 1,
            is_wildcard=is_wildcard,
        )
