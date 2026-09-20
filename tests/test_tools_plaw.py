"""get_public_law and search_public_laws contracts from documentation/40-tools.md and
50-public-law.md: private-law scope boundary, USLM as a reportable not-available
outcome, package-level windowing, and the uscodecitation recall caveat."""

import fx
import httpx
import pytest

from uscode_mcp import tools
from uscode_mcp.htmltext import window_text


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
        assert fx.request_body(seen[0])["query"] == "collection:PLAW lawtype:public congress:118 docnumber:31"
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

    async def test_citation_path_uses_public_law_filter(self, make_client):
        seen = []
        out = await tools.get_public_law(
            make_client(plaw_handler(seen=seen)), citation="Pub. L. 118-31"
        )
        assert out["outcome"] == "success"
        assert fx.request_body(seen[0])["query"] == (
            "collection:PLAW lawtype:public congress:118 docnumber:31"
        )

    async def test_private_law_is_out_of_scope_not_a_failed_lookup(self, make_client):
        out = await tools.get_public_law(make_client(None), citation="Priv. L. 108-1")
        assert out["outcome"] == "out_of_scope_private_law"
        assert "not a" in out["message"] and "failed lookup" in out["message"]

    async def test_uslm_format_returns_raw_xml(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31, format="uslm")
        assert out["outcome"] == "success"
        assert out["format"] == "uslm"
        assert "<uslm" in out["text"]["content"]  # raw XML, not stripped

    @pytest.mark.parametrize(
        ("format", "field"),
        [("text", "txtLink"), ("uslm", "uslmLink")],
    )
    async def test_foreign_summary_download_link_is_refused_without_fetch(
        self, make_client, format, field
    ):
        seen = []
        summary = fx.plaw_summary()
        summary["download"][field] = "https://example.com/law"
        client = make_client(plaw_handler(summary=summary, seen=seen))

        out = await tools.get_public_law(client, congress=118, law_number=31, format=format)

        assert [request.url.path for request in seen] == [
            "/search",
            "/packages/PLAW-118publ31/summary",
        ]
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] is None
        assert "https://example.com/law" in out["detail"]
        assert field in out["detail"]

    @pytest.mark.parametrize("location", ["https://example.com/next", f"{fx.API}/next"])
    async def test_download_redirect_is_not_followed_and_location_is_surfaced(self, make_client, location):
        seen = []

        def handler(request):
            seen.append(request)
            if request.url.path == "/search":
                return fx.json_response(fx.search_response([fx.plaw_hit()]))
            if request.url.path.endswith("/summary"):
                return fx.json_response(fx.plaw_summary())
            if request.url.path.endswith("/htm"):
                return httpx.Response(302, headers={"Location": location})
            raise AssertionError(f"redirect was followed: {request.url}")

        out = await tools.get_public_law(make_client(handler), congress=118, law_number=31)

        assert len(seen) == 3
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 302
        assert out["location"] == location

    async def test_uslm_absent_is_a_distinct_reportable_outcome(self, make_client):
        package_id = "PLAW-104publ1"
        handler = plaw_handler(
            search_payload=fx.search_response([fx.plaw_hit(package_id=package_id)]),
            summary=fx.plaw_summary(package_id=package_id, uslm=False),
        )
        out = await tools.get_public_law(make_client(handler), congress=104, law_number=1, format="uslm")
        assert out["outcome"] == "format_not_available"
        assert out["format"] == "uslm"
        assert "txtLink" in out["available_formats"]
        assert "uslmLink" not in out["available_formats"]
        assert "104-112" in out["message"]  # measured boundary (O25), not "unmeasured"

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
        assert out["query"] == "collection:PLAW lawtype:public congress:118 docnumber:9999"

    async def test_non_public_package_identity_is_upstream_error(self, make_client):
        hit = fx.plaw_hit(package_id="PLAW-119pvtl2")
        out = await tools.get_public_law(
            make_client(plaw_handler(search_payload=fx.search_response([hit]))),
            congress=119,
            law_number=2,
        )
        assert out["outcome"] == "upstream_error"
        assert "PLAW-119publ2" in out["detail"]
        assert "PLAW-119pvtl2" in out["detail"]

    async def test_ambiguous_message_does_not_repeat_the_same_inputs(self, make_client):
        hits = [fx.plaw_hit(), fx.plaw_hit(package_id="PLAW-118publ31-duplicate")]
        out = await tools.get_public_law(
            make_client(plaw_handler(search_payload=fx.search_response(hits, count=2))),
            congress=118,
            law_number=31,
        )
        assert out["outcome"] == "ambiguous"
        assert "did not resolve to one public law" in out["message"]
        assert "package_id" in out["message"]
        assert "re-request" not in out["message"]

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

    async def test_reverse_lookup_carries_the_field_recall_caveat(self, make_client):
        def handler(request):
            return fx.json_response(fx.search_response([fx.plaw_hit()], count=14))

        out = await tools.search_public_laws(make_client(handler), 'uscodecitation:"42 U.S.C. 2210"')
        assert out["recall_caveat"] == tools.RECALL_CAVEAT_USCODECITATION
        assert "never evidence" in out["recall_caveat"]
        assert "25/33" in out["recall_caveat"]
        assert "structural" in out["recall_caveat"]

    async def test_full_text_query_carries_the_full_text_caveat(self, make_client):
        # WO-5 change 4 (O49c): a quoted phrase was measured missing a law containing it
        # verbatim, so full-text results are not evidence of absence either.
        out = await tools.search_public_laws(
            make_client(lambda request: fx.json_response(fx.search_response([], count=0))),
            'congress:119 "Price-Anderson"',
        )
        assert out["outcome"] == "success"
        assert out["count"] == 0
        assert out["recall_caveat"] == tools.RECALL_CAVEAT_FULLTEXT
        assert "never evidence of absence" in out["recall_caveat"]
        assert "25/33" not in out["recall_caveat"]

    async def test_numbered_query_carries_the_full_text_caveat(self, make_client):
        out = await tools.search_public_laws(
            make_client(lambda request: fx.json_response(fx.search_response([fx.plaw_hit()]))),
            "congress:118 docnumber:31",
        )
        assert out["recall_caveat"] == tools.RECALL_CAVEAT_FULLTEXT

    async def test_caveat_selection_is_by_the_query_actually_sent(self, make_client):
        # Mixed query: the field wording wins whenever uscodecitation: is present.
        out = await tools.search_public_laws(
            make_client(lambda request: fx.json_response(fx.search_response([]))),
            'uscodecitation:"42 U.S.C. 2210" publishdate:range(2025-01-07,)',
        )
        assert out["recall_caveat"] == tools.RECALL_CAVEAT_USCODECITATION

    async def test_no_caveat_on_failure_outcomes(self, make_client):
        for resp in (httpx.Response(500, text="err"), httpx.Response(429, text="slow")):
            out = await tools.search_public_laws(make_client(lambda request, r=resp: r), "anything")
            assert out["outcome"] in {"upstream_error", "rate_limited"}
            assert "recall_caveat" not in out

    async def test_search_us_code_has_no_plaw_caveat(self, make_client):
        out = await tools.search_us_code(
            make_client(lambda request: fx.json_response(fx.search_response([]))), "fair use"
        )
        assert "recall_caveat" not in out

    async def test_zero_results_explicit(self, make_client):
        out = await tools.search_public_laws(
            make_client(lambda request: fx.json_response(fx.search_response([], count=0))), "zxqv"
        )
        assert out["outcome"] == "success"
        assert out["count"] == 0
        assert "Zero results" in out["message"]


