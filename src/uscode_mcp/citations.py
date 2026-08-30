"""Citation parsing and normalization.

Implements the normalization contract in documentation/30-search.md:

- Canonicalize US Code citations to ``{title} U.S.C. {section}``.
- Mandatory strips: parenthetical subsection suffixes (O11: they match zero granules)
  and a trailing "note" (O16: same) — both recorded so tool responses can say the
  strip fired and name the containing section that was resolved instead.
- Appendix citations are flagged, not resolved: no citation-field form is known to
  match appendix granules (O19/E10), so the tool layer returns a structured redirect.

Public-law citations normalize to (congress, number, law_type); private laws are
recognized so the tool layer can report them as a distinct out-of-scope outcome (R6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class CitationParseError(ValueError):
    """The input could not be understood as a citation at all."""


@dataclass(frozen=True)
class USCCitation:
    title: str
    section: str | None
    stripped_subsection: str | None = None
    stripped_note: bool = False
    appendix: bool = False
    appendix_text: str = ""

    @property
    def normalized(self) -> str:
        if self.appendix:
            rest = f" {self.appendix_text}" if self.appendix_text else ""
            return f"{self.title} U.S.C. App.{rest}"
        return f"{self.title} U.S.C. {self.section}"


_USC_HEAD_RE = re.compile(r"^\s*(?P<title>\d+[a-z]?)\s+u\.?\s*s\.?\s*c\.?\s*(?P<rest>.*)$", re.IGNORECASE)
_APPENDIX_RE = re.compile(r"^app(?:endix|x)?\.?\s*(?P<rest>.*)$", re.IGNORECASE)
_SECTION_MARKER_RE = re.compile(r"^(?:§+|sec(?:tion)?\.?)\s*", re.IGNORECASE)
_NOTE_RE = re.compile(r"\s*\bnotes?\s*\.?\s*$", re.IGNORECASE)
_SECTION_TOKEN_RE = re.compile(r"^[0-9][0-9a-z.\-]*$", re.IGNORECASE)


def _parse_section_part(rest: str) -> tuple[str, str | None, bool]:
    """Parse a section fragment: '107', '107(b)(2)', '2210 note', '§ 107'.

    Returns (section, stripped_subsection, stripped_note).
    """
    rest = _SECTION_MARKER_RE.sub("", rest.strip())
    stripped_note = False
    if _NOTE_RE.search(rest):
        rest = _NOTE_RE.sub("", rest)
        stripped_note = True
    stripped_subsection = None
    paren_at = rest.find("(")
    if paren_at != -1:
        stripped_subsection = rest[paren_at:].strip()
        rest = rest[:paren_at]
    section = rest.strip().rstrip(".")
    if not _SECTION_TOKEN_RE.match(section):
        raise CitationParseError(f"could not parse a section number from {rest!r}")
    return section, stripped_subsection, stripped_note


def parse_usc(
    citation: str | None = None,
    title: str | None = None,
    section: str | None = None,
) -> USCCitation:
    """Parse a US Code citation, from a single string or separate title/section fields."""
    if citation is not None and citation.strip():
        if title is not None or section is not None:
            raise CitationParseError("pass either 'citation' or 'title'+'section', not both")
        head = _USC_HEAD_RE.match(citation)
        if not head:
            raise CitationParseError(
                f"could not parse {citation!r} as a US Code citation (expected e.g. '17 U.S.C. 107')"
            )
        title_num = head.group("title")
        rest = head.group("rest").strip()
        appendix = _APPENDIX_RE.match(rest)
        if appendix:
            return USCCitation(
                title=title_num,
                section=None,
                appendix=True,
                appendix_text=appendix.group("rest").strip().rstrip("."),
            )
        sec, sub, note = _parse_section_part(rest)
        return USCCitation(title=title_num, section=sec, stripped_subsection=sub, stripped_note=note)
    if title is None or section is None:
        raise CitationParseError("provide 'citation', or both 'title' and 'section'")
    title_str = str(title).strip()
    if not re.fullmatch(r"\d+[a-zA-Z]?", title_str):
        raise CitationParseError(f"could not parse {title!r} as a US Code title number")
    sec, sub, note = _parse_section_part(str(section))
    return USCCitation(title=title_str, section=sec, stripped_subsection=sub, stripped_note=note)


@dataclass(frozen=True)
class PublicLawCitation:
    congress: int
    number: int
    law_type: str  # "public" | "private"


_PL_RE = re.compile(
    r"^\s*(?:"
    r"(?P<priv>priv(?:ate)?\.?\s*l(?:aw)?\.?)"
    r"|pub(?:lic)?\.?\s*l(?:aw)?\.?"
    r"|p\.?\s*l\.?"
    r")\s*(?:no\.?\s*)?(?P<congress>\d+)\s*[-–—]\s*(?P<num>\d+)\s*$",
    re.IGNORECASE,
)


def parse_public_law(citation: str) -> PublicLawCitation:
    """Parse 'Pub. L. 118-31', 'Public Law 118-31', 'P.L. 118-31' (and private-law equivalents)."""
    m = _PL_RE.match(citation)
    if not m:
        raise CitationParseError(
            f"could not parse {citation!r} as a public-law citation (expected e.g. 'Pub. L. 118-31')"
        )
    law_type = "private" if m.group("priv") else "public"
    return PublicLawCitation(congress=int(m.group("congress")), number=int(m.group("num")), law_type=law_type)
