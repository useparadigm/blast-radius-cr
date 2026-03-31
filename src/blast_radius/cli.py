"""CLI entry point for blast-radius."""

from __future__ import annotations

import sys

import click

from .diff import get_diff, parse_diff
from .resolver import resolve_context
from .report import format_context_json, format_context_markdown
from .symbols import identify_changed_functions


@click.command()
@click.option("--ref", default=None, help="Git ref to diff against (default: auto-detect)")
@click.option("--diff", "diff_file", default=None, type=click.Path(exists=True), help="Path to a patch/diff file")
@click.option("--fuel", default=15, type=int, help="Max callers per function (default: 15)")
@click.option("--model", default="claude-sonnet-4-20250514", help="LLM model for analysis")
@click.option("--no-ai", is_flag=True, help="Output raw context only, skip AI analysis")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown", help="Output format")
@click.option("--output", "output_file", default=None, type=click.Path(), help="Write output to file")
@click.option("--verbose", is_flag=True, help="Show resolution details")
@click.option("--repo", default=".", help="Repository directory (default: current dir)")
def main(ref, diff_file, fuel, model, no_ai, fmt, output_file, verbose, repo):
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
            cf.symbol, repo_dir=repo, change_type=cf.change_type, fuel=fuel,
        )
        contexts.append(ctx)
        if verbose:
            click.echo(
                f"  {cf.symbol.name}: {len(ctx.callers)} callers, {len(ctx.callees)} callees",
                err=True,
            )

    # Step 5: Output
    if no_ai:
        if fmt == "json":
            output = format_context_json(contexts)
        else:
            output = format_context_markdown(contexts)
    else:
        from .analyzer import analyze
        try:
            output = analyze(contexts, model=model)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    if output_file:
        with open(output_file, "w") as f:
            f.write(output)
        click.echo(f"Output written to {output_file}", err=True)
    else:
        click.echo(output)


if __name__ == "__main__":
    main()
