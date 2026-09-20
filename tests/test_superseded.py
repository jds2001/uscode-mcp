"""The `possibly_superseded` staleness indicator (R14, WO-1; documentation/40-tools.md).

Mocked fixtures are not evidence of upstream behavior — they prove the code's
handling of each shape: three states never two, the failure surfaced verbatim in
`not_checked`, the exact query and bound echoed in every state, the bound derived
from the returned edition's own currentthrough, and — load-bearing — that no
detector failure of any kind fails the lookup.
"""

from __future__ import annotations

import asyncio

import fx
import httpx
import pytest

from uscode_mcp import superseded, tools

DETECTOR_QUERY_107 = 'collection:PLAW lawtype:public publishdate:range(2025-01-07,) uscodecitation:"17 U.S.C. 107"'


def plaw_hit(n: int, package_id: str | None = None) -> dict:
    return {
        "title": f"An Act number {n}",
        "packageId": package_id or f"PLAW-119publ{n}",
        "granuleId": None,
        "dateIssued": f"2025-0{1 + n % 9}-15",
        "collectionCode": "PLAW",
        "lastModified": "2026-01-01T00:00:00Z",
        "download": {"txtLink": f"{fx.API}/packages/PLAW-119publ{n}/htm"},
        "resultLink": f"{fx.API}/packages/PLAW-119publ{n}/summary",
    }


def is_detector(request: httpx.Request) -> bool:
    return request.url.path == "/search" and "collection:PLAW" in fx.request_body(request)["query"]


def make_handler(
    detector_response=None,
    htm_text: str = fx.SECTION_HTML,
    usc_hits: list[dict] | None = None,
    seen: list | None = None,
    detector_delay: float = 0.0,
    htm_delay: float = 0.0,
):
    """Serve the citation search, the granule /htm, and the PLAW detector query.

    `detector_response` is an httpx.Response, a callable returning one, or an
    exception instance to raise at the transport layer. `htm_delay` makes the text
    fetch yield to the event loop, so a detector task issued alongside it actually
    runs concurrently under the mock transport as it would over a real socket.
    """
    hits = usc_hits if usc_hits is not None else [fx.usc_hit()]

    async def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/search":
            if is_detector(request):
                if detector_delay:
                    await asyncio.sleep(detector_delay)
                if isinstance(detector_response, Exception):
                    raise detector_response
                if callable(detector_response):
                    return detector_response(request)
                if detector_response is None:
                    return fx.json_response(fx.search_response([], count=0))
                return detector_response
            return fx.json_response(fx.search_response(hits))
        if request.url.path.endswith("/htm"):
            if htm_delay:
                await asyncio.sleep(htm_delay)
            return httpx.Response(200, text=htm_text)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


