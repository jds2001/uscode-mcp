"""Text derivation from GovInfo /htm payloads, windowed truncation, and location.

Contracts from documentation/40-tools.md:

- The /htm payload is HTML (O5); the server strips it to readable plain text and
  no statutory content may be dropped — source credits and statutory notes included
  (O15, R4). Stripping here is purely structural (tags removed, block structure
  becomes newlines); every piece of text content is preserved.
- ``currentthrough`` is parsed from the payload's embedded comment (O5, O15) and is
  the non-optional staleness disclosure; callers must state when it cannot be parsed.
- No silent truncation: windowing always reports total length, the window returned,
  and the start_char to continue from — and when the payload is truncated the same
  markers lead ``content`` as a bracketed banner line (E12, from finding F1: a
  consumer given correct structured fields still presented the window as the whole
  law, so the disclosure has to sit in the stream the model actually reads).
- Locating content in large payloads (R12): :func:`find_occurrences` reports the
  true occurrence count with offsets in the same coordinate system as
  ``start_char``/``total_chars``, and :func:`html_to_text_with_structure` derives a
  USCODE granule's field list from the upstream ``field-start``/``field-end``
  comment markers ONLY (O36) — never from heading heuristics — degrading to a
  disclosed omission when those markers are absent or unbalanced. Each field carries
  its extent as an exclusive ``end_char`` (R13b), and the block rides only on
  locating calls (R13a) — see :func:`structure_omitted_for_reading_call`.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from html.parser import HTMLParser
from typing import Any

_CURRENTTHROUGH_RE = re.compile(r"currentthrough\D{0,3}(\d{8})", re.IGNORECASE)
_EDITION_YEAR_RE = re.compile(r"^USCODE-(\d{4})-", re.IGNORECASE)
# Upstream field delimiters, measured in USCODE granule payloads (O36). Tolerant of
# whitespace variation inside the comment; the field name itself is taken verbatim.
_FIELD_MARKER_RE = re.compile(r"^\s*field-(start|end)\s*:\s*(\S+?)\s*$", re.IGNORECASE)

FIND_MAX_OCCURRENCES = 50
FIND_SNIPPET_CONTEXT = 80

# Tags that imply a line break when converting to plain text.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "table", "tr", "hr", "section", "article",
    "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6",
}
_SKIP_TAGS = {"script", "style"}


def extract_currentthrough(html: str) -> str | None:
    """Return the currentthrough date as YYYY-MM-DD, or None if it cannot be parsed."""
    m = _CURRENTTHROUGH_RE.search(html)
    if not m:
        return None
    raw = m.group(1)
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def edition_year_from_package_id(package_id: str | None) -> int | None:
    """Parse the edition year from a USCODE package id like 'USCODE-2024-title17'."""
    if not package_id:
        return None
    m = _EDITION_YEAR_RE.match(package_id)
    return int(m.group(1)) if m else None


class _TextExtractor(HTMLParser):
    """Strip HTML to text while recording, in pre-normalization text coordinates,
    where each upstream field marker and each ``<h4 class="note-head">`` fell."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._len = 0
        self._skip_depth = 0
        self.markers: list[tuple[str, str, int]] = []  # (kind, field, raw offset)
        self.note_heads: list[tuple[int, str]] = []  # (raw offset, heading text)
        self._head_buf: list[str] | None = None
        self._head_offset = 0

    def _emit(self, text: str) -> None:
        self._parts.append(text)
        self._len += len(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._emit("\n")
        if tag == "h4" and self._skip_depth == 0:
            classes = ""
            for name, value in attrs:
                if name.lower() == "class" and value:
                    classes = value
            if "note-head" in classes.split():
                self._head_buf = []
                self._head_offset = self._len

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag == "h4" and self._head_buf is not None:
            heading = re.sub(r"\s+", " ", "".join(self._head_buf)).strip()
            if heading:
                self.note_heads.append((self._head_offset, heading))
            self._head_buf = None
        if tag in _BLOCK_TAGS:
            self._emit("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._head_buf is not None:
            self._head_buf.append(data)
        self._emit(data)

    def handle_comment(self, data: str) -> None:
        m = _FIELD_MARKER_RE.match(data)
        if m:
            self.markers.append((m.group(1).lower(), m.group(2), self._len))

    def raw_text(self) -> str:
        return "".join(self._parts)


def _normalize_indexed(raw: str) -> tuple[str, list[int]]:
    """Normalize whitespace and return (text, src) where ``src[i]`` is the index in
    ``raw`` of normalized character ``i``.

    Every step drops characters and never inserts or rewrites any, so the normalized
    text is a subsequence of ``raw`` and the mapping is exact. The three steps are
    the ones :func:`html_to_text` has always applied: trim trailing spaces/tabs per
    line, collapse runs of 3+ newlines to 2, strip the ends.
    """
    # Trailing [ \t]+ at end of each line (and at end of the string).
    kept: list[int] = []
    at_line_end = True
    for i in range(len(raw) - 1, -1, -1):
        ch = raw[i]
        if ch == "\n":
            at_line_end = True
        elif ch in " \t" and at_line_end:
            continue
        else:
            at_line_end = False
        kept.append(i)
    kept.reverse()

    # Runs of 3+ newlines collapse to 2.
    collapsed: list[int] = []
    run = 0
    for i in kept:
        if raw[i] == "\n":
            run += 1
            if run > 2:
                continue
        else:
            run = 0
        collapsed.append(i)

    # Strip both ends.
    lo, hi = 0, len(collapsed)
    while lo < hi and raw[collapsed[lo]].isspace():
        lo += 1
    while hi > lo and raw[collapsed[hi - 1]].isspace():
        hi -= 1
    src = collapsed[lo:hi]
    return "".join([raw[i] for i in src]), src


def html_to_text(html: str) -> str:
    """Strip HTML to readable plain text, preserving all text content."""
    return html_to_text_with_structure(html)[0]


_MARKERLESS_NOTE = (
    "Structure is derived only from the payload's upstream field-start/field-end markers "
    "(O36), never guessed from headings — so it is omitted rather than approximated. The "
    "text itself is unaffected; use `find` to locate content by substring."
)


def _structure_omitted(reason: str, note: str = _MARKERLESS_NOTE) -> dict[str, Any]:
    return {"omitted": True, "reason": reason, "note": note}


def structure_omitted_for_reading_call(start_char: int) -> dict[str, Any]:
    """R13a: the field list rides only on locating calls (``start_char=0``).

    It is invariant per (section, year) and was measured at roughly 15x the payload of
    a small window (O38) — repeating it on every read is overhead on the exact
    operation the facility exists to make cheap. The omitted flag is still present, so
    a consumer (and the harness check) sees structure-present-or-disclosed either way.
    """
    return _structure_omitted(
        f"this is a reading call (start_char={start_char}), not a locating call",
        note=(
            "The field list is invariant for this section and edition, so it is returned only "
            "on locating calls rather than repeated on every window. Re-request this citation "
            "with start_char=0 (or omitted) to get it."
        ),
    )


def html_to_text_with_structure(html: str) -> tuple[str, dict[str, Any]]:
    """Return (plain text, structure block).

    The structure block is R12b: the payload's fields in document order as
    ``{field, heading, start_char}``, with ``start_char`` in the same coordinate
    system as the windowing arguments. Marker absence or imbalance degrades to a
    disclosed omission (``{"omitted": true, "reason": ...}``), never a failure —
    two granules measured is not a corpus guarantee (O36).
    """
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text, src = _normalize_indexed(extractor.raw_text())

    if not extractor.markers:
        return text, _structure_omitted("this payload carries no field-start/field-end markers")

    # Balance the markers. Proper nesting is required: an end must close the
    # innermost open field, and nothing may be left open.
    stack: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    for kind, name, offset in extractor.markers:
        if kind == "start":
            span = {"field": name, "raw_start": offset, "raw_end": None}
            spans.append(span)
            stack.append(span)
            continue
        if not stack:
            return text, _structure_omitted(f"field-end:{name} with no open field")
        if stack[-1]["field"] != name:
            return text, _structure_omitted(
                f"field-end:{name} does not close the innermost open field-start:{stack[-1]['field']}"
            )
        stack.pop()["raw_end"] = offset
    if stack:
        unclosed = ", ".join(sorted({s["field"] for s in stack}))
        return text, _structure_omitted(f"unclosed field-start marker(s): {unclosed}")

    # Each note-head belongs to the innermost field span containing it; a field's
    # heading is the first such head. Spans are properly nested and in document
    # order, so the innermost container is the last one that opened before the head.
    headings: dict[int, str] = {}
    for head_offset, heading in extractor.note_heads:
        innermost = None
        for idx, span in enumerate(spans):
            if span["raw_start"] <= head_offset < span["raw_end"]:
                innermost = idx
        if innermost is not None and innermost not in headings:
            headings[innermost] = heading

    fields = [
        {
            "field": span["field"],
            "heading": headings.get(idx),
            "start_char": bisect_left(src, span["raw_start"]),
            "end_char": bisect_left(src, span["raw_end"]),
        }
        for idx, span in enumerate(spans)
    ]
    return text, {
        "omitted": False,
        "fields": fields,
        "note": (
            "Field boundaries come from the payload's own upstream markers (O36). `start_char` and "
            "`end_char` (exclusive) share the coordinate system of total_chars/start_char, so a "
            "field can be read by re-requesting with its start_char and max_chars = end_char - "
            "start_char. Fields nest: a container like `notes` spans its typed children. HEADINGS "
            "ARE THE UPSTREAM MARKER HEADINGS VERBATIM, and they describe where a field OPENS, not "
            "everything it contains — a field can run far past what its heading suggests, so judge "
            "a field by its extent and search it with `find` rather than trusting the label."
        ),
    }


def truncation_banner(start_char: int, end: int, total: int) -> str:
    """The E12 in-band banner line: window bounds, true total, continuation offset."""
    return (
        f"[WINDOW chars {start_char:,}–{end - 1:,} of {total:,} "
        f"— truncated; continue with start_char={end}]"
    )


def window_text(text: str, start_char: int = 0, max_chars: int = 100_000) -> dict[str, Any]:
    """Return a window of text with explicit truncation markers (never silent).

    When the window is truncated, ``content`` leads with the banner line (E12); the
    structured fields describe the payload window and are unchanged by it, so
    ``total_chars``/``start_char``/``next_start_char`` remain the coordinate system
    that ``find`` offsets and ``structure`` offsets are expressed in. The banner is
    also returned on its own key so a caller can strip it deterministically.

    R13c: on every bannered response ``message`` must state in-band that the banner is
    outside the offset coordinate system. It began as an un-specced addition here and
    was consumer-validated as correctly placed (O38); it is contractual now so it
    cannot regress away.
    """
    if start_char < 0:
        raise ValueError(f"start_char must be >= 0, got {start_char}")
    if max_chars <= 0:
        raise ValueError(f"max_chars must be > 0, got {max_chars}")
    total = len(text)
    end = min(start_char + max_chars, total)
    content = text[start_char:end]
    truncated = end < total
    result: dict[str, Any] = {
        "total_chars": total,
        "start_char": start_char,
        "returned_chars": len(content),
        "truncated": truncated,
        "next_start_char": end if truncated else None,
        "content": content,
    }
    if truncated:
        banner = truncation_banner(start_char, end, total)
        result["banner"] = banner
        result["content"] = f"{banner}\n{content}"
        result["message"] = (
            f"Payload is {total} chars; returned chars {start_char}-{end}. "
            f"Continue with start_char={end}. The same disclosure leads `content` as a banner "
            f"line, which is NOT part of the payload: content offsets start at start_char after it."
        )
    return result


def find_occurrences(
    text: str,
    needle: str,
    max_occurrences: int = FIND_MAX_OCCURRENCES,
    context: int = FIND_SNIPPET_CONTEXT,
) -> dict[str, Any]:
    """Locate a case-insensitive literal substring in the full payload (R12a).

    Offsets are in the same coordinate system as ``start_char``/``total_chars``, so a
    hit feeds straight back into the window. The list is capped but the count is the
    true total, stated with the cap — the disambiguation-totals rule. Zero matches is
    an explicit success outcome, never silence.
    """
    matches = [m.start() for m in re.finditer(re.escape(needle), text, re.IGNORECASE)]
    shown = matches[:max_occurrences]
    occurrences = []
    for offset in shown:
        lo = max(0, offset - context)
        hi = min(len(text), offset + len(needle) + context)
        snippet = re.sub(r"\s+", " ", text[lo:hi]).strip()
        occurrences.append(
            {
                "start_char": offset,
                "snippet": ("…" if lo > 0 else "") + snippet + ("…" if hi < len(text) else ""),
            }
        )
    capped = len(shown) < len(matches)
    if not matches:
        message = (
            f"Zero occurrences of {needle!r} in the full {len(text)}-char payload. The search "
            "succeeded — this is 'found nothing', not a failure. Note the payload is the plain "
            "text of this document only; try a shorter or differently spelled substring."
        )
    else:
        message = (
            f"{len(matches)} occurrence(s) of {needle!r} in the full {len(text)}-char payload. "
            "Offsets share the coordinate system of total_chars/start_char — re-request with "
            "start_char set to one of them to read around it."
        )
        if capped:
            message += f" The occurrence list is capped: showing {len(shown)} of {len(matches)}."
    return {
        "needle": needle,
        "case_sensitive": False,
        "match_kind": "literal substring, non-overlapping",
        "searched_chars": len(text),
        "total_occurrences": len(matches),
        "occurrences_shown": len(shown),
        "capped": capped,
        "occurrences": occurrences,
        "message": message,
    }
