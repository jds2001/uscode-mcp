"""Text derivation and windowing contracts (documentation/40-tools.md): no content
dropped, currentthrough parsed or explicitly absent, no silent truncation."""

import fx
import pytest

from uscode_mcp.htmltext import (
    add_audience_sentence,
    audience_sentence,
    edition_year_from_package_id,
    extract_currentthrough,
    find_occurrences,
    html_to_text,
    html_to_text_with_structure,
    public_pdf_link,
    structure_omitted_for_reading_call,
    window_text,
)


class TestCurrentthrough:
    def test_parses_embedded_comment(self):
        assert extract_currentthrough(fx.SECTION_HTML) == "2025-01-06"

    def test_tolerates_separator_variants(self):
        assert extract_currentthrough("<!-- currentthrough 20240102 -->") == "2024-01-02"
        assert extract_currentthrough("<!--currentthrough:20240102-->") == "2024-01-02"

    def test_absent_returns_none(self):
        assert extract_currentthrough(fx.SECTION_HTML_NO_CURRENTTHROUGH) is None
        assert extract_currentthrough("<html><body>no comment</body></html>") is None


class TestEditionYear:
    def test_parses_uscode_package_id(self):
        assert edition_year_from_package_id("USCODE-2024-title17") == 2024
        assert edition_year_from_package_id("USCODE-1994-title42-chap23") == 1994

    def test_unrecognized_returns_none(self):
        assert edition_year_from_package_id("PLAW-118publ31") is None
        assert edition_year_from_package_id(None) is None


class TestHtmlToText:
    def test_statutory_text_and_notes_both_preserved(self):
        text = html_to_text(fx.SECTION_HTML)
        assert "fair use of a copyrighted work" in text
        assert "Pub. L. 94-553" in text  # source credit
        assert "Effective date note text lives here and must never be dropped." in text

    def test_tags_and_style_are_stripped(self):
        text = html_to_text(fx.SECTION_HTML)
        assert "<p>" not in text
        assert "margin" not in text  # style content skipped

    def test_entities_are_unescaped(self):
        assert "§107." in html_to_text(fx.SECTION_HTML)

    def test_block_structure_becomes_newlines(self):
        # Adjacent paragraphs render separated by a blank line (runs collapse to one).
        text = html_to_text("<p>one</p><p>two</p>")
        assert text == "one\n\ntwo"


class TestWindowText:
    def test_no_truncation_when_it_fits(self):
        w = window_text("abcdef", start_char=0, max_chars=100)
        assert w["content"] == "abcdef"
        assert w["truncated"] is False
        assert w["next_start_char"] is None
        assert w["total_chars"] == 6

    def test_truncation_is_explicitly_marked(self):
        w = window_text("abcdefghij", start_char=0, max_chars=4)
        assert w["truncated"] is True
        assert w["next_start_char"] == 4
        assert w["total_chars"] == 10
        assert "start_char=4" in w["message"]
        # E12: the same disclosure leads the text, and the payload window follows it intact.
        assert w["content"] == f"{w['banner']}\nabcd"

    def test_continuation_window(self):
        w = window_text("abcdefghij", start_char=4, max_chars=100)
        assert w["content"] == "efghij"
        assert w["truncated"] is False

    def test_start_beyond_end_returns_empty_window(self):
        w = window_text("abc", start_char=10, max_chars=5)
        assert w["content"] == ""
        assert w["truncated"] is False
        assert w["total_chars"] == 3

    def test_invalid_arguments_raise(self):
        with pytest.raises(ValueError):
            window_text("abc", start_char=-1)
        with pytest.raises(ValueError):
            window_text("abc", max_chars=0)


