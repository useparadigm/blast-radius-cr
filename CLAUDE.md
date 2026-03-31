# blast-radius

Blast radius analysis for code reviews. Finds what breaks before it ships.

## Architecture

```
git diff → tree-sitter (changed functions) → grep (callers/callees) → AI analysis → report
```

4 stages, no database, no external servers. Everything computed on-the-fly.

## Stack

- **Symbol extraction**: tree-sitter (Python, JS/TS, Go)
- **Caller/callee resolution**: grep + tree-sitter validation
- **AI analysis**: Anthropic Claude (default) or OpenAI
- **CLI**: Click

## Key files

- `src/blast_radius/diff.py` — git diff parser
- `src/blast_radius/symbols.py` — tree-sitter function extraction + call site detection
- `src/blast_radius/resolver.py` — grep-based caller/callee resolution
- `src/blast_radius/analyzer.py` — LLM blast radius analysis + prompt
- `src/blast_radius/cli.py` — CLI entry point
- `src/blast_radius/report.py` — markdown/json output formatting
- `src/blast_radius/languages.py` — language detection + tree-sitter config

## Development

```bash
pip install -e ".[dev]"
pytest tests/unit                    # fast, no git/LSP needed
pytest tests/integration             # needs git, tree-sitter
pytest tests/ai                      # needs API key, slow
```

## Testing approach

- `--no-ai` flag runs the full deterministic pipeline without LLM
- Unit tests: diff parsing, symbol extraction, report formatting
- Integration tests: real git repos from fixtures, full pipeline
- Test fixtures in `tests/fixtures/simple-python/`

## Commands

```bash
blast-radius                         # analyze last commit
blast-radius --ref main              # diff against main
blast-radius --no-ai --format json   # raw context, no LLM
blast-radius --verbose               # show resolution details
```
