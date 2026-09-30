"""WO-24 part A (40-tools.md, "Result order"): every request the two search tools send
asks upstream for score order; the requests the server builds itself (citation
resolution, the by-id path, public-law resolution, the staleness detector) do not."""

from __future__ import annotations

import fx
import httpx
import pytest

from uscode_mcp import tools

SCORE_DESC = [{"field": "score", "sortOrder": "DESC"}]


@pytest.fixture(params=[(tools.search_us_code, "USCODE"), (tools.search_public_laws, "PLAW")])
def scoped_search(request):
    return request.param


def recording_handler(seen, payload=None, status=200):
    def handler(request):
        seen.append(request)
        body = payload if payload is not None else fx.search_response([])
        return fx.json_response(body, status=status)

    return handler


class TestSearchToolsSendTheScoreSort:
    async def test_first_page_request_carries_the_sort(self, scoped_search, make_client):
        search, collection = scoped_search
        seen = []
        out = await search(make_client(recording_handler(seen)), "bank notes as collateral")

        assert out["outcome"] == "success"
        assert len(seen) == 1
        body = fx.request_body(seen[0])
        assert body["sorts"] == SCORE_DESC
        assert body["query"] == f"collection:{collection} bank notes as collateral"

    async def test_continuation_request_carries_the_sort(self, scoped_search, make_client):
        search, _ = scoped_search
        seen = []
        await search(make_client(recording_handler(seen)), "fair use factors", page_size=5, offset_mark="AoE=")

        body = fx.request_body(seen[0])
        assert body["sorts"] == SCORE_DESC
        assert body["offsetMark"] == "AoE="
        assert body["pageSize"] == 5

    async def test_historical_request_carries_the_sort(self, make_client):
        seen = []
        await tools.search_us_code(make_client(recording_handler(seen)), "fair use", historical=True)

        body = fx.request_body(seen[0])
        assert body["sorts"] == SCORE_DESC
        assert body["historical"] is True

    async def test_nothing_else_in_the_body_changes(self, make_client):
        seen = []
        await tools.search_us_code(make_client(recording_handler(seen)), '"fair use" usctitlenum:17')

        assert fx.request_body(seen[0]) == {
            "query": 'collection:USCODE "fair use" usctitlenum:17',
            "pageSize": tools.DEFAULT_PAGE_SIZE,
            "offsetMark": "*",
            "historical": False,
            "sorts": SCORE_DESC,
        }

    async def test_the_sort_constant_is_not_mutated_by_a_request(self, make_client):
        seen = []
        await tools.search_us_code(make_client(recording_handler(seen)), "fair use")
        await tools.search_public_laws(make_client(recording_handler(seen)), "fair use")

        assert tools.RELEVANCE_SORTS == SCORE_DESC
        assert [fx.request_body(r)["sorts"] for r in seen] == [SCORE_DESC, SCORE_DESC]


class TestServedOrderIsUpstreamOrder:
    async def test_hits_are_served_in_the_order_upstream_returned_them(self, make_client):
        ids = [
            "USCODE-2024-title12-chap6-sec582",
            "USCODE-2024-title7-chap73-sec4201",
            "USCODE-2024-title12-chap3-subchapXII-sec412",
        ]
        hits = [fx.usc_hit(package_id=g.rsplit("-chap", 1)[0], granule_id=g) for g in ids]
        seen = []
        out = await tools.search_us_code(
            make_client(recording_handler(seen, fx.search_response(hits, count=134))), "bank notes as collateral"
        )

        assert [r["granule_id"] for r in out["results"]] == ids
        assert out["count"] == 134

    async def test_duplicate_hits_are_not_merged(self, make_client):
        hits = [fx.plaw_hit("PLAW-119publ74"), fx.plaw_hit("PLAW-119publ74")]
        seen = []
        out = await tools.search_public_laws(
            make_client(recording_handler(seen, fx.search_response(hits))), "Price-Anderson"
        )

        assert [r["package_id"] for r in out["results"]] == ["PLAW-119publ74", "PLAW-119publ74"]


class TestSortedRequestFailuresSurface:
    async def test_upstream_refusing_the_request_is_an_upstream_error_not_zero_results(
        self, scoped_search, make_client
    ):
        search, _ = scoped_search
        seen = []
        payload = {"message": "Invalid sort field"}
        out = await search(make_client(recording_handler(seen, payload, status=400)), "fair use")

        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 400
        assert "results" not in out
        assert fx.request_body(seen[0])["sorts"] == SCORE_DESC

    async def test_refused_collection_sends_nothing(self, scoped_search, make_client):
        search, _ = scoped_search
        seen = []
        out = await search(make_client(recording_handler(seen)), "collection:BILLS fair use")

        assert out["outcome"] == "out_of_scope_collection"
        assert seen == []


def _server_built_handler(seen):
    """Serve every request the lookup tools make: the citation or public-law search, the
    PLAW detector search, granule and package summaries, and the text downloads."""

    def handler(request):
        seen.append(request)
        path = request.url.path
        if path == "/search":
            query = fx.request_body(request)["query"]
            if "docnumber:" in query:
                return fx.json_response(fx.search_response([fx.plaw_hit()]))
            if query.startswith("collection:PLAW"):
                return fx.json_response(fx.search_response([], count=0))
            return fx.json_response(fx.search_response([fx.usc_hit()]))
        if path.endswith("/granules/USCODE-2024-title17-chap1-sec107/summary"):
            return fx.json_response(fx.granule_summary())
        if path.endswith("/summary"):
            return fx.json_response(fx.plaw_summary())
        if "/granules/" in path and path.endswith("/htm"):
            return httpx.Response(200, text=fx.SECTION_HTML)
        if path.endswith("/htm"):
            return httpx.Response(200, text=fx.PLAW_HTML)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


def _search_bodies(seen):
    return [fx.request_body(r) for r in seen if r.url.path == "/search"]


class TestServerBuiltQueriesCarryNoSort:
    async def test_citation_resolution_and_detector_requests_are_unsorted(self, make_client):
        seen = []
        out = await tools.get_us_code_section(make_client(_server_built_handler(seen)), citation="17 U.S.C. 107")

        assert out["outcome"] == "success"
        bodies = _search_bodies(seen)
        queries = [b["query"] for b in bodies]
        assert 'collection:USCODE citation:"17 U.S.C. 107"' in queries
        assert any(q.startswith("collection:PLAW lawtype:public publishdate:range(") for q in queries)
        assert out["possibly_superseded"]["query"] in queries
        assert all("sorts" not in b for b in bodies)

    async def test_by_id_detector_request_is_unsorted(self, make_client):
        seen = []
        out = await tools.get_us_code_section(
            make_client(_server_built_handler(seen)),
            granule_id="USCODE-2024-title17-chap1-sec107",
            citation="17 U.S.C. 107",
        )

        assert out["outcome"] == "success"
        bodies = _search_bodies(seen)
        assert [b["query"] for b in bodies] == [out["possibly_superseded"]["query"]]
        assert all("sorts" not in b for b in bodies)

    async def test_public_law_resolution_request_is_unsorted(self, make_client):
        seen = []
        out = await tools.get_public_law(make_client(_server_built_handler(seen)), citation="Pub. L. 118-31")

        assert out["outcome"] == "success"
        bodies = _search_bodies(seen)
        assert [b["query"] for b in bodies] == ["collection:PLAW lawtype:public congress:118 docnumber:31"]
        assert "sorts" not in bodies[0]
