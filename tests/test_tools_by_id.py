"""R16 / WO-3: `granule_id` on get_us_code_section (documentation/40-tools.md, "By-id
behavior"), the disambiguation message that names it, and the server instructions.

Load-bearing: no URL is ever constructed from the id (the summary's txtLink is used
verbatim); package_id derivation is disclosed; a 404 is not_found and never an
upstream failure; a non-USCODE id makes no HTTP call; and the id path reuses the
citation path's delivery code, so provenance, structure, windowing and
possibly_superseded all appear.
"""

from __future__ import annotations

import fx
import httpx
import pytest

from uscode_mcp import tools
from uscode_mcp.server import SERVER_INSTRUCTIONS, create_server

GID = "USCODE-2024-title17-chap1-sec107"
PID = "USCODE-2024-title17"
SUMMARY_PATH = f"/packages/{PID}/granules/{GID}/summary"
DETECTOR_QUERY_107 = 'collection:PLAW lawtype:public publishdate:range(2025-01-07,) uscodecitation:"17 U.S.C. 107"'


def by_id_handler(summary_response=None, htm_text=fx.SECTION_HTML, seen=None, detector_response=None):
    """Serve the granule summary, the /htm link it carries, and the PLAW detector."""

    def handler(request):
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith("/summary"):
            return summary_response if summary_response is not None else fx.json_response(fx.granule_summary())
        if request.url.path.endswith("/htm"):
            return httpx.Response(200, text=htm_text)
        if request.url.path == "/search":
            body = fx.request_body(request)
            assert "collection:PLAW" in body["query"], "the id path must not run a citation search"
            return detector_response if detector_response is not None else fx.json_response(fx.search_response([]))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


class TestByIdSuccess:
    async def test_success_via_summary_txtlink_with_full_delivery(self, make_client):
        seen = []
        client = make_client(by_id_handler(seen=seen))
        out = await tools.get_us_code_section(client, granule_id=GID, citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        assert out["granule_id"] == GID
        assert out["package_id"] == PID
        assert out["citation"] == "17 U.S.C. 107"
        prov = out["provenance"]
        assert prov["package_id"] == PID
        assert prov["granule_id"] == GID
        assert prov["edition_year"] == 2024
        assert prov["currentthrough"] == "2025-01-06"
        assert prov["last_modified"] == "2025-03-01T00:00:00Z"
        assert prov["pdf_link"].endswith("/pdf")
        assert "fair use of a copyrighted work" in out["text"]["content"]
        assert "must never be dropped" in out["text"]["content"]
        assert "omitted" in out["structure"]
        assert out["possibly_superseded"]["status"] == "none_indexed"
        assert out["possibly_superseded"]["query"] == DETECTOR_QUERY_107
        # The wire: summary GET first, then the txtLink exactly as the summary carried it.
        paths = [r.url.path for r in seen if r.url.path != "/search"]
        assert paths[0] == SUMMARY_PATH
        assert paths[1] == f"/packages/{PID}/granules/{GID}/htm"
        assert all(r.url.path != "/search" or "collection:PLAW" in fx.request_body(r)["query"] for r in seen)

    async def test_txtlink_is_taken_verbatim_not_constructed(self, make_client):
        seen = []
        summary = fx.granule_summary()
        summary["download"]["txtLink"] = "https://api.govinfo.gov/some/other/path/htm"
        client = make_client(by_id_handler(fx.json_response(summary), seen=seen))
        out = await tools.get_us_code_section(client, granule_id=GID)
        assert out["outcome"] == "success"
        assert any(str(r.url) == "https://api.govinfo.gov/some/other/path/htm" for r in seen)

    async def test_foreign_summary_txtlink_is_refused_without_fetch(self, make_client):
        seen = []
        summary = fx.granule_summary()
        summary["download"]["txtLink"] = "https://example.com/section.htm"
        client = make_client(by_id_handler(fx.json_response(summary), seen=seen))

        out = await tools.get_us_code_section(client, granule_id=GID)

        assert [request.url.path for request in seen] == [SUMMARY_PATH]
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] is None
        assert "https://example.com/section.htm" in out["detail"]
        assert "txtLink" in out["detail"]

    async def test_package_id_derived_and_disclosed(self, make_client):
        out = await tools.get_us_code_section(make_client(by_id_handler()), granule_id=GID)
        assert out["package_id"] == PID
        assert out["package_id_derived"] is True
        assert PID in out["package_id_note"]

    async def test_explicit_package_id_honored_not_derived(self, make_client):
        seen = []
        client = make_client(by_id_handler(seen=seen))
        out = await tools.get_us_code_section(client, granule_id=GID, package_id="USCODE-2024-title17")
        assert out["package_id_derived"] is False
        assert "package_id_note" not in out
        assert seen[0].url.path == SUMMARY_PATH

    async def test_explicit_package_id_is_what_gets_requested(self, make_client):
        # A supplied package_id is sent as given, even if it does not match the id's prefix.
        seen = []

        def handler(request):
            seen.append(request)
            if request.url.path.endswith("/summary"):
                return httpx.Response(404, text="no such granule")
            raise AssertionError

        out = await tools.get_us_code_section(make_client(handler), granule_id=GID, package_id="USCODE-2023-title17")
        assert out["outcome"] == "not_found"
        assert seen[0].url.path == f"/packages/USCODE-2023-title17/granules/{GID}/summary"

    async def test_year_is_ignored_with_a_warning(self, make_client):
        out = await tools.get_us_code_section(make_client(by_id_handler()), granule_id=GID, year=1998)
        assert out["outcome"] == "success"
        assert any("year=1998" in w and "ignored" in w for w in out["warnings"])
        assert out["provenance"]["edition_year"] == 2024

    async def test_no_warnings_key_without_year(self, make_client):
        out = await tools.get_us_code_section(make_client(by_id_handler()), granule_id=GID)
        assert "warnings" not in out

    async def test_windowing_and_find_work_on_the_id_path(self, make_client):
        out = await tools.get_us_code_section(
            make_client(by_id_handler()), granule_id=GID, max_chars=30, find="Effective date"
        )
        assert out["text"]["truncated"] is True
        assert out["text"]["banner"].startswith("[WINDOW")
        assert not out["text"]["content"].startswith("[WINDOW")
        assert out["text"]["returned_chars"] == len(out["text"]["content"])
        assert out["find"]["total_occurrences"] == 1

    async def test_structure_from_markers_on_the_id_path(self, make_client):
        out = await tools.get_us_code_section(
            make_client(by_id_handler(htm_text=fx.SECTION_HTML_WITH_FIELDS)), granule_id=GID
        )
        assert out["structure"]["omitted"] is False
        assert [f["field"] for f in out["structure"]["fields"]][:2] == ["head", "statute"]

    @pytest.mark.parametrize("window", [{"max_chars": 0}, {"start_char": -1}, {"max_chars": "20"}])
    async def test_invalid_window_args_on_the_id_path_make_no_request(self, make_client, window):
        seen = []
        out = await tools.get_us_code_section(make_client(by_id_handler(seen=seen)), granule_id=GID, **window)
        assert out["outcome"] == "invalid_argument"
        assert seen == []


