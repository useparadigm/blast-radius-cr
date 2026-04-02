"""Parse git diff output into structured data."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field


@dataclass
class ChangedHunk:
    start_line: int  # 1-based, in the NEW file
    end_line: int
    header: str = ""

    def overlaps(self, func_start: int, func_end: int) -> bool:
        return self.start_line <= func_end and self.end_line >= func_start


@dataclass
class FileChange:
    path: str
    status: str  # "modified", "deleted", "added", "renamed"
    old_path: str | None = None
    hunks: list[ChangedHunk] = field(default_factory=list)


_DIFF_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)")
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@(.*)")
_FILE_MODE = re.compile(r"^(new|deleted) file mode")
_RENAME_FROM = re.compile(r"^rename from (.*)")
_RENAME_TO = re.compile(r"^rename to (.*)")
_SIMILARITY = re.compile(r"^similarity index")


def parse_diff(diff_text: str) -> list[FileChange]:
    """Parse unified diff text into FileChange objects."""
    files: list[FileChange] = []
    current: FileChange | None = None
    lines = diff_text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        m = _DIFF_HEADER.match(line)
        if m:
            old_name, new_name = m.group(1), m.group(2)
            current = FileChange(path=new_name, status="modified")
            files.append(current)

            # Scan ahead for mode/rename headers
            i += 1
            while i < len(lines) and not lines[i].startswith("diff --git") and not lines[i].startswith("@@"):
                if _FILE_MODE.match(lines[i]):
                    if lines[i].startswith("new"):
                        current.status = "added"
                    elif lines[i].startswith("deleted"):
                        current.status = "deleted"
                elif _RENAME_FROM.match(lines[i]):
                    current.old_path = _RENAME_FROM.match(lines[i]).group(1)
                    current.status = "renamed"
                elif _RENAME_TO.match(lines[i]):
                    current.path = _RENAME_TO.match(lines[i]).group(1)
                i += 1
            continue

        m = _HUNK_HEADER.match(line)
        if m and current is not None:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) else 1
            end = start + max(count - 1, 0)
            current.hunks.append(ChangedHunk(
                start_line=start,
                end_line=end,
                header=m.group(3).strip(),
            ))
            i += 1
            continue

        i += 1

    return files


def get_diff(ref: str | None = None, diff_file: str | None = None, repo_dir: str = ".") -> str:
    """Get diff text from git or a file."""
    if diff_file:
        with open(diff_file) as f:
            return f.read()

    if ref is None:
        # Try staged first, fall back to HEAD~1
        result = subprocess.run(
            ["git", "diff", "--cached"],
            capture_output=True, text=True, cwd=repo_dir,
        )
        if result.stdout.strip():
            return result.stdout

        result = subprocess.run(
            ["git", "diff", "HEAD~1"],
            capture_output=True, text=True, cwd=repo_dir,
        )
        return result.stdout

    result = subprocess.run(
        ["git", "diff", ref],
        capture_output=True, text=True, cwd=repo_dir,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr}")
    return result.stdout


def resolve_base_ref(ref: str | None = None, repo_dir: str = ".") -> str:
    """Determine the git ref for the 'old' side of the diff.

    Mirrors the logic in get_diff(): if ref is given use it,
    otherwise try staged changes (→ HEAD) then fall back to HEAD~1.
    """
    if ref is not None:
        return ref

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True, cwd=repo_dir,
    )
    if result.returncode != 0:
        # Has staged changes — old side is HEAD
        return "HEAD"
    return "HEAD~1"


def get_old_file_content(file_path: str, base_ref: str, repo_dir: str = ".") -> str | None:
    """Retrieve file content from a git ref. Returns None if file didn't exist."""
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{file_path}"],
        capture_output=True, text=True, cwd=repo_dir,
    )
    if result.returncode != 0:
        return None
    return result.stdout
