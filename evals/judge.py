"""LLM judge that evaluates whether blast-radius caught the expected findings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import anthropic


JUDGE_PROMPT = """\
You are evaluating the output of a blast-radius analysis tool.

## The scenario

A synthetic breaking change was injected into the `{repo}` repository:

**Changed function:** `{changed_function}` in `{changed_file}`
**Breaking change pattern:** {breaking_pattern}
**Description:** {description}
**Expected verdict:** {expected_verdict}

## The blast-radius output to evaluate

```
{blast_radius_output}
```

## Evaluation criteria

For each criterion below, answer YES or NO followed by a brief explanation (1 sentence).

{criteria_list}

## Additional checks

- VERDICT_MATCH: Does the blast-radius verdict match or exceed the expected severity?
  (Expected: {expected_verdict}. FAIL > WARNING > PASS. If expected is WARNING and actual is FAIL, that's a match.)

## Output format

Respond with ONLY a JSON object (no markdown, no code fences):
{{
  "criteria": {{
    "criterion_1": {{"pass": true/false, "reason": "..."}},
    "criterion_2": {{"pass": true/false, "reason": "..."}},
    ...
  }},
  "verdict_match": {{"pass": true/false, "reason": "..."}},
  "overall_pass": true/false,
  "summary": "1-sentence overall assessment"
}}

"overall_pass" is true only if ALL criteria pass AND verdict_match passes."""


@dataclass
class JudgeResult:
    case_id: str
    overall_pass: bool
    criteria_results: dict
    verdict_match: bool
    summary: str
    raw_response: str = ""


SEVERITY_ORDER = {"PASS": 0, "WARNING": 1, "FAIL": 2}


def judge_case(case: dict, blast_radius_output: str, actual_verdict: str) -> JudgeResult:
    """Use LLM to evaluate whether blast-radius caught the expected findings."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY required for judge")

    # Build criteria list
    criteria_list = "\n".join(
        f"- CRITERION_{i+1}: {c}"
        for i, c in enumerate(case["judge_criteria"])
    )

    prompt = JUDGE_PROMPT.format(
        repo=case["repo"],
        changed_function=case["changed_function"],
        changed_file=case["changed_file"],
        breaking_pattern=case["breaking_pattern"],
        description=case["description"],
        expected_verdict=case["expected_verdict"],
        blast_radius_output=blast_radius_output or "(empty output)",
        criteria_list=criteria_list,
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # Parse JSON from response (handle potential markdown fences)
    json_str = raw
    if "```" in json_str:
        json_str = json_str.split("```")[1]
        if json_str.startswith("json"):
            json_str = json_str[4:]
        json_str = json_str.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return JudgeResult(
            case_id=case["id"],
            overall_pass=False,
            criteria_results={},
            verdict_match=False,
            summary=f"Failed to parse judge response: {raw[:200]}",
            raw_response=raw,
        )

    # Structural verdict check (doesn't need LLM)
    expected_sev = SEVERITY_ORDER.get(case["expected_verdict"], 0)
    actual_sev = SEVERITY_ORDER.get(actual_verdict, -1)
    if case["expected_verdict"] == "PASS":
        # For PASS cases: actual must be PASS (or at most WARNING)
        structural_verdict_match = actual_sev <= SEVERITY_ORDER["WARNING"]
    else:
        # For FAIL/WARNING cases: actual must meet or exceed expected severity
        structural_verdict_match = actual_sev >= expected_sev

    return JudgeResult(
        case_id=case["id"],
        overall_pass=data.get("overall_pass", False),
        criteria_results=data.get("criteria", {}),
        verdict_match=structural_verdict_match and data.get("verdict_match", {}).get("pass", False),
        summary=data.get("summary", ""),
        raw_response=raw,
    )
