# Blast Radius Evals

Evaluation pipeline that tests blast-radius against synthetic breaking changes injected into real open-source Python repos.

## How it works

1. Clone a real repo at a pinned commit (e.g. click 8.1.7, flask 3.1.3)
2. Apply a small patch that introduces a specific change (breaking or safe)
3. Run `blast-radius --ref HEAD~1` to analyze the change
4. LLM judge evaluates whether blast-radius correctly identified (or correctly ignored) the change

## Where the patches come from

These are **not** real PRs. They are synthetic 1-3 line changes injected into real repos:

1. Cloned 8 popular Python libraries (click, rich, requests, flask, marshmallow, httpx, attrs, typer)
2. Analyzed which functions have the most **internal callers** (grep `func_name(` + count)
3. Picked 5 functions with high caller counts and designed minimal breaking patches
4. Picked 3 functions for safe changes (docstring, optimization, optional param)
5. Stored each change as a `.patch` file + pinned commit SHA for reproducibility

The patches are intentionally small — a 1-line default value change is more realistic (and harder to catch) than a giant refactor.

## Test cases

### FAIL cases (expected to be caught)

| Case | Repo | Breaking pattern | Callers | Tokens |
|------|------|-----------------|---------|--------|
| `click-echo-nl-default` | pallets/click | Default `nl: True` -> `False` | 43 | ~5K |
| `rich-cell-len-raises` | Textualize/rich | New ValueError on empty string | 23 | ~7K |
| `requests-merge-setting-signature` | psf/requests | New required param `strategy` | 3 | ~4K |
| `marshmallow-make-error-return` | marshmallow-code/marshmallow | Returns `str` instead of `ValidationError` | 10 | ~4K |
| `flask-ensure-sync-tuple` | pallets/flask | Returns tuple instead of callable | 14 | ~7K |

### PASS cases (should NOT be flagged as breaking)

| Case | Repo | Safe pattern | Callers | Tokens |
|------|------|-------------|---------|--------|
| `click-echo-docstring-only` | pallets/click | Docstring reformatted, zero code change | 43 | ~5K |
| `rich-cell-len-ascii-fastpath` | Textualize/rich | ASCII fast-path, same return values | 23 | ~7K |
| `flask-ensure-sync-optional-param` | pallets/flask | New optional param with `None` default | 13 | ~7K |

## Usage

```bash
# Deterministic only — verify resolver finds callers, no LLM needed, no API key
python evals/run_evals.py --no-ai

# Full run with LLM analysis + judge (~$0.25 per run)
ANTHROPIC_API_KEY=sk-... python evals/run_evals.py

# Single case
python evals/run_evals.py --case flask-ensure-sync-tuple

# Save results
python evals/run_evals.py --output results.json --report report.md

# Keep cloned repos for debugging
python evals/run_evals.py --keep-repos
```

## Cost

~$0.25 per full run (8 cases): Sonnet analysis ($0.14) + Haiku compression ($0.01) + Sonnet judge ($0.08).

## GitHub Actions

The eval pipeline runs as a GitHub Actions workflow:
- **Manual dispatch**: trigger from Actions tab, optionally filter by case
- **Scheduled**: weekly Monday 6am UTC
- Results posted as GitHub Step Summary + uploaded as artifact

## Adding new cases

1. Pick a real Python repo with functions that have internal callers
2. Create a `.patch` file in `fixtures/`
3. Add an entry to `cases.yaml` with pinned commit SHA, expected verdict, and judge criteria
4. Test: `python evals/run_evals.py --case your-case-id --no-ai`

## Dependencies

- `pyyaml` — cases.yaml parsing
- `anthropic` — LLM analysis + judge (not needed for `--no-ai`)
- `blast-radius` — installed from this repo
