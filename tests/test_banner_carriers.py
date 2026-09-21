"""The experimental truncation-banner carrier switch."""

import json

import fx
import httpx
import pytest

from uscode_mcp import tools
from uscode_mcp.htmltext import BANNER_CARRIERS_ENV_VAR
from uscode_mcp.server import create_server


def _payload(result):
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    return json.loads(result.content[0].text)


def _section_handler(request):
    if request.url.path == "/search":
        return fx.json_response(fx.search_response([fx.usc_hit()]))
    if request.url.path.endswith("/htm"):
        return httpx.Response(200, text=fx.SECTION_HTML)
    raise AssertionError(f"unexpected request: {request.method} {request.url}")


def _law_handler(request):
    if request.url.path == "/search":
        return fx.json_response(fx.search_response([fx.plaw_hit()]))
    if request.url.path.endswith("/summary"):
        return fx.json_response(fx.plaw_summary())
    if request.url.path.endswith("/htm"):
        return httpx.Response(200, text=fx.PLAW_HTML)
    raise AssertionError(f"unexpected request: {request.method} {request.url}")


@pytest.mark.parametrize(
    ("tool_name", "arguments", "handler"),
    [
        ("get_us_code_section", {"citation": "17 U.S.C. 107", "max_chars": 20}, _section_handler),
        ("get_public_law", {"congress": 118, "law_number": 31, "max_chars": 20}, _law_handler),
    ],
)
async def test_all_three_modes_change_only_the_specified_carriers(
    monkeypatch, make_client, tool_name, arguments, handler
):
    responses = {}
    for mode in ("both", "field", "content"):
        tools.CURRENTTHROUGH_MEMORY.clear()
        monkeypatch.setenv(BANNER_CARRIERS_ENV_VAR, mode)
        server = create_server(client=make_client(handler))
        responses[mode] = _payload(await server.call_tool(tool_name, arguments))

    both = responses["both"]
    field = responses["field"]
    content = responses["content"]
    assert {key: value for key, value in both.items() if key != "text"} == {
        key: value for key, value in field.items() if key != "text"
    }
    assert {key: value for key, value in both.items() if key != "text"} == {
        key: value for key, value in content.items() if key != "text"
    }

    both_text = both["text"]
    field_text = field["text"]
    content_text = content["text"]
    common_keys = set(both_text) - {"banner", "content", "message"}
    assert {key: both_text[key] for key in common_keys} == {key: field_text[key] for key in common_keys}
    assert {key: both_text[key] for key in common_keys} == {key: content_text[key] for key in common_keys}

    banner, payload = both_text["content"].split("\n", 1)
    assert both_text["banner"] == banner
    assert field_text["banner"] == banner
    assert field_text["content"] == payload
    assert "banner" not in content_text
    assert content_text["content"] == both_text["content"]
    coordinate_sentence = "The same disclosure leads `content` as a banner line"
    assert coordinate_sentence in both_text["message"]
    assert coordinate_sentence not in field_text["message"]
    assert content_text["message"] == both_text["message"]


async def test_unset_is_identical_to_both(monkeypatch, make_client):
    monkeypatch.delenv(BANNER_CARRIERS_ENV_VAR, raising=False)
    unset = create_server(client=make_client(_law_handler))
    unset_payload = _payload(
        await unset.call_tool("get_public_law", {"congress": 118, "law_number": 31, "max_chars": 20})
    )
    monkeypatch.setenv(BANNER_CARRIERS_ENV_VAR, "both")
    explicit = create_server(client=make_client(_law_handler))
    explicit_payload = _payload(
        await explicit.call_tool("get_public_law", {"congress": 118, "law_number": 31, "max_chars": 20})
    )
    assert unset_payload == explicit_payload


@pytest.mark.parametrize("value", ["", " ", "invalid", "BOTH"])
def test_invalid_or_blank_value_fails_at_startup_and_names_the_variable(monkeypatch, value):
    monkeypatch.setenv(BANNER_CARRIERS_ENV_VAR, value)
    with pytest.raises(RuntimeError, match=BANNER_CARRIERS_ENV_VAR):
        create_server()