class TestTruncationBanner:
    """E12 (40-tools.md, from finding F1): when truncated, the structured markers are
    repeated in-band at the head of `content`, because a consumer given only correct
    structured fields still presented the window as the whole law."""

    def test_banner_states_bounds_true_total_and_continuation(self):
        w = window_text("x" * 3_590_552, start_char=0, max_chars=100_000)
        assert w["content"].startswith("[WINDOW chars 0–99,999 of 3,590,552 — truncated;")
        assert w["content"].splitlines()[0].endswith("continue with start_char=100000]")

    def test_banner_is_a_single_leading_line_and_payload_follows_intact(self):
        w = window_text("abcdefghij", start_char=0, max_chars=4)
        first, rest = w["content"].split("\n", 1)
        assert first == w["banner"]
        assert rest == "abcd"
        assert "[WINDOW" not in rest

    def test_no_banner_when_the_whole_payload_fits(self):
        w = window_text("abcdef", start_char=0, max_chars=100)
        assert "banner" not in w
        assert w["content"] == "abcdef"
        assert "[WINDOW" not in w["content"]

    def test_last_window_of_a_paged_read_carries_no_banner(self):
        w = window_text("abcdefghij", start_char=8, max_chars=4)
        assert w["truncated"] is False
        assert w["content"] == "ij"

    def test_continuation_window_banner_reports_its_own_bounds(self):
        w = window_text("x" * 250, start_char=100, max_chars=100)
        assert w["banner"] == "[WINDOW chars 100–199 of 250 — truncated; continue with start_char=200]"

    def test_structured_fields_describe_the_payload_not_the_banner(self):
        # The coordinate system `find` and `structure` offsets live in must not shift
        # because a banner was prepended.
        w = window_text("abcdefghij", start_char=0, max_chars=4)
        assert w["returned_chars"] == 4
        assert w["total_chars"] == 10
        assert w["next_start_char"] == 4
        assert len(w["content"]) == len(w["banner"]) + 1 + 4


class TestStructure:
    """R12b: the field list comes from the payload's own field-start/field-end markers
    (O36) and degrades to a disclosed omission — never a retrieval failure."""

    def test_fields_are_ordered_with_headings_for_notes(self):
        _, structure = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        assert structure["omitted"] is False
        assert [f["field"] for f in structure["fields"]] == [
            "head",
            "statute",
            "sourcecredit",
            "notes",
            "historicalandrevision-note",
            "amendment-note",
        ]
        by_field = {f["field"]: f for f in structure["fields"]}
        assert by_field["historicalandrevision-note"]["heading"] == "Historical and Revision Notes"
        assert by_field["amendment-note"]["heading"] == "Amendments"
        assert by_field["statute"]["heading"] is None

    def test_start_char_offsets_land_on_the_field_in_the_returned_text(self):
        text, structure = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        for field, expected_prefix in [
            ("head", "§107. Limitations"),
            ("statute", "Notwithstanding the provisions"),
            ("sourcecredit", "(Pub. L. 94-553"),
            ("amendment-note", "Amendments"),
        ]:
            offset = next(f["start_char"] for f in structure["fields"] if f["field"] == field)
            assert text[offset:].startswith(expected_prefix), field

    def test_offsets_survive_whitespace_normalization(self):
        # The fixture carries trailing spaces and blank-line runs that html_to_text
        # collapses; an offset computed in raw-HTML coordinates would drift past them.
        text, structure = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        assert "   \n" not in text and "\n\n\n" not in text
        note = next(f for f in structure["fields"] if f["field"] == "amendment-note")
        assert text.index("Amendments") == note["start_char"]

    def test_a_nested_container_does_not_steal_its_child_heading(self):
        _, structure = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        notes = next(f for f in structure["fields"] if f["field"] == "notes")
        assert notes["heading"] is None

    def test_markerless_payload_is_a_disclosed_omission_not_a_failure(self):
        text, structure = html_to_text_with_structure(fx.SECTION_HTML)
        assert structure["omitted"] is True
        assert "no field-start/field-end markers" in structure["reason"]
        assert "fields" not in structure
        assert "Effective date note text" in text  # the text itself is unaffected

    def test_flat_plaw_payload_gets_no_structure(self):
        _, structure = html_to_text_with_structure(fx.PLAW_HTML)
        assert structure["omitted"] is True

    def test_unbalanced_markers_are_a_disclosed_omission(self):
        text, structure = html_to_text_with_structure(fx.SECTION_HTML_UNBALANCED_FIELDS)
        assert structure["omitted"] is True
        assert "field-end:statute" in structure["reason"]
        assert "Amendments" in text

    def test_unclosed_marker_is_a_disclosed_omission(self):
        text, structure = html_to_text_with_structure(fx.SECTION_HTML_UNCLOSED_FIELD)
        assert structure["omitted"] is True
        assert "unclosed" in structure["reason"]
        assert "notes" in structure["reason"]
        assert "Amendments" in text

    def test_crossed_markers_are_a_disclosed_omission(self):
        crossed = "<!-- field-start:a --><p>x</p><!-- field-start:b --><p>y</p><!-- field-end:a -->"
        _, structure = html_to_text_with_structure(crossed)
        assert structure["omitted"] is True
        assert "innermost" in structure["reason"]

    def test_marker_whitespace_variants_are_tolerated(self):
        html = "<!--field-start:statute--><p>text</p><!--  field-end : statute  -->"
        _, structure = html_to_text_with_structure(html)
        assert structure["omitted"] is False
        assert [f["field"] for f in structure["fields"]] == ["statute"]

    def test_html_to_text_output_is_unchanged_by_the_structure_pass(self):
        text, _ = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        assert html_to_text(fx.SECTION_HTML_WITH_FIELDS) == text
        # Markers are comments and must not leak into the text.
        assert "field-start" not in text and "field-end" not in text


