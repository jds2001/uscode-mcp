"""MCP server wiring: registers the four tools from documentation/40-tools.md on an
MCPServer instance. Tool logic lives in tools.py; this layer binds the GovInfo client
and carries the tool descriptions (which are themselves part of the spec contract —
notably the reverse-lookup recipe and its recall caveat on search_public_laws)."""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from . import tools
from ._version import __version__
from .govinfo import GovInfoClient, client_from_env
from .trace import Tracer, TracingMiddleware, tracer_from_env

logger = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = """\
Search and retrieval over the United States Code and Public Laws as published by GPO on GovInfo. The US Code
tools serve the codified law by annual edition (annual editions lag enactment by 18+ months); every text
response carries a `currentthrough` date as the staleness disclosure. For law enacted after that date — or law
that never enters the Code at all — use the public-law tools.

You do not need to check for later laws yourself: every `get_us_code_section` success already carries
`possibly_superseded`, a three-state indicator (`laws_indexed` / `none_indexed` / `not_checked`) computed on
every call by querying GovInfo for public laws published after that edition's `currentthrough` and indexed
against the section. It is an indicator, never a certification. `laws_indexed` means a listed law MENTIONS the
section — it may amend it, amend something else and merely cite it, or waive it for one named person; read the
law with `get_public_law` to find out. `none_indexed` means the server's query found nothing — re-running the
same query by hand will find nothing more, and it is NOT evidence the text is current: the index misses about
one in seven listed (law, section) pairs. `not_checked` means the check failed and says nothing either way; the
echoed `query` is your manual retry. Read the object's `caveat`.

To widen beyond what the indicator ran: `search_public_laws` with the echoed `query` minus its `publishdate`
bound, or a full-text search over the public-law collection; and read the section's own source credits for the
amendment history GovInfo prints.

Text windows default to 20,000 characters (`max_chars`), because larger windows are measured not to reach the
model inline on the current driver; every window states `total_chars` and `next_start_char`, and `find` locates
content in the full payload so you can read exactly the window you need.
"""