class TestPublicLawFind:
    """R12a on get_public_law: the structure-free locator. PLAW payloads carry no
    field markers upstream (O36), so `find` is the whole location story here."""

    async def test_find_reports_offsets_in_the_full_payload(self, make_client):
        out = await tools.get_public_law(
            make_client(plaw_handler()), congress=118, law_number=31, find="NDAA fixture"
        )
        found = out["find"]
        assert found["total_occurrences"] == 1
        offset = found["occurrences"][0]["start_char"]
        assert out["text"]["content"][offset:].startswith("NDAA fixture")

    async def test_find_locates_content_outside_the_returned_window(self, make_client):
        out = await tools.get_public_law(
            make_client(plaw_handler()), congress=118, law_number=31, max_chars=30, find="NDAA fixture"
        )
        assert out["text"]["truncated"] is True
        assert "NDAA fixture" not in out["text"]["content"]
        assert out["find"]["total_occurrences"] == 1
        assert out["find"]["occurrences"][0]["start_char"] > out["text"]["returned_chars"]

    async def test_no_structure_block_on_a_flat_plaw_payload(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31)
        assert out["outcome"] == "success"
        assert "structure" not in out

    async def test_find_works_on_the_uslm_format(self, make_client):
        out = await tools.get_public_law(
            make_client(plaw_handler()), congress=118, law_number=31, format="uslm", find="Sec. 1."
        )
        assert out["format"] == "uslm"
        assert out["find"]["total_occurrences"] == 1

    async def test_zero_matches_is_a_success_with_an_explicit_report(self, make_client):
        out = await tools.get_public_law(
            make_client(plaw_handler()), congress=118, law_number=31, find="no such provision"
        )
        assert out["outcome"] == "success"
        assert out["find"]["total_occurrences"] == 0
        assert "Zero occurrences" in out["find"]["message"]

    async def test_blank_find_is_rejected_before_any_upstream_call(self, make_client):
        seen = []
        out = await tools.get_public_law(
            make_client(plaw_handler(seen=seen)), congress=118, law_number=31, find=""
        )
        assert out["outcome"] == "invalid_argument"
        assert "find" in out["detail"]
        assert seen == []

    async def test_find_is_absent_when_not_requested(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31)
        assert "find" not in out

    async def test_find_is_not_attached_to_a_scope_boundary_outcome(self, make_client):
        out = await tools.get_public_law(
            make_client(plaw_handler()), citation="Private Law 118-3", find="anything"
        )
        assert out["outcome"] == "out_of_scope_private_law"
        assert "find" not in out