class TestByIdDetector:
    async def test_detector_runs_on_the_supplied_citation(self, make_client):
        seen = []
        law = {"packageId": "PLAW-119publ1", "title": "x", "dateIssued": "2025-02-01"}
        resp = fx.json_response(fx.search_response([law], count=1))
        client = make_client(by_id_handler(seen=seen, detector_response=resp))
        out = await tools.get_us_code_section(client, granule_id=GID, citation="17 U.S.C. § 107(b)")
        ps = out["possibly_superseded"]
        assert ps["status"] == "laws_indexed"
        assert ps["checked_citation"] == "17 U.S.C. 107"  # the subsection strip applied
        assert ps["query"] == DETECTOR_QUERY_107
        assert out["normalization"]["stripped_subsection"] == "(b)"
        assert out["normalization"]["citation_basis"] == "caller_supplied"
        assert "caller supplied" in ps["citation_statement"]
        assert "did not verify" in ps["citation_statement"]
        assert out["citation"] == "17 U.S.C. 107"

    @pytest.mark.parametrize(
        ("detector_response", "status"),
        [
            (fx.json_response(fx.search_response([], count=0)), "none_indexed"),
            (
                fx.json_response(
                    fx.search_response(
                        [{"packageId": "PLAW-119publ1", "title": "x", "dateIssued": "2025-02-01"}],
                        count=1,
                    )
                ),
                "laws_indexed",
            ),
            (httpx.Response(500, text="detector failed"), "not_checked"),
        ],
    )
    async def test_caller_supplied_statement_is_present_in_every_detector_state(
        self, make_client, detector_response, status
    ):
        out = await tools.get_us_code_section(
            make_client(by_id_handler(detector_response=detector_response)),
            granule_id=GID,
            citation="17 U.S.C. 106",
        )
        assert out["outcome"] == "success"
        assert out["normalization"]["citation_basis"] == "caller_supplied"
        assert out["possibly_superseded"]["status"] == status
        assert "different section" in out["possibly_superseded"]["citation_statement"]

    async def test_detector_on_title_and_section_fields(self, make_client):
        out = await tools.get_us_code_section(make_client(by_id_handler()), granule_id=GID, title="17", section="107")
        assert out["possibly_superseded"]["checked_citation"] == "17 U.S.C. 107"

    async def test_stripped_note_statement_on_the_id_path(self, make_client):
        out = await tools.get_us_code_section(
            make_client(by_id_handler()), granule_id=GID, citation="17 U.S.C. 107 note"
        )
        assert "note_statement" in out["possibly_superseded"]

    async def test_no_citation_is_not_checked_with_its_own_reason(self, make_client):
        seen = []
        out = await tools.get_us_code_section(make_client(by_id_handler(seen=seen)), granule_id=GID)
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked"
        assert ps["reason"] == "no_citation_for_detector"
        assert "citation" in ps["detail"] and "granule_id" in ps["detail"]
        assert ps["query"] is None
        assert ps["checked_citation"] is None
        assert out["citation"] is None
        assert "normalization" not in out
        assert not any(r.url.path == "/search" for r in seen)

    async def test_rule_id_with_rule_citation_is_no_measured_form(self, make_client):
        gid = "USCODE-2024-title28-app-federalru-dup1-rule9"
        summary = fx.granule_summary(package_id="USCODE-2024-title28", granule_id=gid)
        out = await tools.get_us_code_section(
            make_client(by_id_handler(fx.json_response(summary))), granule_id=gid, citation="28 U.S.C. App. Rule 9"
        )
        assert out["outcome"] == "success"
        assert out["package_id"] == "USCODE-2024-title28"
        assert out["possibly_superseded"]["reason"] == "no_measured_citation_form"

    async def test_bad_citation_alongside_id_is_invalid_argument_before_any_call(self, make_client):
        seen = []
        out = await tools.get_us_code_section(make_client(by_id_handler(seen=seen)), granule_id=GID, citation="banana")
        assert out["outcome"] == "invalid_argument"
        assert seen == []

    async def test_mismatched_citation_title_is_rejected_before_any_call(self, make_client):
        seen = []
        out = await tools.get_us_code_section(
            make_client(by_id_handler(seen=seen)), granule_id=GID, citation="42 U.S.C. 2210"
        )
        assert out["outcome"] == "invalid_argument"
        assert "citation title '42'" in out["detail"]
        assert "package title '17'" in out["detail"]
        assert "nothing was fetched" in out["detail"]
        assert seen == []

    async def test_explicit_package_title_controls_the_title_check(self, make_client):
        seen = []
        out = await tools.get_us_code_section(
            make_client(by_id_handler(seen=seen)),
            granule_id=GID,
            package_id="USCODE-2024-title42",
            citation="17 U.S.C. 107",
        )
        assert out["outcome"] == "invalid_argument"
        assert "citation title '17'" in out["detail"]
        assert "package title '42'" in out["detail"]
        assert seen == []

    async def test_warm_id_lookup_issues_the_detector_before_the_summary(self, make_client):
        # Remember the 2024 edition, then look up by id: the id names its edition, so
        # the detector can go out before the summary GET and be verified after the fetch.
        await tools.get_us_code_section(make_client(by_id_handler()), granule_id=GID, citation="17 U.S.C. 107")
        seen = []
        out = await tools.get_us_code_section(
            make_client(by_id_handler(seen=seen)), granule_id=GID, citation="17 U.S.C. 107"
        )
        assert out["possibly_superseded"]["issued"] == "before_search"
        assert "prediction_note" not in out["possibly_superseded"]