# Every property of every tool's input schema carries a description, character for
# character as documentation/40-tools.md ("Parameter descriptions") pins it. The texts
# restate the prose descriptions on purpose: the schema is the one text a host shows the
# model at every step, and `find` had been called as a tool by a consumer that never
# learned it was an argument. Types, defaults, titles, required lists and property order
# are untouched; `description` is the only key the schemas carry beyond what pydantic
# derives from the signature.
PARAMETER_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "get_us_code_section": {
        "citation": (
            'A US Code citation as the asker gave it — "17 U.S.C. 107", "17 USC 107", "17 U.S.C. § 107(b)", "42 '
            'U.S.C. 2210 note". A subsection suffix is stripped and reported; "note" resolves to the containing '
            "section. Pass this, or title with section."
        ),
        "title": 'US Code title number as a string ("17"), paired with section — an alternative to citation.',
        "section": 'Section number within the title ("107", "2210"), paired with title — an alternative to citation.',
        "year": (
            "Annual edition year to read instead of the latest (2023). Ignored with granule_id, which names its own "
            "edition."
        ),
        "granule_id": (
            "A granule id exactly as a search result or an ambiguous candidate list gives it "
            '("USCODE-2024-title28-app-federalru-rule9"), to read one provision when a citation matches several. Pass'
            " the same citation alongside so the staleness check still runs."
        ),
        "package_id": (
            'The package the granule belongs to ("USCODE-2024-title28"). Optional with granule_id, from which it is '
            "otherwise derived."
        ),
        "max_chars": (
            "Upper bound on the characters of text returned; default 20000. A truncated window ends at a paragraph "
            "break, carries explicit truncation markers and says where to continue. Pass 1 to receive the structure "
            "map and nothing else."
        ),
        "start_char": (
            "Character offset the window starts at, in the payload's own coordinates — the same ones find, structure "
            "and next_start_char use. Default 0."
        ),
        "find": (
            "An argument of this tool, not a tool. A case-insensitive literal substring searched across the FULL "
            "section, not only the returned window; the response reports the true occurrence count with offsets in "
            "the start_char coordinate system and short snippets. Snippets locate; they are not the text — read a "
            "window at an offset to quote."
        ),
    },
    "search_us_code": {
        "query": (
            "govinfo query syntax over the USCODE collection: the asker's topical words unquoted (all required); \"an "
            'exact phrase" in double quotes; fields such as citation:"17 U.S.C. 107", usctitlenum:28, '
            "title:collateral, packageid:USCODE-2024-title17. collection:USCODE is added when absent; any other "
            "collection is refused."
        ),
        "historical": (
            "Include superseded annual editions as well as the latest; default false. An argument, not a query term."
        ),
        "page_size": "Results per page; default 20.",
        "offset_mark": (
            'Pagination cursor: "*" for the first page (the default), then the offset_mark the previous response '
            "returned."
        ),
    },
    "get_public_law": {
        "citation": (
            'A public-law citation string — "Pub. L. 118-31", "Public Law 118-31", "P.L. 118-31". A private-law '
            'citation ("Private Law 118-1") is answered as out of scope, not as a failed lookup. Pass this, or '
            "congress with law_number."
        ),
        "congress": "Congress number (118), paired with law_number. Names the PUBLIC-law series only.",
        "law_number": (
            "Law number within the congress (31), paired with congress. Public laws only — not a private-law number."
        ),
        "format": (
            '"text" (the default) or "uslm" for USLM XML, which packages offer for the 113th Congress (2013) and '
            "later; its absence is reported as a distinct outcome."
        ),
        "max_chars": (
            "Upper bound on the characters of text returned; default 20000. A law can run to millions of characters, "
            "so a window is never the whole law; a truncated window ends at a paragraph break, carries explicit "
            "truncation markers and says where to continue."
        ),
        "start_char": (
            "Character offset the window starts at, in the payload's own coordinates — the same ones find, structure "
            "and next_start_char use. Default 0."
        ),
        "find": (
            "An argument of this tool, not a tool. A case-insensitive literal substring searched across the FULL law,"
            " not only the returned window; the response reports the true occurrence count with offsets in the "
            "start_char coordinate system and short snippets. Snippets locate; they are not the text — read a window "
            "at an offset to quote."
        ),
    },
    "search_public_laws": {
        "query": (
            'govinfo query syntax over the PLAW collection: uscodecitation:"42 U.S.C. 2210" for the laws that mention'
            " a section (recall is incomplete — absence is never evidence), congress:118 docnumber:31, "
            "publishdate:range(YYYY-MM-DD,), packageid:PLAW-118publ31 <terms> to test one law for terms. "
            "collection:PLAW is accepted; any other collection is refused."
        ),
        "page_size": "Results per page; default 20.",
        "offset_mark": (
            'Pagination cursor: "*" for the first page (the default), then the offset_mark the previous response '
            "returned."
        ),
    },
}


def _described(tool: str, parameter: str) -> Any:
    """The pydantic Field carrying the pinned description for one tool parameter.

    An unknown name raises KeyError at import, so a signature cannot name a parameter the
    table does not describe."""
    return Field(description=PARAMETER_DESCRIPTIONS[tool][parameter])


