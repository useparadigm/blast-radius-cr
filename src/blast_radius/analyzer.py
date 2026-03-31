"""LLM-powered blast radius analysis."""

from __future__ import annotations

import os

from .resolver import FunctionContext


SYSTEM_PROMPT = """\
You are a blast radius analyzer. Output goes on a GitHub PR comment — be short and scannable.
A new default parameter that changes return values for existing callers IS breaking.
Never write analysis steps. Only output the final report."""

ANALYSIS_PROMPT = """\
{context}

---

**VERDICT: FAIL** (or WARNING or PASS)

### Summary
1-2 sentences.

### Findings

✅ function — safe (reason)

⚠️ **function → caller** | what changed
> Impact: ... / Check: ...

🔴 **function → caller(s)** | what changed
> Why: ... / Evidence: ... / Fix: ...

### Action items
🚫 [BLOCK] ... / ⚠️ [TODO] ...

---
Fill in the template above. Only include relevant severity levels. No preamble."""


def build_prompt(contexts: list[FunctionContext]) -> str:
    """Build the analysis prompt from resolved contexts."""
    parts = []
    for ctx in contexts:
        f = ctx.function
        cls = f"{f.containing_class}." if f.containing_class else ""
        parts.append(f"### Changed function: `{cls}{f.name}` ({f.file_path}:{f.start_line}) [{ctx.change_type}]")
        parts.append("")

        if ctx.diff_text:
            parts.append("**Diff (what changed — lines prefixed with - are OLD, + are NEW):**")
            parts.append(f"```diff\n{ctx.diff_text}\n```")
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

    # Use extended thinking on models that support it to keep reasoning internal
    kwargs = {}
    if "sonnet" not in model and "haiku" not in model:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": 10000}
        kwargs["max_tokens"] = 16000
    else:
        kwargs["max_tokens"] = 4096

    messages = [{"role": "user", "content": prompt}]
    # Prefill to force the model to start with verdict, not reasoning
    if "thinking" not in kwargs:
        messages.append({"role": "assistant", "content": "**VERDICT:"})

    response = client.messages.create(
        model=model,
        system=SYSTEM_PROMPT,
        messages=messages,
        **kwargs,
    )

    # Extract text output (skip thinking blocks)
    text = ""
    for block in response.content:
        if block.type == "text":
            text = block.text
            break
    if not text:
        text = response.content[-1].text

    # If we prefilled, prepend it
    if "thinking" not in kwargs:
        text = "**VERDICT:" + text

    return _trim_reasoning(text)


def _trim_reasoning(text: str) -> str:
    """Strip reasoning steps, keep only the final report.

    The model writes Step 1/2/3... before the report. Find the last
    VERDICT line that's followed by ### Summary/Findings and keep from there.
    """
    lines = text.splitlines()

    # Find the last VERDICT line that has ### Summary or ### Findings after it
    # This is the real report verdict, not one mentioned in reasoning
    best_start = 0
    for i, line in enumerate(lines):
        if "VERDICT:" in line.upper() and any(
            v in line.upper() for v in ("FAIL", "WARNING", "PASS")
        ):
            # Check if ### Summary or ### Findings follows within 5 lines
            for j in range(i + 1, min(i + 6, len(lines))):
                if lines[j].strip().startswith("###"):
                    best_start = i
                    break

    if best_start > 0:
        return "\n".join(lines[best_start:])

    return text


def parse_verdict(report: str) -> str:
    """Extract verdict from LLM report. Returns PASS, WARNING, or FAIL."""
    for line in report.splitlines()[:5]:
        upper = line.upper()
        if "VERDICT:" in upper:
            if "FAIL" in upper:
                return "FAIL"
            if "WARNING" in upper:
                return "WARNING"
            if "PASS" in upper:
                return "PASS"
    # Fallback: scan for severity markers
    upper_report = report.upper()
    if "BREAKING" in upper_report:
        return "FAIL"
    if "CAUTION" in upper_report:
        return "WARNING"
    return "PASS"


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
