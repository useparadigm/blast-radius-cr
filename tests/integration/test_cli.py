"""CLI smoke tests — verify the CLI runs without crashing."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from blast_radius.cli import main

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "simple-python"


@pytest.fixture
def cli_repo(tmp_path):
    """Create a git repo with a breaking change ready to analyze."""
    for f in FIXTURES_DIR.iterdir():
        if f.is_file():
            shutil.copy2(f, tmp_path / f.name)

    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, env=env, check=True)

    # Apply a breaking change
    utils = tmp_path / "utils.py"
    content = utils.read_text()
    content = content.replace(
        "def validate_order(order_data):",
        "def validate_order(order_data, strict=False):",
    )
    utils.write_text(content)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "breaking change"], cwd=tmp_path, capture_output=True, env=env, check=True)

    return tmp_path


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "blast radius" in result.output.lower()
    assert "--ref" in result.output
    assert "--no-ai" in result.output


def test_no_ai_markdown(cli_repo):
    runner = CliRunner()
    result = runner.invoke(main, ["--no-ai", "--repo", str(cli_repo)])
    assert result.exit_code == 0
    assert "validate_order" in result.output


def test_no_ai_json(cli_repo):
    runner = CliRunner()
    result = runner.invoke(main, ["--no-ai", "--format", "json", "--repo", str(cli_repo)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) >= 1
    assert data[0]["function"]["name"] == "validate_order"


def test_no_ai_verbose(cli_repo):
    runner = CliRunner()
    result = runner.invoke(main, ["--no-ai", "--verbose", "--repo", str(cli_repo)])
    assert result.exit_code == 0
    assert "validate_order" in result.output


def test_no_ai_output_file(cli_repo):
    out = cli_repo / "report.md"
    runner = CliRunner()
    result = runner.invoke(main, ["--no-ai", "--output", str(out), "--repo", str(cli_repo)])
    assert result.exit_code == 0
    assert out.exists()
    assert "validate_order" in out.read_text()


def test_no_changes(tmp_path):
    """Repo with no changes should exit cleanly."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    (tmp_path / "hello.py").write_text("x = 1\n")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, env=env, check=True)

    runner = CliRunner()
    result = runner.invoke(main, ["--no-ai", "--repo", str(tmp_path)])
    # Should exit 0 with a "no changes" message (exit code 0 from sys.exit(0))
    assert result.exit_code == 0
