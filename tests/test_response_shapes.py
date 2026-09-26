"""WO-11 part E: malformed 2xx bodies stay structured and traced."""

import json

import fx
import pytest

from uscode_mcp import tools
from uscode_mcp.trace import Tracer, TracingMiddleware


class _Ctx:
    method = "tools/call"

    def __init__(self, tool, arguments):
        self.params = {"name": tool, "arguments": arguments}


async def _traced(tmp_path, tool, arguments, action):
    tracer = Tracer(tmp_path)
    middleware = TracingMiddleware(tracer)

    async def call_next(ctx):
        return await action()

    result = await middleware(_Ctx(tool, arguments), call_next)
    line = json.loads(tracer.path.read_text().splitlines()[0])
    assert line["request"] == {"tool": tool, "arguments": arguments}
    assert line["response"] == result
    return result


async def _call_search_reader(tool, client):
    if tool == "search_us_code":
        return await tools.search_us_code(client, "x")
    if tool == "search_public_laws":
        return await tools.search_public_laws(client, "x")
    if tool == "get_us_code_section":
        return await tools.get_us_code_section(client, citation="17 U.S.C. 107")
    return await tools.get_public_law(client, congress=118, law_number=31)


@pytest.mark.parametrize(
    ("results", "arrived"),
    [("not-a-list", "str"), ([None], "NoneType")],
)
@pytest.mark.parametrize(
    "tool",
    ["search_us_code", "search_public_laws", "get_us_code_section", "get_public_law"],
)
async def test_wrongly_typed_search_results_are_structured_and_traced(make_client, tmp_path, results, arrived, tool):
    response = fx.json_response({"count": 1, "results": results})
    client = make_client(lambda request: response)
    arguments = (
        {"query": "x"}
        if tool.startswith("search_")
        else ({"citation": "17 U.S.C. 107"} if tool == "get_us_code_section" else {"congress": 118, "law_number": 31})
    )
    out = await _traced(tmp_path, tool, arguments, lambda: _call_search_reader(tool, client))
    assert out["outcome"] == "upstream_error"
    assert out["http_status"] == 200
    assert arrived in out["detail"]
    assert out["body"] == response.text


@pytest.mark.parametrize("tool", ["get_public_law", "get_us_code_section"])
async def test_list_valued_summary_is_structured_and_traced(make_client, tmp_path, tool):
    summary_response = fx.json_response([])

    def handler(request):
        if request.url.path == "/search":
            return fx.json_response(fx.search_response([fx.plaw_hit()]))
        return summary_response

    if tool == "get_public_law":
        client = make_client(handler)
        arguments = {"congress": 118, "law_number": 31}

        async def action():
            return await tools.get_public_law(client, **arguments)
    else:
        client = make_client(lambda request: summary_response)
        arguments = {"granule_id": "USCODE-2024-title17-chap1-sec107"}

        async def action():
            return await tools.get_us_code_section(client, **arguments)

    out = await _traced(tmp_path, tool, arguments, action)
    assert out["outcome"] == "upstream_error"
    assert out["http_status"] == 200
    assert "expected a JSON object, got list" in out["detail"]
    assert out["body"] == summary_response.text


@pytest.mark.parametrize("tool", ["get_public_law", "get_us_code_section"])
async def test_wrongly_typed_summary_download_map_is_structured(make_client, tool):
    if tool == "get_public_law":

        def handler(request):
            if request.url.path == "/search":
                return fx.json_response(fx.search_response([fx.plaw_hit()]))
            return fx.json_response({"packageId": "PLAW-118publ31", "download": []})

        out = await tools.get_public_law(make_client(handler), congress=118, law_number=31)
    else:
        summary = fx.granule_summary()
        summary["download"] = []
        out = await tools.get_us_code_section(
            make_client(lambda request: fx.json_response(summary)),
            granule_id="USCODE-2024-title17-chap1-sec107",
        )

    assert out["outcome"] == "upstream_error"
    assert out["http_status"] == 200
    assert "'download' to be an object, got list" in out["detail"]


async def test_wrongly_typed_search_hit_download_map_is_structured(make_client):
    hit = fx.usc_hit()
    hit["download"] = []
    response = fx.json_response(fx.search_response([hit]))
    out = await tools.get_us_code_section(make_client(lambda request: response), citation="17 U.S.C. 107")
    assert out["outcome"] == "upstream_error"
    assert out["http_status"] == 200
    assert "'download' to be an object, got list" in out["detail"]
    assert out["body"] == response.text
