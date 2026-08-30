"""get_us_code_section and search_us_code contracts from documentation/40-tools.md.

The load-bearing assertions: the three outcomes never collapse (an upstream failure
must never present as not-found), provenance is complete or explicitly incomplete,
truncation is always marked, and normalization strips are reported."""

import fx
import httpx

from uscode_mcp import tools


def section_handler(search_payload, htm_text=fx.SECTION_HTML, seen=None):
    """Handler serving POST /search and the granule /htm download link."""

    def handler(request):
        if seen is not None:
            seen.append(request)
        if request.url.path == "/search":
            return fx.json_response(search_payload)
        if request.url.path.endswith("/htm"):
            return httpx.Response(200, text=htm_text)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


class TestGetSectionSuccess:
    async def test_success_with_full_provenance(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        assert out["citation"] == "17 U.S.C. 107"
        prov = out["provenance"]
        assert prov["package_id"] == "USCODE-2024-title17"
        assert prov["granule_id"] == "USCODE-2024-title17-chap1-sec107"
        assert prov["edition_year"] == 2024
        assert prov["currentthrough"] == "2025-01-06"
        assert prov["last_modified"] == "2025-03-01T00:00:00Z"
        assert prov["pdf_link"].endswith("/pdf")

    async def test_text_includes_notes_and_source_credit(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        content = out["text"]["content"]
        assert "fair use of a copyrighted work" in content
        assert "Pub. L. 94-553" in content
        assert "Effective date note text lives here and must never be dropped." in content
        assert out["text"]["truncated"] is False

    async def test_query_uses_normalized_citation(self, make_client):
        seen = []
        client = make_client(section_handler(fx.search_response([fx.usc_hit()]), seen=seen))
        await tools.get_us_code_section(client, citation="17 USC 107")
        body = fx.request_body(seen[0])
        assert body["query"] == 'collection:USCODE citation:"17 U.S.C. 107"'
        assert body["historical"] is False

    async def test_title_section_fields(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, title="17", section="107")
        assert out["outcome"] == "success"

    async def test_subsection_strip_is_reported(self, make_client):
        seen = []
        client = make_client(section_handler(fx.search_response([fx.usc_hit()]), seen=seen))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. § 107(b)")
        assert out["normalization"]["stripped_subsection"] == "(b)"
        assert any("(b)" in m for m in out["normalization"]["messages"])
        assert '"17 U.S.C. 107"' in fx.request_body(seen[0])["query"]

    async def test_note_strip_is_reported(self, make_client):
        hit = fx.usc_hit(
            package_id="USCODE-2024-title42",
            granule_id="USCODE-2024-title42-chap23-divsnA-subchapXIII-sec2210",
        )
        client = make_client(section_handler(fx.search_response([hit])))
        out = await tools.get_us_code_section(client, citation="42 U.S.C. 2210 note")
        assert out["outcome"] == "success"
        assert out["normalization"]["stripped_note"] is True
        assert any("note" in m for m in out["normalization"]["messages"])

    async def test_truncation_is_marked_and_resumable(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        first = await tools.get_us_code_section(client, citation="17 U.S.C. 107", max_chars=50)
        assert first["text"]["truncated"] is True
        assert first["text"]["returned_chars"] == 50
        next_start = first["text"]["next_start_char"]
        assert next_start == 50
        rest = await tools.get_us_code_section(client, citation="17 U.S.C. 107", start_char=next_start)
        assert rest["text"]["start_char"] == 50
        full = first["text"]["content"] + rest["text"]["content"]
        assert "must never be dropped" in full


class TestGetSectionYear:
    async def test_year_sets_historical_and_filters(self, make_client):
        hits = [
            fx.usc_hit(package_id="USCODE-1998-title17", granule_id="USCODE-1998-title17-chap1-sec107",
                       date_issued="1998-01-05"),
            fx.usc_hit(date_issued="2025-01-06"),
        ]
        seen = []
        client = make_client(section_handler(fx.search_response(hits), seen=seen))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", year=1998)
        assert fx.request_body(seen[0])["historical"] is True
        assert out["outcome"] == "success"
        assert out["provenance"]["edition_year"] == 1998

    async def test_year_with_no_matching_edition_is_not_found(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit(date_issued="2025-01-06")])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", year=1980)
        assert out["outcome"] == "not_found"
        assert "1980" in out["message"]


class TestGetSectionNonSuccessOutcomes:
    async def test_zero_hits_is_not_found_with_query_echo(self, make_client):
        client = make_client(section_handler(fx.search_response([])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 9999")
        assert out["outcome"] == "not_found"
        assert out["query"] == 'collection:USCODE citation:"17 U.S.C. 9999"'
        assert out["normalized_citation"] == "17 U.S.C. 9999"
        assert "search_us_code" in out["message"]

    async def test_multiple_hits_is_disambiguation_not_a_guess(self, make_client):
        hits = [fx.usc_hit(), fx.usc_hit(granule_id="USCODE-2024-title17-chap1-sec107a")]
        client = make_client(section_handler(fx.search_response(hits)))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "ambiguous"
        assert len(out["candidates"]) == 2
        assert {c["granule_id"] for c in out["candidates"]} == {
            "USCODE-2024-title17-chap1-sec107",
            "USCODE-2024-title17-chap1-sec107a",
        }

    async def test_upstream_500_is_never_not_found(self, make_client):
        client = make_client(lambda request: httpx.Response(500, text="internal error"))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 500
        assert "internal error" in out["body"]

    async def test_rate_limited_is_distinct_with_headers(self, make_client):
        def handler(request):
            return httpx.Response(
                429, text="slow down",
                headers={"X-RateLimit-Limit": "36000", "X-RateLimit-Remaining": "0", "Retry-After": "60"},
            )

        out = await tools.get_us_code_section(make_client(handler), citation="17 U.S.C. 107")
        assert out["outcome"] == "rate_limited"
        assert out["rate_limit"]["x-ratelimit-remaining"] == "0"
        assert out["rate_limit"]["retry-after"] == "60"

    async def test_transport_failure_surfaces(self, make_client):
        def handler(request):
            raise httpx.ConnectError("boom")

        out = await tools.get_us_code_section(make_client(handler), citation="17 U.S.C. 107")
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] is None
        assert "boom" in out["detail"]

    async def test_non_json_search_response_fails_loudly(self, make_client):
        client = make_client(lambda request: httpx.Response(200, text="<html>maintenance page</html>"))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "upstream_error"
        assert "drift" in out["detail"]

    async def test_missing_txt_link_fails_loudly_not_constructed(self, make_client):
        hit = fx.usc_hit()
        hit["download"] = {"pdfLink": hit["download"]["pdfLink"]}
        client = make_client(section_handler(fx.search_response([hit])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "upstream_error"
        assert "txtLink" in out["detail"]

    async def test_htm_fetch_failure_surfaces(self, make_client):
        def handler(request):
            if request.url.path == "/search":
                return fx.json_response(fx.search_response([fx.usc_hit()]))
            return httpx.Response(503, text="unavailable")

        out = await tools.get_us_code_section(make_client(handler), citation="17 U.S.C. 107")
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 503

    async def test_unparseable_currentthrough_is_stated(self, make_client):
        client = make_client(
            section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_NO_CURRENTTHROUGH)
        )
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        assert out["provenance"]["currentthrough"] is None
        assert "could not be parsed" in out["provenance"]["currentthrough_note"]

    async def test_invalid_citation_is_invalid_argument(self, make_client):
        out = await tools.get_us_code_section(make_client(None), citation="banana")
        assert out["outcome"] == "invalid_argument"

    async def test_invalid_window_args_are_invalid_argument(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", start_char=-5)
        assert out["outcome"] == "invalid_argument"


class TestGetSectionAppendix:
    """O24 upgraded the contract: appendix citations resolve directly through the
    citation field; the redirect survives only as the zero-hit fallback."""

    async def test_appendix_rule_resolves_directly(self, make_client):
        seen = []
        hit = fx.usc_hit(
            package_id="USCODE-2024-title28",
            granule_id="USCODE-2024-title28-app-federalru-rule9",
        )
        client = make_client(section_handler(fx.search_response([hit]), seen=seen))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App. Rule 9")
        assert out["outcome"] == "success"
        assert fx.request_body(seen[0])["query"] == 'collection:USCODE citation:"28 U.S.C. App. Rule 9"'
        assert out["provenance"]["granule_id"] == "USCODE-2024-title28-app-federalru-rule9"

    async def test_appendix_multi_hit_uses_standard_disambiguation(self, make_client):
        # The measured O24 case: "28 U.S.C. App. Rule 9" -> federalru-rule9 and federalru-dup1-rule9.
        hits = [
            fx.usc_hit(package_id="USCODE-2024-title28", granule_id="USCODE-2024-title28-app-federalru-rule9"),
            fx.usc_hit(
                package_id="USCODE-2024-title28", granule_id="USCODE-2024-title28-app-federalru-dup1-rule9"
            ),
        ]
        client = make_client(section_handler(fx.search_response(hits, count=2)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App. Rule 9")
        assert out["outcome"] == "ambiguous"
        assert out["count"] == 2
        assert {c["granule_id"] for c in out["candidates"]} == {
            "USCODE-2024-title28-app-federalru-rule9",
            "USCODE-2024-title28-app-federalru-dup1-rule9",
        }

    async def test_zero_hit_appendix_falls_back_to_structured_redirect(self, make_client):
        # Real for eliminated appendices: citation:"50 U.S.C. App. 1" -> 0 in the current edition (O24).
        client = make_client(section_handler(fx.search_response([], count=0)))
        out = await tools.get_us_code_section(client, citation="50 U.S.C. App. 1")
        assert out["outcome"] == "appendix_redirect"
        assert out["query"] == 'collection:USCODE citation:"50 U.S.C. App. 1"'
        assert out["suggested_tool"] == "search_us_code"
        assert "usctitlenum:50" in out["suggested_query"]

    async def test_zero_hit_non_appendix_is_still_not_found(self, make_client):
        client = make_client(section_handler(fx.search_response([], count=0)))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 99999")
        assert out["outcome"] == "not_found"


class TestSearchUSCode:
    async def test_collection_prepended(self, make_client):
        seen = []

        def handler(request):
            seen.append(request)
            return fx.json_response(fx.search_response([fx.usc_hit()]))

        out = await tools.search_us_code(make_client(handler), "fair use")
        assert fx.request_body(seen[0])["query"] == "collection:USCODE fair use"
        assert out["outcome"] == "success"
        assert out["results"][0]["package_id"] == "USCODE-2024-title17"

    async def test_existing_collection_term_respected(self, make_client):
        seen = []

        def handler(request):
            seen.append(request)
            return fx.json_response(fx.search_response([]))

        await tools.search_us_code(make_client(handler), "collection:PLAW fair use")
        assert fx.request_body(seen[0])["query"] == "collection:PLAW fair use"

    async def test_zero_results_is_explicit_success_with_query_echo(self, make_client):
        out = await tools.search_us_code(
            make_client(lambda request: fx.json_response(fx.search_response([], count=0))), "zxqv"
        )
        assert out["outcome"] == "success"
        assert out["count"] == 0
        assert out["results"] == []
        assert "Zero results" in out["message"]
        assert out["query"] == "collection:USCODE zxqv"

    async def test_page_size_clamped_with_note(self, make_client):
        seen = []

        def handler(request):
            seen.append(request)
            return fx.json_response(fx.search_response([]))

        out = await tools.search_us_code(make_client(handler), "x", page_size=500)
        assert fx.request_body(seen[0])["pageSize"] == 100
        assert "clamped" in out["page_size_note"]

    async def test_historical_and_offset_mark_passed_through(self, make_client):
        seen = []

        def handler(request):
            seen.append(request)
            return fx.json_response(fx.search_response([], offset_mark="NEXT"))

        out = await tools.search_us_code(make_client(handler), "x", historical=True, offset_mark="CUR")
        body = fx.request_body(seen[0])
        assert body["historical"] is True
        assert body["offsetMark"] == "CUR"
        assert out["offset_mark"] == "NEXT"

    async def test_empty_query_is_invalid_argument(self, make_client):
        out = await tools.search_us_code(make_client(None), "   ")
        assert out["outcome"] == "invalid_argument"

    async def test_upstream_error_passthrough(self, make_client):
        out = await tools.search_us_code(make_client(lambda request: httpx.Response(500, text="err")), "x")
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 500
