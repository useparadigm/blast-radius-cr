"""LLM-powered blast radius analysis."""

from __future__ import annotations

import os

from .resolver import FunctionContext


SYSTEM_PROMPT = """\
You are a senior code reviewer performing blast radius analysis. \
You analyze code changes and their impact on callers and callees.

For each changed function, you receive:
- The diff hunks (what changed)
- The function's full body
- All functions that CALL this function (callers) with their bodies
- All functions this function CALLS (callees) with their bodies

Your job is to identify potential issues caused by the changes."""

ANALYSIS_PROMPT = """\
Analyze the blast radius of the following code changes.

{context}

---

For each changed function, classify every finding as:

**BREAKING** — Will cause failures if callers/consumers are not updated:
- Signature changes (args added/removed/reordered)
- Return type/shape changes
- Removed functionality that callers depend on
- Exception/error behavior changes

**CAUTION** — May cause issues, needs verification:
- Behavioral changes (same interface, different semantics)
- Performance changes in hot paths
- New edge cases not handled by callers
- Changed side effects (DB writes, API calls, logging)

**SAFE** — No impact on callers/callees:
- Internal refactors with unchanged interface
- Additive changes (new optional params with defaults)
- Documentation/comment changes
- Formatting changes

Structure your response as:

## Blast Radius Analysis

### Summary
One paragraph: what changed and the overall risk level.

### Findings

For each finding:
```
SEVERITY | Function → Affected | What
  Why: mechanism of impact
  Evidence: specific code reference
  Action: what to do about it
```

### Action Plan
1. [BLOCK MERGE] — must fix before merging
2. [BEFORE MERGE] — should fix, can be separate PR
3. [AFTER MERGE] — monitor or follow-up

If there are no issues, say "No blast radius concerns found." and explain why the changes are safe."""


def build_prompt(contexts: list[FunctionContext]) -> str:
    """Build the analysis prompt from resolved contexts."""
    parts = []
    for ctx in contexts:
        f = ctx.function
        cls = f"{f.containing_class}." if f.containing_class else ""
        parts.append(f"### Changed function: `{cls}{f.name}` ({f.file_path}:{f.start_line}) [{ctx.change_type}]")
        parts.append("")
        parts.append("**Current body:**")
        parts.append(f"```\n{f.body}\n```")
        parts.append("")

        if ctx.callers:
            parts.append(f"**Callers ({len(ctx.callers)}):**")
            for c in ctx.callers:
                ccls = f"{c.containing_class}." if c.containing_class else ""
                parts.append(f"\n`{ccls}{c.name}` ({c.file_path}:{c.start_line}):")
                parts.append(f"```\n{c.body}\n```")
            parts.append("")

        if ctx.callees:
            parts.append(f"**Callees ({len(ctx.callees)}):**")
            for c in ctx.callees:
                ccls = f"{c.containing_class}." if c.containing_class else ""
                parts.append(f"\n`{ccls}{c.name}` ({c.file_path}:{c.start_line}):")
                parts.append(f"```\n{c.body}\n```")
            parts.append("")

        parts.append("---")
        parts.append("")

    return ANALYSIS_PROMPT.format(context="\n".join(parts))


def analyze(contexts: list[FunctionContext], model: str = "claude-sonnet-4-20250514") -> str:
    """Run LLM analysis on resolved contexts. Returns markdown report."""
    if not contexts:
        return "No changed functions found. Nothing to analyze."

    prompt = build_prompt(contexts)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            return _analyze_openai(prompt, model="gpt-4o")
        raise RuntimeError(
            "No API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
        )

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _analyze_openai(prompt: str, model: str = "gpt-4o") -> str:
    import openai
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content
