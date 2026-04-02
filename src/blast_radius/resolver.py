"""Resolve callers and callees for changed functions using grep + tree-sitter."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .languages import DEF_PATTERNS, EXTENSION_MAP, detect_language
from .symbols import FunctionSymbol, extract_functions

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".eggs", "vendor", ".next", ".nuxt",
}

IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".o", ".a", ".dylib",
    ".min.js", ".map", ".lock",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2",
}


@dataclass
class FunctionContext:
    """Full context for a changed function: its callers and callees."""
    function: FunctionSymbol
    callers: list[FunctionSymbol] = field(default_factory=list)
    callees: list[FunctionSymbol] = field(default_factory=list)
    change_type: str = "modified"
    diff_text: str = ""  # raw diff for this file
    old_body: str = ""  # old version of function body (before change)


def _should_skip(path: str) -> bool:
    parts = Path(path).parts
    for part in parts:
        if part in IGNORE_DIRS:
            return True
    if Path(path).suffix in IGNORE_EXTENSIONS:
        return True
    return False


def _load_gitignore_patterns(repo_dir: str) -> list[str]:
    gitignore = Path(repo_dir) / ".gitignore"
    if not gitignore.exists():
        return []
    patterns = []
    for line in gitignore.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _matches_gitignore(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(Path(path).name, pat):
            return True
        if pat.endswith("/") and any(part == pat.rstrip("/") for part in Path(path).parts):
            return True
    return False


def grep_for_callers(
    func_name: str,
    repo_dir: str,
    exclude_file: str | None = None,
    fuel: int = 15,
) -> list[dict]:
    """Grep the repo for call sites of func_name. Returns list of {file, line, text}."""
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "--include=*.js", "--include=*.ts",
             "--include=*.tsx", "--include=*.go", "--include=*.jsx",
             f"{func_name}(", repo_dir],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    gitignore_patterns = _load_gitignore_patterns(repo_dir)
    hits: list[dict] = []

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # Format: /path/to/file:123:code
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        file_path = parts[0]
        try:
            line_no = int(parts[1])
        except ValueError:
            continue
        text = parts[2]

        # Make path relative to repo_dir
        rel_path = os.path.relpath(file_path, repo_dir)

        if _should_skip(rel_path):
            continue
        if _matches_gitignore(rel_path, gitignore_patterns):
            continue
        if exclude_file and rel_path == exclude_file:
            # Don't exclude same file entirely — the function might be called
            # from a different function in the same file
            pass

        # Basic filtering: skip comments and strings (heuristic)
        stripped = text.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        # Skip import lines
        if stripped.startswith("import ") or stripped.startswith("from "):
            continue
        # Skip function definitions (we want calls, not defs)
        if re.match(rf"^\s*(async\s+)?def\s+{re.escape(func_name)}\s*\(", stripped):
            continue
        if re.match(rf"^\s*function\s+{re.escape(func_name)}\s*\(", stripped):
            continue
        if re.match(rf"^\s*func\s+.*{re.escape(func_name)}\s*\(", stripped):
            continue

        hits.append({"file": rel_path, "line": line_no, "text": text})

        if len(hits) >= fuel:
            break

    return hits


def grep_for_definition(
    func_name: str,
    lang: str,
    repo_dir: str,
) -> dict | None:
    """Grep for the definition of a function. Returns {file, line} or None."""
    pattern = DEF_PATTERNS.get(lang)
    if not pattern:
        return None

    regex = pattern.format(name=re.escape(func_name))
    exts = [ext for ext, l in EXTENSION_MAP.items() if l == lang]
    includes = [f"--include=*{ext}" for ext in exts]

    try:
        result = subprocess.run(
            ["grep", "-rn", "-E", *includes, regex, repo_dir],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    for line in result.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        rel_path = os.path.relpath(parts[0], repo_dir)
        if _should_skip(rel_path):
            continue
        try:
            return {"file": rel_path, "line": int(parts[1])}
        except ValueError:
            continue

    return None


def _find_containing_function(
    file_path: str,
    line_no: int,
    repo_dir: str,
    _cache: dict | None = None,
) -> FunctionSymbol | None:
    """Find the function that contains a given line in a file."""
    if _cache is None:
        _cache = {}

    abs_path = os.path.join(repo_dir, file_path)
    if file_path not in _cache:
        try:
            source = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return None
        lang = detect_language(file_path)
        if lang is None:
            return None
        _cache[file_path] = extract_functions(source, file_path, lang)

    functions = _cache[file_path]
    # Find the innermost function containing this line
    best: FunctionSymbol | None = None
    for func in functions:
        if func.start_line <= line_no <= func.end_line:
            if best is None or (func.end_line - func.start_line) < (best.end_line - best.start_line):
                best = func
    return best


def resolve_context(
    func: FunctionSymbol,
    repo_dir: str,
    change_type: str = "modified",
    fuel: int = 15,
) -> FunctionContext:
    """Resolve callers and callees for a function."""
    ctx = FunctionContext(function=func, change_type=change_type)
    file_cache: dict[str, list[FunctionSymbol]] = {}

    # --- Find callers ---
    hits = grep_for_callers(func.name, repo_dir, exclude_file=None, fuel=fuel * 2)
    seen_callers: set[tuple[str, str]] = set()

    for hit in hits:
        caller = _find_containing_function(hit["file"], hit["line"], repo_dir, file_cache)
        if caller is None:
            continue
        # Skip self-references
        if caller.file_path == func.file_path and caller.name == func.name:
            continue
        key = (caller.file_path, caller.name)
        if key in seen_callers:
            continue
        seen_callers.add(key)
        ctx.callers.append(caller)
        if len(ctx.callers) >= fuel:
            break

    # --- Find callees (skip for deleted functions — irrelevant) ---
    if change_type == "deleted":
        return ctx
    lang = detect_language(func.file_path)
    if lang and func.call_sites:
        seen_callees: set[str] = set()
        for callee_name in func.call_sites:
            if callee_name in seen_callees:
                continue
            seen_callees.add(callee_name)

            # Skip builtins / very common names
            if callee_name in ("print", "len", "str", "int", "float", "bool",
                               "list", "dict", "set", "tuple", "range", "type",
                               "isinstance", "issubclass", "super", "getattr",
                               "setattr", "hasattr", "open", "map", "filter",
                               "sorted", "reversed", "enumerate", "zip",
                               "console", "require", "import", "fmt"):
                continue

            defn = grep_for_definition(callee_name, lang, repo_dir)
            if defn is None:
                continue

            callee_func = _find_containing_function(
                defn["file"], defn["line"], repo_dir, file_cache
            )
            if callee_func and callee_func.name == callee_name:
                ctx.callees.append(callee_func)

    return ctx
