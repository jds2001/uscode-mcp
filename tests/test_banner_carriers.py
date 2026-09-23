"""The single consumer-facing shape for truncated text windows."""

import json

import fx
import httpx
import pytest

from uscode_mcp import tools
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
async def test_truncated_content_is_payload_only_for_both_text_tools(
    make_client, tool_name, arguments, handler
):
    response = _payload(await create_server(client=make_client(handler)).call_tool(tool_name, arguments))
    text = response["text"]

    assert text["truncated"] is True
    assert text["banner"].startswith("[WINDOW ")
    assert not text["content"].startswith("[WINDOW ")
    assert text["returned_chars"] == len(text["content"]) == 20
    assert "Continue with start_char=20." in text["message"]
    assert "banner" not in text["message"]
    assert "NOT part of the payload" not in text["message"]
    assert response["provenance"]["public_pdf_link"] in text["message"]


def test_retired_environment_variable_is_ignored(monkeypatch):
    monkeypatch.setenv("USCODE_MCP_BANNER_CARRIERS", "invalid")
    assert create_server() is not None


@pytest.mark.parametrize("tool_name", ["get_us_code_section", "get_public_law"])
async def test_zero_max_chars_teaches_the_locating_call(make_client, tool_name):
    seen = []

    def must_not_run(request):
        seen.append(request)
        raise AssertionError(f"unexpected request: {request.url}")

    if tool_name == "get_us_code_section":
        response = await tools.get_us_code_section(
            make_client(must_not_run), citation="17 U.S.C. 107", max_chars=0
        )
    else:
        response = await tools.get_public_law(
            make_client(must_not_run), congress=118, law_number=31, max_chars=0
        )

    assert response["outcome"] == "invalid_argument"
    assert "at least 1" in response["detail"]
    assert "locating call" in response["detail"]
    assert "`structure`" in response["detail"]
    assert "`find`" in response["detail"]
    assert "`max_chars: 1`" in response["detail"]
    assert seen == []