def create_server(client: GovInfoClient | None = None, tracer: Tracer | None = None) -> MCPServer:
    """Build the MCP server. A client may be injected for tests; otherwise one is
    created lazily from GOVINFO_API_KEY on first tool call.

    R8 tracing: when no tracer is injected, one is built from USCODE_MCP_TRACE_DIR
    if set — an unusable trace directory raises here, at startup, per the spec's
    instrument rules. Absence of the variable means tracing is off."""
    if tracer is None:
        tracer = tracer_from_env()
    middleware = [TracingMiddleware(tracer)] if tracer is not None else None
    state: dict[str, GovInfoClient] = {}
    owned_client = False
    if client is not None:
        state["client"] = client

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        nonlocal owned_client
        try:
            yield None
        finally:
            if owned_client:
                owned_client = False
                created_client = state.pop("client", None)
                if created_client is not None:
                    try:
                        await created_client.aclose()
                    except Exception:  # noqa: BLE001 — cleanup failure must not mask shutdown
                        logger.exception("failed to close the server-owned GovInfo client during shutdown")

    mcp = MCPServer(
        "uscode-mcp",
        instructions=SERVER_INSTRUCTIONS,
        version=__version__,
        middleware=middleware,
        lifespan=lifespan,
    )

    def _client() -> GovInfoClient:
        nonlocal owned_client
        if "client" not in state:
            state["client"] = client_from_env()
            owned_client = True
        return state["client"]

    def consumer_tool():
        """Register a tool with source indentation removed from its description."""

        def decorator(fn):
            description = "\n".join(" ".join(line.split()) for line in inspect.cleandoc(fn.__doc__ or "").splitlines())
            return mcp.tool(description=description)(fn)

        return decorator

    @consumer_tool()
    async def get_us_code_section(
        citation: Annotated[str | None, _described("get_us_code_section", "citation")] = None,
        title: Annotated[str | None, _described("get_us_code_section", "title")] = None,
        section: Annotated[str | None, _described("get_us_code_section", "section")] = None,
        year: Annotated[int | None, _described("get_us_code_section", "year")] = None,
        max_chars: Annotated[int, _described("get_us_code_section", "max_chars")] = tools.DEFAULT_MAX_CHARS,
        start_char: Annotated[int, _described("get_us_code_section", "start_char")] = 0,
        find: Annotated[str | None, _described("get_us_code_section", "find")] = None,
        granule_id: Annotated[str | None, _described("get_us_code_section", "granule_id")] = None,
        package_id: Annotated[str | None, _described("get_us_code_section", "package_id")] = None,
    ) -> dict[str, Any]:
        """Resolve a US Code citation and return the section's full text — statutory text, source
        credits, and statutory notes included (note citations like "42 U.S.C. 2210 note" resolve to
        the containing section, whose payload contains the notes). Notes are not only editorial —
        statutory notes are enacted law placed under the section; a question about a section's notes
        is about all of them, so list them with structure before answering from one.

        Pass `citation` (accepts "17 U.S.C. 107", "17 USC 107", "17 U.S.C. § 107(b)",
        "42 U.S.C. 2210 note") or `title` + `section` as separate fields. Subsection suffixes are
        stripped (the whole section is the retrieval unit). Pass the citation as the asker gave it,
        subsection included — the server strips the suffix and reports whether that subsection exists
        in the statute text. Optional `year` selects a historical
        annual edition. When a citation matches several granules the response is `ambiguous` with a
        candidate list: re-request with `granule_id` taken from that list (exactly as it appears
        there or in a search_us_code result; `package_id` is optional and otherwise derived from the
        id), passing the same `citation` alongside so the staleness check still runs — by id alone
        it reports `not_checked`. `year` is ignored with `granule_id`, which names its edition.
        Large sections are windowed via `max_chars`/`start_char` with explicit truncation markers;
        `max_chars` defaults to 20,000 because larger windows are measured not to reach the model
        inline on the current driver — pass a larger value explicitly if your host delivers it.
        Every text response carries provenance including the `currentthrough` staleness date.

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
        The statutory text is the first field after a short header, so `max_chars` around 6,000 usually returns
        the statute and source credit whole along with `structure`. When a section's size is unknown, a very small
        `max_chars` returns `structure` alone for only a few thousand characters of response envelope.
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
            granule_id=granule_id,
            package_id=package_id,
        )

    @consumer_tool()
    async def search_us_code(
        query: Annotated[str, _described("search_us_code", "query")],
        page_size: Annotated[int, _described("search_us_code", "page_size")] = tools.DEFAULT_PAGE_SIZE,
        offset_mark: Annotated[str, _described("search_us_code", "offset_mark")] = "*",
        historical: Annotated[bool, _described("search_us_code", "historical")] = False,
    ) -> dict[str, Any]:
        """Full-text and fielded search over the USCODE collection (govinfo query syntax) — the
        discovery path for topics, appendix material, and anything citation resolution redirects
        here. `collection:USCODE` is prepended when the query has no collection clause; a clause
        naming USCODE is accepted, and any other collection clause is refused before searching.
        Fielded search is available (e.g. `citation:"17 U.S.C. 107"`, `usctitlenum:28`,
        `shorttitle:...`). Results are relevance-ordered. Unquoted terms are all required, so start
        with the asker's own topical words, unquoted; double quotes match an exact phrase; `title:`
        searches section headings (e.g. `title:collateral usctitlenum:12`). The `historical`
        ARGUMENT (not a query term) includes superseded annual editions. Within-title section-level
        search: scope by package, `packageid:USCODE-2024-title17 <terms>` — this tests which
        sections contain the terms, not where in a section; `find` on get_us_code_section locates.
        Returns result pointers (ids, dates, download links), not text — follow up with
        get_us_code_section (or pass a result's `granule_id` to it). Pagination via `offset_mark`:
        pass "*" to start, then echo back the returned value.
        """
        return await tools.search_us_code(
            _client(), query, page_size=page_size, offset_mark=offset_mark, historical=historical
        )

    @consumer_tool()
    async def get_public_law(
        congress: Annotated[int | None, _described("get_public_law", "congress")] = None,
        law_number: Annotated[int | None, _described("get_public_law", "law_number")] = None,
        citation: Annotated[str | None, _described("get_public_law", "citation")] = None,
        format: Annotated[str, _described("get_public_law", "format")] = "text",
        max_chars: Annotated[int, _described("get_public_law", "max_chars")] = tools.DEFAULT_MAX_CHARS,
        start_char: Annotated[int, _described("get_public_law", "start_char")] = 0,
        find: Annotated[str | None, _described("get_public_law", "find")] = None,
    ) -> dict[str, Any]:
        """Resolve a public law and return its text with provenance. Pass `congress` + `law_number`,
        or a `citation` string ("Pub. L. 118-31", "Public Law 118-31", "P.L. 118-31"). Public laws
        only: a private-law request is a distinct out-of-scope outcome, not a failed lookup.
        `congress` + `law_number` names the PUBLIC-law series only — do not use it for a
        private-law number (Private Law 118-1 is not Public Law 118-1); pass the citation string
        ("Private Law 118-1") instead and the server returns the out-of-scope outcome.
        `format="uslm"` returns USLM XML when the package offers it — present for congresses 113
        (2013) and later, absent for 104-112 — and absence is a distinct not-available outcome.

        Retrieval is package-level and a law can run to millions of characters, so a single call
        almost never returns the whole thing: `max_chars`/`start_char` window it, `truncated` and
        `total_chars` say so, and a truncated response carries a separate `text.banner` while
        `text.content` remains payload only. `max_chars` defaults to 20,000 because larger windows
        are measured not to reach the model inline on the current driver — pass a larger value explicitly
        if your host delivers it.
        A window is NEVER the complete law — do not describe it as one.

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

    @consumer_tool()
    async def search_public_laws(
        query: Annotated[str, _described("search_public_laws", "query")],
        page_size: Annotated[int, _described("search_public_laws", "page_size")] = tools.DEFAULT_PAGE_SIZE,
        offset_mark: Annotated[str, _described("search_public_laws", "offset_mark")] = "*",
    ) -> dict[str, Any]:
        """Full-text and fielded search over the PLAW collection (public laws only). Reverse lookup —
        which public laws touch a US Code section — is `uscodecitation:"42 U.S.C. 2210"`. A
        `collection:PLAW` clause is accepted; any other collection clause is refused before
        searching.

        CAVEAT (measured and structural): the uscodecitation field's recall gap is
        25/33 on sampled membership tests, with misses in every congress sampled from the 115th on,
        varying per (law, section) — not a recency artifact. Absence of a law from these results is
        never evidence it doesn't touch the section, and this result set must never be presented as
        complete. Full-text matching has unmeasured gaps too: a quoted phrase was measured missing a
        law that contains it verbatim, so absence from any result set here is not evidence of
        absence. Other useful fields: `congress:118 docnumber:31`, `billscitation:...`, and a date
        bound as `publishdate:range(YYYY-MM-DD,)` (open-ended upper bound measured to work) — do NOT
        use `approveddate:range(...)`, which returns HTTP 500 upstream in every form tried.
        Within-law presence test: `packageid:PLAW-118publ31 <terms>` says whether that law's text
        contains the terms, not where; `find` on get_public_law locates. Returns result pointers,
        not text — follow up with get_public_law.
        """
        return await tools.search_public_laws(_client(), query, page_size=page_size, offset_mark=offset_mark)

    return mcp