def detector_requests(seen: list) -> list[httpx.Request]:
    return [r for r in seen if r.url.path == "/search" and is_detector(r)]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_since_is_currentthrough_plus_one_day(self):
        assert superseded.since_from_currentthrough("2025-01-06") == "2025-01-07"

    def test_since_rolls_over_month_and_year(self):
        assert superseded.since_from_currentthrough("2024-12-31") == "2025-01-01"
        assert superseded.since_from_currentthrough("2024-02-29") == "2024-03-01"

    def test_since_rejects_a_non_date(self):
        with pytest.raises(ValueError):
            superseded.since_from_currentthrough("2025-13-45")

    def test_query_is_the_pinned_publishdate_form(self):
        q = superseded.build_query("42 U.S.C. 2210", "2025-01-07")
        assert q == 'collection:PLAW lawtype:public publishdate:range(2025-01-07,) uscodecitation:"42 U.S.C. 2210"'
        assert "approveddate" not in q
        assert "congress:" not in q

    @pytest.mark.parametrize("citation", ["42 U.S.C. 2210", "18 U.S.C. App. 1201", "17 U.S.C. 107"])
    def test_every_query_carries_lawtype_public(self, citation):
        # O44e: private laws are indexed against sections they waive, never amend, and
        # get_public_law refuses their packages under R6 — the filter is in the query.
        q = superseded.build_query(citation, "2025-01-07")
        assert q.startswith("collection:PLAW lawtype:public publishdate:range(2025-01-07,) ")
        assert q.endswith(f'uscodecitation:"{citation}"')

    def test_appendix_section_query_uses_the_measured_app_form(self):
        q = superseded.build_query("18 U.S.C. App. 1201", "2025-01-07")
        assert q == (
            'collection:PLAW lawtype:public publishdate:range(2025-01-07,) uscodecitation:"18 U.S.C. App. 1201"'
        )

    def test_laws_indexed_caveat_is_the_pinned_wording(self):
        # Literal comparison against the text pinned in 40-tools.md (R14a addendum,
        # O44f/O44g): any drift in either direction fails loudly.
        assert superseded.CAVEAT_LAWS_INDEXED == (
            "INDICATOR ONLY — NOT A FINDING THAT THE TEXT CHANGED. A listed law MENTIONS this section; "
            "that is all the index records. It may amend the section, amend something else and merely "
            "cite this one, waive it for a named party, or not yet be in effect. The verification set's "
            "own example: Public Law 119-74 is listed against 42 U.S.C. 2210 because one appropriations "
            "rider cites it in a parenthetical, and it amends nothing in the section. This server does "
            "not read enacting laws. YOU MUST READ THE LISTED LAW TO FIND OUT — get_public_law with its "
            "package_id, then search its text for this section. The list may also be incomplete: the "
            "index misses about one in seven listed (law, section) pairs."
        )


# ---------------------------------------------------------------------------
# The three states
# ---------------------------------------------------------------------------


class TestLawsIndexed:
    async def test_hits_are_laws_indexed_with_true_count(self, make_client):
        seen = []
        resp = fx.json_response(fx.search_response([plaw_hit(74), plaw_hit(21)], count=2))
        client = make_client(make_handler(resp, seen=seen))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "laws_indexed"
        assert ps["count"] == 2
        assert ps["laws"] == [
            {"package_id": "PLAW-119publ74", "title": "An Act number 74", "date_issued": plaw_hit(74)["dateIssued"]},
            {"package_id": "PLAW-119publ21", "title": "An Act number 21", "date_issued": plaw_hit(21)["dateIssued"]},
        ]
        assert ps["capped"] is False
        assert "showing" not in ps["message"]
        assert ps["query"] == DETECTOR_QUERY_107
        assert ps["since"] == "2025-01-07"
        assert ps["checked_citation"] == "17 U.S.C. 107"

    async def test_caveat_says_indicator_not_stale(self, make_client):
        resp = fx.json_response(fx.search_response([plaw_hit(74)], count=1))
        out = await tools.get_us_code_section(make_client(make_handler(resp)), citation="17 U.S.C. 107")
        ps = out["possibly_superseded"]
        assert ps["caveat"] == superseded.CAVEAT_LAWS_INDEXED
        assert "NOT A FINDING THAT THE TEXT CHANGED" in ps["caveat"]
        assert "YOU MUST READ THE LISTED LAW" in ps["caveat"]
        assert "get_public_law" in ps["caveat"]
        assert "one in seven" in ps["caveat"]
        assert "mentions the section" in ps["message"]

    async def test_capping_is_stated_with_the_true_total(self, make_client):
        page = [plaw_hit(i) for i in range(superseded.LAWS_CAP)]
        resp = fx.json_response(fx.search_response(page, count=57))
        out = await tools.get_us_code_section(make_client(make_handler(resp)), citation="17 U.S.C. 107")
        ps = out["possibly_superseded"]
        assert ps["status"] == "laws_indexed"
        assert ps["count"] == 57
        assert ps["laws_shown"] == superseded.LAWS_CAP
        assert ps["laws_cap"] == superseded.LAWS_CAP
        assert ps["capped"] is True
        assert f"showing {superseded.LAWS_CAP} of 57" in ps["message"]

    async def test_detector_request_shape(self, make_client):
        seen = []
        client = make_client(make_handler(seen=seen))
        await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        [req] = detector_requests(seen)
        assert req.method == "POST"
        assert req.headers["X-Api-Key"] == "test-key"
        body = fx.request_body(req)
        assert body == {"query": DETECTOR_QUERY_107, "pageSize": superseded.LAWS_CAP, "offsetMark": "*"}


