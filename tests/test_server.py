"""Server wiring: the four tools are registered, their descriptions carry the
spec-mandated caveats, and calls route through to the tool layer."""

import json
import re

import fx
import httpx

from uscode_mcp.govinfo import UpstreamResponse
from uscode_mcp.server import create_server

INTERNAL_IDENTIFIER = re.compile(r"\b[OREFSQ]\d{1,3}[a-z]?\b|WO-\d+")

EXPECTED_TOOLS = {"get_us_code_section", "search_us_code", "get_public_law", "search_public_laws"}


class _LifecycleClient:
    def __init__(self, *, close_error=False):
        self.close_calls = 0
        self.search_calls = 0
        self.close_error = close_error

    async def search(self, body):
        self.search_calls += 1
        return UpstreamResponse(
            status=200,
            headers={},
            text=json.dumps(fx.search_response([])),
            url="https://api.govinfo.gov/search",
        )

    async def aclose(self):
        self.close_calls += 1
        if self.close_error:
            raise RuntimeError("close failed")


def _lifespan(server):
    assert server.settings.lifespan is not None
    return server.settings.lifespan(server)


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


async def test_served_surface_has_no_internal_identifiers_or_source_indentation():
    from uscode_mcp.server import SERVER_INSTRUCTIONS

    listed = await create_server().list_tools()
    served_strings = [SERVER_INSTRUCTIONS]
    for tool in listed:
        served_strings.append(tool.description or "")
        served_strings.extend(_strings(tool.input_schema))
        served_strings.extend(_strings(tool.output_schema))

    assert not [value for value in served_strings if INTERNAL_IDENTIFIER.search(value)]
    assert all("YOU MUST READ" not in value for value in served_strings)
    assert all("  " not in (tool.description or "") for tool in listed)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


async def test_search_public_laws_description_carries_recipe_and_recall_caveat():
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["search_public_laws"]
    assert "uscodecitation" in tool.description
    assert "never evidence" in tool.description
    assert "25/33" in tool.description
    assert "structural" in tool.description
    assert "complete" in tool.description


async def test_get_public_law_description_states_private_law_scope():
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["get_public_law"]
    assert "private-law" in tool.description
    assert "out-of-scope" in tool.description


async def test_get_public_law_description_says_numbered_path_is_the_public_series():
    """WO-5 change 3 (F4): congress + law_number names the public series only."""
    server = create_server()
    flat = " ".join({t.name: t for t in await server.list_tools()}["get_public_law"].description.split())
    assert "PUBLIC-law series only" in flat
    assert "Private Law 118-1" in flat
    assert "out-of-scope outcome" in flat


async def test_search_descriptions_carry_the_packageid_recipe():
    """WO-5 change 2 (F6b, O30): within-title / within-law scoping by package, with the
    presence-not-location caveat on both."""
    server = create_server()
    by_name = {t.name: t for t in await server.list_tools()}
    usc = " ".join(by_name["search_us_code"].description.split())
    plaw = " ".join(by_name["search_public_laws"].description.split())
    assert "packageid:USCODE-2024-title17" in usc
    assert "packageid:PLAW-118publ31" in plaw
    assert "`find`" in usc and "`find`" in plaw
    assert "not where" in usc and "not where" in plaw


async def test_search_descriptions_state_the_collection_boundary():
    server = create_server()
    by_name = {t.name: " ".join(t.description.split()) for t in await server.list_tools()}
    assert "collection:USCODE" in by_name["search_us_code"]
    assert "any other collection clause is refused before searching" in by_name["search_us_code"]
    assert "collection:PLAW" in by_name["search_public_laws"]
    assert "any other collection clause is refused before searching" in by_name["search_public_laws"]


async def test_search_public_laws_description_names_publishdate_not_approveddate_ranges():
    """WO-5 change 1 (F6a, O43f/O49a): approveddate ranges return HTTP 500 upstream."""
    server = create_server()
    flat = " ".join({t.name: t for t in await server.list_tools()}["search_public_laws"].description.split())
    assert "publishdate:range(YYYY-MM-DD,)" in flat
    assert "approveddate:range(...)" not in flat.replace("do NOT use `approveddate:range(...)`", "")
    assert "do NOT use `approveddate:range(...)`" in flat
    assert "HTTP 500" in flat
    assert "not evidence of absence" in flat


