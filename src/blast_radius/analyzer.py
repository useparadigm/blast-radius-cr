"""LLM-powered blast radius analysis."""

from __future__ import annotations

import os

from .resolver import FunctionContext


SYSTEM_PROMPT = """\
You are a blast radius analyzer for pull requests. You find how code changes break callers.

IMPORTANT RULES:
- A new default parameter that changes the return value for existing callers IS breaking
- Assume every change is guilty until proven innocent
- Your output goes directly on a GitHub PR as a comment — be concise and scannable
- Output ONLY the report format shown. No preamble, no analysis steps, no "let me think"
- Start your response with the verdict line, nothing else before it"""

ANALYSIS_PROMPT = """\
{context}

---

Analyze the blast radius. Check: return value changes, signature changes, side effects, and per-caller impact.

Output this exact format and nothing else:

**VERDICT: FAIL** (or WARNING or PASS)

### Summary
1-2 sentences.

### Findings

For safe changes, one line:
✅ function_name — no caller impact (reason)

For warnings:
⚠️ **function → caller** | what changed
> Impact: ...
> Check: ...

For breaking changes:
🔴 **function → caller(s)** | what changed
> Why: how this breaks callers
> Evidence: quote the line
> Fix: what to do

### Action items
🚫 [BLOCK] action (only for FAIL)
⚠️ [TODO] action (only for WARNING)"""


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

    The model often outputs Step 1/2/3... analysis before the actual report.
    We find the verdict line and the report structure, and drop everything else.
    """
    lines = text.splitlines()

    # Find the VERDICT line
    verdict_idx = None
    for i, line in enumerate(lines):
        if "VERDICT:" in line.upper() and ("FAIL" in line.upper() or "WARNING" in line.upper() or "PASS" in line.upper()):
            verdict_idx = i
            # Take the LAST verdict line (the one in the actual report, not reasoning)
            # But if the first line is the verdict (from prefill), use that

    if verdict_idx is None:
        return text

    # Find where the actual report starts: verdict followed by ### Summary or ### Findings
    report_start = verdict_idx
    for i in range(verdict_idx, len(lines)):
        if lines[i].strip().startswith("### Summary") or lines[i].strip().startswith("### Findings"):
            # Report starts at the verdict line before this
            for j in range(i - 1, -1, -1):
                if "VERDICT:" in lines[j].upper():
                    report_start = j
                    break
            break

    # Check if there's reasoning before the report (Steps, analysis, etc.)
    has_reasoning = False
    for i in range(report_start):
        line = lines[i].strip()
        if line.startswith("## Step") or line.startswith("**Step") or line.startswith("I'll analyze") or line.startswith("Let me"):
            has_reasoning = True
            break

    if has_reasoning:
        return "\n".join(lines[report_start:])

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