class TestByIdFailures:
    async def test_summary_404_is_not_found_with_the_id(self, make_client):
        def handler(request):
            assert request.url.path.endswith("/summary")
            return httpx.Response(404, text='{"message":"Not Found"}')

        out = await tools.get_us_code_section(make_client(handler), granule_id=GID)
        assert out["outcome"] == "not_found"
        assert out["granule_id"] == GID
        assert out["package_id"] == PID
        assert out["http_status"] == 404
        assert "Not Found" in out["body"]
        assert "not an upstream failure" in out["message"]

    async def test_summary_400_invalid_granule_id_is_not_found(self, make_client):
        # The measured shape for a nonexistent granule under an existing package.
        out = await tools.get_us_code_section(
            make_client(lambda request: httpx.Response(400, text='{"message":"invalid granuleId"}')), granule_id=GID
        )
        assert out["outcome"] == "not_found"
        assert out["not_found_kind"] == "granule"
        assert out["http_status"] == 400
        assert "invalid granuleId" in out["body"]
        assert out["granule_id"] == GID

    async def test_summary_404_is_package_not_found(self, make_client):
        out = await tools.get_us_code_section(
            make_client(lambda request: httpx.Response(404, text="gone")), granule_id=GID
        )
        assert out["not_found_kind"] == "package"

    async def test_other_400_stays_an_upstream_error(self, make_client):
        out = await tools.get_us_code_section(
            make_client(lambda request: httpx.Response(400, text='{"message":"bad request"}')), granule_id=GID
        )
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 400

    async def test_summary_500_is_upstream_error_not_not_found(self, make_client):
        out = await tools.get_us_code_section(
            make_client(lambda request: httpx.Response(500, text="boom")), granule_id=GID
        )
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 500
        assert "boom" in out["body"]

    async def test_summary_429_is_rate_limited(self, make_client):
        def handler(request):
            return httpx.Response(429, text="slow", headers={"Retry-After": "7"})

        out = await tools.get_us_code_section(make_client(handler), granule_id=GID)
        assert out["outcome"] == "rate_limited"
        assert out["rate_limit"]["retry-after"] == "7"

    async def test_summary_transport_failure(self, make_client):
        def handler(request):
            raise httpx.ConnectError("down")

        out = await tools.get_us_code_section(make_client(handler), granule_id=GID)
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] is None

    async def test_summary_not_json_fails_loudly(self, make_client):
        out = await tools.get_us_code_section(
            make_client(lambda request: httpx.Response(200, text="<html>")), granule_id=GID
        )
        assert out["outcome"] == "upstream_error"
        assert "not valid JSON" in out["detail"]

    async def test_summary_without_txtlink_fails_loudly_not_constructed(self, make_client):
        seen = []
        summary = fx.granule_summary(txt_link=False)
        out = await tools.get_us_code_section(
            make_client(by_id_handler(fx.json_response(summary), seen=seen)), granule_id=GID
        )
        assert out["outcome"] == "upstream_error"
        assert "txtLink" in out["detail"]
        assert "pdfLink" in out["available_formats"]
        assert not any(r.url.path.endswith("/htm") for r in seen)

    async def test_htm_fetch_failure_on_the_id_path(self, make_client):
        def handler(request):
            if request.url.path.endswith("/summary"):
                return fx.json_response(fx.granule_summary())
            return httpx.Response(503, text="unavailable")

        out = await tools.get_us_code_section(make_client(handler), granule_id=GID)
        assert out["outcome"] == "upstream_error"
        assert out["http_status"] == 503

    @pytest.mark.parametrize("bad", ["PLAW-118publ31", "banana", "uscode-2024", "USCODE-2024-title17"])
    async def test_non_uscode_id_rejected_before_any_call(self, make_client, bad):
        seen = []
        out = await tools.get_us_code_section(make_client(by_id_handler(seen=seen)), granule_id=bad)
        assert out["outcome"] == "invalid_argument"
        assert "granule_id" in out["detail"]
        assert seen == []

    async def test_non_uscode_package_id_rejected_before_any_call(self, make_client):
        seen = []
        out = await tools.get_us_code_section(
            make_client(by_id_handler(seen=seen)), granule_id=GID, package_id="PLAW-118publ31"
        )
        assert out["outcome"] == "invalid_argument"
        assert "package_id" in out["detail"]
        assert seen == []

    async def test_package_id_without_granule_id_is_invalid(self, make_client):
        seen = []
        out = await tools.get_us_code_section(
            make_client(by_id_handler(seen=seen)), citation="17 U.S.C. 107", package_id=PID
        )
        assert out["outcome"] == "invalid_argument"
        assert seen == []

    async def test_blank_granule_id_falls_back_to_the_citation_path(self, make_client):
        def handler(request):
            if request.url.path == "/search":
                body = fx.request_body(request)
                if "collection:PLAW" in body["query"]:
                    return fx.json_response(fx.search_response([]))
                return fx.json_response(fx.search_response([fx.usc_hit()]))
            return httpx.Response(200, text=fx.SECTION_HTML)

        out = await tools.get_us_code_section(make_client(handler), citation="17 U.S.C. 107", granule_id="  ")
        assert out["outcome"] == "success"
        assert "granule_id" not in out


