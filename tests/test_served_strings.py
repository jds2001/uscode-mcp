"""Consumer-facing strings never expose specification-internal identifiers."""

import ast
import json
import re
from pathlib import Path

from uscode_mcp import htmltext, superseded
from uscode_mcp.govinfo import UpstreamResponse

INTERNAL_IDENTIFIER = re.compile(r"\b[OREFSQ]\d{1,3}[a-z]?\b|WO-\d+")
CONSUMER_MODULES = ("htmltext.py", "server.py", "superseded.py", "tools.py")


def _response_literals(path: Path):
    """Yield every string literal except module, class, and function docstrings."""
    tree = ast.parse(path.read_text())
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    for node in ast.walk(tree):
        if id(node) not in docstrings and isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _assert_clean(value):
    if isinstance(value, str):
        assert not INTERNAL_IDENTIFIER.search(value), value
    elif isinstance(value, dict):
        for key, item in value.items():
            _assert_clean(key)
            _assert_clean(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_clean(item)


def test_every_response_literal_is_free_of_internal_identifiers():
    source = Path(__file__).parents[1] / "src" / "uscode_mcp"
    for name in CONSUMER_MODULES:
        for value in _response_literals(source / name):
            assert not INTERNAL_IDENTIFIER.search(value), f"{name}: {value}"


def test_representative_derived_responses_and_all_detector_states_are_clean():
    base = {
        "query": 'collection:PLAW uscodecitation:"17 U.S.C. 107"',
        "since": "2025-01-07",
        "currentthrough": "2025-01-06",
        "checked_citation": "17 U.S.C. 107",
    }
    responses = [
        superseded.render(
            superseded.DetectorOutcome(
                response=UpstreamResponse(200, {}, json.dumps({"count": 0, "results": []}), "https://example.test")
            ),
            **base,
        ),
        superseded.render(
            superseded.DetectorOutcome(
                response=UpstreamResponse(
                    200,
                    {},
                    json.dumps({"count": 1, "results": [{"packageId": "PLAW-119publ1"}]}),
                    "https://example.test",
                )
            ),
            **base,
        ),
        superseded.render(superseded.DetectorOutcome(error_reason="transport_error"), **base),
        htmltext.window_text("abcdefghij", max_chars=4),
        htmltext.html_to_text_with_structure("<p>text</p>")[1],
    ]
    _assert_clean(responses)


def test_no_served_literal_addresses_the_reader_with_you_must_read():
    source = Path(__file__).parents[1] / "src" / "uscode_mcp"
    for path in source.glob("*.py"):
        for value in _response_literals(path):
            assert "YOU MUST READ" not in value, f"{path.name}: {value}"
