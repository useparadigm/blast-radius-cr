# blast-radius

Find what breaks before it ships. Automated blast radius analysis for pull requests.

For every changed function in your PR, blast-radius finds all callers and callees, then uses an LLM to identify breaking changes, behavioral shifts, and silent failures.

```
git diff → tree-sitter (changed functions) → grep (callers/callees) → LLM analysis → verdict
```

## Example output

On a PR that changes `clean_neo4j_value()` to return `""` instead of `None`:

> **VERDICT: FAIL**
>
> ```
> BREAKING | clean_neo4j_value → ALL 13 callers | Return value changed from None to ""
>   Why: Existing callers don't pass the new default parameter, so they get default="",
>        changing None returns to "" returns
>   Evidence: Every caller like file_path=clean_neo4j_value(record.get("file_path"))
>            now gets "" instead of None for missing file paths
>   Action: BLOCK MERGE - this breaks the data contract
> ```

## Install

```bash
pip install git+https://github.com/useparadigm/blast-radius-cr.git
```

## Usage

```bash
# Analyze last commit
blast-radius

# Analyze against main branch
blast-radius --ref origin/main

# Just show callers/callees, no LLM
blast-radius --no-ai --format json

# Full options
blast-radius --ref origin/main --fuel 20 --model claude-sonnet-4-20250514 --verbose
```

Requires `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) in your environment.

## GitHub Actions

Add to `.github/workflows/blast-radius.yml`:

```yaml
name: Blast Radius
on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  blast-radius:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install blast-radius
        run: pip install git+https://github.com/useparadigm/blast-radius-cr.git

      - name: Run analysis
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: blast-radius --ref origin/${{ github.base_ref }} --output report.md --verbose

      - name: Post PR comment
        if: success()
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('report.md', 'utf8');
            if (!report.trim()) return;
            await github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: `## Blast Radius Analysis\n\n${report}`,
            });
```

## How it works

1. **Diff parsing** — parses `git diff` into structured file changes and hunks
2. **Symbol extraction** — tree-sitter parses changed files, extracts functions with line ranges, intersects with diff hunks to find changed functions
3. **Context resolution** — `grep` finds all callers across the repo, tree-sitter validates they're real call sites and identifies the containing function. Same process for callees
4. **LLM analysis** — 7-step forced reasoning: what changed, return value analysis, signature analysis, side effects, caller-by-caller impact, classification, verdict

The LLM sees the full diff, the changed function body, and the bodies of all callers and callees. It classifies each finding as:

- **BREAKING** — will cause failures (return type changes, removed functionality)
- **CAUTION** — may cause issues (behavioral changes, performance)
- **SAFE** — no impact (internal refactors, additive changes)

Verdict: **FAIL** (has BREAKING) / **WARNING** (has CAUTION) / **PASS** (all SAFE).

## Supported languages

Python, JavaScript, TypeScript, Go (via tree-sitter grammars).

## CLI options

```
blast-radius [OPTIONS]
  --ref TEXT      Git ref to diff against (default: auto-detect)
  --diff FILE     Path to a patch/diff file
  --fuel INT      Max callers per function (default: 15)
  --model TEXT    LLM model (default: claude-sonnet-4-20250514)
  --no-ai         Output raw context only, skip LLM
  --format        markdown | json
  --output FILE   Write output to file
  --verbose       Show resolution details
  --repo PATH     Repository directory (default: cwd)
```

## Development

```bash
git clone https://github.com/useparadigm/blast-radius-cr.git
cd blast-radius-cr
pip install -e ".[dev]"
pytest
```

## License

MIT
