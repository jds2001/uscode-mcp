"""get_us_code_section and search_us_code contracts from documentation/40-tools.md.

The load-bearing assertions: the three outcomes never collapse (an upstream failure
must never present as not-found), provenance is complete or explicitly incomplete,
truncation is always marked, and normalization strips are reported."""

import fx
import httpx
import pytest

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

    async def test_citation_path_marks_citation_as_resolved(self, make_client):
        out = await tools.get_us_code_section(
            make_client(section_handler(fx.search_response([fx.usc_hit()]))), citation="17 U.S.C. 107"
        )
        assert out["normalization"]["citation_basis"] == "resolved"
        assert "citation_statement" not in out["possibly_superseded"]

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

    async def test_note_strip_disclosure_teaches_that_notes_carry_law_verbatim(self, make_client):
        # WO-18 (R29): the disclosure is contractual character for character; spelled out
        # here, not imported, so a drift in either direction fails.
        hit = fx.usc_hit(
            package_id="USCODE-2024-title42",
            granule_id="USCODE-2024-title42-chap23-divsnA-subchapXIII-sec2210",
        )
        client = make_client(section_handler(fx.search_response([hit])))
        out = await tools.get_us_code_section(client, citation="42 U.S.C. 2210 note")
        assert out["outcome"] == "success"
        assert out["normalization"]["messages"] == [NOTE_STRIP_DISCLOSURE.format(citation="42 U.S.C. 2210")]
        assert out["normalization"] == {
            "normalized_citation": "42 U.S.C. 2210",
            "citation_basis": "resolved",
            "stripped_subsection": None,
            "stripped_note": True,
            "messages": [NOTE_STRIP_DISCLOSURE.format(citation="42 U.S.C. 2210")],
        }

    async def test_note_strip_disclosure_names_the_resolved_section_not_the_input(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 USC 107 note")
        assert out["normalization"]["messages"] == [NOTE_STRIP_DISCLOSURE.format(citation="17 U.S.C. 107")]

    async def test_note_and_subsection_strips_each_get_their_own_disclosure(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107(b) note")
        messages = out["normalization"]["messages"]
        assert len(messages) == 2
        assert messages[0].startswith("Subsection suffix '(b)' was stripped")
        assert messages[1] == NOTE_STRIP_DISCLOSURE.format(citation="17 U.S.C. 107")

    async def test_no_strip_means_no_messages_key(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert "messages" not in out["normalization"]
        assert out["normalization"]["stripped_note"] is False

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


SUBSECTION_ZERO = (
    "Subsection suffix '{d}' was stripped and the whole containing section {c} is returned. '{d}' occurs 0 times "
    "in the statute text of {c} — {c}{d} does not exist in this edition. Tell the person asking that the section "
    "has no subsection {d}, and say what the section does contain. Do not answer with other text labelled '{d}'. "
    "{notes} A request for a provision that does not exist is answered by saying so, not by quoting the nearest "
    "label. If you quote one of those passages, name its own source and say it is not {c}{d}. What follows is for "
    "the tool caller, not the person asking: structure lists the section's fields and find locates text within "
    "the returned payload."
)
SUBSECTION_ZERO_NOTES = (
    "The notes under this section contain {n} such labels, but those are other material, not {c}{d}."
)
SUBSECTION_ZERO_NO_NOTES = "The notes under this section contain no such label either."
SUBSECTION_NONZERO = (
    "Subsection suffix '{d}' was stripped and the whole containing section {c} is returned; '{d}' occurs {n} "
    "times in its statute text. What follows is for the tool caller, not the person asking: use find with '{d}' "
    "to locate it within the returned payload."
)
SUBSECTION_NOT_CHECKED = (
    "Subsection suffix '{d}' was stripped and the whole containing section {c} is returned; whether the section "
    "has a subsection {d} was not checked. What follows is for the tool caller, not the person asking: use find "
    "with '{d}' to locate it within the returned payload."
)


def fielded_section(statute: str, notes: str, head: str = "<h3>&sect;107. Fair use</h3>") -> str:
    """A granule with upstream field markers around the given statute and notes HTML."""
    return (
        "<!-- documentid:USCODE-2024-title17-chap1-sec107 currentthrough:20250106 -->\n<html><body>\n"
        f"<!-- field-start:head -->{head}<!-- field-end:head -->\n"
        f"<!-- field-start:statute -->{statute}<!-- field-end:statute -->\n"
        "<!-- field-start:sourcecredit --><p>(Pub. L. 94-553.)</p><!-- field-end:sourcecredit -->\n"
        f'<!-- field-start:notes --><!-- field-start:miscellaneous-note --><h4 class="note-head">Statutory Notes '
        f"and Related Subsidiaries</h4>{notes}<!-- field-end:miscellaneous-note --><!-- field-end:notes -->\n"
        "</body></html>\n"
    )


NO_B_STATUTE = "<p>Notwithstanding sections 106 and 106A, fair use is not an infringement. (a) One label only.</p>"
GUIDELINES_WITH_B = (
    "<p>Guidelines. (a) Single copying. (b) Multiple copies. (B) Spontaneity. "
    "(b) Cumulative effect. (c) Prohibitions.</p>"
)


class TestStripMessageNamesItsReader:
    """WO-19 (R30): the subsection-strip message is one of three counted messages,
    contractual character for character — spelled out above, never imported. The
    count is the designator as a literal inside the `statute` extent and, separately,
    the `notes` extent, matched the way `find` matches."""

    def _client(self, make_client, html):
        return make_client(section_handler(fx.search_response([fx.usc_hit()]), htm_text=html))

    async def test_zero_in_statute_with_labels_in_the_notes(self, make_client):
        # 17 U.S.C. 107(b) as measured (O97): no "(b)" in the statute, labels in the
        # guidelines under the notes — including a "(B)", which counts, as find counts.
        out = await tools.get_us_code_section(
            self._client(make_client, fielded_section(NO_B_STATUTE, GUIDELINES_WITH_B)), citation="17 U.S.C. 107(b)"
        )
        assert out["outcome"] == "success"
        assert out["normalization"]["messages"] == [
            SUBSECTION_ZERO.format(
                d="(b)", c="17 U.S.C. 107", notes=SUBSECTION_ZERO_NOTES.format(n=3, c="17 U.S.C. 107", d="(b)")
            )
        ]

    async def test_zero_in_statute_and_none_in_the_notes(self, make_client):
        out = await tools.get_us_code_section(
            self._client(make_client, fielded_section(NO_B_STATUTE, "<p>An effective date note.</p>")),
            citation="17 U.S.C. 107(b)",
        )
        assert out["normalization"]["messages"] == [
            SUBSECTION_ZERO.format(d="(b)", c="17 U.S.C. 107", notes=SUBSECTION_ZERO_NO_NOTES)
        ]

    async def test_nonzero_in_statute_states_the_count_and_nothing_about_which(self, make_client):
        html = fielded_section("<p>(a) First. (b) Second. (B) Upper. (c) Third.</p>", GUIDELINES_WITH_B)
        out = await tools.get_us_code_section(self._client(make_client, html), citation="17 U.S.C. 107(b)")
        assert out["normalization"]["messages"] == [SUBSECTION_NONZERO.format(d="(b)", c="17 U.S.C. 107", n=2)]

    async def test_not_checked_when_structure_is_disclosed_absent(self, make_client):
        # fx.SECTION_HTML carries no field markers: structure is omitted, so nonexistence
        # is never asserted — even though the text has no "(b)" anywhere.
        out = await tools.get_us_code_section(self._client(make_client, fx.SECTION_HTML), citation="17 U.S.C. 107(b)")
        assert out["structure"]["omitted"] is True
        assert "(b)" not in out["text"]["content"].lower()
        assert out["normalization"]["messages"] == [SUBSECTION_NOT_CHECKED.format(d="(b)", c="17 U.S.C. 107")]

    async def test_not_checked_when_the_markers_are_present_but_no_statute_field(self, make_client):
        html = (
            fielded_section(NO_B_STATUTE, GUIDELINES_WITH_B)
            .replace("field-start:statute", "field-start:body")
            .replace("field-end:statute", "field-end:body")
        )
        out = await tools.get_us_code_section(self._client(make_client, html), citation="17 U.S.C. 107(b)")
        assert out["structure"]["omitted"] is False
        assert out["normalization"]["messages"] == [SUBSECTION_NOT_CHECKED.format(d="(b)", c="17 U.S.C. 107")]

    async def test_counts_agree_with_find_over_the_same_extents(self, make_client):
        from uscode_mcp.htmltext import find_occurrences

        html = fielded_section("<p>(a) First. (b) Second. (B) Upper.</p>", GUIDELINES_WITH_B)
        out = await tools.get_us_code_section(self._client(make_client, html), citation="17 U.S.C. 107(b)", find="(b)")
        text = out["text"]["content"]
        by_field = {f["field"]: f for f in out["structure"]["fields"]}
        in_statute = find_occurrences(text[by_field["statute"]["start_char"] : by_field["statute"]["end_char"]], "(b)")
        in_notes = find_occurrences(text[by_field["notes"]["start_char"] : by_field["notes"]["end_char"]], "(b)")
        assert in_statute["total_occurrences"] == 2 and in_notes["total_occurrences"] == 3
        assert out["find"]["total_occurrences"] == 5
        assert out["normalization"]["messages"] == [SUBSECTION_NONZERO.format(d="(b)", c="17 U.S.C. 107", n=2)]

    async def test_a_label_in_the_heading_or_source_credit_is_outside_both_extents(self, make_client):
        html = fielded_section(NO_B_STATUTE, "<p>Nothing here.</p>", head="<h3>&sect;107. Fair use (b)</h3>").replace(
            "(Pub. L. 94-553.)", "(Pub. L. 94-553, (b).)"
        )
        out = await tools.get_us_code_section(self._client(make_client, html), citation="17 U.S.C. 107(b)")
        assert out["normalization"]["messages"] == [
            SUBSECTION_ZERO.format(d="(b)", c="17 U.S.C. 107", notes=SUBSECTION_ZERO_NO_NOTES)
        ]

    async def test_multi_level_designator_is_counted_whole(self, make_client):
        html = fielded_section("<p>(h)(2)(A) deep. (h)(2)(a) lower. (h)(2) partial.</p>", "<p>(h)(2)(A) in notes.</p>")
        out = await tools.get_us_code_section(self._client(make_client, html), citation="17 U.S.C. 107(h)(2)(A)")
        assert out["normalization"]["stripped_subsection"] == "(h)(2)(A)"
        assert out["normalization"]["messages"] == [SUBSECTION_NONZERO.format(d="(h)(2)(A)", c="17 U.S.C. 107", n=2)]

    async def test_reading_call_still_counts_from_the_derived_structure(self, make_client):
        html = fielded_section(NO_B_STATUTE, GUIDELINES_WITH_B)
        out = await tools.get_us_code_section(
            self._client(make_client, html), citation="17 U.S.C. 107(b)", start_char=10, max_chars=20
        )
        assert out["structure"]["omitted"] is True
        assert out["normalization"]["messages"][0].startswith(
            "Subsection suffix '(b)' was stripped and the whole containing section 17 U.S.C. 107 is returned. "
            "'(b)' occurs 0 times"
        )

    async def test_both_strips_keep_their_order_and_the_envelope_is_unchanged(self, make_client):
        html = fielded_section(NO_B_STATUTE, GUIDELINES_WITH_B)
        out = await tools.get_us_code_section(self._client(make_client, html), citation="17 U.S.C. 107(b) note")
        n = out["normalization"]
        assert set(n) == {"normalized_citation", "citation_basis", "stripped_subsection", "stripped_note", "messages"}
        assert n["normalized_citation"] == "17 U.S.C. 107" and n["citation_basis"] == "resolved"
        assert n["stripped_subsection"] == "(b)" and n["stripped_note"] is True
        assert len(n["messages"]) == 2
        assert n["messages"][0].startswith("Subsection suffix '(b)' was stripped and the whole containing section")
        assert n["messages"][1] == NOTE_STRIP_DISCLOSURE.format(citation="17 U.S.C. 107")
        assert {"outcome", "provenance", "possibly_superseded", "structure", "text"} <= out.keys()

    async def test_no_strip_means_no_counting_and_no_messages(self, make_client):
        html = fielded_section("<p>(b) present.</p>", GUIDELINES_WITH_B)
        out = await tools.get_us_code_section(self._client(make_client, html), citation="17 U.S.C. 107")
        assert "messages" not in out["normalization"]

    async def test_not_found_has_no_returned_section_so_the_message_is_not_counted(self, make_client):
        # Nothing was returned to count in, and none of the three messages is true of
        # an empty result, so the pre-WO-19 wording stands on this envelope.
        client = make_client(section_handler(fx.search_response([], count=0)))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107(b)")
        assert out["outcome"] == "not_found"
        assert out["normalization"]["messages"] == [
            "Subsection suffix '(b)' was stripped: the granule is the retrieval unit, so the whole containing "
            "section 17 U.S.C. 107 is returned; navigate within it."
        ]


class TestGetSectionYear:
    async def test_year_sets_historical_and_filters(self, make_client):
        hits = [
            fx.usc_hit(
                package_id="USCODE-1998-title17",
                granule_id="USCODE-1998-title17-chap1-sec107",
                date_issued="1998-01-05",
            ),
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


NOTE_STRIP_DISCLOSURE = (
    "Trailing 'note' was stripped: the containing section {citation} was resolved instead, and ALL of its notes "
    "are in the returned payload. Notes carry law, not only editorial history: fields headed 'Statutory Notes and "
    "Related Subsidiaries', 'Findings', short-title and effective-date notes are enacted provisions Congress placed "
    "under the section rather than in it; 'Codification', 'Amendments' and 'References in Text' are editorial. A "
    "question about the note or notes to a section is about that whole body — list it with `structure` (the "
    "`notes` field and its typed children, each with its heading) and search it with `find`. The 'Codification' "
    "note alone is one editorial note, not the notes."
)
COLLISION_MESSAGE = (
    "{n} DISTINCT PROVISIONS SHARE THIS CITATION — this is not a lookup failure and there is no single answer. "
    "Tell the person asking that {n} provisions match and name each by its title below; if you go on to read one "
    "or more of them, present each as a distinct provision by its title and say which you did not read. Do not "
    "present one as the only match. What follows is for the tool caller, not the person asking: to read a "
    "candidate, re-request with its `granule_id` (pass the same `citation` alongside it to keep the staleness "
    "check)."
)
EDITIONS_MESSAGE = (
    "{n} EDITIONS OF THIS PROVISION MATCH. Tell the person asking which edition you are quoting; the current "
    "edition is {year} unless they asked for another. What follows is for the tool caller, not the person "
    "asking: re-request with `year` to choose an edition, or with a candidate's `granule_id`."
)


class TestAmbiguousMessageNamesItsReader:
    """The two `ambiguous` templates are contractual character for character (40-tools.md,
    "The `ambiguous` message names its reader"): the expected strings are spelled out here,
    not imported from the implementation, so a drift in either direction fails."""

    def _rule9_pair(self):
        return [
            fx.usc_hit(
                package_id="USCODE-2024-title28",
                granule_id="USCODE-2024-title28-app-federalru-rule9",
                title="Rule 9. Pleading Special Matters",
            ),
            fx.usc_hit(
                package_id="USCODE-2024-title28",
                granule_id="USCODE-2024-title28-app-federalru-dup1-rule9",
                title="Rule 9. Release in a Criminal Case",
            ),
        ]

    async def test_same_year_candidates_get_the_collision_message_verbatim(self, make_client):
        client = make_client(section_handler(fx.search_response(self._rule9_pair(), count=2)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App. Rule 9")
        assert out["outcome"] == "ambiguous"
        assert out["message"] == COLLISION_MESSAGE.format(n=2)
        assert out["count"] == 2 and out["candidates_shown"] == 2 and out["capped"] is False
        assert [c["title"] for c in out["candidates"]] == [
            "Rule 9. Pleading Special Matters",
            "Rule 9. Release in a Criminal Case",
        ]

    async def test_collision_message_reports_the_true_total_not_the_shown_count(self, make_client):
        hits = [fx.usc_hit(granule_id=f"USCODE-2024-title28-app-federalru-rule{i}") for i in range(100)]
        client = make_client(section_handler(fx.search_response(hits, count=251)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App.")
        assert out["outcome"] == "ambiguous"
        assert out["message"] == (
            COLLISION_MESSAGE.format(n=251) + " The candidate list is capped at one search page: showing 100 of 251."
        )
        assert out["count"] == 251 and out["candidates_shown"] == 100 and out["capped"] is True

    async def test_candidates_across_years_get_the_editions_message_with_the_newest_year(self, make_client):
        hits = [
            fx.usc_hit(
                package_id="USCODE-2022-title17",
                granule_id="USCODE-2022-title17-chap1-sec107",
                date_issued="2023-01-03",
            ),
            fx.usc_hit(),  # 2025-01-06: the 2024 edition
            fx.usc_hit(
                package_id="USCODE-2023-title17",
                granule_id="USCODE-2023-title17-chap1-sec107",
                date_issued="2024-01-08",
            ),
        ]
        client = make_client(section_handler(fx.search_response(hits, count=3)))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "ambiguous"
        assert out["message"] == EDITIONS_MESSAGE.format(n=3, year=2025)
        assert out["capped"] is False

    async def test_capped_editions_message_appends_the_capping_sentence(self, make_client):
        hits = [
            fx.usc_hit(
                package_id=f"USCODE-{1994 + i}-title17",
                granule_id=f"USCODE-{1994 + i}-title17-chap1-sec107",
                date_issued=f"{1995 + i}-01-06",
            )
            for i in range(31)
        ]
        client = make_client(section_handler(fx.search_response(hits, count=40)))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "ambiguous"
        assert out["message"] == (
            EDITIONS_MESSAGE.format(n=40, year=2025)
            + " The candidate list is capped at one search page: showing 31 of 40."
        )
        assert out["capped"] is True

    def _rule9_all_editions(self, per_year: int = 2, years: range = range(1997, 2025)) -> list[dict]:
        """A `historical: true` page for `28 U.S.C. App. Rule 9`: `per_year` same-citation
        candidates in each edition year, the measured shape behind O93c's 78."""
        hits = []
        for year in years:
            for i in range(per_year):
                hits.append(
                    fx.usc_hit(
                        package_id=f"USCODE-{year}-title28",
                        granule_id=f"USCODE-{year}-title28-app-federalru-{'dup1-' if i else ''}rule9",
                        title="Rule 9. Pleading Special Matters" if i == 0 else "Rule 9. Release in a Criminal Case",
                        date_issued=f"{year}-01-06",
                    )
                )
        return hits

    async def test_a_requested_year_leaves_only_one_edition_so_a_pair_is_a_collision(self, make_client):
        # `year` filters the historical results to that edition first; two survivors share
        # the citation within it, so the collision template is what the caller must see.
        hits = [
            fx.usc_hit(
                package_id="USCODE-2023-title28",
                granule_id="USCODE-2023-title28-app-federalru-rule9",
                date_issued="2024-01-08",
            ),
            fx.usc_hit(
                package_id="USCODE-2023-title28",
                granule_id="USCODE-2023-title28-app-federalru-dup1-rule9",
                date_issued="2024-01-08",
            ),
            fx.usc_hit(
                package_id="USCODE-2022-title28",
                granule_id="USCODE-2022-title28-app-federalru-rule9",
                date_issued="2023-01-03",
            ),
        ]
        client = make_client(section_handler(fx.search_response(hits, count=3)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App. Rule 9", year=2024)
        assert out["outcome"] == "ambiguous"
        assert out["candidates_shown"] == 2
        # WO-17 C: `{N}` is the filtered total, not upstream's count across editions.
        assert out["message"] == COLLISION_MESSAGE.format(n=2)
        assert out["count"] == 2 and out["count_all_editions"] == 3 and out["capped"] is False

    async def test_year_filtered_pair_states_the_filtered_total_and_discloses_the_all_editions_count(self, make_client):
        # O93c as measured: upstream counts 78 across every edition since 1997; `year: 2024`
        # keeps two. The message says 2, `count` is 2, nothing is capped (the page held all
        # 78), and upstream's figure rides beside as `count_all_editions`.
        hits = self._rule9_all_editions()
        assert len(hits) == 56  # 28 editions x 2; padded to the measured 78 below
        hits += self._rule9_all_editions(per_year=1, years=range(1975, 1997))
        assert len(hits) == 78
        client = make_client(section_handler(fx.search_response(hits, count=78)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App. Rule 9", year=2024)
        assert out["outcome"] == "ambiguous"
        assert out["message"] == COLLISION_MESSAGE.format(n=2)
        assert out["count"] == 2
        assert out["count_all_editions"] == 78
        assert out["candidates_shown"] == 2
        assert out["capped"] is False
        assert out["year"] == 2024
        assert [c["granule_id"] for c in out["candidates"]] == [
            "USCODE-2024-title28-app-federalru-rule9",
            "USCODE-2024-title28-app-federalru-dup1-rule9",
        ]
        assert all(c["date_issued"].startswith("2024") for c in out["candidates"])

    async def test_year_filtered_list_from_an_incomplete_page_is_capped_and_says_so(self, make_client):
        # Upstream holds 251 candidates across editions and served one page of 100; the
        # year filter ran over that page alone and kept 40. The 40 is a floor, not the
        # 2024 total, so the list is capped and the capping sentence says why — on the
        # filtered figures, never "showing 100 of 251".
        hits = self._rule9_all_editions(per_year=40, years=range(2024, 2025))  # the 40 for 2024
        hits += self._rule9_all_editions(per_year=30, years=range(2022, 2024))  # 60 for other years
        assert len(hits) == 100
        client = make_client(section_handler(fx.search_response(hits, count=251)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App. Rule 9", year=2024)
        assert out["outcome"] == "ambiguous"
        assert out["count"] == 40 and out["candidates_shown"] == 40
        assert out["count_all_editions"] == 251
        assert out["capped"] is True
        assert out["message"] == (
            COLLISION_MESSAGE.format(n=40)
            + " The candidate list is capped at one search page: showing 40 of at least 40 for 2024 — the year "
            "filter ran over the first page only, of 251 candidates across all editions."
        )
        assert len(out["candidates"]) == 40

    async def test_year_filtered_count_is_the_filtered_total_even_when_upstream_count_is_not_an_integer(
        self, make_client
    ):
        hits = self._rule9_all_editions(years=range(2023, 2025))
        client = make_client(section_handler(fx.search_response(hits, count="4")))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App. Rule 9", year=2024)
        assert out["outcome"] == "ambiguous"
        assert out["count"] == 2 and out["count_all_editions"] == "4" and out["capped"] is False
        assert out["message"] == COLLISION_MESSAGE.format(n=2)

    async def test_without_year_the_envelope_carries_no_all_editions_count_and_the_messages_are_unchanged(
        self, make_client
    ):
        # The three O93a inputs served the unfiltered messages byte for byte; WO-17 C
        # touches only the `year` path, so without `year` nothing moves.
        client = make_client(section_handler(fx.search_response(self._rule9_pair(), count=2)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App. Rule 9")
        assert "count_all_editions" not in out
        assert out["message"] == COLLISION_MESSAGE.format(n=2)
        assert out["count"] == 2 and out["capped"] is False

        hits = [fx.usc_hit(granule_id=f"USCODE-2024-title28-app-federalru-rule{i}") for i in range(100)]
        client = make_client(section_handler(fx.search_response(hits, count=251)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App.")
        assert "count_all_editions" not in out
        assert out["message"] == (
            COLLISION_MESSAGE.format(n=251) + " The candidate list is capped at one search page: showing 100 of 251."
        )
        assert out["count"] == 251 and out["capped"] is True

    async def test_year_filtered_success_and_not_found_paths_carry_no_all_editions_count(self, make_client):
        hits = self._rule9_all_editions(per_year=1, years=range(2023, 2025))
        client = make_client(section_handler(fx.search_response(hits, count=2)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App. Rule 9", year=2024)
        assert out["outcome"] == "success"
        assert "count_all_editions" not in out
        client = make_client(section_handler(fx.search_response([fx.usc_hit()], count=1)))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", year=1980)
        assert out["outcome"] == "not_found"
        assert "count_all_editions" not in out

    async def test_missing_or_unparseable_date_issued_is_a_collision_not_an_exception(self, make_client):
        # No year to differ by → "all equal" → collision; the outcome is served, never raised.
        hits = [
            fx.usc_hit(date_issued=""),
            fx.usc_hit(granule_id="USCODE-2024-title17-chap1-sec107a", date_issued="n/a"),
        ]
        del hits[0]["dateIssued"]
        client = make_client(section_handler(fx.search_response(hits, count=2)))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "ambiguous"
        assert out["message"] == COLLISION_MESSAGE.format(n=2)

    async def test_one_dated_and_one_undated_candidate_reads_as_editions_on_the_dated_year(self, make_client):
        hits = [fx.usc_hit(), fx.usc_hit(granule_id="USCODE-2024-title17-chap1-sec107a", date_issued=None)]
        client = make_client(section_handler(fx.search_response(hits, count=2)))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "ambiguous"
        assert out["message"] == EDITIONS_MESSAGE.format(n=2, year=2025)

    async def test_a_non_integer_count_is_echoed_and_never_capped(self, make_client):
        hits = [fx.usc_hit(), fx.usc_hit(granule_id="USCODE-2024-title17-chap1-sec107a")]
        client = make_client(section_handler(fx.search_response(hits, count="2")))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        assert out["outcome"] == "ambiguous"
        assert out["message"] == COLLISION_MESSAGE.format(n="2")
        assert out["capped"] is False

    async def test_ambiguous_envelope_fields_are_unchanged(self, make_client):
        client = make_client(section_handler(fx.search_response(self._rule9_pair(), count=2)))
        out = await tools.get_us_code_section(client, citation="28 U.S.C. App. Rule 9")
        assert {"count", "candidates_shown", "capped", "candidates", "message"} <= out.keys()
        for c in out["candidates"]:
            assert {"package_id", "granule_id", "title", "date_issued"} <= c.keys()

    async def test_public_law_disambiguation_message_is_untouched(self, make_client):
        hits = [fx.plaw_hit(), fx.plaw_hit(package_id="PLAW-118publ31-duplicate")]
        client = make_client(lambda request: fx.json_response(fx.search_response(hits, count=2)))
        out = await tools.get_public_law(client, congress=118, law_number=31)
        assert out["outcome"] == "ambiguous"
        assert out["message"] == (
            "Multiple matches (2 total); not guessing. The number did not resolve to one public law; "
            "treat the candidates' package_id values as findings."
        )


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
        hits = [fx.usc_hit(granule_id=f"USCODE-2024-title28-app-federalru-rule{i}") for i in range(100)]
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
                429,
                text="slow down",
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

    @pytest.mark.parametrize(
        "window",
        [{"start_char": -5}, {"max_chars": 0}, {"start_char": "5"}, {"max_chars": "20"}],
    )
    async def test_invalid_window_args_are_rejected_before_any_request(self, make_client, window):
        seen = []
        client = make_client(section_handler(fx.search_response([fx.usc_hit()]), seen=seen))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", **window)
        assert out["outcome"] == "invalid_argument"
        assert seen == []

    @pytest.mark.parametrize("extra", [0, 10])
    async def test_start_at_or_past_end_is_invalid_with_total(self, make_client, extra):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        located = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        total = located["text"]["total_chars"]
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", start_char=total + extra)
        assert out["outcome"] == "invalid_argument"
        assert out["total_chars"] == total
        assert "no text exists" in out["detail"]
        assert "not empty" in out["detail"]

    async def test_last_character_window_still_succeeds(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()])))
        located = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        total = located["text"]["total_chars"]
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", start_char=total - 1)
        assert out["outcome"] == "success"
        assert out["text"]["returned_chars"] == 1

    async def test_empty_payload_at_zero_still_succeeds(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()]), htm_text=""))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", start_char=0)
        assert out["outcome"] == "success"
        assert out["text"]["total_chars"] == 0


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
            fx.usc_hit(package_id="USCODE-2024-title28", granule_id="USCODE-2024-title28-app-federalru-dup1-rule9"),
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
        client = make_client(section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_WITH_FIELDS))
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107")
        structure = out["structure"]
        assert structure["omitted"] is False
        assert [f["field"] for f in structure["fields"]][:3] == ["head", "statute", "sourcecredit"]
        assert any(f["heading"] == "Amendments" for f in structure["fields"])

    async def test_structure_offsets_are_usable_as_start_char(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_WITH_FIELDS))
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
        out = await tools.get_us_code_section(client, citation="17 U.S.C. 107", max_chars=20, find="Effective date")
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
        return make_client(section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_WITH_FIELDS))

    async def test_locating_call_carries_the_field_list(self, make_client):
        out = await tools.get_us_code_section(self._client(make_client), citation="17 U.S.C. 107")
        assert out["structure"]["omitted"] is False
        assert out["structure"]["fields"]

    async def test_explicit_zero_start_char_is_still_a_locating_call(self, make_client):
        out = await tools.get_us_code_section(self._client(make_client), citation="17 U.S.C. 107", start_char=0)
        assert out["structure"]["omitted"] is False

    async def test_reading_call_omits_it_and_points_back(self, make_client):
        out = await tools.get_us_code_section(self._client(make_client), citation="17 U.S.C. 107", start_char=50)
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
            out = await tools.get_us_code_section(self._client(make_client), citation="17 U.S.C. 107", start_char=start)
            assert "omitted" in out["structure"]

    async def test_a_reading_call_is_much_smaller_than_a_locating_one(self, make_client):
        # The symptom R13a fixes: the invariant block dwarfing a small read (O38).
        import json

        located = await tools.get_us_code_section(self._client(make_client), citation="17 U.S.C. 107", max_chars=40)
        read = await tools.get_us_code_section(
            self._client(make_client), citation="17 U.S.C. 107", start_char=50, max_chars=40
        )
        assert len(json.dumps(read["structure"])) < len(json.dumps(located["structure"]))


class TestSectionFieldExtent:
    async def test_fields_carry_usable_end_char(self, make_client):
        client = make_client(section_handler(fx.search_response([fx.usc_hit()]), htm_text=fx.SECTION_HTML_WITH_FIELDS))
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
        hit = fx.usc_hit(
            package_id="USCODE-1998-title17", granule_id="USCODE-1998-title17-chap1-sec107", date_issued="1998-01-05"
        )
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
        assert "NOT part of the payload" not in bare["message"]
        assert text["banner"] == bare["banner"]
        assert len(text["content"]) == text["returned_chars"] == 50

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
        assert "https://" not in message
        assert "None" not in message
