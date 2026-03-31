"""Language detection and tree-sitter grammar configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
}

# Tree-sitter node types for function definitions per language
FUNCTION_NODE_TYPES: dict[str, list[str]] = {
    "python": ["function_definition"],
    "javascript": ["function_declaration", "method_definition", "arrow_function"],
    "typescript": ["function_declaration", "method_definition", "arrow_function"],
    "tsx": ["function_declaration", "method_definition", "arrow_function"],
    "go": ["function_declaration", "method_declaration"],
}

# Tree-sitter node types for call expressions per language
CALL_NODE_TYPES: dict[str, list[str]] = {
    "python": ["call"],
    "javascript": ["call_expression"],
    "typescript": ["call_expression"],
    "tsx": ["call_expression"],
    "go": ["call_expression"],
}

# Patterns to grep for function definitions per language
DEF_PATTERNS: dict[str, str] = {
    "python": r"^\s*(async\s+)?def\s+{name}\s*\(",
    "javascript": r"(function\s+{name}\s*\(|{name}\s*[:=]\s*(async\s+)?\(|{name}\s*[:=]\s*(async\s+)?function)",
    "typescript": r"(function\s+{name}\s*[\(<]|{name}\s*[:=]\s*(async\s+)?\(|{name}\s*[:=]\s*(async\s+)?function)",
    "tsx": r"(function\s+{name}\s*[\(<]|{name}\s*[:=]\s*(async\s+)?\(|{name}\s*[:=]\s*(async\s+)?function)",
    "go": r"func\s+(\([^)]*\)\s+)?{name}\s*\(",
}


@dataclass
class LanguageConfig:
    name: str
    extensions: list[str]
    function_nodes: list[str]
    call_nodes: list[str]
    def_pattern: str


def get_language_config(lang: str) -> LanguageConfig | None:
    exts = [ext for ext, l in EXTENSION_MAP.items() if l == lang]
    if not exts:
        return None
    return LanguageConfig(
        name=lang,
        extensions=exts,
        function_nodes=FUNCTION_NODE_TYPES.get(lang, []),
        call_nodes=CALL_NODE_TYPES.get(lang, []),
        def_pattern=DEF_PATTERNS.get(lang, ""),
    )


def detect_language(path: str) -> str | None:
    return EXTENSION_MAP.get(Path(path).suffix)


def get_ts_language(lang: str):
    """Load tree-sitter Language object for a given language name."""
    import tree_sitter as ts

    if lang == "python":
        import tree_sitter_python as tsp
        return ts.Language(tsp.language())
    elif lang == "javascript":
        import tree_sitter_javascript as tsjs
        return ts.Language(tsjs.language())
    elif lang in ("typescript", "tsx"):
        import tree_sitter_typescript as tsts
        if lang == "tsx":
            return ts.Language(tsts.language_tsx())
        return ts.Language(tsts.language_typescript())
    elif lang == "go":
        import tree_sitter_go as tsgo
        return ts.Language(tsgo.language())
    else:
        raise ValueError(f"Unsupported language: {lang}")