class TestFindOccurrences:
    """R12a: true occurrence count, offsets in the windowing coordinate system,
    capped list stating the true total, zero matches reported explicitly."""

    def test_offsets_index_the_full_text(self):
        text = "alpha beta gamma beta delta"
        r = find_occurrences(text, "beta")
        assert r["total_occurrences"] == 2
        assert [o["start_char"] for o in r["occurrences"]] == [6, 17]
        for o in r["occurrences"]:
            assert text[o["start_char"]:].startswith("beta")

    def test_match_is_case_insensitive_but_offsets_stay_exact(self):
        text = "The BETA and the beta"
        r = find_occurrences(text, "beta")
        assert r["total_occurrences"] == 2
        assert [o["start_char"] for o in r["occurrences"]] == [4, 17]
        assert r["case_sensitive"] is False

    def test_finds_matches_beyond_the_returned_window(self):
        text = "x" * 100_000 + "NEEDLE" + "y" * 100
        window = window_text(text, start_char=0, max_chars=100)
        r = find_occurrences(text, "needle")
        assert window["truncated"] is True
        assert "NEEDLE" not in window["content"]
        assert r["occurrences"][0]["start_char"] == 100_000
        # The offset feeds straight back in as a start_char.
        second = window_text(text, start_char=100_000, max_chars=1_000)
        assert second["truncated"] is False
        assert second["content"].startswith("NEEDLE")

    def test_zero_matches_is_explicit_and_not_an_error(self):
        r = find_occurrences("alpha beta", "gamma")
        assert r["total_occurrences"] == 0
        assert r["occurrences"] == []
        assert r["capped"] is False
        assert "Zero occurrences" in r["message"]

    def test_capped_list_states_the_true_total(self):
        r = find_occurrences("ab" * 100, "a", max_occurrences=5)
        assert r["total_occurrences"] == 100
        assert r["occurrences_shown"] == 5
        assert r["capped"] is True
        assert "5 of 100" in r["message"]

    def test_uncapped_list_says_so(self):
        r = find_occurrences("ab" * 3, "a", max_occurrences=5)
        assert r["capped"] is False
        assert r["occurrences_shown"] == r["total_occurrences"] == 3

    def test_regex_metacharacters_are_matched_literally(self):
        r = find_occurrences("a.c and abc", "a.c")
        assert r["total_occurrences"] == 1
        assert r["occurrences"][0]["start_char"] == 0

    def test_overlapping_matches_are_counted_non_overlappingly(self):
        r = find_occurrences("aaaa", "aa")
        assert r["total_occurrences"] == 2
        assert r["match_kind"] == "literal substring, non-overlapping"

    def test_snippet_carries_context_on_one_line(self):
        text = "lead in words\nbefore the NEEDLE and after it\ntrailing words"
        r = find_occurrences(text, "needle", context=10)
        snippet = r["occurrences"][0]["snippet"]
        assert "NEEDLE" in snippet
        assert "\n" not in snippet
        assert snippet.startswith("…") and snippet.endswith("…")

    def test_searched_chars_reports_the_denominator(self):
        r = find_occurrences("alpha beta", "beta")
        assert r["searched_chars"] == 10