class TestNoneIndexed:
    async def test_zero_hits_is_none_indexed_with_the_caveat(self, make_client):
        resp = fx.json_response(fx.search_response([], count=0))
        out = await tools.get_us_code_section(make_client(make_handler(resp)), citation="17 U.S.C. 107")
        ps = out["possibly_superseded"]
        assert ps["status"] == "none_indexed"
        assert ps["count"] == 0
        assert ps["caveat"] == superseded.CAVEAT_NONE_INDEXED
        assert "NOT A CURRENCY CHECK" in ps["caveat"]
        assert "not" in ps["caveat"] and "evidence the text is current" in ps["caveat"]
        assert "one in seven" in ps["caveat"] and "one in four" in ps["caveat"]
        assert ps["query"] == DETECTOR_QUERY_107
        assert ps["since"] == "2025-01-07"
        assert "laws" not in ps


class TestNotChecked:
    async def test_500_is_not_checked_with_status_and_body(self, make_client):
        resp = httpx.Response(500, text='{"message":"Oops, Something went wrong"}')
        out = await tools.get_us_code_section(make_client(make_handler(resp)), citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        assert "fair use of a copyrighted work" in out["text"]["content"]
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "upstream_error"
        assert ps["http_status"] == 500
        assert "Oops, Something went wrong" in ps["body"]
        assert ps["url"].endswith("/search")
        assert ps["query"] == DETECTOR_QUERY_107
        assert ps["since"] == "2025-01-07"
        assert ps["caveat"] == superseded.CAVEAT_NOT_CHECKED
        assert "count" not in ps

    async def test_429_is_named_rate_limit_and_carries_headers(self, make_client):
        resp = httpx.Response(
            429,
            text="Over rate limit",
            headers={"X-RateLimit-Limit": "36000", "X-RateLimit-Remaining": "0", "Retry-After": "3600"},
        )
        out = await tools.get_us_code_section(make_client(make_handler(resp)), citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "rate_limited"
        assert ps["http_status"] == 429
        assert ps["rate_limit"] == {"x-ratelimit-limit": "36000", "x-ratelimit-remaining": "0", "retry-after": "3600"}
        assert "rate limit" in ps["detail"]

    async def test_500_is_distinct_from_429(self, make_client):
        a = await tools.get_us_code_section(
            make_client(make_handler(httpx.Response(500, text="x"))), citation="17 U.S.C. 107"
        )
        b = await tools.get_us_code_section(
            make_client(make_handler(httpx.Response(429, text="x"))), citation="17 U.S.C. 107"
        )
        assert a["possibly_superseded"]["reason"] != b["possibly_superseded"]["reason"]
        assert "rate_limit" not in a["possibly_superseded"]

    async def test_timeout_is_not_checked_and_the_text_still_arrives(self, make_client, monkeypatch):
        monkeypatch.setattr(superseded, "DETECTOR_BUDGET_SECONDS", 0.05)
        client = make_client(make_handler(detector_delay=5.0))
        out = await asyncio.wait_for(tools.get_us_code_section(client, citation="17 U.S.C. 107"), timeout=2.0)
        assert out["outcome"] == "success"
        assert "fair use of a copyrighted work" in out["text"]["content"]
        assert out["provenance"]["currentthrough"] == "2025-01-06"
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "timeout"
        assert "0.05 s" in ps["detail"]
        assert ps["query"] == DETECTOR_QUERY_107
        assert ps["since"] == "2025-01-07"

    async def test_malformed_json_is_not_checked(self, make_client):
        resp = httpx.Response(200, text="<html>maintenance</html>")
        out = await tools.get_us_code_section(make_client(make_handler(resp)), citation="17 U.S.C. 107")
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "malformed_response"
        assert ps["http_status"] == 200
        assert "<html>maintenance</html>" in ps["body"]

    async def test_json_without_count_or_results_is_not_checked(self, make_client):
        resp = fx.json_response({"unexpected": True})
        out = await tools.get_us_code_section(make_client(make_handler(resp)), citation="17 U.S.C. 107")
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "malformed_response"

    async def test_transport_failure_is_not_checked(self, make_client):
        out = await tools.get_us_code_section(
            make_client(make_handler(httpx.ConnectError("boom"))), citation="17 U.S.C. 107"
        )
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "transport_error"
        assert "boom" in ps["detail"]

    async def test_unexpected_exception_in_detector_never_fails_the_lookup(self, make_client):
        class Client:
            """A client whose search blows up with a non-transport error on the detector."""

            def __init__(self, inner):
                self._inner = inner

            async def search(self, body):
                if "collection:PLAW" in body["query"]:
                    raise RuntimeError("something unforeseen")
                return await self._inner.search(body)

            async def fetch(self, url, source_field):
                return await self._inner.fetch(url, source_field)

        out = await tools.get_us_code_section(Client(make_client(make_handler())), citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "internal_error"
        assert "something unforeseen" in ps["detail"]

    async def test_unparseable_currentthrough_is_no_bound_and_no_query(self, make_client):
        seen = []
        client = make_client(make_handler(htm_text=fx.SECTION_HTML_NO_CURRENTTHROUGH, seen=seen))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "no_bound"
        assert ps["query"] is None
        assert ps["since"] is None
        assert detector_requests(seen) == []

    async def test_impossible_currentthrough_date_is_no_bound_not_a_crash(self, make_client):
        html = fx.SECTION_HTML.replace("currentthrough:20250106", "currentthrough:20251345")
        seen = []
        out = await tools.get_us_code_section(
            make_client(make_handler(htm_text=html, seen=seen)), citation="17 U.S.C. 107"
        )
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "no_bound"
        assert "2025-13-45" in ps["detail"]
        assert detector_requests(seen) == []

    @pytest.mark.parametrize("citation", ["28 U.S.C. App. Rule 9", "28 U.S.C. App."])
    async def test_appendix_rule_or_bare_appendix_is_not_checked_without_a_query(self, make_client, citation):
        # O44d: no uscodecitation form is measured for rules or bare appendix citations.
        seen = []
        hit = fx.usc_hit(package_id="USCODE-2024-title28", granule_id="USCODE-2024-title28-app-federalru-rule9")
        client = make_client(make_handler(usc_hits=[hit], seen=seen))
        out = await tools.get_us_code_section(client, citation=citation)
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "no_measured_citation_form"
        assert ps["query"] is None
        assert ps["checked_citation"] is None
        assert detector_requests(seen) == []

    async def test_numbered_appendix_section_runs_the_detector_on_the_app_form(self, make_client):
        # O44d: numbered appendix sections have the measured "{t} U.S.C. App. {s}" form.
        seen = []
        hit = fx.usc_hit(package_id="USCODE-2024-title18", granule_id="USCODE-2024-title18-app-sec1201")
        resp = fx.json_response(fx.search_response([plaw_hit(75)], count=1))
        client = make_client(make_handler(resp, usc_hits=[hit], seen=seen))
        out = await tools.get_us_code_section(client, citation="18 U.S.C. App. 1201")
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "laws_indexed"
        assert ps["checked_citation"] == "18 U.S.C. App. 1201"
        assert ps["query"] == (
            'collection:PLAW lawtype:public publishdate:range(2025-01-07,) uscodecitation:"18 U.S.C. App. 1201"'
        )
        assert fx.request_body(detector_requests(seen)[0])["query"] == ps["query"]

    async def test_not_checked_is_never_collapsed_into_none_indexed(self, make_client):
        for resp in (httpx.Response(500, text="x"), httpx.Response(429, text="x"), httpx.ConnectError("x")):
            out = await tools.get_us_code_section(make_client(make_handler(resp)), citation="17 U.S.C. 107")
            assert out["possibly_superseded"]["status"] == "not_checked"
            assert out["possibly_superseded"]["status"] != "none_indexed"


# ---------------------------------------------------------------------------
# Every state echoes query and since; the object rides on every success
# ---------------------------------------------------------------------------


class TestEchoInEveryState:
    @pytest.mark.parametrize(
        "resp",
        [
            fx.json_response(fx.search_response([plaw_hit(1)], count=1)),
            fx.json_response(fx.search_response([], count=0)),
            httpx.Response(500, text="x"),
            httpx.Response(429, text="x"),
            httpx.Response(200, text="not json"),
        ],
    )
    async def test_query_and_since_present(self, make_client, resp):
        out = await tools.get_us_code_section(make_client(make_handler(resp)), citation="17 U.S.C. 107")
        ps = out["possibly_superseded"]
        assert ps["status"] in {"laws_indexed", "none_indexed", "not_checked"}
        assert ps["query"] == DETECTOR_QUERY_107
        assert ps["since"] == "2025-01-07"
        assert "currentthrough 2025-01-06" in ps["since_basis"]
        assert ps["caveat"]

    async def test_object_present_on_a_reading_call_too(self, make_client):
        out = await tools.get_us_code_section(make_client(make_handler()), citation="17 U.S.C. 107", start_char=20)
        assert out["outcome"] == "success"
        assert out["possibly_superseded"]["status"] == "none_indexed"

    async def test_no_detector_query_on_non_success_outcomes(self, make_client):
        seen = []
        client = make_client(make_handler(usc_hits=[], seen=seen))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "not_found"
        assert "possibly_superseded" not in out
        assert detector_requests(seen) == []

    async def test_fetch_failure_drops_an_in_flight_detector(self, make_client):
        # Warm the edition memory so the second lookup issues the detector with the fetch.
        await tools.get_us_code_section(make_client(make_handler()), citation="17 U.S.C. 107")
        seen = []

        async def handler(request):
            seen.append(request)
            if request.url.path == "/search":
                if is_detector(request):
                    await asyncio.sleep(0.2)
                    return fx.json_response(fx.search_response([], count=0))
                return fx.json_response(fx.search_response([fx.usc_hit()]))
            return httpx.Response(503, text="unavailable")

        out = await tools.get_us_code_section(make_client(handler), citation="17 U.S.C. 107")
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 503
        assert "possibly_superseded" not in out


# ---------------------------------------------------------------------------
# Normalization interplay: stripped note, subsection, edition-relative bound
# ---------------------------------------------------------------------------


class TestBoundAndCitation:
    async def test_stripped_note_checks_the_parent_and_says_so(self, make_client):
        seen = []
        hit = fx.usc_hit(package_id="USCODE-2024-title42", granule_id="USCODE-2024-title42-chap23-sec2210")
        client = make_client(make_handler(usc_hits=[hit], seen=seen))
        out = await tools.get_us_code_section(client, citation="42 U.S.C. 2210 note")
        assert out["normalization"]["stripped_note"] is True
        ps = out["possibly_superseded"]
        assert ps["query"] == (
            'collection:PLAW lawtype:public publishdate:range(2025-01-07,) '
            'uscodecitation:"42 U.S.C. 2210"'
        )
        assert ps["checked_citation"] == "42 U.S.C. 2210"
        assert "parent section 42 U.S.C. 2210" in ps["note_statement"]
        assert "neither citation" in ps["note_statement"]
        assert fx.request_body(detector_requests(seen)[0])["query"] == ps["query"]

    async def test_no_note_statement_without_a_stripped_note(self, make_client):
        out = await tools.get_us_code_section(make_client(make_handler()), citation="17 U.S.C. 107")
        assert "note_statement" not in out["possibly_superseded"]

    async def test_stripped_subsection_checks_the_containing_section(self, make_client):
        out = await tools.get_us_code_section(make_client(make_handler()), citation="17 U.S.C. 107(b)(2)")
        ps = out["possibly_superseded"]
        assert ps["query"] == DETECTOR_QUERY_107
        assert "note_statement" not in ps

    async def test_year_selected_edition_bounds_on_its_own_currentthrough(self, make_client):
        hits = [
            fx.usc_hit(package_id="USCODE-2023-title17", granule_id="USCODE-2023-title17-chap1-sec107",
                       date_issued="2023-12-31"),
            fx.usc_hit(date_issued="2024-12-31"),
        ]
        html_2023 = fx.SECTION_HTML.replace("currentthrough:20250106", "currentthrough:20240105")
        seen = []
        client = make_client(make_handler(usc_hits=hits, htm_text=html_2023, seen=seen))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", year=2023)
        assert out["provenance"]["edition_year"] == 2023
        assert out["provenance"]["currentthrough"] == "2024-01-05"
        ps = out["possibly_superseded"]
        assert ps["since"] == "2024-01-06"
        assert ps["query"] == (
            'collection:PLAW lawtype:public publishdate:range(2024-01-06,) '
            'uscodecitation:"17 U.S.C. 107"'
        )
        assert fx.request_body(detector_requests(seen)[0])["query"] == ps["query"]

    async def test_two_editions_of_one_section_get_different_bounds(self, make_client):
        html_2023 = fx.SECTION_HTML.replace("currentthrough:20250106", "currentthrough:20240105")
        hit_2023 = fx.usc_hit(package_id="USCODE-2023-title17", granule_id="USCODE-2023-title17-chap1-sec107",
                              date_issued="2023-12-31")
        newest = await tools.get_us_code_section(make_client(make_handler()), citation="17 U.S.C. 107")
        older = await tools.get_us_code_section(
            make_client(make_handler(usc_hits=[hit_2023], htm_text=html_2023)), citation="17 U.S.C. 107", year=2023
        )
        assert newest["possibly_superseded"]["since"] == "2025-01-07"
        assert older["possibly_superseded"]["since"] == "2024-01-06"


# ---------------------------------------------------------------------------
# Concurrency: cold lookups issue after the fetch; warm ones before the search, verified
# ---------------------------------------------------------------------------


class TestConcurrency:
    async def test_cold_lookup_issues_after_the_fetch(self, make_client):
        seen = []
        out = await tools.get_us_code_section(make_client(make_handler(seen=seen)), citation="17 U.S.C. 107")
        kinds = [("detector" if is_detector(r) else "search") if r.url.path == "/search" else "htm" for r in seen]
        assert kinds == ["search", "htm", "detector"]
        assert out["possibly_superseded"]["issued"] == "after_fetch"
        assert "prediction_note" not in out["possibly_superseded"]

    async def test_warm_lookup_issues_with_the_fetch_and_verifies(self, make_client):
        await tools.get_us_code_section(make_client(make_handler()), citation="17 U.S.C. 107")
        events = []
        seen = []
        hit = fx.usc_hit(package_id="USCODE-2024-title42", granule_id="USCODE-2024-title42-chap23-sec2210")

        async def handler(request):
            seen.append(request)
            if request.url.path == "/search":
                if is_detector(request):
                    events.append("detector-start")
                    return fx.json_response(fx.search_response([], count=0))
                events.append("search-start")
                await asyncio.sleep(0.02)
                events.append("search-end")
                return fx.json_response(fx.search_response([hit]))
            events.append("htm-start")
            await asyncio.sleep(0.02)
            events.append("htm-end")
            return httpx.Response(200, text=fx.SECTION_HTML)

        out = await tools.get_us_code_section(make_client(handler), citation="42 U.S.C. 2210")
        # The detector is in flight while the citation search is still outstanding,
        # so it overlaps both upstream round trips.
        assert events.index("detector-start") < events.index("search-end")
        ps = out["possibly_superseded"]
        assert ps["issued"] == "before_search"
        assert ps["since"] == "2025-01-07"
        assert ps["query"] == (
            'collection:PLAW lawtype:public publishdate:range(2025-01-07,) '
            'uscodecitation:"42 U.S.C. 2210"'
        )
        assert "prediction_note" not in ps
        assert len(detector_requests(seen)) == 1

    async def test_wrong_prediction_is_discarded_and_reissued_on_the_true_bound(self, make_client):
        await tools.get_us_code_section(make_client(make_handler()), citation="17 U.S.C. 107")
        # Same edition year, but this payload's currentthrough differs from the remembered one.
        html = fx.SECTION_HTML.replace("currentthrough:20250106", "currentthrough:20250301")
        seen = []
        out = await tools.get_us_code_section(
            make_client(make_handler(htm_text=html, seen=seen, htm_delay=0.02)), citation="17 U.S.C. 107"
        )
        ps = out["possibly_superseded"]
        assert ps["since"] == "2025-03-02"
        assert ps["query"] == (
            'collection:PLAW lawtype:public publishdate:range(2025-03-02,) '
            'uscodecitation:"17 U.S.C. 107"'
        )
        assert ps["issued"] == "after_fetch"
        assert "2025-01-06" in ps["prediction_note"] and "2025-03-01" in ps["prediction_note"]
        sent = [fx.request_body(r)["query"] for r in detector_requests(seen)]
        assert sent[-1] == ps["query"]
        assert sent[0] != ps["query"]  # the speculative one went out, and was not used
        # And the corrected currentthrough is what later lookups predict from.
        assert tools.CURRENTTHROUGH_MEMORY.predict(2024) == "2025-03-01"

    async def test_memory_is_per_edition_year(self):
        memory = superseded.CurrentthroughMemory()
        assert memory.predict(None) is None  # nothing remembered: no prediction
        memory.observe(2023, "2024-01-05")
        memory.observe(2024, "2025-01-06")
        assert memory.predict(2024) == "2025-01-06"
        assert memory.predict(2023) == "2024-01-05"
        assert memory.predict(1998) is None
        # A lookup without `year` resolves to the newest edition, so that is the prediction.
        assert memory.predict(None) == "2025-01-06"
        memory.observe(None, "2020-01-01")
        memory.observe(2022, None)
        assert memory.predict(2022) is None
        assert memory.predict(None) == "2025-01-06"

    async def test_year_lookup_predicts_from_its_own_edition_not_the_newest(self, make_client):
        # Remember 2024, then look up the 2023 edition cold: no 2023 prediction exists,
        # so the detector must wait for the payload rather than borrow 2024's bound.
        await tools.get_us_code_section(make_client(make_handler()), citation="17 U.S.C. 107")
        html_2023 = fx.SECTION_HTML.replace("currentthrough:20250106", "currentthrough:20240105")
        hit_2023 = fx.usc_hit(package_id="USCODE-2023-title17", granule_id="USCODE-2023-title17-chap1-sec107",
                              date_issued="2023-12-31")
        seen = []
        out = await tools.get_us_code_section(
            make_client(make_handler(usc_hits=[hit_2023], htm_text=html_2023, seen=seen)),
            citation="17 U.S.C. 107", year=2023,
        )
        ps = out["possibly_superseded"]
        assert ps["issued"] == "after_fetch"
        assert ps["since"] == "2024-01-06"
        assert len(detector_requests(seen)) == 1
        assert "prediction_note" not in ps

    async def test_early_outcome_drops_an_in_flight_detector(self, make_client):
        # Warm, then a lookup that ends at the citation search (not_found): the
        # speculative detector is abandoned and the outcome is unchanged.
        await tools.get_us_code_section(make_client(make_handler()), citation="17 U.S.C. 107")
        seen = []
        out = await tools.get_us_code_section(
            make_client(make_handler(usc_hits=[], seen=seen, htm_delay=0.02)), citation="17 U.S.C. 9999"
        )
        assert out["outcome"] == "not_found"
        assert "possibly_superseded" not in out

    async def test_detector_results_are_never_reused_across_lookups(self, make_client):
        seen = []
        client = make_client(make_handler(seen=seen))
        await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert len(detector_requests(seen)) == 2

    async def test_detector_ms_is_reported(self, make_client):
        out = await tools.get_us_code_section(make_client(make_handler()), citation="17 U.S.C. 107")
        assert isinstance(out["possibly_superseded"]["detector_ms"], int)
