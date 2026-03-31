#!/usr/bin/env python3
"""Run the full blast-radius eval pipeline.

Usage:
    python evals/run_evals.py                          # full run with LLM judge
    python evals/run_evals.py --no-judge               # just run blast-radius, skip judge
    python evals/run_evals.py --case click-echo-nl-default  # run single case
    python evals/run_evals.py --no-ai                  # deterministic only (no LLM analysis)
    python evals/run_evals.py --output results.json    # save structured results
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import click
import yaml

# Add parent to path so we can import blast_radius
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from runner import CaseResult, run_case
from judge import JudgeResult, judge_case


EVALS_DIR = Path(__file__).parent


def load_cases(case_filter: str | None = None) -> list[dict]:
    """Load eval cases from cases.yaml."""
    with open(EVALS_DIR / "cases.yaml") as f:
        data = yaml.safe_load(f)

    cases = data["cases"]
    if case_filter:
        cases = [c for c in cases if c["id"] == case_filter]
        if not cases:
            raise ValueError(f"No case found with id: {case_filter}")

    return cases


def format_report(results: list[dict]) -> str:
    """Generate markdown report from results."""
    lines = ["# Blast Radius Eval Results", ""]

    passed = sum(1 for r in results if r.get("judge", {}).get("overall_pass", False))
    total = len(results)
    lines.append(f"**Score: {passed}/{total} cases passed**")
    lines.append("")

    for r in results:
        case = r["case"]
        run = r["run"]
        judge = r.get("judge", {})

        # Status icon
        if judge.get("overall_pass"):
            icon = "PASS"
        elif run.get("verdict") in ("FAIL", "WARNING"):
            icon = "PARTIAL"
        else:
            icon = "FAIL"

        lines.append(f"## [{icon}] {case['id']}")
        lines.append("")
        lines.append(f"**Repo:** {case['repo']} | **Pattern:** {case['breaking_pattern']}")
        lines.append(f"**Expected verdict:** {case['expected_verdict']} | **Actual verdict:** {run.get('verdict', 'N/A')}")
        lines.append("")

        # Criteria results
        criteria = judge.get("criteria_results", {})
        if criteria:
            lines.append("| Criterion | Result | Reason |")
            lines.append("|-----------|--------|--------|")
            for name, result in criteria.items():
                status = "PASS" if result.get("pass") else "FAIL"
                reason = result.get("reason", "")
                lines.append(f"| {name} | {status} | {reason} |")
            lines.append("")

        if judge.get("summary"):
            lines.append(f"**Judge summary:** {judge['summary']}")
            lines.append("")

        # Show first 20 lines of blast-radius output
        output = run.get("output", "")
        if output:
            output_lines = output.strip().splitlines()[:20]
            lines.append("<details><summary>Blast radius output (first 20 lines)</summary>")
            lines.append("")
            lines.append("```")
            lines.extend(output_lines)
            lines.append("```")
            lines.append("</details>")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


@click.command()
@click.option("--case", "case_filter", default=None, help="Run only this case ID")
@click.option("--no-judge", is_flag=True, help="Skip LLM judge (just run blast-radius)")
@click.option("--no-ai", is_flag=True, help="Run blast-radius with --no-ai (deterministic only)")
@click.option("--model", default="claude-sonnet-4-20250514", help="Model for blast-radius analysis")
@click.option("--output", "output_file", default=None, help="Write JSON results to file")
@click.option("--report", "report_file", default=None, help="Write markdown report to file")
@click.option("--keep-repos", is_flag=True, help="Don't delete cloned repos after run")
def main(case_filter, no_judge, no_ai, model, output_file, report_file, keep_repos):
    """Run blast-radius eval pipeline."""
    cases = load_cases(case_filter)
    click.echo(f"Running {len(cases)} eval case(s)...\n", err=True)

    results = []
    work_dir = tempfile.mkdtemp(prefix="blast-eval-")
    click.echo(f"Work directory: {work_dir}\n", err=True)

    for case in cases:
        click.echo(f"{'='*60}", err=True)
        click.echo(f"Case: {case['id']}", err=True)
        click.echo(f"  Repo: {case['repo']}", err=True)
        click.echo(f"  Breaking pattern: {case['breaking_pattern']}", err=True)
        click.echo(f"  Expected verdict: {case['expected_verdict']}", err=True)

        # Run blast-radius
        t0 = time.time()
        if no_ai:
            from runner import clone_and_patch, run_blast_radius
            case_result = CaseResult(case_id=case["id"])
            try:
                repo_dir = clone_and_patch(
                    case["repo"], case["base_ref"], case["patch_file"], work_dir,
                    case_id=case["id"],
                )
                case_result.repo_dir = repo_dir
                stdout, stderr, exit_code = run_blast_radius(repo_dir, no_ai=True)
                case_result.blast_radius_output = stdout
                case_result.exit_code = exit_code
                case_result.verdict = "N/A (no-ai)"
                case_result.error = stderr
            except Exception as e:
                case_result.error = str(e)
        else:
            case_result = run_case(case, work_dir, model=model)
        elapsed = time.time() - t0

        click.echo(f"  Verdict: {case_result.verdict} (exit {case_result.exit_code}) [{elapsed:.1f}s]", err=True)

        # Show resolution stats from stderr
        if case_result.error:
            for line in (case_result.error or "").splitlines():
                if any(kw in line for kw in ("changed functions", "callers,", "Context:", "Total:")):
                    click.echo(f"  {line.strip()}", err=True)
            if "Error" in case_result.error and "Verdict:" not in case_result.error:
                click.echo(f"  Error: {case_result.error.splitlines()[-1][:200]}", err=True)

        # Run judge
        judge_result = None
        if not no_judge and not no_ai and case_result.blast_radius_output:
            click.echo(f"  Running LLM judge...", err=True)
            try:
                judge_result = judge_case(
                    case, case_result.blast_radius_output, case_result.verdict
                )
                click.echo(f"  Judge: {'PASS' if judge_result.overall_pass else 'FAIL'} — {judge_result.summary}", err=True)
            except Exception as e:
                click.echo(f"  Judge error: {e}", err=True)

        result = {
            "case": {
                "id": case["id"],
                "repo": case["repo"],
                "breaking_pattern": case["breaking_pattern"],
                "expected_verdict": case["expected_verdict"],
            },
            "run": {
                "verdict": case_result.verdict,
                "exit_code": case_result.exit_code,
                "output": case_result.blast_radius_output,
                "error": case_result.error if "Verdict:" not in (case_result.error or "") else "",
            },
        }
        if judge_result:
            result["judge"] = {
                "overall_pass": judge_result.overall_pass,
                "criteria_results": judge_result.criteria_results,
                "verdict_match": judge_result.verdict_match,
                "summary": judge_result.summary,
            }

        results.append(result)
        click.echo("", err=True)

    # Summary
    click.echo(f"{'='*60}", err=True)
    if not no_judge and not no_ai:
        passed = sum(1 for r in results if r.get("judge", {}).get("overall_pass", False))
        click.echo(f"Results: {passed}/{len(results)} cases passed", err=True)
    else:
        for r in results:
            click.echo(f"  {r['case']['id']}: verdict={r['run']['verdict']}", err=True)

    # Output
    if output_file:
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        click.echo(f"\nJSON results written to {output_file}", err=True)

    # Report
    if not no_judge and not no_ai:
        report = format_report(results)
        if report_file:
            with open(report_file, "w") as f:
                f.write(report)
            click.echo(f"Markdown report written to {report_file}", err=True)
        else:
            click.echo(report)

    # Cleanup
    if not keep_repos:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)

    # Exit code: number of failed cases
    if not no_judge and not no_ai:
        failed = sum(1 for r in results if not r.get("judge", {}).get("overall_pass", False))
        sys.exit(min(failed, 1))


if __name__ == "__main__":
    main()
