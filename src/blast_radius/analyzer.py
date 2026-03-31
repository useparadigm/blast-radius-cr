"""LLM-powered blast radius analysis."""

from __future__ import annotations

import os

from .resolver import FunctionContext


SYSTEM_PROMPT = """\
You are a paranoid senior code reviewer performing blast radius analysis.
Your job is to find ways that code changes WILL break callers and callees.
You are not here to be nice. You are here to prevent production incidents.
Assume every change is guilty until proven innocent."""

ANALYSIS_PROMPT = """\
Analyze the blast radius of the following code changes.

{context}

---

You MUST work through the following checklist step by step. Do NOT skip steps.
Think hard about each one. Write your reasoning for each step.

## Step 1: What exactly changed?

For each changed function, describe precisely:
- What did the old version do? (infer from context, callers, function name)
- What does the new version do?
- What is DIFFERENT between old and new behavior?

## Step 2: Return value analysis

For each changed function, answer:
- Did the return VALUE change for any input? (e.g. None → "", 0 → False, list → tuple)
- Did the return TYPE change? (e.g. Optional[str] → str, int → float)
- For each caller: what does it do with the return value? Will it still work?
- CRITICAL: A new default parameter that changes the return value for EXISTING callers
  is BREAKING, not safe. Existing callers don't pass the new param, so they get
  the new default, which changes what they receive back.

## Step 3: Argument/signature analysis

For each changed function, answer:
- Were args added, removed, renamed, or reordered?
- If a new arg was added with a default: does the default preserve OLD behavior exactly?
  Or does it change behavior for existing callers who don't pass it?
- Could any caller be passing positional args that now map to wrong parameters?

## Step 4: Side effect analysis

For each changed function, answer:
- Did any side effects change? (DB writes, API calls, logging, file I/O, caching)
- Does it now raise different exceptions?
- Does it now silently swallow errors it used to raise?
- Performance: could this be called in a hot path? Did complexity change?

## Step 5: Caller-by-caller impact

For EACH caller provided, answer:
- Does this caller check the return value? How? (is None, == "", truthiness, type check)
- Does this caller pass all required args correctly?
- Will this caller's behavior change as a result of the function change?
- Be specific: quote the line in the caller that will break or change.

## Step 6: Classify findings

Now classify each finding:

**BREAKING** — Will cause failures or silently wrong behavior:
- Return value changes for existing callers (even with "optional" new params)
- Return type changes (None → "", None → 0, etc.)
- Callers that check `is None` when function now returns `""`
- Callers that use truthiness checks when falsy values changed
- Signature changes that break positional arg mapping
- Removed or renamed functionality
- Changed exception behavior

**CAUTION** — May cause issues, needs verification:
- Behavioral changes where caller impact is unclear
- Performance changes in potentially hot paths
- New edge cases
- Changed side effects

**SAFE** — Only if you can PROVE no caller is affected:
- Pure internal refactors with identical input→output mapping
- Formatting/comment/docstring only changes
- New code paths that existing callers cannot reach

## Step 7: Verdict

Based on your findings, output your verdict.

IMPORTANT: Start your final report with exactly one of:
**VERDICT: FAIL** — if any BREAKING findings
**VERDICT: WARNING** — if CAUTION findings but no BREAKING
**VERDICT: PASS** — ONLY if you can prove all changes are safe for all callers

Then write the report:

## Blast Radius Analysis

### Summary
What changed and the risk level.

### Findings

For each finding:
```
SEVERITY | Function → Affected caller(s) | What changed
  Why: the mechanism — HOW does this break the caller? Be specific.
  Evidence: quote the exact line in the caller that breaks
  Action: what to do about it
```

### Action Plan
1. [BLOCK MERGE] — must fix before merging
2. [BEFORE MERGE] — should fix, can be separate PR
3. [AFTER MERGE] — monitor or follow-up"""


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
