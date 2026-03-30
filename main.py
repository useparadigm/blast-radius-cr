from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import tree_sitter_python as tspython
from openai import OpenAI
from tree_sitter import Language, Parser


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FunctionInfo:
    name: str          # "my_func" or "MyClass.my_method"
    file_path: str     # relative to repo root
    start_line: int    # 1-indexed
    end_line: int      # 1-indexed
    source: str
    calls: list[str] = field(default_factory=list)


@dataclass
class ChangedFunction:
    info: FunctionInfo
    callers: list[FunctionInfo] = field(default_factory=list)
    callees: list[FunctionInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 1: PR input handling
# ---------------------------------------------------------------------------

def parse_pr_url(url: str) -> tuple[str, str]:
    """Return (owner/repo, pr_number) from a GitHub PR URL."""
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)", url)
    if not m:
        raise ValueError(f"Invalid PR URL: {url}")
    return m.group(1), m.group(2)


def fetch_pr_data(pr_url: str) -> tuple[str, Path, str]:
    """Fetch diff, clone repo at PR head. Returns (diff_text, repo_path, base_ref)."""
    repo_slug, pr_number = parse_pr_url(pr_url)
    log(f"Fetching PR #{pr_number} from {repo_slug}...")

    diff = subprocess.run(
        ["gh", "pr", "diff", pr_number, "-R", repo_slug],
        capture_output=True, text=True, check=True,
    ).stdout

    pr_info = json.loads(subprocess.run(
        ["gh", "pr", "view", pr_number, "-R", repo_slug,
         "--json", "headRefName,headRepository,baseRefName"],
        capture_output=True, text=True, check=True,
    ).stdout)

    head_branch = pr_info["headRefName"]
    base_ref = pr_info["baseRefName"]
    head_repo = pr_info.get("headRepository") or {}
    clone_url = f"https://github.com/{head_repo.get('nameWithOwner') or repo_slug}.git"

    tmpdir = Path(tempfile.mkdtemp(prefix="blast-radius-"))
    log(f"Cloning {clone_url}...")

    # Try cloning the PR head branch; if it's been deleted (merged PR), fetch the merge commit
    result = subprocess.run(
        ["git", "clone", "--depth=50", f"--branch={head_branch}", clone_url, str(tmpdir)],
        capture_output=True,
    )
    if result.returncode != 0:
        log(f"Branch '{head_branch}' not found, fetching PR merge ref...")
        subprocess.run(
            ["git", "clone", "--depth=1", clone_url, str(tmpdir)],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmpdir), "fetch", "origin",
             f"pull/{pr_number}/head:pr-{pr_number}"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmpdir), "checkout", f"pr-{pr_number}"],
            capture_output=True, check=True,
        )

    return diff, tmpdir, base_ref


# ---------------------------------------------------------------------------
# Step 2: Diff parsing
# ---------------------------------------------------------------------------

