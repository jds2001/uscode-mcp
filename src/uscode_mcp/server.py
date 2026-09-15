"""MCP server wiring: registers the four tools from documentation/40-tools.md on an
MCPServer instance. Tool logic lives in tools.py; this layer binds the GovInfo client
and carries the tool descriptions (which are themselves part of the spec contract —
notably the reverse-lookup recipe and its recall caveat on search_public_laws)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from . import tools
from ._version import __version__
from .govinfo import GovInfoClient, client_from_env
from .trace import Tracer, TracingMiddleware, tracer_from_env

SERVER_INSTRUCTIONS = """\
Search and retrieval over the United States Code and Public Laws as published by GPO on GovInfo.

The US Code tools serve the codified law by annual edition (annual editions lag enactment by 18+ months);
every text response carries a `currentthrough` date as the staleness disclosure. For law enacted after that
date — or law that never enters the Code at all — use the public-law tools.

Every get_us_code_section success also carries `possibly_superseded`: a three-state indicator
(`laws_indexed` / `none_indexed` / `not_checked`) of whether GovInfo indexes any public law published
after that edition's `currentthrough` against the section. It is an indicator, never a certification —
a fire does not mean the text is stale, silence does not mean it is current, and `not_checked` means the
check failed and says nothing either way. Read its `caveat`.

