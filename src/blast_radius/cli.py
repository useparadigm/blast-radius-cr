"""CLI entry point for blast-radius."""

from __future__ import annotations

import sys

import click

from .diff import get_diff, parse_diff
from .resolver import resolve_context
from .report import format_context_json, format_context_markdown
from .symbols import identify_changed_functions


def _extract_file_diffs(diff_text: str) -> dict[str, str]:
    """Split a unified diff into per-file diffs keyed by new file path."""
    files: dict[str, str] = {}
    current_path = None
    current_lines: list[str] = []

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            if current_path and current_lines:
                files[current_path] = "\n".join(current_lines)
            parts = line.split(" b/", 1)
            current_path = parts[1] if len(parts) > 1 else None
            current_lines = [line]
        elif current_path is not None:
            current_lines.append(line)

    if current_path and current_lines:
        files[current_path] = "\n".join(current_lines)

    return files


@click.command()
@click.option("--ref", default=None, help="Git ref to diff against (default: auto-detect)")
@click.option("--diff", "diff_file", default=None, type=click.Path(exists=True), help="Path to a patch/diff file")
@click.option("--max-callers", default=15, type=int, help="Max callers per function (default: 15)")
@click.option("--max-functions", default=20, type=int, help="Max changed functions to analyze (default: 20)")
@click.option("--max-tokens", default=100_000, type=int, help="Max input tokens for LLM (default: 100000)")
@click.option("--max-body-lines", default=50, type=int, help="Truncate function bodies beyond N lines (default: 50)")
@click.option("--model", default="claude-sonnet-4-20250514", help="LLM model for analysis")
@click.option("--no-ai", is_flag=True, help="Output raw context only, skip AI analysis")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown", help="Output format")
@click.option("--output", "output_file", default=None, type=click.Path(), help="Write output to file")
@click.option("--verbose", is_flag=True, help="Show resolution details and cost estimate")
@click.option("--repo", default=".", help="Repository directory (default: current dir)")
def main(ref, diff_file, max_callers, max_functions, max_tokens, max_body_lines,
         model, no_ai, fmt, output_file, verbose, repo):
    """Analyze blast radius of code changes."""
    # Step 1: Get diff
    try:
        diff_text = get_diff(ref=ref, diff_file=diff_file, repo_dir=repo)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not diff_text.strip():
        click.echo("No changes found.", err=True)
        sys.exit(0)

    # Step 2: Parse diff
    file_changes = parse_diff(diff_text)
    if verbose:
        click.echo(f"Found {len(file_changes)} changed files", err=True)

    # Build per-file diff map for context
    file_diffs = _extract_file_diffs(diff_text)

    # Step 3: Identify changed functions
    all_changed = []
    for fc in file_changes:
        changed = identify_changed_functions(fc, repo_dir=repo)
        all_changed.extend(changed)
        if verbose:
            click.echo(f"  {fc.path}: {len(changed)} changed functions", err=True)

    if not all_changed:
        click.echo("No changed functions found.", err=True)
        sys.exit(0)

    if verbose:
        click.echo(f"Total: {len(all_changed)} changed functions", err=True)

    # Step 4: Resolve context
    contexts = []
    for cf in all_changed:
        ctx = resolve_context(
            cf.symbol, repo_dir=repo, change_type=cf.change_type, fuel=max_callers,
        )
        ctx.diff_text = file_diffs.get(cf.symbol.file_path, "")
        contexts.append(ctx)
        if verbose:
            click.echo(
                f"  {cf.symbol.name}: {len(ctx.callers)} callers, {len(ctx.callees)} callees",
                err=True,
            )

    # Step 5: Apply budget
    from .budget import apply_budget
    contexts, budget = apply_budget(
        contexts,
        max_tokens=max_tokens,
        max_functions=max_functions,
        max_callers=max_callers,
        max_body_lines=max_body_lines,
        model=model,
    )
    if verbose:
        click.echo(budget.summary(), err=True)

    # Step 6: Output
    verdict = "PASS"
    if no_ai:
        if fmt == "json":
            output = format_context_json(contexts)
        else:
            output = format_context_markdown(contexts)
    else:
        from .analyzer import analyze, parse_verdict
        try:
            output = analyze(contexts, model=model)
            verdict = parse_verdict(output)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    if verbose:
        click.echo(f"Verdict: {verdict}", err=True)

    if output_file:
        with open(output_file, "w") as f:
            f.write(output)
        click.echo(f"Output written to {output_file}", err=True)
    else:
        click.echo(output)

    # Exit codes: 0=PASS, 1=FAIL
    if verdict == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()
