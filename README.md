# blast-radius

Find what breaks before it ships.

blast-radius statically analyzes your PR, finds every caller of every changed function, and asks an LLM: "will this break anything?"

```
git diff → tree-sitter (changed functions) → grep (callers) → LLM analysis → verdict
```

No LSP, no build step, no project configuration. Works on any repo with Python, JavaScript, TypeScript, or Go.

## What you get

On a PR that changes `clean_neo4j_value()` to return `""` instead of `None`:

```
VERDICT: FAIL

Summary
Return value contract changed — 13 callers expect None for missing values, now get "".

Findings
🔴 clean_neo4j_value → ALL 13 callers | Return value changed from None to ""
   Why: Callers like file_path=clean_neo4j_value(record.get("file_path")) now get ""
   instead of None for missing data — breaks every `if value is None` check downstream.

Action items
🚫 BLOCK — revert default return or update all 13 callers to handle ""
```

On a PR that adds an early-return ASCII fast path to `cell_len()`:

```
VERDICT: PASS

Summary
Performance optimization — ASCII fast path returns same values, no caller impact.

Findings
✅ cell_len — safe (early return for ASCII produces identical results)
```

## Install

```bash
pip install blast-radius-analysis
```

## Quick start

```bash
export ANTHROPIC_API_KEY=sk-...

# Analyze the last commit
blast-radius

# Analyze your branch against main
blast-radius --ref origin/main

# See what the LLM will see, without calling it
blast-radius --no-ai --verbose
```

## GitHub Actions

Add this to `.github/workflows/blast-radius.yml` and every PR gets a blast radius comment:

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

      - name: Install
        run: pip install blast-radius-analysis

      - name: Analyze
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: blast-radius --ref origin/${{ github.base_ref }} --verbose --output report.md

      - name: Comment on PR
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            if (!fs.existsSync('report.md')) return;
            const report = fs.readFileSync('report.md', 'utf8');
            if (!report.trim()) return;
            await github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: `## Blast Radius Analysis\n\n${report}`,
            });
```

That's it. Add `ANTHROPIC_API_KEY` to your repo secrets and open a PR.

## How it works

1. **Diff** — parses `git diff` into file changes and hunks
2. **Extract** — tree-sitter parses changed files, finds which functions overlap with changed hunks
3. **Resolve** — `grep` finds all callers across the repo, tree-sitter validates they're real call sites and identifies the containing function. Same for callees.
4. **Analyze** — LLM sees the full diff, old and new function bodies, and the bodies of every caller and callee. Classifies each finding:
   - **BREAKING** — will cause failures (return type changed, parameter removed)
   - **CAUTION** — may cause issues (behavioral change, new exception path)
   - **SAFE** — no impact (internal refactor, additive change)
5. **Verdict** — FAIL (has BREAKING) / WARNING (has CAUTION) / PASS (all SAFE)

### What the LLM sees

For each changed function, the prompt includes:

- Old and new function body (before/after)
- Unified diff
- Full body of every caller (who calls this function?)
- Full body of every callee (what does this function call?)

The LLM checks against a breaking change checklist: deleted functions with callers, removed/reordered parameters, changed defaults, return type changes, new exceptions, behavioral changes.

## Cost

~$0.03–$0.30 per PR depending on diff size. Default caps at ~100K input tokens (~$0.30 on Sonnet).

```bash
# See token count and cost estimate before running
blast-radius --no-ai --verbose

# Cap spending
blast-radius --max-callers 5 --max-body-lines 30 --max-tokens 50000
```

## CLI reference

```
blast-radius [OPTIONS]
  --ref TEXT            Git ref to diff against (default: auto-detect)
  --diff FILE           Path to a patch/diff file
  --max-callers INT     Max callers per function (default: 15)
  --max-functions INT   Max changed functions to analyze (default: 20)
  --max-tokens INT      Max input tokens for LLM (default: 100000)
  --max-body-lines INT  Truncate function bodies beyond N lines (default: 50)
  --model TEXT          LLM model (default: claude-sonnet-4-20250514)
  --no-ai               Output raw context only, skip LLM
  --format              markdown | json
  --output FILE         Write output to file
  --verbose             Show resolution details and cost estimate
  --repo PATH           Repository directory (default: cwd)
```

## Supported languages

Python, JavaScript, TypeScript (including TSX), Go — via tree-sitter grammars.

Go requires an extra dependency: `pip install blast-radius-analysis[go]`

## Development

```bash
git clone https://github.com/useparadigm/blast-radius.git
cd blast-radius
pip install -e ".[dev]"
pytest
```

## License

MIT
