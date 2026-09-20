"""get_us_code_section and search_us_code contracts from documentation/40-tools.md.

The load-bearing assertions: the three outcomes never collapse (an upstream failure
must never present as not-found), provenance is complete or explicitly incomplete,
truncation is always marked, and normalization strips are reported."""

import fx
import httpx

from uscode_mcp import tools
from uscode_mcp.htmltext import window_text


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
    async def test_foreign_search_hit_txtlink_is_refused_without_fetch(self, make_client):
        seen = []
        hit = fx.usc_hit()
        hit["download"]["txtLink"] = "https://example.com/section.htm"

        def handler(request):
            seen.append(request)
            assert request.url.path == "/search"
            return fx.json_response(fx.search_response([hit]))

        out = await tools.get_us_code_section(make_client(handler), citation="17 U.S.C. 107")

        assert len(seen) == 1
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] is None
        assert "https://example.com/section.htm" in out["detail"]
        assert "txtLink" in out["detail"]
        assert "no request was made" in out["detail"]

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

    async def test_capped_disambiguation_states_shown_of_total(self, make_client):
        # The measured bare-appendix case (O24): 251 matches, one page shown —
        # capping must be stated so it never reads as complete.
        hits = [
            fx.usc_hit(granule_id=f"USCODE-2024-title28-app-federalru-rule{i}") for i in range(100)
        ]
        client = make_client(section_handler(fx.search_response(hits, count=251)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App.")
        assert out["outcome"] == "ambiguous"
        assert out["count"] == 251
        assert out["candidates_shown"] == 100
        assert out["capped"] is True
        assert "showing 100 of 251" in out["message"]

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
        assert out["capped"] is False  # 2 shown of 2 must not claim capping
        assert "capped" not in out["message"]
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


class TestSectionStructure:
    """R12b: every get_us_code_section success carries a structure block, derived from
    the payload's own field markers or explicitly omitted with a reason."""

    async def test_success_carries_the_field_list(self, make_client):
        client = make_client(
            section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_WITH_FIELDS)
        )
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        structure = out["structure"]
        assert structure["omitted"] is False
        assert [f["field"] for f in structure["fields"]][:3] == ["head", "statute", "sourcecredit"]
        assert any(f["heading"] == "Amendments" for f in structure["fields"])

    async def test_structure_offsets_are_usable_as_start_char(self, make_client):
        client = make_client(
            section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_WITH_FIELDS)
        )
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        note = next(f for f in out["structure"]["fields"] if f["field"] == "amendment-note")
        jumped = await tools.get_us_code_section(
            make_client(section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_WITH_FIELDS)),
            citation="17 U.S.C. 107",
            start_char=note["start_char"],
        )
        assert jumped["text"]["content"].startswith("Amendments")

    async def test_markerless_granule_still_succeeds_with_a_disclosure(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        assert out["structure"]["omitted"] is True
        assert out["structure"]["reason"]
        assert "Effective date note text" in out["text"]["content"]

    async def test_unbalanced_markers_still_succeed_with_a_disclosure(self, make_client):
        client = make_client(
            section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_UNBALANCED_FIELDS)
        )
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        assert out["structure"]["omitted"] is True
        assert "field-end:statute" in out["structure"]["reason"]