class TestFieldExtent:
    """R13b: every field carries an exclusive end_char, so a heading that undersells
    its field (a 38K "Findings" note holding an entire Act, O38) is self-evident."""

    def test_every_field_carries_an_exclusive_end_char(self):
        text, structure = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        for f in structure["fields"]:
            assert f["end_char"] > f["start_char"], f["field"]
            assert f["end_char"] <= len(text)

    def test_extent_slices_exactly_the_field(self):
        text, structure = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        note = next(f for f in structure["fields"] if f["field"] == "amendment-note")
        body = text[note["start_char"]:note["end_char"]]
        assert body.startswith("Amendments")
        assert "Pub. L. 102-492" in body
        # The next field's content must not bleed in, nor the previous field's out.
        assert "committee report text" not in body

    def test_extent_is_the_max_chars_a_caller_needs(self):
        text, structure = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        note = next(f for f in structure["fields"] if f["field"] == "amendment-note")
        w = window_text(text, start_char=note["start_char"], max_chars=note["end_char"] - note["start_char"])
        assert w["content"] == text[note["start_char"]:note["end_char"]]

    def test_final_field_ends_at_total_chars(self):
        text, structure = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        assert structure["fields"][-1]["end_char"] == len(text)

    def test_a_container_field_spans_its_nested_children(self):
        _, structure = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        by_field = {f["field"]: f for f in structure["fields"]}
        notes, child = by_field["notes"], by_field["amendment-note"]
        assert notes["start_char"] <= child["start_char"]
        assert child["end_char"] <= notes["end_char"]

    def test_note_warns_that_headings_describe_the_opening_not_the_contents(self):
        _, structure = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        note = structure["note"].lower()
        assert "opens" in note
        assert "end_char" in note


class TestStructureOmittedForReadingCall:
    """R13a: the invariant block rides only on the locating call."""

    def test_reading_call_form_is_omitted_with_a_pointer_back(self):
        s = structure_omitted_for_reading_call(2000)
        assert s["omitted"] is True
        assert "start_char=2000" in s["reason"]
        assert "start_char=0" in s["note"]
        assert "fields" not in s

    def test_the_omitted_flag_is_present_either_way(self):
        # The harness's structure-present-or-disclosed check reads this key and must
        # keep working across both shapes.
        _, derived = html_to_text_with_structure(fx.SECTION_HTML_WITH_FIELDS)
        assert derived["omitted"] is False
        assert structure_omitted_for_reading_call(1)["omitted"] is True


