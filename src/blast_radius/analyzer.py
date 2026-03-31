"""LLM-powered blast radius analysis."""

from __future__ import annotations

import os

from .resolver import FunctionContext


SYSTEM_PROMPT = """\
You are a code reviewer performing blast radius analysis on pull requests.
Your job is to find how code changes affect callers and callees.
Assume every change is guilty until proven innocent.

Output rules:
- Be concise. Developers will read this on a PR — respect their time.
- PASS findings: one line each, no explanation needed.
- WARNING findings: 2-3 lines — what changed, who's affected, what to check.
- FAIL findings: full detail — mechanism, evidence, action. These block merges.
- Skip boilerplate. No "let me analyze...", no restating the code. Go straight to findings."""

ANALYSIS_PROMPT = """\
Analyze the blast radius of the following code changes.

{context}

---

Think through this checklist internally (do NOT write it out):
1. What exactly changed? Old behavior vs new behavior.
2. Return values: did any return value/type change for existing callers? A new default param that changes the return value IS breaking.
3. Signatures: do existing callers still pass correct args?
4. Side effects: DB, API, exceptions, performance changes?
5. Per caller: will it break or behave differently? Quote the specific line.

Then output ONLY the report below. No reasoning steps, no checklist — just the report.

---

Start with exactly one verdict line:

**VERDICT: FAIL** — if any BREAKING findings
**VERDICT: WARNING** — if CAUTION findings but no BREAKING
**VERDICT: PASS** — if all safe

Then:

### Summary
1-2 sentences: what changed and risk level.

### Findings

PASS — list safe changes in one line each, or omit if nothing interesting.

For WARNING findings:
```
⚠️ CAUTION | function → affected | what changed
  Impact: who's affected and how
  Check: what to verify before merging
```

For FAIL findings:
```
🔴 BREAKING | function → affected caller(s) | what changed
  Why: HOW this breaks the caller — be specific
  Evidence: the exact line in the caller that breaks
  Fix: what to do
```

### Action items
Only if there are WARNING or FAIL findings. One line each:
- 🚫 [BLOCK] — must fix before merge
- ⚠️ [TODO] — fix before or after merge
"""


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
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


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