class TestPublicLawTruncationBanner:
    """E12: a windowed law leads its text with the in-band disclosure (finding F1)."""

    async def test_truncated_response_leads_with_the_banner(self, make_client):
        out = await tools.get_public_law(
            make_client(plaw_handler()), congress=118, law_number=31, max_chars=40
        )
        text = out["text"]
        assert text["truncated"] is True
        first_line = text["content"].split("\n", 1)[0]
        assert first_line == text["banner"]
        assert str(text["total_chars"]) in first_line.replace(",", "")
        assert f"start_char={text['next_start_char']}" in first_line

    async def test_untruncated_response_carries_no_banner(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31)
        assert out["text"]["truncated"] is False
        assert "banner" not in out["text"]
        assert "[WINDOW" not in out["text"]["content"]


class TestBannerCoordinateDisclosure:
    """R13c: the in-band statement that the banner sits outside the offset coordinate
    system is contractual on every bannered response, so it cannot regress away."""

    async def test_bannered_response_states_the_banner_is_not_the_payload(self, make_client):
        out = await tools.get_public_law(
            make_client(plaw_handler()), congress=118, law_number=31, max_chars=40
        )
        message = out["text"]["message"]
        assert "banner" in message
        assert "NOT part of the payload" in message
        assert "start_char" in message

    async def test_find_offset_round_trips_through_start_char_under_truncation(self, make_client):
        # O38's own verification: locate in a payload never fully read, then open a
        # window on the offset — the banner must not shift the coordinate system.
        located = await tools.get_public_law(
            make_client(plaw_handler()), congress=118, law_number=31, max_chars=30, find="NDAA fixture"
        )
        assert located["text"]["truncated"] is True
        assert "NDAA fixture" not in located["text"]["content"]
        offset = located["find"]["occurrences"][0]["start_char"]

        read = await tools.get_public_law(
            make_client(plaw_handler()), congress=118, law_number=31, start_char=offset, max_chars=12
        )
        payload = read["text"]["content"].split("\n", 1)[1] if "banner" in read["text"] else read["text"]["content"]
        assert payload == "NDAA fixture"

    async def test_no_message_claim_when_there_is_no_banner(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31)
        assert "message" not in out["text"]


