"""get_public_law and search_public_laws contracts from documentation/40-tools.md and
50-public-law.md: private-law scope boundary, USLM as a reportable not-available
outcome, package-level windowing, and the uscodecitation recall caveat."""

import fx
import httpx

from uscode_mcp import tools


def plaw_handler(search_payload=None, summary=None, htm=fx.PLAW_HTML, uslm=fx.PLAW_USLM, seen=None):
    search_payload = search_payload if search_payload is not None else fx.search_response([fx.plaw_hit()])
    summary = summary if summary is not None else fx.plaw_summary()

    def handler(request):
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if path == "/search":
            return fx.json_response(search_payload)
        if path.endswith("/summary"):
            return fx.json_response(summary)
        if path.endswith("/htm"):
            return httpx.Response(200, text=htm)
        if path.endswith("/uslm"):
            return httpx.Response(200, text=uslm)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


class TestGetPublicLaw:
    async def test_success_by_congress_and_number(self, make_client):
        seen = []
        client = make_client(plaw_handler(seen=seen))
        out = await tools.get_public_law(client, congress=118, law_number=31)
        assert out["outcome"] == "success"
        assert fx.request_body(seen[0])["query"] == "collection:PLAW congress:118 docnumber:31"
        prov = out["provenance"]
        assert prov["package_id"] == "PLAW-118publ31"
        assert prov["date_issued"] == "2023-12-22"
        assert prov["pdf_link"].endswith("/pdf")
        assert "NDAA fixture" in out["text"]["content"]
        assert "<p>" not in out["text"]["content"]

    async def test_citation_forms_resolve(self, make_client):
        for citation in ("Pub. L. 118-31", "Public Law 118-31", "P.L. 118-31"):
            out = await tools.get_public_law(make_client(plaw_handler()), citation=citation)
            assert out["outcome"] == "success", citation
            assert out["congress"] == 118
            assert out["law_number"] == 31

    async def test_private_law_is_out_of_scope_not_a_failed_lookup(self, make_client):
        out = await tools.get_public_law(make_client(None), citation="Priv. L. 108-1")
        assert out["outcome"] == "out_of_scope_private_law"
        assert "not a" in out["message"] and "failed lookup" in out["message"]

    async def test_uslm_format_returns_raw_xml(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31, format="uslm")
        assert out["outcome"] == "success"
        assert out["format"] == "uslm"
        assert "<uslm" in out["text"]["content"]  # raw XML, not stripped

    async def test_uslm_absent_is_a_distinct_reportable_outcome(self, make_client):
        handler = plaw_handler(summary=fx.plaw_summary(uslm=False))
        out = await tools.get_public_law(make_client(handler), congress=104, law_number=1, format="uslm")
        assert out["outcome"] == "format_not_available"
        assert out["format"] == "uslm"
        assert "txtLink" in out["available_formats"]
        assert "uslmLink" not in out["available_formats"]

    async def test_invalid_format_rejected(self, make_client):
        out = await tools.get_public_law(make_client(None), congress=118, law_number=31, format="docx")
        assert out["outcome"] == "invalid_argument"

    async def test_missing_arguments_rejected(self, make_client):
        out = await tools.get_public_law(make_client(None), congress=118)
        assert out["outcome"] == "invalid_argument"
        out = await tools.get_public_law(make_client(None))
        assert out["outcome"] == "invalid_argument"

    async def test_citation_and_fields_together_rejected(self, make_client):
        out = await tools.get_public_law(make_client(None), congress=118, citation="Pub. L. 118-31")
        assert out["outcome"] == "invalid_argument"

    async def test_zero_hits_is_not_found_with_query_echo(self, make_client):
        out = await tools.get_public_law(
            make_client(plaw_handler(search_payload=fx.search_response([]))), congress=118, law_number=9999
        )
        assert out["outcome"] == "not_found"
        assert out["query"] == "collection:PLAW congress:118 docnumber:9999"

    async def test_search_failure_is_never_not_found(self, make_client):
        out = await tools.get_public_law(
            make_client(lambda request: httpx.Response(500, text="err")), congress=118, law_number=31
        )
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 500

    async def test_summary_failure_surfaces(self, make_client):
        def handler(request):
            if request.url.path == "/search":
                return fx.json_response(fx.search_response([fx.plaw_hit()]))
            return httpx.Response(502, text="bad gateway")

        out = await tools.get_public_law(make_client(handler), congress=118, law_number=31)
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 502

    async def test_rate_limited_distinct(self, make_client):
        def handler(request):
            return httpx.Response(429, text="limit", headers={"X-RateLimit-Remaining": "0"})

        out = await tools.get_public_law(make_client(handler), congress=118, law_number=31)
        assert out["outcome"] == "rate_limited"
        assert out["rate_limit"]["x-ratelimit-remaining"] == "0"

    async def test_truncation_marked_on_large_law(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31, max_chars=20)
        assert out["outcome"] == "success"
        assert out["text"]["truncated"] is True
        assert out["text"]["next_start_char"] == 20
        assert out["text"]["total_chars"] > 20


class TestSearchPublicLaws:
    async def test_collection_scoped_to_plaw(self, make_client):
        seen = []

        def handler(request):
            seen.append(request)
            return fx.json_response(fx.search_response([fx.plaw_hit()]))

        out = await tools.search_public_laws(make_client(handler), "defense authorization")
        assert fx.request_body(seen[0])["query"] == "collection:PLAW defense authorization"
        assert out["outcome"] == "success"

    async def test_reverse_lookup_carries_recall_caveat(self, make_client):
        def handler(request):
            return fx.json_response(fx.search_response([fx.plaw_hit()], count=14))

        out = await tools.search_public_laws(make_client(handler), 'uscodecitation:"42 U.S.C. 2210"')
        assert "recall_caveat" in out
        assert "NOT evidence" in out["recall_caveat"]

    async def test_non_reverse_lookup_has_no_caveat(self, make_client):
        out = await tools.search_public_laws(
            make_client(lambda request: fx.json_response(fx.search_response([]))), "congress:118 docnumber:31"
        )
        assert "recall_caveat" not in out

    async def test_zero_results_explicit(self, make_client):
        out = await tools.search_public_laws(
            make_client(lambda request: fx.json_response(fx.search_response([], count=0))), "zxqv"
        )
        assert out["outcome"] == "success"
        assert out["count"] == 0
        assert "Zero results" in out["message"]
