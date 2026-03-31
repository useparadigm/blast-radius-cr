"""Shared test fixtures."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def simple_python_repo(tmp_path):
    """Create a git repo from the simple-python fixture with an initial commit,
    then apply a modification so there's a diff to analyze."""
    fixture_src = FIXTURES_DIR / "simple-python"

    # Copy fixture files
    for f in fixture_src.iterdir():
        if f.is_file():
            shutil.copy2(f, tmp_path / f.name)

    # Init git repo and commit
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
    )

    return tmp_path


@pytest.fixture
def modified_validate_repo(simple_python_repo):
    """Modify validate_order signature (add required param) — a breaking change."""
    utils = simple_python_repo / "utils.py"
    content = utils.read_text()
    content = content.replace(
        "def validate_order(order_data):",
        "def validate_order(order_data, strict=False):",
    )
    content = content.replace(
        '    if not order_data.get("items"):',
        '    if not order_data.get("items"):\n        if strict:\n            raise TypeError("Items must be a list")',
    )
    utils.write_text(content)
    return simple_python_repo


@pytest.fixture
def deleted_function_repo(simple_python_repo):
    """Delete calculate_tax from utils.py — callers should break."""
    utils = simple_python_repo / "utils.py"
    lines = utils.read_text().splitlines(keepends=True)
    # Remove calculate_tax function (lines with that function)
    new_lines = []
    skip = False
    for line in lines:
        if "def calculate_tax" in line:
            skip = True
            continue
        if skip and (line.startswith("def ") or line.startswith("class ") or line.strip() == ""):
            if line.strip() == "":
                continue
            skip = False
        if not skip:
            new_lines.append(line)
    utils.write_text("".join(new_lines))
    return simple_python_repo
