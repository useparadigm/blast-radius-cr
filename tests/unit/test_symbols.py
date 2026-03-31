"""Tests for tree-sitter symbol extraction."""

import pytest

from blast_radius.symbols import extract_functions, identify_changed_functions
from blast_radius.diff import FileChange, ChangedHunk


PYTHON_SOURCE = '''\
def top_level_func():
    print("hello")
    other_func()

def other_func():
    return 42

class MyService:
    def process(self, data):
        validate(data)
        result = transform(data)
        return self.save(result)

    def save(self, result):
        return {"saved": True}
'''


def test_extract_python_functions():
    funcs = extract_functions(PYTHON_SOURCE, "test.py", "python")
    names = [f.name for f in funcs]
    assert "top_level_func" in names
    assert "other_func" in names
    assert "process" in names
    assert "save" in names


def test_function_line_ranges():
    funcs = extract_functions(PYTHON_SOURCE, "test.py", "python")
    by_name = {f.name: f for f in funcs}
    # top_level_func starts at line 1
    assert by_name["top_level_func"].start_line == 1
    # other_func starts at line 5
    assert by_name["other_func"].start_line == 5


def test_call_sites_extracted():
    funcs = extract_functions(PYTHON_SOURCE, "test.py", "python")
    by_name = {f.name: f for f in funcs}
    # top_level_func calls print and other_func
    calls = by_name["top_level_func"].call_sites
    assert "print" in calls
    assert "other_func" in calls


def test_containing_class():
    funcs = extract_functions(PYTHON_SOURCE, "test.py", "python")
    by_name = {f.name: f for f in funcs}
    assert by_name["process"].containing_class == "MyService"
    assert by_name["save"].containing_class == "MyService"
    assert by_name["top_level_func"].containing_class is None


def test_method_call_sites():
    funcs = extract_functions(PYTHON_SOURCE, "test.py", "python")
    by_name = {f.name: f for f in funcs}
    calls = by_name["process"].call_sites
    assert "validate" in calls
    assert "transform" in calls


def test_identify_changed_functions_modified(tmp_path):
    """Changed hunk overlapping a function should identify it."""
    src = tmp_path / "test.py"
    src.write_text(PYTHON_SOURCE)

    fc = FileChange(
        path="test.py",
        status="modified",
        hunks=[ChangedHunk(start_line=1, end_line=3)],  # overlaps top_level_func
    )
    changed = identify_changed_functions(fc, repo_dir=str(tmp_path))
    names = [c.symbol.name for c in changed]
    assert "top_level_func" in names
    assert "other_func" not in names  # not in hunk range


def test_identify_changed_no_overlap(tmp_path):
    """Hunk that doesn't overlap any function should return empty."""
    src = tmp_path / "test.py"
    src.write_text(PYTHON_SOURCE)

    fc = FileChange(
        path="test.py",
        status="modified",
        hunks=[ChangedHunk(start_line=100, end_line=105)],
    )
    changed = identify_changed_functions(fc, repo_dir=str(tmp_path))
    assert changed == []


def test_identify_added_file(tmp_path):
    """All functions in an added file should be marked as added."""
    src = tmp_path / "new.py"
    src.write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")

    fc = FileChange(
        path="new.py",
        status="added",
        hunks=[ChangedHunk(start_line=1, end_line=5)],
    )
    changed = identify_changed_functions(fc, repo_dir=str(tmp_path))
    assert len(changed) == 2
    assert all(c.change_type == "added" for c in changed)


def test_unsupported_language(tmp_path):
    """Files with unsupported extensions should return empty."""
    src = tmp_path / "data.csv"
    src.write_text("a,b,c\n1,2,3")

    fc = FileChange(path="data.csv", status="modified", hunks=[ChangedHunk(start_line=1, end_line=2)])
    changed = identify_changed_functions(fc, repo_dir=str(tmp_path))
    assert changed == []


def test_extract_empty_file():
    funcs = extract_functions("", "empty.py", "python")
    assert funcs == []
