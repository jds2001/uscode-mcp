"""Server wiring: the four tools are registered, their descriptions carry the
spec-mandated caveats, and calls route through to the tool layer."""

import json

import fx
import httpx

from uscode_mcp.server import create_server

EXPECTED_TOOLS = {"get_us_code_section", "search_us_code", "get_public_law", "search_public_laws"}


def _payload(result):
    """Extract the tool's dict payload from a CallToolResult."""
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    return json.loads(result.content[0].text)


async def test_exactly_four_tools_registered():
    server = create_server()
    listed = await server.list_tools()
    assert {t.name for t in listed} == EXPECTED_TOOLS


async def test_search_public_laws_description_carries_recipe_and_recall_caveat():
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["search_public_laws"]
    assert "uscodecitation" in tool.description
    assert "NOT evidence" in tool.description
    assert "complete" in tool.description


async def test_get_public_law_description_states_private_law_scope():
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["get_public_law"]
    assert "private-law" in tool.description
    assert "out-of-scope" in tool.description


async def test_get_us_code_section_description_promises_notes():
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["get_us_code_section"]
    assert "notes" in tool.description
    assert "currentthrough" in tool.description


async def test_call_tool_routes_to_injected_client(make_client):
    client = make_client(lambda request: fx.json_response(fx.search_response([fx.usc_hit()])))
    server = create_server(client=client)
    result = await server.call_tool("search_us_code", {"query": "fair use"})
    payload = _payload(result)
    assert payload["outcome"] == "success"
    assert payload["results"][0]["package_id"] == "USCODE-2024-title17"


async def test_call_tool_surfaces_upstream_error_as_data(make_client):
    client = make_client(lambda request: httpx.Response(500, text="err"))
    server = create_server(client=client)
    result = await server.call_tool("search_us_code", {"query": "fair use"})
    payload = _payload(result)
    assert payload["outcome"] == "upstream_error"
    assert payload["http_status"] == 500


async def test_call_tool_end_to_end_section_retrieval(make_client):
    def handler(request):
        if request.url.path == "/search":
            return fx.json_response(fx.search_response([fx.usc_hit()]))
        return httpx.Response(200, text=fx.SECTION_HTML)

    server = create_server(client=make_client(handler))
    result = await server.call_tool("get_us_code_section", {"citation": "17 U.S.C. 107"})
    payload = _payload(result)
    assert payload["outcome"] == "success"
    assert payload["provenance"]["currentthrough"] == "2025-01-06"
    assert "fair use of a copyrighted work" in payload["text"]["content"]