class TestDisambiguationMessage:
    async def test_ambiguous_message_names_granule_id_never_by_ids(self, make_client):
        hits = [fx.usc_hit(), fx.usc_hit(granule_id="USCODE-2024-title17-chap1-sec107a")]

        def handler(request):
            return fx.json_response(fx.search_response(hits, count=2))

        out = await tools.get_us_code_section(make_client(handler), citation="17 U.S.C. 107")
        assert out["outcome"] == "ambiguous"
        assert "`granule_id`" in out["message"]
        assert "`citation`" in out["message"]
        assert "`year`" in out["message"]
        assert "by ids" not in out["message"]
        assert all("granule_id" in c and "package_id" in c for c in out["candidates"])

    async def test_public_law_ambiguous_message_does_not_promise_granule_id(self, make_client):
        hits = [fx.plaw_hit(), fx.plaw_hit(package_id="PLAW-118publ31-dup")]
        client = make_client(lambda request: fx.json_response(fx.search_response(hits, count=2)))
        out = await tools.get_public_law(client, congress=118, law_number=31)
        assert out["outcome"] == "ambiguous"
        assert "granule_id" not in out["message"]
        assert "by ids" not in out["message"]


class TestServerWiring:
    async def test_tool_schema_carries_optional_granule_id_and_package_id(self):
        server = create_server()
        tool = {t.name: t for t in await server.list_tools()}["get_us_code_section"]
        props = tool.input_schema["properties"]
        assert "granule_id" in props and "package_id" in props
        assert "granule_id" not in tool.input_schema.get("required", [])
        assert "granule_id" in tool.description
        assert "`citation` alongside" in tool.description

    async def test_other_tools_do_not_accept_granule_id(self):
        server = create_server()
        for name in ("search_us_code", "get_public_law", "search_public_laws"):
            tool = {t.name: t for t in await server.list_tools()}[name]
            assert "granule_id" not in tool.input_schema["properties"]

    def test_instructions_carry_the_contract_content(self):
        # 40-tools.md "Server instructions": contractual in content; the reference
        # text is used verbatim here (line-wrapped), so pinned sentences are checked
        # literally against the whitespace-normalized string.
        flat = " ".join(SERVER_INSTRUCTIONS.split())
        for sentence in (
            "every text response carries a `currentthrough` date as the staleness disclosure",
            "You do not need to check for later laws yourself",
            "It is an indicator, never a certification.",
            "`laws_indexed` means a listed law MENTIONS the section",
            "read the law with `get_public_law` to find out",
            "re-running the same query by hand will find nothing more",
            "NOT evidence the text is current",
            "one in seven listed (law, section) pairs",
            "the echoed `query` is your manual retry",
            "To widen beyond what the indicator ran",
            "minus its `publishdate` bound",
            "source credits",
        ):
            assert sentence in flat, sentence
        # Order: what it is, then the indicator, then the widening step.
        assert flat.index("annual edition") < flat.index("possibly_superseded") < flat.index("To widen beyond")

    async def test_served_instructions_are_the_constant(self):
        server = create_server()
        assert server.instructions == SERVER_INSTRUCTIONS


