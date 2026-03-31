"""Tests for report formatting."""

import json

from blast_radius.resolver import FunctionContext
from blast_radius.symbols import FunctionSymbol
from blast_radius.report import format_context_json, format_context_markdown


def _make_context():
    func = FunctionSymbol(
        name="validate_order",
        file_path="utils.py",
        start_line=1,
        end_line=5,
        body="def validate_order(order_data):\n    pass",
    )
    caller = FunctionSymbol(
        name="create_order",
        file_path="service.py",
        start_line=3,
        end_line=10,
        body="def create_order(user_id, order_data):\n    validate_order(order_data)",
        containing_class=None,
    )
    callee = FunctionSymbol(
        name="save_order",
        file_path="db.py",
        start_line=1,
        end_line=5,
        body="def save_order(data):\n    pass",
    )
    return FunctionContext(
        function=func,
        callers=[caller],
        callees=[callee],
        change_type="modified",
    )


def test_markdown_output():
    ctx = _make_context()
    md = format_context_markdown([ctx])
    assert "# Blast Radius" in md
    assert "validate_order" in md
    assert "create_order" in md
    assert "save_order" in md
    assert "Callers (1)" in md
    assert "Callees (1)" in md


def test_json_output():
    ctx = _make_context()
    out = format_context_json([ctx])
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["function"]["name"] == "validate_order"
    assert len(data[0]["callers"]) == 1
    assert data[0]["callers"][0]["name"] == "create_order"
    assert len(data[0]["callees"]) == 1


def test_empty_context():
    md = format_context_markdown([])
    assert "No changed functions found" in md


def test_json_empty():
    out = format_context_json([])
    assert json.loads(out) == []


def test_context_with_class():
    func = FunctionSymbol(
        name="process",
        file_path="service.py",
        start_line=10,
        end_line=20,
        body="def process(self, data): pass",
        containing_class="OrderService",
    )
    ctx = FunctionContext(function=func)
    md = format_context_markdown([ctx])
    assert "OrderService.process" in md
