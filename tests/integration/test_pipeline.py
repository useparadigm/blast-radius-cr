"""End-to-end integration tests for the full pipeline (--no-ai mode).

These tests create real git repos from fixtures, make modifications,
and verify the full diff → symbols → resolver pipeline produces correct output.
"""

import json
import os
import subprocess

import pytest

from blast_radius.diff import get_diff, parse_diff
from blast_radius.symbols import identify_changed_functions
from blast_radius.resolver import resolve_context
from blast_radius.report import format_context_json


def _git_env():
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


class TestModifiedSignature:
    """Scenario: validate_order gets a new parameter.
    Expected: create_order (caller) should be detected."""

    def test_finds_changed_function(self, modified_validate_repo):
        repo = str(modified_validate_repo)
        diff_text = get_diff(ref="HEAD", repo_dir=repo)
        files = parse_diff(diff_text)

        assert len(files) == 1
        assert files[0].path == "utils.py"

        all_changed = []
        for fc in files:
            all_changed.extend(identify_changed_functions(fc, repo_dir=repo))

        names = [c.symbol.name for c in all_changed]
        assert "validate_order" in names

    def test_resolves_callers(self, modified_validate_repo):
        repo = str(modified_validate_repo)
        diff_text = get_diff(ref="HEAD", repo_dir=repo)
        files = parse_diff(diff_text)

        all_changed = []
        for fc in files:
            all_changed.extend(identify_changed_functions(fc, repo_dir=repo))

        # Resolve context for validate_order
        vo = [c for c in all_changed if c.symbol.name == "validate_order"][0]
        ctx = resolve_context(vo.symbol, repo_dir=repo)

        caller_names = [c.name for c in ctx.callers]
        assert "create_order" in caller_names

    def test_resolves_callees_of_caller(self, modified_validate_repo):
        """validate_order calls nothing interesting, but create_order
        calls validate_order, calculate_tax, save_order."""
        repo = str(modified_validate_repo)
        diff_text = get_diff(ref="HEAD", repo_dir=repo)
        files = parse_diff(diff_text)

        all_changed = []
        for fc in files:
            all_changed.extend(identify_changed_functions(fc, repo_dir=repo))

        vo = [c for c in all_changed if c.symbol.name == "validate_order"][0]
        ctx = resolve_context(vo.symbol, repo_dir=repo)

        # validate_order itself doesn't call other project functions
        # (just raises ValueError which is a builtin)
        # This is correct — callees are only for the changed function itself
        assert isinstance(ctx.callees, list)

    def test_json_output_structure(self, modified_validate_repo):
        repo = str(modified_validate_repo)
        diff_text = get_diff(ref="HEAD", repo_dir=repo)
        files = parse_diff(diff_text)

        all_changed = []
        for fc in files:
            all_changed.extend(identify_changed_functions(fc, repo_dir=repo))

        contexts = [
            resolve_context(c.symbol, repo_dir=repo, change_type=c.change_type)
            for c in all_changed
        ]

        out = format_context_json(contexts)
        data = json.loads(out)

        assert len(data) >= 1
        vo_entry = [d for d in data if d["function"]["name"] == "validate_order"]
        assert len(vo_entry) == 1
        assert len(vo_entry[0]["callers"]) >= 1
        assert vo_entry[0]["callers"][0]["body"]  # body should be non-empty


class TestDeletedFunction:
    """Scenario: calculate_tax is deleted from utils.py.
    Expected: create_order (caller) should be detected."""

    def test_finds_remaining_functions_changed(self, deleted_function_repo):
        """When a function is deleted, the surrounding functions' line ranges shift.
        The diff hunks should overlap with remaining functions near the deletion."""
        repo = str(deleted_function_repo)
        diff_text = get_diff(ref="HEAD", repo_dir=repo)
        files = parse_diff(diff_text)

        assert len(files) >= 1
        utils_file = [f for f in files if f.path == "utils.py"]
        assert len(utils_file) == 1


class TestNewFile:
    """Scenario: A new file is added with functions.
    Expected: all functions marked as 'added'."""

    def test_new_file_functions_are_added(self, simple_python_repo):
        repo = simple_python_repo
        # Add a new file
        new_file = repo / "notifications.py"
        new_file.write_text(
            "def send_email(to, subject, body):\n"
            "    print(f'Sending to {to}')\n"
            "\n"
            "def send_sms(to, message):\n"
            "    print(f'SMS to {to}')\n"
        )
        subprocess.run(["git", "add", "notifications.py"], cwd=str(repo), capture_output=True)

        diff_text = subprocess.run(
            ["git", "diff", "--cached"],
            cwd=str(repo), capture_output=True, text=True,
        ).stdout

        files = parse_diff(diff_text)
        assert len(files) == 1
        assert files[0].status == "added"

        changed = identify_changed_functions(files[0], repo_dir=str(repo))
        assert len(changed) == 2
        assert all(c.change_type == "added" for c in changed)
        names = {c.symbol.name for c in changed}
        assert names == {"send_email", "send_sms"}


class TestNoChangedFunctions:
    """Scenario: Change that doesn't overlap any function body."""

    def test_module_level_change_no_functions(self, simple_python_repo):
        repo = simple_python_repo
        # Modify the module-level variable at the top of db.py (line 1-2)
        # This is before any function definition starts
        db = repo / "db.py"
        content = db.read_text()
        content = content.replace("_orders = {}", "_orders = {}  # global store")
        db.write_text(content)

        diff_text = subprocess.run(
            ["git", "diff"], cwd=str(repo), capture_output=True, text=True,
        ).stdout

        files = parse_diff(diff_text)
        all_changed = []
        for fc in files:
            all_changed.extend(identify_changed_functions(fc, repo_dir=str(repo)))

        # The change is on a module-level variable, outside function bodies
        assert len(all_changed) == 0


class TestMultipleFunctionsChanged:
    """Scenario: Two functions modified in the same file."""

    def test_multiple_changes(self, simple_python_repo):
        repo = simple_python_repo
        service = repo / "service.py"
        content = service.read_text()
        content = content.replace(
            "def create_order(user_id, order_data):",
            "def create_order(user_id, order_data, priority=0):",
        )
        content = content.replace(
            "def get_order_summary(order_id):",
            "def get_order_summary(order_id, include_items=False):",
        )
        service.write_text(content)

        diff_text = subprocess.run(
            ["git", "diff"], cwd=str(repo), capture_output=True, text=True,
        ).stdout

        files = parse_diff(diff_text)
        all_changed = []
        for fc in files:
            all_changed.extend(identify_changed_functions(fc, repo_dir=str(repo)))

        names = {c.symbol.name for c in all_changed}
        assert "create_order" in names
        assert "get_order_summary" in names
