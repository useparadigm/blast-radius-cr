"""Accuracy tests for tree-sitter symbol extraction.

Each test defines a ground truth (expected functions, expected call sites)
and measures how well tree-sitter extraction matches.
"""

import pytest
from pathlib import Path

from blast_radius.symbols import extract_functions

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _extract(fixture_dir: str, filename: str):
    source = (FIXTURES / fixture_dir / filename).read_text()
    return extract_functions(source, filename, "python")


def _by_name(funcs):
    return {f.name: f for f in funcs}


# ---- Decorated functions ----

class TestDecoratedFunctions:
    """Tree-sitter should extract decorated functions correctly."""

    def test_finds_decorated_functions(self):
        funcs = _by_name(_extract("decorators", "core.py"))
        assert "process_data" in funcs
        assert "fetch_remote" in funcs

    def test_decorated_function_call_sites(self):
        funcs = _by_name(_extract("decorators", "core.py"))
        calls = funcs["process_data"].call_sites
        assert "clean" in calls
        assert "transform" in calls

    def test_decorator_itself_is_extracted(self):
        funcs = _by_name(_extract("decorators", "core.py"))
        assert "log_calls" in funcs
        assert "retry" in funcs

    def test_inner_wrapper_extracted(self):
        """Wrapper functions inside decorators should be found."""
        funcs = _by_name(_extract("decorators", "core.py"))
        assert "wrapper" in funcs  # inner wrapper of log_calls


# ---- Class patterns ----

class TestClassPatterns:
    """Methods, inheritance, self calls."""

    def test_extracts_all_methods(self):
        funcs = _by_name(_extract("class-patterns", "models.py"))
        assert "validate" in funcs
        assert "process" in funcs
        assert "_transform" in funcs
        assert "compress" in funcs
        assert "run" in funcs
        assert "_finalize" in funcs

    def test_containing_class(self):
        funcs = _by_name(_extract("class-patterns", "models.py"))
        # validate is defined in BaseProcessor
        assert funcs["validate"].containing_class == "BaseProcessor"

    def test_overridden_methods_found(self):
        """_transform exists in BaseProcessor, JSONProcessor, XMLProcessor."""
        funcs = _extract("class-patterns", "models.py")
        transforms = [f for f in funcs if f.name == "_transform"]
        classes = {f.containing_class for f in transforms}
        assert "BaseProcessor" in classes
        assert "JSONProcessor" in classes
        assert "XMLProcessor" in classes

    def test_method_call_sites_include_self_calls(self):
        funcs = _by_name(_extract("class-patterns", "models.py"))
        # process() calls self.validate() and self._transform()
        calls = funcs["process"].call_sites
        assert "validate" in calls
        assert "_transform" in calls

    def test_pipeline_run_calls(self):
        funcs = _by_name(_extract("class-patterns", "models.py"))
        calls = funcs["run"].call_sites
        assert "validate" in calls
        assert "process" in calls
        assert "_finalize" in calls


# ---- Nested / closures ----

class TestNestedFunctions:
    """Closures, factory functions, nested defs."""

    def test_outer_function_extracted(self):
        funcs = _by_name(_extract("nested", "engine.py"))
        assert "outer_process" in funcs
        assert "make_processor" in funcs

    def test_outer_function_callees(self):
        funcs = _by_name(_extract("nested", "engine.py"))
        calls = funcs["outer_process"].call_sites
        assert "aggregate" in calls

    def test_inner_function_extracted(self):
        """Inner helper functions should be found."""
        funcs = _by_name(_extract("nested", "engine.py"))
        # inner_helper is a nested def inside outer_process
        assert "inner_helper" in funcs

    def test_class_method_with_nested_def(self):
        funcs = _by_name(_extract("nested", "engine.py"))
        assert "run" in funcs
        calls = funcs["run"].call_sites
        assert "outer_process" in calls


# ---- Async code ----

class TestAsyncFunctions:
    """async def, await expressions."""

    def test_async_functions_extracted(self):
        funcs = _by_name(_extract("async-code", "service.py"))
        assert "fetch_user" in funcs
        assert "fetch_orders" in funcs
        assert "get_user_summary" in funcs
        assert "batch_process" in funcs

    def test_sync_function_among_async(self):
        funcs = _by_name(_extract("async-code", "service.py"))
        assert "calculate_total" in funcs

    def test_async_call_sites(self):
        """await fetch_user() should extract 'fetch_user' as call site."""
        funcs = _by_name(_extract("async-code", "service.py"))
        calls = funcs["get_user_summary"].call_sites
        assert "fetch_user" in calls
        assert "fetch_orders" in calls
        assert "calculate_total" in calls

    def test_gather_call_detected(self):
        funcs = _by_name(_extract("async-code", "service.py"))
        calls = funcs["batch_process"].call_sites
        assert "get_user_summary" in calls


# ---- Chained calls ----

class TestChainedCalls:
    """Functions that call multiple other functions in sequence."""

    def test_full_pipeline_all_callees(self):
        funcs = _by_name(_extract("chained-calls", "chain.py"))
        calls = funcs["full_pipeline"].call_sites
        assert "step_one" in calls
        assert "step_two" in calls
        assert "step_three" in calls

    def test_partial_pipeline_callees(self):
        funcs = _by_name(_extract("chained-calls", "chain.py"))
        calls = funcs["partial_pipeline"].call_sites
        assert "step_one" in calls
        assert "step_three" in calls
        assert "step_two" not in calls

    def test_method_calling_functions(self):
        funcs = _by_name(_extract("chained-calls", "chain.py"))
        calls = funcs["build"].call_sites
        assert "step_one" in calls
        assert "step_two" in calls
        assert "finalize" in calls
