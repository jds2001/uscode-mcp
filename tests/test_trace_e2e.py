"""End-to-end R8 check: drive the server through a real MCP session over in-memory
streams and verify the trace line carries the wire-level request verbatim — the
middleware sees pre-validation params, not arguments rebound with defaults."""

import json

import anyio
import fx
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from uscode_mcp.server import create_server
from uscode_mcp.trace import Tracer


async def test_real_session_tool_call_is_traced_verbatim(tmp_path, make_client):
    client = make_client(lambda request: fx.json_response(fx.search_response([fx.usc_hit()])))
    tracer = Tracer(tmp_path)
    server = create_server(client=client, tracer=tracer)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                server._lowlevel_server.run,
                server_read,
                server_write,
                server._lowlevel_server.create_initialization_options(),
            )
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                result = await session.call_tool("search_us_code", {"query": "fair use"})
                assert not result.is_error
            tg.cancel_scope.cancel()

    lines = tracer.path.read_text().splitlines()
    assert len(lines) == 1  # initialize/tools handshake traffic is not traced; the tool call is
    line = json.loads(lines[0])
    # Verbatim: exactly what the client sent, no page_size/offset_mark defaults added.
    assert line["request"] == {"tool": "search_us_code", "arguments": {"query": "fair use"}}
    assert line["response"]["structuredContent"]["outcome"] == "success"


async def test_collection_refusal_is_traced_without_upstream_request(tmp_path, make_client):
    def must_not_run(request):
        raise AssertionError(f"unexpected upstream request: {request.url}")

    tracer = Tracer(tmp_path)
    server = create_server(client=make_client(must_not_run), tracer=tracer)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                server._lowlevel_server.run,
                server_read,
                server_write,
                server._lowlevel_server.create_initialization_options(),
            )
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                result = await session.call_tool("search_us_code", {"query": "collection:PLAW congress:118"})
                assert not result.is_error
            tg.cancel_scope.cancel()

    lines = tracer.path.read_text().splitlines()
    assert len(lines) == 1
    line = json.loads(lines[0])
    assert line["request"] == {
        "tool": "search_us_code",
        "arguments": {"query": "collection:PLAW congress:118"},
    }
    assert line["response"]["structuredContent"]["outcome"] == "out_of_scope_collection"
