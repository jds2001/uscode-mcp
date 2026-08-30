"""Text derivation and windowing contracts (documentation/40-tools.md): no content
dropped, currentthrough parsed or explicitly absent, no silent truncation."""

import fx
import pytest

from uscode_mcp.htmltext import (
    edition_year_from_package_id,
    extract_currentthrough,
    html_to_text,
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
        assert w["content"] == "abcd"
        assert w["truncated"] is True
        assert w["next_start_char"] == 4
        assert w["total_chars"] == 10
        assert "start_char=4" in w["message"]

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