async def test_search_us_code_description_says_historical_is_an_argument():
    """O49b: a consumer typed historical:true into the query string and got a 500."""
    server = create_server()
    flat = " ".join({t.name: t for t in await server.list_tools()}["search_us_code"].description.split())
    assert "`historical` ARGUMENT (not a query term)" in flat


async def test_get_us_code_section_description_promises_notes():
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["get_us_code_section"]
    assert "notes" in tool.description
    assert "currentthrough" in tool.description


async def test_get_us_code_section_description_states_the_indicator_contract():
    """R14a: the description names all three states and says the indicator certifies nothing."""
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["get_us_code_section"]
    for token in ("possibly_superseded", "laws_indexed", "none_indexed", "not_checked"):
        assert token in tool.description
    assert "NEVER A CERTIFICATION" in tool.description
    assert "NOT" in tool.description and "evidence the text is current" in tool.description
    assert "one in seven" in tool.description


async def test_server_instructions_describe_the_indicator():
    from uscode_mcp.server import SERVER_INSTRUCTIONS

    assert "possibly_superseded" in SERVER_INSTRUCTIONS
    assert "not_checked" in SERVER_INSTRUCTIONS
    assert "never a certification" in SERVER_INSTRUCTIONS


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


async def test_lifespan_closes_server_created_client_exactly_once(monkeypatch):
    client = _LifecycleClient()
    monkeypatch.setattr("uscode_mcp.server.client_from_env", lambda: client)
    server = create_server()

    async with _lifespan(server):
        await server.call_tool("search_us_code", {"query": "x"})
        assert client.close_calls == 0

    assert client.search_calls == 1
    assert client.close_calls == 1


async def test_lifespan_never_closes_injected_client():
    client = _LifecycleClient()
    server = create_server(client=client)

    async with _lifespan(server):
        await server.call_tool("search_us_code", {"query": "x"})

    assert client.search_calls == 1
    assert client.close_calls == 0


async def test_lifespan_does_not_create_client_only_to_close_it(monkeypatch):
    created = []
    monkeypatch.setattr("uscode_mcp.server.client_from_env", lambda: created.append(_LifecycleClient()))
    server = create_server()

    async with _lifespan(server):
        pass

    assert created == []


async def test_client_close_failure_does_not_mask_shutdown(monkeypatch, caplog):
    client = _LifecycleClient(close_error=True)
    monkeypatch.setattr("uscode_mcp.server.client_from_env", lambda: client)
    server = create_server()

    async with _lifespan(server):
        await server.call_tool("search_us_code", {"query": "x"})

    assert client.close_calls == 1
    assert "failed to close" in caplog.text


async def test_create_server_registers_tracing_middleware(tmp_path):
    from uscode_mcp.trace import Tracer, TracingMiddleware

    server = create_server(tracer=Tracer(tmp_path))
    assert any(isinstance(m, TracingMiddleware) for m in server.middleware)


async def test_create_server_without_tracer_registers_no_tracing_middleware(monkeypatch):
    from uscode_mcp.trace import TRACE_DIR_ENV_VAR, TracingMiddleware

    monkeypatch.delenv(TRACE_DIR_ENV_VAR, raising=False)
    server = create_server()
    assert not any(isinstance(m, TracingMiddleware) for m in server.middleware)


async def test_create_server_fails_at_startup_on_unusable_trace_dir(monkeypatch, tmp_path):
    from uscode_mcp.trace import TRACE_DIR_ENV_VAR

    blocker = tmp_path / "blocker"
    blocker.write_text("file, not dir")
    monkeypatch.setenv(TRACE_DIR_ENV_VAR, str(blocker))
    import pytest

    with pytest.raises(RuntimeError, match=TRACE_DIR_ENV_VAR):
        create_server()


async def test_create_server_fails_at_startup_on_blank_trace_dir(monkeypatch):
    from uscode_mcp.trace import TRACE_DIR_ENV_VAR

    monkeypatch.setenv(TRACE_DIR_ENV_VAR, "")
    import pytest

    with pytest.raises(RuntimeError, match="set but blank"):
        create_server()