Composition recipe: resolve a section with get_us_code_section, note its `currentthrough` date, then
search_public_laws with `uscodecitation:"{title} U.S.C. {section}"` for later laws touching it — noting that
recipe's documented recall gap (absence from results is not evidence of absence). The `possibly_superseded`
object echoes the exact `query` it ran, so that same search can be repeated or widened by hand.
"""


def create_server(client: GovInfoClient | None = None, tracer: Tracer | None = None) -> MCPServer:
    """Build the MCP server. A client may be injected for tests; otherwise one is
    created lazily from GOVINFO_API_KEY on first tool call.

    R8 tracing: when no tracer is injected, one is built from USCODE_MCP_TRACE_DIR
    if set — an unusable trace directory raises here, at startup, per the spec's
    instrument rules. Absence of the variable means tracing is off."""
    if tracer is None:
        tracer = tracer_from_env()
    middleware = [TracingMiddleware(tracer)] if tracer is not None else None
    mcp = MCPServer("uscode-mcp", instructions=SERVER_INSTRUCTIONS, version=__version__, middleware=middleware)
    state: dict[str, GovInfoClient] = {}
    if client is not None:
        state["client"] = client

    def _client() -> GovInfoClient:
        if "client" not in state:
            state["client"] = client_from_env()
        return state["client"]

    @mcp.tool()
    async def get_us_code_section(
        citation: str | None = None,
        title: str | None = None,
        section: str | None = None,
        year: int | None = None,
        max_chars: int = tools.DEFAULT_MAX_CHARS,
        start_char: int = 0,
        find: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a US Code citation and return the section's full text — statutory text, source
        credits, and statutory notes included (note citations like "42 U.S.C. 2210 note" resolve to
        the containing section, whose payload contains the notes).

        Pass `citation` (accepts "17 U.S.C. 107", "17 USC 107", "17 U.S.C. § 107(b)",
        "42 U.S.C. 2210 note") or `title` + `section` as separate fields. Subsection suffixes are
        stripped (the whole section is the retrieval unit). Optional `year` selects a historical
        annual edition. Large sections are windowed via `max_chars`/`start_char` with explicit
        truncation markers. Every text response carries provenance including the `currentthrough`
        staleness date.

        STALENESS INDICATOR: every success carries `possibly_superseded`, with `status` one of
        `laws_indexed` (GovInfo indexes at least one public law published after this edition's
        `currentthrough` against this section — the true `count` plus a capped `laws` list),
        `none_indexed` (checked, nothing indexed), or `not_checked` (the check failed; the upstream
        failure is surfaced). It is an INDICATOR IN BOTH DIRECTIONS, NEVER A CERTIFICATION. A listing
        means the law MENTIONS the section — it may amend it, amend something else and merely cite
        it, or not yet be in effect — and only reading the listed law (get_public_law with its
        package_id, then `find` this section) says whether the text changed. The index misses about
        one in seven real (law, section) pairs, so `none_indexed` is NOT evidence the text is current.
        Never say a section is "current" or "up to date" on the strength of this object; never say
        it is "outdated" or "amended" without reading the listed law. Public laws only
        (`lawtype:public`). The object echoes the exact `query` and `since` bound it used.

        Appendix citations ("28 U.S.C. App.", "28 U.S.C. App. Rule 9") resolve
        directly; when one matches multiple granules the standard disambiguation list is returned,
        and only a zero-hit appendix citation (e.g. the eliminated title 50 Appendix) falls back to
        a structured redirect to search_us_code.

        DON'T GUESS OFFSETS in a big section — one call locates, one call reads:
        - `structure` comes back on the LOCATING call (`start_char` 0 or omitted): the payload's
          fields in order (`statute`, `sourcecredit`, and each typed note with its heading), each
          with a `start_char` and an exclusive `end_char`. To read one, re-request with that
          field's `start_char` and `max_chars` = `end_char` - `start_char`. On a reading call
          (nonzero `start_char`) the block says `omitted` and points back — it is invariant for
          the section, not worth repeating. It is read from the payload's own upstream field
          markers, so a granule lacking them also gets `omitted` with a reason, never a guess.
        - HEADINGS DESCRIBE WHERE A FIELD OPENS, NOT WHAT IT CONTAINS. They are upstream labels
          reported verbatim, and a field can run far past what its label suggests — one 38K
          "Findings" note holds an entire Act. Judge a field by `end_char` - `start_char` and
          search it with `find`; never conclude something is absent because no heading named it.
        - `find` takes a case-insensitive literal substring and reports the true number of
          occurrences in the FULL section with their offsets and context snippets — even when
          the match lies outside the returned window. Offsets share the `start_char` coordinate
          system, so feed one straight back as `start_char`. Zero matches is reported explicitly.
        """
        return await tools.get_us_code_section(
            _client(),
            citation=citation,
            title=title,
            section=section,
            year=year,
            max_chars=max_chars,
            start_char=start_char,
            find=find,
        )

    @mcp.tool()
    async def search_us_code(
        query: str,
        page_size: int = tools.DEFAULT_PAGE_SIZE,
        offset_mark: str = "*",
        historical: bool = False,
    ) -> dict[str, Any]:
        """Full-text and fielded search over the USCODE collection (govinfo query syntax) — the
        discovery path for topics, appendix material, and anything citation resolution redirects
        here. `collection:USCODE` is prepended unless the query already contains a `collection:`
        term. Fielded search is available (e.g. `citation:"17 U.S.C. 107"`, `usctitlenum:28`,
        `shorttitle:...`); `historical:true` includes superseded annual editions. Returns result
        pointers (ids, dates, download links), not text — follow up with get_us_code_section.
        Pagination via `offset_mark`: pass "*" to start, then echo back the returned value.
        """
        return await tools.search_us_code(
            _client(), query, page_size=page_size, offset_mark=offset_mark, historical=historical
        )

    @mcp.tool()
    async def get_public_law(
        congress: int | None = None,
        law_number: int | None = None,
        citation: str | None = None,
        format: str = "text",
        max_chars: int = tools.DEFAULT_MAX_CHARS,
        start_char: int = 0,
        find: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a public law and return its text with provenance. Pass `congress` + `law_number`,
        or a `citation` string ("Pub. L. 118-31", "Public Law 118-31", "P.L. 118-31"). Public laws
        only: a private-law request is a distinct out-of-scope outcome, not a failed lookup.
        `format="uslm"` returns USLM XML when the package offers it — present for congresses 113
        (2013) and later, absent for 104-112 — and absence is a distinct not-available outcome.

        Retrieval is package-level and a law can run to millions of characters, so a single call
        almost never returns the whole thing: `max_chars`/`start_char` window it, `truncated` and
        `total_chars` say so, and a truncated response repeats that as a banner line at the head of
        the text. A window is NEVER the complete law — do not describe it as one.

        DON'T PAGE BLINDLY looking for a provision. `find` takes a case-insensitive literal
        substring, searches the FULL law (not just the returned window), and reports the true
        occurrence count with offsets and context snippets. Offsets share the `start_char`
        coordinate system: one call locates, one call reads. Zero matches is reported explicitly.
        """
        return await tools.get_public_law(
            _client(),
            congress=congress,
            law_number=law_number,
            citation=citation,
            format=format,
            max_chars=max_chars,
            start_char=start_char,
            find=find,
        )

    @mcp.tool()
    async def search_public_laws(
        query: str,
        page_size: int = tools.DEFAULT_PAGE_SIZE,
        offset_mark: str = "*",
    ) -> dict[str, Any]:
        """Full-text and fielded search over the PLAW collection (public laws only). Reverse lookup —
        which public laws touch a US Code section — is `uscodecitation:"42 U.S.C. 2210"`.

        CAVEAT (measured, structural — O21, O17/O18): the uscodecitation field's recall gap is
        25/33 on sampled membership tests, with misses in every congress sampled from the 115th on,
        varying per (law, section) — not a recency artifact. Absence of a law from these results is
        never evidence it doesn't touch the section, and this result set must never be presented as
        complete. Other useful fields: `congress:118 docnumber:31`,
        `approveddate:range(...)`, `billscitation:...`. Returns result pointers, not text — follow up
        with get_public_law.
        """
        return await tools.search_public_laws(_client(), query, page_size=page_size, offset_mark=offset_mark)

    return mcp
