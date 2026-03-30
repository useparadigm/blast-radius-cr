# blast-radius

Given a GitHub PR link, find the blast radius of changes: which functions changed, what calls them, and what they call. Then ask an LLM what could break.

## Usage

```bash
uv run main.py <github-pr-url> [output-dir]
```

Example:
```bash
OPENAI_API_KEY=... uv run main.py https://github.com/pallets/flask/pull/5928
```

## Requirements

- Python 3.12+
- `gh` CLI (authenticated)
- `OPENAI_API_KEY` environment variable
