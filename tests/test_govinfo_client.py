"""GovInfo client behavior: auth, outcome material passthrough, and transport failure."""

import fx
import httpx
import pytest

from uscode_mcp.govinfo import GovInfoClient, GovInfoTransportError, client_from_env


async def test_api_key_sent_as_query_param(make_client):
    seen = {}

    def handler(request):
        seen["api_key"] = request.url.params.get("api_key")
        return fx.json_response(fx.search_response([]))

    client = make_client(handler)
    await client.search({"query": "x"})
    assert seen["api_key"] == "test-key"


async def test_api_key_not_echoed_in_response_url(make_client):
    client = make_client(lambda request: fx.json_response({}))
    resp = await client.search({"query": "x"})
    assert "test-key" not in resp.url
    assert "api_key" not in resp.url


async def test_search_posts_body_verbatim(make_client):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = fx.request_body(request)
        return fx.json_response(fx.search_response([]))

    body = {"query": 'collection:USCODE citation:"17 U.S.C. 107"', "pageSize": 100, "offsetMark": "*"}
    await make_client(handler).search(body)
    assert seen["method"] == "POST"
    assert seen["path"] == "/search"
    assert seen["body"] == body


async def test_fetch_preserves_existing_query_params(make_client):
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, text="ok")

    await make_client(handler).fetch("https://api.govinfo.gov/packages/X/htm?foo=1")
    assert seen["params"]["foo"] == "1"
    assert seen["params"]["api_key"] == "test-key"


async def test_rate_limit_info_extracted_from_429(make_client):
    def handler(request):
        return httpx.Response(
            429,
            text="Over rate limit",
            headers={"X-RateLimit-Limit": "36000", "X-RateLimit-Remaining": "0", "Retry-After": "3600"},
        )

    resp = await make_client(handler).search({"query": "x"})
    assert resp.rate_limited
    assert resp.rate_limit_info() == {"x-ratelimit-limit": "36000", "x-ratelimit-remaining": "0", "retry-after": "3600"}


async def test_error_response_surfaces_status_and_body(make_client):
    def handler(request):
        return httpx.Response(502, text="upstream exploded")

    resp = await make_client(handler).package_summary("USCODE-2024-title17")
    assert not resp.ok
    assert resp.status == 502
    assert resp.text == "upstream exploded"


async def test_network_failure_raises_transport_error(make_client):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(GovInfoTransportError, match="ConnectError"):
        await make_client(handler).search({"query": "x"})


def test_empty_api_key_rejected():
    with pytest.raises(ValueError, match="GOVINFO_API_KEY"):
        GovInfoClient(api_key="")


def test_client_from_env_fails_loudly_when_unset(monkeypatch):
    monkeypatch.delenv("GOVINFO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOVINFO_API_KEY"):
        client_from_env()
