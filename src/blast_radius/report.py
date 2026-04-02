"""Output formatting for blast radius analysis."""

from __future__ import annotations

import json

from .resolver import FunctionContext


def _func_ref(func) -> str:
    cls = f"{func.containing_class}." if func.containing_class else ""
    return f"`{cls}{func.name}` ({func.file_path}:{func.start_line})"


def format_context_markdown(contexts: list[FunctionContext]) -> str:
    """Format raw resolution context as markdown (--no-ai mode)."""
    lines = ["# Blast Radius — Resolved Context", ""]

    if not contexts:
        lines.append("No changed functions found.")
        return "\n".join(lines)

    for ctx in contexts:
        f = ctx.function
        lines.append(f"## {_func_ref(f)} [{ctx.change_type}]")
        lines.append("")

        if ctx.change_type == "deleted" and ctx.old_body:
            lines.append("**Deleted body:**")
            lines.append(f"```\n{ctx.old_body}\n```")
            lines.append("")
        elif ctx.old_body and ctx.old_body != f.body:
            lines.append("**Old body → New body changed**")
            lines.append("")

        if ctx.callers:
            lines.append(f"### Callers ({len(ctx.callers)})")
            for c in ctx.callers:
                lines.append(f"- {_func_ref(c)}")
            lines.append("")

        if ctx.callees:
            lines.append(f"### Callees ({len(ctx.callees)})")
            for c in ctx.callees:
                lines.append(f"- {_func_ref(c)}")
            lines.append("")

        if not ctx.callers and not ctx.callees:
            lines.append("_No callers or callees found._")
            lines.append("")

    return "\n".join(lines)


def format_context_json(contexts: list[FunctionContext]) -> str:
    """Format raw resolution context as JSON."""
    data = []
    for ctx in contexts:
        f = ctx.function
        data.append({
            "function": {
                "name": f.name,
                "file": f.file_path,
                "start_line": f.start_line,
                "end_line": f.end_line,
                "containing_class": f.containing_class,
                "call_sites": f.call_sites,
            },
            "change_type": ctx.change_type,
            "old_body": ctx.old_body if ctx.old_body else None,
            "callers": [
                {
                    "name": c.name,
                    "file": c.file_path,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "containing_class": c.containing_class,
                    "body": c.body,
                }
                for c in ctx.callers
            ],
            "callees": [
                {
                    "name": c.name,
                    "file": c.file_path,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "containing_class": c.containing_class,
                    "body": c.body,
                }
                for c in ctx.callees
            ],
        })
    return json.dumps(data, indent=2)
