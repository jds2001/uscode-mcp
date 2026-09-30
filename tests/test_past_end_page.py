"""WO-27 (F19, O111e; documentation/40-tools.md, "A page past the end is not zero
results"): a continuation page — any `offset_mark` but "*" — that comes back with no
hits is served with the past-the-end message, character for character; the
zero-results message stays for first pages, where it is true. Everything else in
the envelope is served as before.
"""

from __future__ import annotations

import fx
import httpx
import pytest

from uscode_mcp import tools

PAST_END = (
    "No more results: this continuation page is past the end of the result set. The search itself succeeded; "
    "'count' on this page is upstream's value for a page past the end, not the size of the result set, which "
    "the first page reported."
)
ZERO = (
    "Zero results. The search itself succeeded — this is 'found nothing', not a failure; "
    "the exact query sent upstream is in 'query'."
)


def handler_for(hits: list[dict], count: int, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(fx.request_body(request))
        return fx.json_response(fx.search_response(hits, count=count, offset_mark="AoJ/end"))

    return handler


SEARCHES = [
    pytest.param(lambda c, **kw: tools.search_us_code(c, "bank notes as collateral", **kw), fx.usc_hit, id="uscode"),
    pytest.param(lambda c, **kw: tools.search_public_laws(c, "bank notes", **kw), fx.plaw_hit, id="plaw"),
]


class TestPastEndMessage:
    def test_constant_is_the_contract_text(self):
        assert tools.PAST_END_MESSAGE == PAST_END
        assert tools.ZERO_RESULTS_MESSAGE == ZERO

    @pytest.mark.parametrize("search,hit", SEARCHES)
    async def test_empty_continuation_page_gets_the_past_end_message(self, make_client, search, hit):
        seen = []
        out = await search(make_client(handler_for([], count=0, seen=seen)), page_size=100, offset_mark="AoJ/abc")
        assert seen[0]["offsetMark"] == "AoJ/abc"
        assert out["outcome"] == "success"
        assert out["results"] == []
        assert out["count"] == 0  # upstream's own value, served as sent
        assert out["offset_mark"] == "AoJ/end"
        assert out["page_size"] == 100
        assert out["message"] == PAST_END

    @pytest.mark.parametrize("search,hit", SEARCHES)
    async def test_empty_first_page_keeps_the_zero_results_message(self, make_client, search, hit):
        out = await search(make_client(handler_for([], count=0)), page_size=100, offset_mark="*")
        assert out["outcome"] == "success" and out["results"] == []
        assert out["message"] == ZERO

    @pytest.mark.parametrize("search,hit", SEARCHES)
    async def test_default_offset_mark_is_a_first_page(self, make_client, search, hit):
        out = await search(make_client(handler_for([], count=0)))
        assert out["message"] == ZERO

    @pytest.mark.parametrize("search,hit", SEARCHES)
    async def test_blank_offset_mark_is_sent_as_star_and_is_a_first_page(self, make_client, search, hit):
        seen = []
        out = await search(make_client(handler_for([], count=0, seen=seen)), offset_mark="")
        assert seen[0]["offsetMark"] == "*"
        assert out["message"] == ZERO

    @pytest.mark.parametrize("search,hit", SEARCHES)
    async def test_non_empty_continuation_page_is_unchanged(self, make_client, search, hit):
        out = await search(make_client(handler_for([hit()], count=134)), offset_mark="AoJ/abc")
        assert out["outcome"] == "success"
        assert len(out["results"]) == 1 and out["count"] == 134
        assert "message" not in out

    @pytest.mark.parametrize("search,hit", SEARCHES)
    async def test_empty_continuation_with_a_nonzero_count_still_says_past_end(self, make_client, search, hit):
        # The message speaks to `count` whatever upstream puts there.
        out = await search(make_client(handler_for([], count=134)), offset_mark="AoJ/abc")
        assert out["count"] == 134
        assert out["message"] == PAST_END

    async def test_public_laws_past_end_page_still_carries_the_recall_caveat(self, make_client):
        out = await tools.search_public_laws(make_client(handler_for([], count=0)), "bank notes", offset_mark="AoJ/abc")
        assert out["message"] == PAST_END
        assert out["recall_caveat"] == tools.RECALL_CAVEAT_FULLTEXT