class TestPublicLinksOnLaw:
    """WO-7 (O53): every text-bearing success carries a keyless content-path PDF built
    from the package id and nothing else, plus the package summary's detailsLink
    verbatim; pdf_link (api.govinfo.gov, 401 without the key) stays exactly as it was."""

    async def test_provenance_carries_public_pdf_link_and_details_link(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31)
        prov = out["provenance"]
        assert prov["package_id"] == "PLAW-118publ31"
        assert prov["public_pdf_link"] == "https://www.govinfo.gov/content/pkg/PLAW-118publ31/pdf/PLAW-118publ31.pdf"
        assert prov["details_link"] == fx.plaw_summary()["detailsLink"]
        assert prov["pdf_link"] == fx.plaw_summary()["download"]["pdfLink"]  # unchanged

    async def test_untruncated_response_carries_both_links_and_no_sentence(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31)
        assert out["text"]["truncated"] is False
        assert "message" not in out["text"]
        assert out["provenance"]["public_pdf_link"]
        assert out["provenance"]["details_link"]
        assert "govinfo.gov" not in out["text"]["content"]

    async def test_summary_without_details_link_yields_null_not_an_error(self, make_client):
        summary = fx.plaw_summary()
        del summary["detailsLink"]
        out = await tools.get_public_law(make_client(plaw_handler(summary=summary)), congress=118, law_number=31)
        assert out["outcome"] == "success"
        assert out["provenance"]["details_link"] is None
        assert out["provenance"]["public_pdf_link"].endswith("/PLAW-118publ31.pdf")

    async def test_uslm_format_carries_the_same_public_links(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31, format="uslm")
        assert out["outcome"] == "success"
        assert out["provenance"]["public_pdf_link"].endswith("/pdf/PLAW-118publ31.pdf")
        assert out["provenance"]["details_link"] == fx.plaw_summary()["detailsLink"]


class TestAudienceSentenceOnTruncatedLaw:
    """WO-6 (O51c) as amended by WO-7 (O53a): a truncated get_public_law response tells
    the tool caller the start_char continuation is theirs and gives the person asking
    the PUBLIC PDF link inline — the api.govinfo.gov pdf_link answers 401 without a key."""

    async def test_message_carries_public_pdf_link_inline_and_not_the_keyed_one(self, make_client):
        out = await tools.get_public_law(
            make_client(plaw_handler()), congress=118, law_number=31, max_chars=40
        )
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
        assert "provenance" not in message  # the URL itself, never a pointer to the field

    async def test_continuation_sentence_and_banner_are_byte_unchanged(self, make_client):
        out = await tools.get_public_law(
            make_client(plaw_handler()), congress=118, law_number=31, max_chars=40
        )
        text = out["text"]
        # Reconstruct what the window said before WO-6 from the response's own coordinates.
        bare = window_text("x" * text["total_chars"], start_char=text["start_char"], max_chars=40)
        assert text["message"].startswith(bare["message"])
        assert "NOT part of the payload" in bare["message"]  # R13c's statement is what stays first
        assert text["banner"] == bare["banner"]
        assert text["content"].split("\n", 1)[0] == bare["banner"]

    async def test_untruncated_response_has_no_audience_sentence(self, make_client):
        out = await tools.get_public_law(make_client(plaw_handler()), congress=118, law_number=31)
        assert out["text"]["truncated"] is False
        assert "message" not in out["text"]

    async def test_summary_without_a_keyed_pdf_link_still_gives_the_public_link(self, make_client):
        # The public link is built from the package id, so a download map without
        # pdfLink changes pdf_link (null) and nothing about the sentence.
        summary = fx.plaw_summary()
        del summary["download"]["pdfLink"]
        out = await tools.get_public_law(
            make_client(plaw_handler(summary=summary)), congress=118, law_number=31, max_chars=40
        )
        assert out["outcome"] == "success"
        assert out["provenance"]["pdf_link"] is None
        message = out["text"]["message"]
        assert out["provenance"]["public_pdf_link"] in message
        assert "no PDF link is available" not in message
        assert "None" not in message