class TestSectionFind:
    """R12a on get_us_code_section: locate in the full payload, in window coordinates."""

    async def test_find_reports_offsets_in_the_full_payload(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", find="Effective date")
        found = out["find"]
        assert found["total_occurrences"] == 1
        offset = found["occurrences"][0]["start_char"]
        assert out["text"]["content"][offset:].startswith("Effective date")

    async def test_find_locates_content_outside_the_returned_window(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(
            client, citation="17 U.S.C. 107", max_chars=20, find="Effective date"
        )
        assert out["text"]["truncated"] is True
        assert "Effective date" not in out["text"]["content"]
        assert out["find"]["total_occurrences"] == 1
        assert out["find"]["searched_chars"] == out["text"]["total_chars"]

    async def test_zero_matches_is_a_success_with_an_explicit_report(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", find="antidisestablishment")
        assert out["outcome"] == "success"
        assert out["find"]["total_occurrences"] == 0
        assert "Zero occurrences" in out["find"]["message"]

    async def test_find_is_absent_when_not_requested(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert "find" not in out

    async def test_blank_find_is_rejected_before_any_upstream_call(self, make_client):
        seen = []
        client = make_client(section_handler(fx.search_response([fx.usc_hit()]), seen=seen))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", find="   ")
        assert out["outcome"] == "invalid_argument"
        assert "find" in out["detail"]
        assert seen == []

    async def test_find_is_not_attached_to_a_failure_outcome(self, make_client):
        def handler(request):
            return fx.json_response(fx.search_response([]))

        out = await tools.get_us_code_section(make_client(handler), citation="17 U.S.C. 107", find="anything")
        assert out["outcome"] == "not_found"
        assert "find" not in out


class TestStructureRidesOnTheLocatingCall:
    """R13a: structure on start_char=0, disclosed omission on a reading call."""

    def _client(self, make_client):
        return make_client(
            section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_WITH_FIELDS)
        )

    async def test_locating_call_carries_the_field_list(self, make_client):
        out = await tools.get_us_code_section(self._client(make_client), citation="17 U.S.C. 107")
        assert out["structure"]["omitted"] is False
        assert out["structure"]["fields"]

    async def test_explicit_zero_start_char_is_still_a_locating_call(self, make_client):
        out = await tools.get_us_code_section(
            self._client(make_client), citation="17 U.S.C. 107", start_char=0
        )
        assert out["structure"]["omitted"] is False

    async def test_reading_call_omits_it_and_points_back(self, make_client):
        out = await tools.get_us_code_section(
            self._client(make_client), citation="17 U.S.C. 107", start_char=50
        )
        assert out["outcome"] == "success"
        structure = out["structure"]
        assert structure["omitted"] is True
        assert "start_char=50" in structure["reason"]
        assert "start_char=0" in structure["note"]
        assert "fields" not in structure

    async def test_reading_call_still_returns_the_text(self, make_client):
        out = await tools.get_us_code_section(
            self._client(make_client), citation="17 U.S.C. 107", start_char=50, max_chars=40
        )
        assert out["text"]["returned_chars"] == 40
        assert out["text"]["start_char"] == 50

    async def test_the_omitted_key_is_present_on_every_success(self, make_client):
        # The harness check reads structure.omitted; it must never be missing.
        for start in (0, 10):
            out = await tools.get_us_code_section(
                self._client(make_client), citation="17 U.S.C. 107", start_char=start
            )
            assert "omitted" in out["structure"]

    async def test_a_reading_call_is_much_smaller_than_a_locating_one(self, make_client):
        # The symptom R13a fixes: the invariant block dwarfing a small read (O38).
        import json

        located = await tools.get_us_code_section(
            self._client(make_client), citation="17 U.S.C. 107", max_chars=40
        )
        read = await tools.get_us_code_section(
            self._client(make_client), citation="17 U.S.C. 107", start_char=50, max_chars=40
        )
        assert len(json.dumps(read["structure"])) < len(json.dumps(located["structure"]))


class TestSectionFieldExtent:
    async def test_fields_carry_usable_end_char(self, make_client):
        client = make_client(
            section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_WITH_FIELDS)
        )
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        note = next(f for f in out["structure"]["fields"] if f["field"] == "amendment-note")
        read = await tools.get_us_code_section(
            make_client(section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_WITH_FIELDS)),
            citation="17 U.S.C. 107",
            start_char=note["start_char"],
            max_chars=note["end_char"] - note["start_char"],
        )
        assert read["text"]["truncated"] is False
        assert read["text"]["content"].startswith("Amendments")


class TestPublicLinksOnSection:
    """WO-7 (O53): the granule form of the keyless content-path PDF, built from the
    response's own package_id and granule_id. The citation path resolves through a
    search hit, which carries no detailsLink (measured 2026-09-19), so details_link is
    null here; the granule_id path (test_tools_by_id) has the summary's value."""

    async def test_provenance_carries_granule_form_public_pdf_link(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        prov = out["provenance"]
        assert prov["public_pdf_link"] == (
            "https://www.govinfo.gov/content/pkg/USCODE-2024-title17/pdf/USCODE-2024-title17-chap1-sec107.pdf"
        )
        assert prov["pdf_link"] == fx.usc_hit()["download"]["pdfLink"]  # unchanged

    async def test_citation_path_details_link_is_null_because_search_hits_carry_none(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        assert "details_link" in out["provenance"]
        assert out["provenance"]["details_link"] is None

    async def test_public_link_follows_the_resolved_ids_not_the_citation(self, make_client):
        hit = fx.usc_hit(package_id="USCODE-1998-title17", granule_id="USCODE-1998-title17-chap1-sec107",
                         date_issued="1998-01-05")
        client = make_client(section_handler(fx.search_response([hit])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", year=1998)
        assert out["outcome"] == "success"
        assert out["provenance"]["public_pdf_link"] == (
            "https://www.govinfo.gov/content/pkg/USCODE-1998-title17/pdf/USCODE-1998-title17-chap1-sec107.pdf"
        )

    async def test_untruncated_response_carries_both_fields_and_no_sentence(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["text"]["truncated"] is False
        assert "message" not in out["text"]
        assert "public_pdf_link" in out["provenance"] and "details_link" in out["provenance"]


class TestAudienceSentenceOnTruncatedSection:
    """WO-6 as amended by WO-7: the audience sentence on truncated get_us_code_section
    responses carries the granule's PUBLIC PDF link, not the keyed api.govinfo.gov one."""

    async def test_message_carries_public_pdf_link_inline_and_not_the_keyed_one(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", max_chars=50)
        text = out["text"]
        assert text["truncated"] is True
        prov = out["provenance"]
        message = text["message"]
        assert prov["public_pdf_link"] in message
        assert prov["pdf_link"] not in message
        assert "api.govinfo.gov" not in message
        assert "PDF" in message
        assert "tool caller" in message
        assert "person asking" in message
        assert "provenance" not in message

    async def test_continuation_sentence_and_banner_are_byte_unchanged(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", max_chars=50)
        text = out["text"]
        bare = window_text("x" * text["total_chars"], start_char=text["start_char"], max_chars=50)
        assert text["message"].startswith(bare["message"])
        assert "NOT part of the payload" in bare["message"]
        assert text["banner"] == bare["banner"]
        assert text["content"].split("\n", 1)[0] == bare["banner"]

    async def test_reading_call_window_also_carries_the_sentence(self, make_client):
        # A continuation window that is itself truncated is still a truncated response.
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", start_char=10, max_chars=20)
        assert out["text"]["truncated"] is True
        assert out["provenance"]["public_pdf_link"] in out["text"]["message"]

    async def test_untruncated_response_has_no_audience_sentence(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["text"]["truncated"] is False
        assert "message" not in out["text"]

    async def test_hit_without_a_keyed_pdf_link_still_gives_the_public_link(self, make_client):
        hit = fx.usc_hit()
        del hit["download"]["pdfLink"]
        client = make_client(section_handler(fx.search_response([hit])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", max_chars=50)
        assert out["outcome"] == "success"
        assert out["provenance"]["pdf_link"] is None
        message = out["text"]["message"]
        assert out["provenance"]["public_pdf_link"] in message
        assert "no PDF link is available" not in message
        assert "None" not in message

    async def test_hit_without_a_package_id_reaches_the_no_link_wording(self, make_client):
        # The one reachable fallback: a search hit with no packageId (shape drift) is
        # the only way public_pdf_link cannot be built, and the citation path has no
        # summary so details_link is null too — the sentence says so rather than
        # emitting an empty URL. (The details-page fallback is NOT reachable: details_link
        # exists only on the summary paths, where a package id always exists.)
        hit = fx.usc_hit()
        del hit["packageId"]
        client = make_client(section_handler(fx.search_response([hit])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", max_chars=50)
        assert out["outcome"] == "success"
        assert out["provenance"]["public_pdf_link"] is None
        assert out["provenance"]["details_link"] is None
        message = out["text"]["message"]
        assert "no PDF link is available" in message
        assert "https://" not in message.split("NOT part of the payload", 1)[1]
        assert "None" not in message
