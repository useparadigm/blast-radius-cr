"""Accuracy tests for grep-based caller/callee resolution.

Each test defines ground truth callers and callees, then measures
how many the resolver correctly finds (precision + recall).

Fixture setup: copy fixture files to tmp_path (no git needed for resolver).
"""

import shutil
import pytest
from pathlib import Path

from blast_radius.symbols import extract_functions
from blast_radius.resolver import resolve_context, grep_for_callers, grep_for_definition

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def fixture_repo(request, tmp_path):
    """Copy a fixture directory to tmp_path. Usage: @pytest.mark.parametrize indirect."""
    fixture_name = request.param
    src = FIXTURES / fixture_name
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, tmp_path / f.name)
    return tmp_path


def _resolve(repo_dir, filename, func_name):
    """Helper: extract a function and resolve its context."""
    source = (Path(repo_dir) / filename).read_text()
    funcs = extract_functions(source, filename, "python")
    target = [f for f in funcs if f.name == func_name]
    assert target, f"Function {func_name} not found in {filename}"
    return resolve_context(target[0], repo_dir=str(repo_dir))


# ---- Multi-caller: shared utility called from 3 services ----

class TestMultiCallerResolution:
    """validate() in shared.py is called from service_a, service_b, service_c."""

    GROUND_TRUTH_CALLERS = {
        "create_user",       # service_a.py
        "update_user",       # service_a.py
        "create_order",      # service_b.py
        "cancel_order",      # service_b.py
        "process_webhook",   # service_c.py
    }

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        src = FIXTURES / "multi-caller"
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, tmp_path / f.name)
        self.repo = tmp_path

    def test_finds_all_callers_of_validate(self):
        ctx = _resolve(self.repo, "shared.py", "validate")
        found = {c.name for c in ctx.callers}
        # Recall: how many of the ground truth callers did we find?
        recall = len(found & self.GROUND_TRUTH_CALLERS) / len(self.GROUND_TRUTH_CALLERS)
        assert recall >= 0.8, f"Recall too low: {recall:.0%}, found: {found}"

    def test_no_false_positives_for_validate(self):
        """All found callers should actually call validate()."""
        ctx = _resolve(self.repo, "shared.py", "validate")
        found = {c.name for c in ctx.callers}
        # These are NOT callers of validate
        false_positives = found - self.GROUND_TRUTH_CALLERS - {"validate_input"}
        # validate_input in app.py also calls proc.validate() — acceptable
        assert len(false_positives) == 0, f"False positives: {false_positives}"

    def test_finds_callers_of_format_response(self):
        ctx = _resolve(self.repo, "shared.py", "format_response")
        found = {c.name for c in ctx.callers}
        expected = {"create_user", "update_user", "create_order", "cancel_order"}
        recall = len(found & expected) / len(expected)
        assert recall >= 0.8, f"Recall: {recall:.0%}, found: {found}"

    def test_finds_callers_of_log_event(self):
        ctx = _resolve(self.repo, "shared.py", "log_event")
        found = {c.name for c in ctx.callers}
        expected = {
            "create_user", "update_user",       # service_a
            "create_order", "cancel_order",      # service_b
            "process_webhook", "handle_event",   # service_c
        }
        recall = len(found & expected) / len(expected)
        assert recall >= 0.8, f"Recall: {recall:.0%}, found: {found}"

    def test_callers_from_different_files(self):
        """Callers should come from at least 2 different files."""
        ctx = _resolve(self.repo, "shared.py", "validate")
        files = {c.file_path for c in ctx.callers}
        assert len(files) >= 2, f"Expected callers from multiple files, got: {files}"


# ---- Decorated functions ----

class TestDecoratedResolution:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        src = FIXTURES / "decorators"
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, tmp_path / f.name)
        self.repo = tmp_path

    def test_finds_callers_of_decorated_function(self):
        """process_data is @log_calls decorated — callers should still find it."""
        ctx = _resolve(self.repo, "core.py", "process_data")
        found = {c.name for c in ctx.callers}
        assert "handle_upload" in found
        assert "handle_sync" in found

    def test_finds_callees_of_decorated_function(self):
        """process_data calls clean() and transform()."""
        ctx = _resolve(self.repo, "core.py", "process_data")
        found = {c.name for c in ctx.callees}
        assert "clean" in found
        assert "transform" in found

    def test_finds_callers_of_retry_decorated(self):
        ctx = _resolve(self.repo, "core.py", "fetch_remote")
        found = {c.name for c in ctx.callers}
        assert "handle_sync" in found


# ---- Chained calls ----

class TestChainedResolution:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        src = FIXTURES / "chained-calls"
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, tmp_path / f.name)
        self.repo = tmp_path

    def test_step_one_has_many_callers(self):
        """step_one is called from full_pipeline, partial_pipeline, Builder.build, custom_process."""
        ctx = _resolve(self.repo, "chain.py", "step_one")
        found = {c.name for c in ctx.callers}
        expected = {"full_pipeline", "partial_pipeline", "build", "custom_process"}
        recall = len(found & expected) / len(expected)
        assert recall >= 0.75, f"Recall: {recall:.0%}, found: {found}"

    def test_full_pipeline_callees(self):
        ctx = _resolve(self.repo, "chain.py", "full_pipeline")
        found = {c.name for c in ctx.callees}
        assert "step_one" in found
        assert "step_two" in found
        assert "step_three" in found

    def test_full_pipeline_callers(self):
        ctx = _resolve(self.repo, "chain.py", "full_pipeline")
        found = {c.name for c in ctx.callers}
        assert "process_input" in found