class TestPublicLinksById:
    """WO-7 (O53), the Rule 9 case (O46): on a granule_id lookup public_pdf_link names
    THAT granule, from the ids the response carries, and details_link is the granule
    summary's detailsLink verbatim."""

    async def test_public_pdf_link_names_the_looked_up_granule(self, make_client):
        out = await tools.get_us_code_section(make_client(by_id_handler()), granule_id=GID)
        assert out["outcome"] == "success"
        assert out["provenance"]["public_pdf_link"] == f"https://www.govinfo.gov/content/pkg/{PID}/pdf/{GID}.pdf"
        assert out["provenance"]["details_link"] == fx.granule_summary()["detailsLink"]
        assert out["provenance"]["pdf_link"] == fx.granule_summary()["download"]["pdfLink"]  # unchanged

    async def test_summary_without_details_link_yields_null_not_an_error(self, make_client):
        summary = fx.granule_summary()
        del summary["detailsLink"]
        out = await tools.get_us_code_section(
            make_client(by_id_handler(summary_response=fx.json_response(summary))), granule_id=GID
        )
        assert out["outcome"] == "success"
        assert out["provenance"]["details_link"] is None
        assert out["provenance"]["public_pdf_link"].endswith(f"/{GID}.pdf")

    async def test_truncated_by_id_sentence_carries_the_public_granule_link(self, make_client):
        out = await tools.get_us_code_section(make_client(by_id_handler()), granule_id=GID, max_chars=50)
        assert out["text"]["truncated"] is True
        message = out["text"]["message"]
        assert out["provenance"]["public_pdf_link"] in message
        assert out["provenance"]["pdf_link"] not in message