class TestAudienceSentence:
    """WO-6 (40-tools.md, "No silent truncation"; E17): a truncated window's message
    says the start_char continuation is the tool caller's and gives the person asking
    the PDF link inline — O51c saw consumers relay the continuation verbatim to an
    asker with no tool access and never surface the link the response carried."""

    PDF = "https://www.govinfo.gov/content/pkg/PLAW-118publ31/pdf/PLAW-118publ31.pdf"
    DETAILS = "https://www.govinfo.gov/app/details/PLAW-118publ31"

    def test_sentence_names_both_audiences_and_carries_the_url_inline(self):
        s = audience_sentence(self.PDF)
        assert "tool caller" in s
        assert "person asking" in s
        assert "PDF" in s
        assert self.PDF in s
        assert "provenance" not in s  # never a pointer to the field (O51c)

    def test_sentence_without_a_pdf_link_says_unavailable_not_an_empty_url(self):
        for missing in (None, ""):
            s = audience_sentence(missing)
            assert "tool caller" in s
            assert "no PDF link is available" in s
            assert "https://" not in s
            assert not s.endswith(": ")

    def test_truncated_window_keeps_the_continuation_sentence_first_byte_for_byte(self):
        before = window_text("abcdefghij", start_char=0, max_chars=4)
        original_message = before["message"]
        original_banner = before["banner"]
        original_content = before["content"]
        after = add_audience_sentence(window_text("abcdefghij", start_char=0, max_chars=4), self.PDF)
        assert after["message"] == f"{original_message} {audience_sentence(self.PDF)}"
        assert after["message"].startswith(original_message)
        assert "NOT part of the payload" in after["message"]  # R13c stays intact
        assert after["banner"] == original_banner
        assert after["content"] == original_content

    def test_untruncated_window_gains_no_message(self):
        w = add_audience_sentence(window_text("abcdef", start_char=0, max_chars=100), self.PDF)
        assert "message" not in w
        assert self.PDF not in w["content"]

    def test_returns_the_same_window_object(self):
        w = window_text("abcdefghij", start_char=0, max_chars=4)
        assert add_audience_sentence(w, self.PDF) is w

    def test_fallback_chain_public_pdf_then_details_then_unavailable(self):
        # WO-7: public PDF wins; the details page stands in only when it cannot be built.
        with_pdf = audience_sentence(self.PDF, self.DETAILS)
        assert self.PDF in with_pdf and self.DETAILS not in with_pdf
        details_only = audience_sentence(None, self.DETAILS)
        assert self.DETAILS in details_only
        assert "details page" in details_only
        assert "PDF link: " not in details_only  # a details page is not offered as a PDF
        assert "tool caller" in details_only and "person asking" in details_only
        neither = audience_sentence(None, None)
        assert "no PDF link is available" in neither
        assert "https://" not in neither

    def test_add_audience_sentence_passes_the_details_fallback_through(self):
        w = add_audience_sentence(window_text("abcdefghij", start_char=0, max_chars=4), None, self.DETAILS)
        assert w["message"].endswith(self.DETAILS)


class TestPublicPdfLink:
    """WO-7 (O53): the keyless content-path PDF, built from ids only, never fetched."""

    def test_package_form(self):
        assert public_pdf_link("PLAW-118publ31") == (
            "https://www.govinfo.gov/content/pkg/PLAW-118publ31/pdf/PLAW-118publ31.pdf"
        )

    def test_granule_form(self):
        assert public_pdf_link("USCODE-2024-title42", "USCODE-2024-title42-chap23-divsnA-subchapXIII-sec2210") == (
            "https://www.govinfo.gov/content/pkg/USCODE-2024-title42/pdf/"
            "USCODE-2024-title42-chap23-divsnA-subchapXIII-sec2210.pdf"
        )

    def test_empty_granule_id_means_package_form(self):
        assert public_pdf_link("PLAW-118publ31", None) == public_pdf_link("PLAW-118publ31", "")
        assert public_pdf_link("PLAW-118publ31", "").endswith("/PLAW-118publ31.pdf")

    def test_no_package_id_cannot_be_built(self):
        assert public_pdf_link(None) is None
        assert public_pdf_link("") is None
        assert public_pdf_link(None, "USCODE-2024-title17-chap1-sec107") is None
