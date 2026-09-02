"""Text derivation and windowing contracts (documentation/40-tools.md): no content
dropped, currentthrough parsed or explicitly absent, no silent truncation."""

import fx
import pytest

from uscode_mcp.htmltext import (
    edition_year_from_package_id,
    extract_currentthrough,
    find_occurrences,
    html_to_text,
    html_to_text_with_structure,
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
