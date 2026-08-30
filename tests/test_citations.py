"""Citation normalization per documentation/30-search.md: canonical form, the two
mandatory strips (subsection O11, trailing note O16), appendix flagging, and
public-law citation forms including the private-law scope boundary (R6)."""

import pytest

from uscode_mcp.citations import CitationParseError, parse_public_law, parse_usc


class TestUSCVariants:
    @pytest.mark.parametrize(
        "raw",
        ["17 U.S.C. 107", "17 USC 107", "17 usc 107", "17 U.S.C. § 107", "17 U.S.C. §107", "  17 U.S.C. 107  "],
    )
    def test_variants_normalize_to_canonical(self, raw):
        c = parse_usc(citation=raw)
        assert c.normalized == "17 U.S.C. 107"
        assert not c.stripped_note
        assert c.stripped_subsection is None
        assert not c.appendix

    def test_subsection_suffix_is_stripped_and_recorded(self):
        c = parse_usc(citation="17 U.S.C. § 107(b)")
        assert c.normalized == "17 U.S.C. 107"
        assert c.stripped_subsection == "(b)"

    def test_nested_subsection_suffix(self):
        c = parse_usc(citation="42 U.S.C. 2210(h)(2)(A)")
        assert c.normalized == "42 U.S.C. 2210"
        assert c.stripped_subsection == "(h)(2)(A)"

    def test_trailing_note_is_stripped_and_recorded(self):
        c = parse_usc(citation="42 U.S.C. 2210 note")
        assert c.normalized == "42 U.S.C. 2210"
        assert c.stripped_note

    def test_subsection_and_note_together(self):
        c = parse_usc(citation="42 U.S.C. 2210(h) note")
        assert c.normalized == "42 U.S.C. 2210"
        assert c.stripped_subsection == "(h)"
        assert c.stripped_note

    def test_letter_suffixed_section_numbers(self):
        assert parse_usc(citation="42 U.S.C. 300gg-11").normalized == "42 U.S.C. 300gg-11"
        assert parse_usc(citation="42 U.S.C. 1395w-21").normalized == "42 U.S.C. 1395w-21"

    def test_letter_suffixed_title(self):
        assert parse_usc(citation="5a U.S.C. 1").normalized == "5a U.S.C. 1"


class TestUSCTitleSectionFields:
    def test_separate_fields(self):
        c = parse_usc(title="17", section="107")
        assert c.normalized == "17 U.S.C. 107"

    def test_separate_fields_with_note_and_subsection(self):
        c = parse_usc(title="42", section="2210(h) note")
        assert c.normalized == "42 U.S.C. 2210"
        assert c.stripped_subsection == "(h)"
        assert c.stripped_note

    def test_both_citation_and_fields_rejected(self):
        with pytest.raises(CitationParseError):
            parse_usc(citation="17 U.S.C. 107", title="17", section="107")

    def test_missing_section_rejected(self):
        with pytest.raises(CitationParseError):
            parse_usc(title="17")

    def test_bad_title_rejected(self):
        with pytest.raises(CitationParseError):
            parse_usc(title="banana", section="107")


class TestUSCAppendix:
    def test_bare_appendix(self):
        c = parse_usc(citation="28 U.S.C. App.")
        assert c.appendix
        assert c.title == "28"
        assert c.appendix_text == ""

    def test_appendix_with_terms(self):
        c = parse_usc(citation="28 U.S.C. App. Fed. R. Civ. P. 9")
        assert c.appendix
        assert "Fed. R. Civ. P. 9" in c.appendix_text


class TestUSCInvalid:
    @pytest.mark.parametrize("raw", ["", "banana", "U.S.C. 107", "17 U.S.C.", "17 U.S.C. (b)"])
    def test_unparseable_raises(self, raw):
        with pytest.raises(CitationParseError):
            parse_usc(citation=raw)

    def test_no_arguments_raises(self):
        with pytest.raises(CitationParseError):
            parse_usc()


class TestPublicLaw:
    @pytest.mark.parametrize(
        "raw",
        ["Pub. L. 118-31", "Public Law 118-31", "P.L. 118-31", "PL 118-31", "pub. l. no. 118-31", "Pub. L. 118–31"],
    )
    def test_public_variants(self, raw):
        c = parse_public_law(raw)
        assert (c.congress, c.number, c.law_type) == (118, 31, "public")

    @pytest.mark.parametrize("raw", ["Priv. L. 108-1", "Private Law 108-1"])
    def test_private_recognized_as_private(self, raw):
        c = parse_public_law(raw)
        assert (c.congress, c.number, c.law_type) == (108, 1, "private")

    @pytest.mark.parametrize("raw", ["", "118-31", "Pub. L.", "House Bill 42", "Pub. L. eighteen-31"])
    def test_unparseable_raises(self, raw):
        with pytest.raises(CitationParseError):
            parse_public_law(raw)
