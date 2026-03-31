"""Tests for grep-based resolver — mocked grep, real tree-sitter."""

import pytest

from blast_radius.resolver import (
    _should_skip,
    _matches_gitignore,
    grep_for_callers,
    grep_for_definition,
)


def test_should_skip_node_modules():
    assert _should_skip("node_modules/foo/bar.js") is True


def test_should_skip_git():
    assert _should_skip(".git/objects/abc") is True


def test_should_skip_pycache():
    assert _should_skip("src/__pycache__/mod.cpython-313.pyc") is True


def test_should_skip_binary_extensions():
    assert _should_skip("image.png") is True
    assert _should_skip("lib.so") is True


def test_should_not_skip_normal():
    assert _should_skip("src/service.py") is False
    assert _should_skip("api/handler.ts") is False


def test_matches_gitignore():
    patterns = ["*.pyc", "dist/", "node_modules/"]
    assert _matches_gitignore("foo.pyc", patterns) is True
    assert _matches_gitignore("dist/bundle.js", patterns) is True
    assert _matches_gitignore("src/app.py", patterns) is False


def test_grep_for_callers_in_fixture(simple_python_repo):
    """Grep for callers of validate_order in the fixture repo."""
    hits = grep_for_callers("validate_order", str(simple_python_repo))
    files = [h["file"] for h in hits]
    # service.py calls validate_order
    assert any("service.py" in f for f in files)
    # utils.py defines it — should be filtered out
    assert not any(
        h["text"].strip().startswith("def validate_order")
        for h in hits
    )


def test_grep_for_callers_respects_fuel(simple_python_repo):
    hits = grep_for_callers("validate_order", str(simple_python_repo), fuel=1)
    assert len(hits) <= 1


def test_grep_for_definition_python(simple_python_repo):
    defn = grep_for_definition("validate_order", "python", str(simple_python_repo))
    assert defn is not None
    assert "utils.py" in defn["file"]


def test_grep_for_definition_not_found(simple_python_repo):
    defn = grep_for_definition("nonexistent_function", "python", str(simple_python_repo))
    assert defn is None


@pytest.fixture
def simple_python_repo(tmp_path):
    """Minimal fixture — just copy the files, no git needed for grep tests."""
    import shutil
    from pathlib import Path

    fixture_src = Path(__file__).parent.parent / "fixtures" / "simple-python"
    for f in fixture_src.iterdir():
        if f.is_file():
            shutil.copy2(f, tmp_path / f.name)
    return tmp_path
