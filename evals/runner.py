"""Clone repos, apply patches, run blast-radius, capture output."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

EVALS_DIR = Path(__file__).parent
FIXTURES_DIR = EVALS_DIR / "fixtures"
BLAST_RADIUS_SRC = str(EVALS_DIR.parent / "src")


@dataclass
class CaseResult:
    case_id: str
    blast_radius_output: str = ""
    verdict: str = ""
    exit_code: int = -1
    error: str = ""
    repo_dir: str = ""
    callers_found: list[str] = field(default_factory=list)


def clone_and_patch(
    repo: str,
    base_ref: str,
    patch_file: str,
    work_dir: str,
    case_id: str = "",
) -> str:
    """Clone repo at base_ref, apply patch, commit. Returns repo path."""
    repo_url = f"https://github.com/{repo}.git"
    dir_name = case_id or repo.split("/")[-1]
    repo_dir = os.path.join(work_dir, dir_name)

    # Full clone — these are small repos (<30K LOC) and we need
    # the exact commit for reproducibility
    r = subprocess.run(
        ["git", "clone", repo_url, repo_dir],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git clone failed: {r.stderr}")

    r = subprocess.run(
        ["git", "checkout", base_ref],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git checkout failed: {r.stderr}")

    # Apply patch (patch_file is relative to evals/ dir)
    patch_path = EVALS_DIR / patch_file
    subprocess.run(
        ["git", "apply", str(patch_path)],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    # Commit the change so blast-radius can diff against HEAD~1
    subprocess.run(
        ["git", "add", "-A"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=eval", "-c", "user.email=eval@test",
         "commit", "-m", "eval: inject breaking change"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    return repo_dir


def run_blast_radius(
    repo_dir: str,
    model: str = "claude-sonnet-4-20250514",
    no_ai: bool = False,
) -> tuple[str, str, int]:
    """Run blast-radius on repo. Returns (stdout, stderr, exit_code)."""
    cmd = [
        sys.executable, "-m", "blast_radius.cli",
        "--ref", "HEAD~1",
        "--repo", repo_dir,
        "--verbose",
        "--format", "markdown",
        "--max-callers", "50",
    ]
    if no_ai:
        cmd.append("--no-ai")
    else:
        cmd.extend(["--model", model])

    env = os.environ.copy()
    env["PYTHONPATH"] = BLAST_RADIUS_SRC + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    return result.stdout, result.stderr, result.returncode


def run_case(case: dict, work_dir: str, model: str = "claude-sonnet-4-20250514") -> CaseResult:
    """Run a single eval case. Returns CaseResult."""
    result = CaseResult(case_id=case["id"])

    try:
        # Clone and patch
        repo_dir = clone_and_patch(
            repo=case["repo"],
            base_ref=case["base_ref"],
            patch_file=case["patch_file"],
            work_dir=work_dir,
            case_id=case["id"],
        )
        result.repo_dir = repo_dir

        # Run blast-radius
        stdout, stderr, exit_code = run_blast_radius(repo_dir, model=model)
        result.blast_radius_output = stdout
        result.exit_code = exit_code

        # Parse verdict from stderr (--verbose prints it)
        for line in stderr.splitlines():
            if "Verdict:" in line:
                result.verdict = line.split("Verdict:")[-1].strip()

        # If no verdict parsed from stderr, try to parse from stdout
        if not result.verdict:
            for line in stdout.splitlines()[:5]:
                upper = line.upper()
                if "VERDICT" in upper:
                    if "FAIL" in upper:
                        result.verdict = "FAIL"
                    elif "WARNING" in upper:
                        result.verdict = "WARNING"
                    elif "PASS" in upper:
                        result.verdict = "PASS"
                    break

        if not result.verdict:
            result.verdict = "UNKNOWN"

        # Collect stderr for debugging
        if stderr:
            result.error = stderr

    except subprocess.TimeoutExpired:
        result.error = "Timed out after 120 seconds"
    except subprocess.CalledProcessError as e:
        result.error = f"Command failed: {e.cmd}\nstderr: {e.stderr}\nstdout: {e.stdout}"
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"

    return result