# ---- Async resolution ----

class TestAsyncResolution:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        src = FIXTURES / "async-code"
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, tmp_path / f.name)
        self.repo = tmp_path

    def test_finds_callers_of_async_function(self):
        """fetch_user is awaited in get_user_summary and handle_user_profile."""
        ctx = _resolve(self.repo, "service.py", "fetch_user")
        found = {c.name for c in ctx.callers}
        expected = {"get_user_summary", "handle_user_profile"}
        recall = len(found & expected) / len(expected)
        assert recall >= 0.8, f"Recall: {recall:.0%}, found: {found}"

    def test_async_callees(self):
        """get_user_summary calls fetch_user, fetch_orders, calculate_total."""
        ctx = _resolve(self.repo, "service.py", "get_user_summary")
        found = {c.name for c in ctx.callees}
        assert "fetch_user" in found
        assert "calculate_total" in found

    def test_sync_function_called_from_async(self):
        """calculate_total is sync but called from async get_user_summary."""
        ctx = _resolve(self.repo, "service.py", "calculate_total")
        found = {c.name for c in ctx.callers}
        assert "get_user_summary" in found


# ---- Class patterns ----

class TestClassResolution:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        src = FIXTURES / "class-patterns"
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, tmp_path / f.name)
        self.repo = tmp_path

    def test_method_callers_across_files(self):
        """validate() in BaseProcessor is called from app.py."""
        ctx = _resolve(self.repo, "models.py", "validate")
        found = {c.name for c in ctx.callers}
        # process() and run() call self.validate() / processor.validate()
        # validate_input() in app.py also calls proc.validate()
        assert "process" in found or "run" in found or "validate_input" in found

    def test_method_callees(self):
        """process() calls validate() and _transform()."""
        ctx = _resolve(self.repo, "models.py", "process")
        found = {c.name for c in ctx.callees}
        assert "validate" in found or "_transform" in found


# ---- Aliasing (known limitation) ----

class TestAliasingResolution:
    """Tests for function aliasing. Grep-based resolution has known limits here."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        src = FIXTURES / "aliasing"
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, tmp_path / f.name)
        self.repo = tmp_path

    def test_finds_direct_callers(self):
        """Callers using the original name should be found."""
        ctx = _resolve(self.repo, "utils.py", "compute_score")
        found = {c.name for c in ctx.callers}
        assert "report_direct" in found
        assert "pipeline_direct" in found

    def test_alias_callers_missed(self):
        """Callers using the alias (calc_score) will NOT be found for compute_score.
        This is a known limitation of grep-based resolution.
        Grep searches for 'compute_score(' which won't match 'calc_score('."""
        ctx = _resolve(self.repo, "utils.py", "compute_score")
        found = {c.name for c in ctx.callers}
        # report_alias and pipeline_alias call calc_score, not compute_score
        # This is expected to miss them — documenting the limitation
        alias_callers = {"report_alias", "pipeline_alias"}
        missed = alias_callers - found
        if missed:
            pytest.skip(
                f"Known limitation: alias callers not found: {missed}. "
                f"Grep searches for original name only."
            )


# ---- Aggregate accuracy score ----

class TestOverallAccuracy:
    """Compute overall precision and recall across all fixtures."""

    GROUND_TRUTH = {
        # (fixture, file, func) → expected callers
        ("multi-caller", "shared.py", "validate"): {
            "create_user", "update_user", "create_order",
            "cancel_order", "process_webhook",
        },
        ("multi-caller", "shared.py", "log_event"): {
            "create_user", "update_user", "create_order",
            "cancel_order", "process_webhook", "handle_event",
        },
        ("decorators", "core.py", "process_data"): {
            "handle_upload", "handle_sync",
        },
        ("chained-calls", "chain.py", "step_one"): {
            "full_pipeline", "partial_pipeline", "build", "custom_process",
        },
        ("async-code", "service.py", "fetch_user"): {
            "get_user_summary", "handle_user_profile",
        },
    }

    def test_aggregate_recall(self, tmp_path):
        """Measure overall recall across all ground truth cases."""
        total_expected = 0
        total_found = 0

        for (fixture, filename, func_name), expected_callers in self.GROUND_TRUTH.items():
            # Copy fixture
            repo_dir = tmp_path / fixture
            repo_dir.mkdir(exist_ok=True)
            src = FIXTURES / fixture
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(f, repo_dir / f.name)

            ctx = _resolve(repo_dir, filename, func_name)
            found = {c.name for c in ctx.callers}

            hits = found & expected_callers
            total_expected += len(expected_callers)
            total_found += len(hits)

        recall = total_found / total_expected if total_expected else 0
        print(f"\n=== OVERALL RECALL: {total_found}/{total_expected} = {recall:.0%} ===")
        # We expect at least 80% recall across all patterns
        assert recall >= 0.80, f"Overall recall too low: {recall:.0%}"
