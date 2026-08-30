"""Text derivation from GovInfo /htm payloads, and windowed truncation.

Contracts from documentation/40-tools.md:

- The /htm payload is HTML (O5); the server strips it to readable plain text and
  no statutory content may be dropped — source credits and statutory notes included
  (O15, R4). Stripping here is purely structural (tags removed, block structure
  becomes newlines); every piece of text content is preserved.
- ``currentthrough`` is parsed from the payload's embedded comment (O5, O15) and is
  the non-optional staleness disclosure; callers must state when it cannot be parsed.
- No silent truncation: windowing always reports total length, the window returned,
  and the start_char to continue from.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

_CURRENTTHROUGH_RE = re.compile(r"currentthrough\D{0,3}(\d{8})", re.IGNORECASE)
_EDITION_YEAR_RE = re.compile(r"^USCODE-(\d{4})-", re.IGNORECASE)

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
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    """Strip HTML to readable plain text, preserving all text content."""
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = extractor.text()
    # Normalize whitespace without dropping content: trim trailing space per line,
    # collapse runs of blank lines to a single blank line.
    lines = [re.sub(r"[ \t]+$", "", line) for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def window_text(text: str, start_char: int = 0, max_chars: int = 100_000) -> dict[str, Any]:
    """Return a window of text with explicit truncation markers (never silent)."""
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
        result["message"] = (
            f"Payload is {total} chars; returned chars {start_char}-{end}. "
            f"Continue with start_char={end}."
        )
    return result