def parse_diff(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Parse unified diff into {file_path: [(start_line, end_line), ...]} for .py files."""
    hunks: dict[str, list[tuple[int, int]]] = {}
    current_file = None

    for line in diff_text.splitlines():
        # New file header
        if line.startswith("+++ b/"):
            path = line[6:]
            current_file = path if path.endswith(".py") else None
        # Hunk header
        elif line.startswith("@@") and current_file:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) else 1
                end = start + count - 1
                hunks.setdefault(current_file, []).append((start, end))

    return hunks


# ---------------------------------------------------------------------------
# Step 3: Tree-sitter indexing
# ---------------------------------------------------------------------------

def make_parser() -> Parser:
    PY_LANGUAGE = Language(tspython.language())
    parser = Parser(PY_LANGUAGE)
    return parser


def extract_call_name(node) -> str | None:
    """Extract the callable name from a call node's function child."""
    fn = node.child_by_field_name("function")
    if fn is None:
        return None
    if fn.type == "identifier":
        return fn.text.decode()
    if fn.type == "attribute":
        return fn.text.decode()
    return None


def find_calls_in_body(node) -> list[str]:
    """Recursively find all call expressions within a node."""
    calls = []
    if node.type == "call":
        name = extract_call_name(node)
        if name:
            calls.append(name)
    for child in node.children:
        calls.extend(find_calls_in_body(child))
    return calls


def get_class_name(node) -> str | None:
    """Walk up from a function_definition to find enclosing class name."""
    parent = node.parent
    while parent:
        if parent.type == "class_definition":
            name_node = parent.child_by_field_name("name")
            if name_node:
                return name_node.text.decode()
        parent = parent.parent
    return None


def extract_functions_from_tree(tree, source_bytes: bytes, file_path: str) -> list[FunctionInfo]:
    """Walk AST and extract all function definitions."""
    functions = []

    def visit(node):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                fn_name = name_node.text.decode()
                class_name = get_class_name(node)
                qualified = f"{class_name}.{fn_name}" if class_name else fn_name

                body = node.child_by_field_name("body")
                calls = find_calls_in_body(body) if body else []

                # Use the decorated_definition if present for full source
                source_node = node
                if node.parent and node.parent.type == "decorated_definition":
                    source_node = node.parent

                functions.append(FunctionInfo(
                    name=qualified,
                    file_path=file_path,
                    start_line=source_node.start_point[0] + 1,
                    end_line=source_node.end_point[0] + 1,
                    source=source_bytes[source_node.start_byte:source_node.end_byte].decode(errors="replace"),
                    calls=calls,
                ))

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return functions


def index_repo(repo_root: Path, parser: Parser) -> list[FunctionInfo]:
    """Index all Python files in the repo."""
    exclude_dirs = {".venv", "__pycache__", ".git", "node_modules", ".tox", ".eggs"}
    all_functions = []

    py_files = sorted(repo_root.rglob("*.py"))
    log(f"Indexing {len(py_files)} Python files...")

    for py_file in py_files:
        # Skip excluded directories
        if any(part in exclude_dirs for part in py_file.parts):
            continue
        try:
            source = py_file.read_bytes()
            tree = parser.parse(source)
            rel_path = str(py_file.relative_to(repo_root))
            all_functions.extend(extract_functions_from_tree(tree, source, rel_path))
        except Exception as e:
            log(f"  Warning: could not parse {py_file}: {e}")

    log(f"Found {len(all_functions)} functions")
    return all_functions


# ---------------------------------------------------------------------------
# Step 4: Map diff hunks to changed functions
# ---------------------------------------------------------------------------

def find_changed_functions(
    all_functions: list[FunctionInfo],
    changed_hunks: dict[str, list[tuple[int, int]]],
) -> list[FunctionInfo]:
    """Find functions whose line ranges overlap with changed hunks."""
    changed = []
    for fn in all_functions:
        hunks = changed_hunks.get(fn.file_path)
        if not hunks:
            continue
        for hunk_start, hunk_end in hunks:
            if hunk_start <= fn.end_line and hunk_end >= fn.start_line:
                changed.append(fn)
                break
    return changed


# ---------------------------------------------------------------------------
# Step 5: Caller/callee resolution
# ---------------------------------------------------------------------------

def unqualified_name(name: str) -> str:
    """Get the last component: 'self.bar' -> 'bar', 'Foo.baz' -> 'baz', 'func' -> 'func'."""
    return name.rsplit(".", 1)[-1]


def resolve_blast_radius(
    changed_fns: list[FunctionInfo],
    all_functions: list[FunctionInfo],
) -> list[ChangedFunction]:
    """For each changed function, find its callers and callees (1 level)."""
    # Build a lookup: unqualified name -> list of FunctionInfo
    by_name: dict[str, list[FunctionInfo]] = {}
    for fn in all_functions:
        uq = unqualified_name(fn.name)
        by_name.setdefault(uq, []).append(fn)

    changed_set = {id(fn) for fn in changed_fns}
    results = []

    for cf in changed_fns:
        # Callees: functions that cf calls
        callees = []
        seen_callees = set()
        for call_name in cf.calls:
            uq = unqualified_name(call_name)
            for candidate in by_name.get(uq, []):
                if id(candidate) not in seen_callees and id(candidate) != id(cf):
                    callees.append(candidate)
                    seen_callees.add(id(candidate))

        # Callers: functions that call cf
        callers = []
        cf_uq = unqualified_name(cf.name)
        for fn in all_functions:
            if id(fn) == id(cf) or id(fn) in changed_set:
                continue
            for call_name in fn.calls:
                if unqualified_name(call_name) == cf_uq:
                    callers.append(fn)
                    break

        results.append(ChangedFunction(info=cf, callers=callers, callees=callees))

    return results


# ---------------------------------------------------------------------------
# Step 6: Context assembly
# ---------------------------------------------------------------------------

def assemble_context(blast_radius: list[ChangedFunction], diff_text: str) -> str:
    """Build the context string for the LLM."""
    parts = []

    parts.append("# PR Diff\n```diff\n" + diff_text[:20000] + "\n```\n")

    for cf in blast_radius:
        parts.append(f"## Changed Function: `{cf.info.name}` ({cf.info.file_path}:{cf.info.start_line}-{cf.info.end_line})")
        parts.append(f"```python\n{cf.info.source}\n```\n")

        if cf.callees:
            parts.append("### Callees (functions this calls):")
            for callee in cf.callees[:10]:  # cap at 10
                parts.append(f"#### `{callee.name}` ({callee.file_path}:{callee.start_line}-{callee.end_line})")
                source = callee.source
                if source.count("\n") > 100:
                    source = "\n".join(source.splitlines()[:100]) + "\n# ... truncated"
                parts.append(f"```python\n{source}\n```\n")

        if cf.callers:
            parts.append("### Callers (functions that call this):")
            for caller in cf.callers[:10]:  # cap at 10
                parts.append(f"#### `{caller.name}` ({caller.file_path}:{caller.start_line}-{caller.end_line})")
                source = caller.source
                if source.count("\n") > 100:
                    source = "\n".join(source.splitlines()[:100]) + "\n# ... truncated"
                parts.append(f"```python\n{source}\n```\n")

    context = "\n\n".join(parts)

    # Rough token estimate
    est_tokens = len(context) / 3.5
    if est_tokens > 120000:
        log(f"Warning: context is ~{int(est_tokens)} tokens, truncating...")
        context = context[:420000]  # ~120k tokens

    return context


# ---------------------------------------------------------------------------
# Step 7: LLM analysis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior software engineer reviewing a pull request.

You are given:
1. The PR diff
2. For each changed function: its source code, the functions it calls (callees), and the functions that call it (callers)

Analyze what could break. Be specific about:
- Behavioral changes that callers might not expect
- Callees whose contracts the changed code might now violate
- Edge cases or regressions introduced by the changes
- Any callers that may need to be updated

Be concise and actionable. Focus on real risks, not hypotheticals."""


def analyze_with_llm(context: str) -> str:
    """Send context to OpenAI for analysis."""
    client = OpenAI()
    log("Sending to OpenAI for analysis...")

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Step 8: Report generation
# ---------------------------------------------------------------------------

def generate_report(
    pr_url: str,
    repo_slug: str,
    pr_number: str,
    diff_text: str,
    changed_hunks: dict[str, list[tuple[int, int]]],
    blast_radius: list[ChangedFunction],
    analysis: str,
) -> str:
    """Generate a full markdown report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_callers = sum(len(cf.callers) for cf in blast_radius)
    total_callees = sum(len(cf.callees) for cf in blast_radius)

    lines = []
    lines.append(f"# Blast Radius Report")
    lines.append(f"")
    lines.append(f"**PR:** [{repo_slug}#{pr_number}]({pr_url})")
    lines.append(f"**Generated:** {now}")
    lines.append(f"")

    # Summary stats
    lines.append(f"## Summary")
    lines.append(f"")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Python files changed | {len(changed_hunks)} |")
    lines.append(f"| Functions changed | {len(blast_radius)} |")
    lines.append(f"| Callers (1 level up) | {total_callers} |")
    lines.append(f"| Callees (1 level down) | {total_callees} |")
    lines.append(f"")

    # Changed functions detail
    lines.append(f"## Changed Functions")
    lines.append(f"")
    for cf in blast_radius:
        lines.append(f"### `{cf.info.name}`")
        lines.append(f"**File:** `{cf.info.file_path}:{cf.info.start_line}-{cf.info.end_line}`")
        lines.append(f"")
        lines.append(f"```python")
        lines.append(cf.info.source)
        lines.append(f"```")
        lines.append(f"")

        if cf.callers:
            lines.append(f"**Callers ({len(cf.callers)}):**")
            lines.append(f"")
            for caller in cf.callers:
                lines.append(f"- `{caller.name}` (`{caller.file_path}:{caller.start_line}`)")
            lines.append(f"")

        if cf.callees:
            lines.append(f"**Callees ({len(cf.callees)}):**")
            lines.append(f"")
            for callee in cf.callees:
                lines.append(f"- `{callee.name}` (`{callee.file_path}:{callee.start_line}`)")
            lines.append(f"")

    # LLM analysis
    lines.append(f"## LLM Analysis")
    lines.append(f"")
    lines.append(analysis)
    lines.append(f"")

    # Diff (collapsed)
    lines.append(f"## Diff")
    lines.append(f"")
    lines.append(f"<details>")
    lines.append(f"<summary>Full diff ({len(diff_text.splitlines())} lines)</summary>")
    lines.append(f"")
    lines.append(f"```diff")
    lines.append(diff_text)
    lines.append(f"```")
    lines.append(f"")
    lines.append(f"</details>")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def log(msg: str):
    print(msg, file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run main.py <github-pr-url> [output-dir]", file=sys.stderr)
        print("Example: uv run main.py https://github.com/org/repo/pull/123", file=sys.stderr)
        sys.exit(1)

    pr_url = sys.argv[1]
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
    repo_path = None

    try:
        repo_slug, pr_number = parse_pr_url(pr_url)

        # Fetch PR data and clone
        diff_text, repo_path, base_ref = fetch_pr_data(pr_url)

        # Parse diff
        changed_hunks = parse_diff(diff_text)
        log(f"Found changes in {len(changed_hunks)} Python files")

        if not changed_hunks:
            log("No Python files changed in this PR.")
            sys.exit(0)

        # Index repo
        parser = make_parser()
        all_functions = index_repo(repo_path, parser)

        # Find changed functions
        changed_fns = find_changed_functions(all_functions, changed_hunks)
        log(f"Found {len(changed_fns)} changed functions")

        if not changed_fns:
            log("No function definitions were changed in this PR.")
            sys.exit(0)

        # Resolve blast radius
        blast_radius = resolve_blast_radius(changed_fns, all_functions)

        total_callers = sum(len(cf.callers) for cf in blast_radius)
        total_callees = sum(len(cf.callees) for cf in blast_radius)
        log(f"Blast radius: {len(changed_fns)} changed, {total_callers} callers, {total_callees} callees")

        # Assemble context and analyze
        context = assemble_context(blast_radius, diff_text)
        analysis = analyze_with_llm(context)

        # Generate report
        report = generate_report(
            pr_url, repo_slug, pr_number, diff_text,
            changed_hunks, blast_radius, analysis,
        )

        # Write report
        safe_slug = repo_slug.replace("/", "-")
        filename = f"blast-radius-{safe_slug}-{pr_number}.md"
        output_path = output_dir / filename
        output_path.write_text(report)
        log(f"Report written to {output_path}")

        # Also print analysis to stdout
        print(analysis)

    finally:
        if repo_path and repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)


if __name__ == "__main__":
    main()
