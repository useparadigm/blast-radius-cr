"""Extract function symbols and call sites from source files using tree-sitter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Parser

from .diff import ChangedHunk, FileChange
from .languages import (
    CALL_NODE_TYPES,
    FUNCTION_NODE_TYPES,
    detect_language,
    get_ts_language,
)


@dataclass
class FunctionSymbol:
    name: str
    file_path: str
    start_line: int  # 1-based
    end_line: int  # 1-based
    body: str = ""
    containing_class: str | None = None
    call_sites: list[str] = field(default_factory=list)  # names of called functions


@dataclass
class ChangedFunction:
    symbol: FunctionSymbol
    hunks: list[ChangedHunk]
    change_type: str = "modified"  # "modified", "deleted", "added"


def extract_functions(source: str, file_path: str, lang: str | None = None) -> list[FunctionSymbol]:
    """Extract all function/method definitions from source code."""
    if lang is None:
        lang = detect_language(file_path)
    if lang is None:
        return []

    ts_lang = get_ts_language(lang)
    parser = Parser(ts_lang)
    tree = parser.parse(source.encode("utf-8"))

    func_types = set(FUNCTION_NODE_TYPES.get(lang, []))
    call_types = set(CALL_NODE_TYPES.get(lang, []))
    functions: list[FunctionSymbol] = []

    def _get_name(node) -> str | None:
        """Extract function name from a function node."""
        for child in node.children:
            if child.type == "name" or child.type == "identifier":
                return child.text.decode("utf-8")
            if child.type == "property_identifier":
                return child.text.decode("utf-8")
        # For arrow functions assigned to variables: look at parent
        if node.type == "arrow_function" and node.parent:
            p = node.parent
            if p.type == "variable_declarator":
                for child in p.children:
                    if child.type in ("identifier", "name"):
                        return child.text.decode("utf-8")
            elif p.type == "pair":
                for child in p.children:
                    if child.type in ("property_identifier", "string"):
                        return child.text.decode("utf-8")
        return None

    def _get_containing_class(node) -> str | None:
        """Walk up to find containing class."""
        current = node.parent
        while current:
            if current.type in ("class_definition", "class_declaration", "class_body"):
                if current.type == "class_body" and current.parent:
                    current = current.parent
                for child in current.children:
                    if child.type in ("name", "identifier", "type_identifier"):
                        return child.text.decode("utf-8")
            current = current.parent
        return None

    def _extract_calls(node, call_types: set[str]) -> list[str]:
        """Extract called function names from a subtree."""
        calls = []
        _walk_calls(node, call_types, calls)
        return calls

    def _walk_calls(node, call_types: set[str], calls: list[str]):
        if node.type in call_types:
            name = _call_name(node)
            if name:
                calls.append(name)
        for child in node.children:
            _walk_calls(child, call_types, calls)

    def _call_name(node) -> str | None:
        """Extract the function name from a call node."""
        # Python: call -> function child
        # JS/TS/Go: call_expression -> function child
        func_node = node.child_by_field_name("function")
        if func_node is None and node.children:
            func_node = node.children[0]
        if func_node is None:
            return None

        if func_node.type in ("identifier", "name"):
            return func_node.text.decode("utf-8")
        # attribute/member access: obj.method → "method"
        if func_node.type in ("attribute", "member_expression"):
            for child in func_node.children:
                if child.type in ("identifier", "property_identifier", "name"):
                    last_name = child.text.decode("utf-8")
            return last_name
        # selector_expression (Go): pkg.Func
        if func_node.type == "selector_expression":
            field = func_node.child_by_field_name("field")
            if field:
                return field.text.decode("utf-8")
        return func_node.text.decode("utf-8")

    def _walk(node):
        if node.type in func_types:
            name = _get_name(node)
            if name:
                start = node.start_point[0] + 1
                end = node.end_point[0] + 1
                body = source[node.start_byte:node.end_byte]
                calls = _extract_calls(node, call_types)
                functions.append(FunctionSymbol(
                    name=name,
                    file_path=file_path,
                    start_line=start,
                    end_line=end,
                    body=body,
                    containing_class=_get_containing_class(node),
                    call_sites=calls,
                ))
        for child in node.children:
            _walk(child)

    _walk(tree.root_node)
    return functions


def identify_changed_functions(
    file_change: FileChange,
    repo_dir: str = ".",
) -> list[ChangedFunction]:
    """Given a FileChange, identify which functions were modified/added/deleted."""
    path = Path(repo_dir) / file_change.path
    lang = detect_language(file_change.path)
    if lang is None:
        return []

    if file_change.status == "deleted":
        # For deleted files, we can't read the current version.
        # The caller should handle this via git show or old version.
        return []

    if not path.exists():
        return []

    source = path.read_text(encoding="utf-8", errors="replace")
    functions = extract_functions(source, file_change.path, lang)

    if file_change.status == "added":
        return [
            ChangedFunction(symbol=f, hunks=file_change.hunks, change_type="added")
            for f in functions
        ]

    changed: list[ChangedFunction] = []
    for func in functions:
        overlapping = [
            h for h in file_change.hunks
            if h.overlaps(func.start_line, func.end_line)
        ]
        if overlapping:
            changed.append(ChangedFunction(
                symbol=func,
                hunks=overlapping,
                change_type="modified",
            ))

    return changed