class TestGranuleIdGrammar:
    """WO-15 B (40-tools.md "By-id behavior"): the id is accepted only when it is
    USCODE-{year}-title{n} followed by hyphen-separated segments of letters and digits
    — a character class, not a parse — and anything else is refused before any request,
    so no id can ever reach the summary URL (S26 finding 2)."""

    REFUSED = [
        "USCODE-2024-title17-x/../../../search?x=1",  # the S26 traversal id
        "USCODE-2024-title17-chap1.sec107",  # dotted
        "USCODE-2024-title17-chap1-sec107?api_key=x",  # query-bearing
        "USCODE-2024-title17-chap1 sec107",  # whitespace inside
        "USCODE-2024-title17-chap1-sec107#frag",
        "USCODE-2024-title17-chap1-sec107/",
        "USCODE-2024-title17-",  # empty trailing segment
        "USCODE-2024-title17--sec107",  # empty middle segment
        "USCODE-2024-title17-chap1-sec107\n",
        "uscode-2024-title17-chap1-sec107",  # the grammar is case-exact, as served
        "USCODE-24-title17-chap1-sec107",
        "USCODE-2024-title17",  # a package id is not a granule id
    ]

    @pytest.mark.parametrize("bad", REFUSED)
    async def test_refused_ids_make_zero_requests(self, make_client, bad):
        seen = []

        def must_not_run(request):
            seen.append(request)
            raise AssertionError(f"an id reached the network: {request.url}")

        out = await tools.get_us_code_section(make_client(must_not_run), granule_id=bad)
        assert out["outcome"] == "invalid_argument"
        assert repr(bad) in out["detail"]  # the id is named, as given
        assert "nothing was fetched" in out["detail"]
        assert seen == []

    # Real GovInfo-served ids from the artifacts on record (O86b corpus): appendix,
    # front matter, deeply nested, and hyphenated-section forms.
    ACCEPTED = [
        "USCODE-2024-title17-chap1-sec107",
        "USCODE-2014-title50-app-warclaim-sec2012",
        "USCODE-2011-title50-app-tradingwi-sec1",
        "USCODE-2024-title28-app-federalru-rule9",
        "USCODE-2023-title5-front",
        "USCODE-2022-title26-subtitleA-chap1-subchapN-partIII-subpartB-sec911",
        "USCODE-2022-title34-subtitleII-chap201-subchapIII-sec20144",
        "USCODE-2012-title42-chap23-divsnA-subchapXIII-sec2210",
        "USCODE-2024-title42-chap6A-subchapII-partD-sec254c-8",
        "USCODE-2024-title12-chap13-sec1701z-6",
        "USCODE-2024-title5a-app-inspector-sec1",
    ]

    @pytest.mark.parametrize("good", ACCEPTED)
    async def test_real_id_forms_are_accepted_and_reach_the_summary(self, make_client, good):
        seen = []
        package = good.split("-")[0] + "-" + good.split("-")[1] + "-" + good.split("-")[2]

        def handler(request):
            seen.append(request)
            if request.url.path.endswith("/summary"):
                return fx.json_response(fx.granule_summary(package_id=package, granule_id=good))
            if request.url.path.endswith("/htm"):
                return httpx.Response(200, text=fx.SECTION_HTML)
            return fx.json_response(fx.search_response([]))

        out = await tools.get_us_code_section(make_client(handler), granule_id=good)
        assert out["outcome"] == "success", out
        assert seen[0].url.path == f"/packages/{package}/granules/{good}/summary"

    def test_grammar_is_a_character_class_not_a_parse(self):
        # Nothing beyond the leading segments is interpreted: arbitrary segment names pass.
        assert tools._USCODE_GRANULE_ID_RE.match("USCODE-2024-title17-anything-at-all-9")
        assert tools._USCODE_GRANULE_ID_RE.match("USCODE-2024-title17-x")
        assert not tools._USCODE_GRANULE_ID_RE.match("USCODE-2024-title17-x-")
