"""The four tool implementations from documentation/40-tools.md.

Each function takes the GovInfo client explicitly (the MCP layer in server.py binds
it), returns a JSON-serializable dict, and never raises for upstream conditions.

Cross-cutting contracts implemented here:

- Three distinct outcomes, never collapsed: "success" (possibly zero results, said
  explicitly with the exact upstream query echoed), "upstream_error" (HTTP status and
  body surfaced; never presented as not-found), and "rate_limited" (429 with
  x-ratelimit-*/Retry-After passed through).
- Provenance on every text payload: packageId, granuleId (when granule-level),
  edition year, currentthrough, lastModified, canonical PDF link. An unparseable
  currentthrough is stated, never silently omitted.
- No silent truncation: max_chars/start_char windows with explicit markers, and the
  same disclosure in-band at the head of the returned text (E12).
- Locating content in large payloads (R12/R13): an optional `find` on both text tools,
  and a marker-derived `structure` block on get_us_code_section successes — carried on
  locating calls (start_char=0) and disclosed as omitted on reading calls.
- Staleness indicator (R14, WO-1): every get_us_code_section success carries a
  three-state `possibly_superseded` object from superseded.py — laws_indexed /
  none_indexed / not_checked — bounded by the returned edition's own currentthrough;
  a detector failure never fails the lookup.
- Links are data: download URLs come from search results and summaries verbatim.
- Response-shape drift fails loudly (the search service is a public preview), never
  coerced into a guess.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from . import superseded
from .citations import CitationParseError, USCCitation, parse_public_law, parse_usc
from .govinfo import GovInfoClient, GovInfoTransportError, GovInfoURLPolicyError, UpstreamResponse
from .htmltext import (
    add_audience_sentence,
    edition_year_from_package_id,
    extract_currentthrough,
    find_occurrences,
    html_to_text_with_structure,
    public_pdf_link,
    structure_omitted_for_reading_call,
    window_text,
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
# WO-4 (O47b): windows much larger than this were measured not to reach the model
# inline on the current driver (a 100,082-char window was replaced by a ~3 KB
# stand-in; a 20,081-char window arrived), so a larger default would spend the
# first call discovering that. Explicit larger values are honored unchanged.
DEFAULT_MAX_CHARS = 20_000

# Per-process memory of each edition's observed currentthrough, so a repeat lookup
# of an edition can issue the staleness detector concurrently with the text fetch
# (superseded.py explains the verified-prediction scheme).
CURRENTTHROUGH_MEMORY = superseded.CurrentthroughMemory()

# A numbered appendix section ("18 U.S.C. App. 1201"), as opposed to a rule
# ("28 U.S.C. App. Rule 9") or a bare appendix citation — only the former has a
# measured uscodecitation form (O44d).
_NUMBERED_APPENDIX_RE = re.compile(r"^\d")


# ---------------------------------------------------------------------------
# Outcome helpers
# ---------------------------------------------------------------------------


def _transport_failure(exc: GovInfoTransportError) -> dict[str, Any]:
    return {
        "outcome": "upstream_error",
        "http_status": None,
        "detail": f"no HTTP response received from GovInfo: {exc}",
    }


def _upstream_failure(resp: UpstreamResponse, detail: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "outcome": "upstream_error",
        "http_status": resp.status,
        "url": resp.url,
        "body": resp.text[:5000],
    }
    if detail:
        out["detail"] = detail
    if 300 <= resp.status < 400 and "location" in resp.headers:
        out["location"] = resp.headers["location"]
    return out


def _rate_limited(resp: UpstreamResponse) -> dict[str, Any]:
    return {
        "outcome": "rate_limited",
        "http_status": 429,
        "rate_limit": resp.rate_limit_info(),
        "url": resp.url,
        "body": resp.text[:2000],
    }


def _classify(resp: UpstreamResponse) -> dict[str, Any] | None:
    """Return a failure outcome for a non-2xx response, or None if the response is usable."""
    if resp.rate_limited:
        return _rate_limited(resp)
    if not resp.ok:
        return _upstream_failure(resp)
    return None


async def _search(client: GovInfoClient, body: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Run a search. Returns (parsed_json, None) on success or (None, failure_outcome)."""
    try:
        resp = await client.search(body)
    except GovInfoTransportError as exc:
        return None, _transport_failure(exc)
    failure = _classify(resp)
    if failure is not None:
        return None, failure
    try:
        data = resp.json()
    except ValueError:
        return None, _upstream_failure(
            resp, detail="search response was not valid JSON (response-shape drift; failing loudly per spec)"
        )
    if not isinstance(data, dict) or "results" not in data:
        return None, _upstream_failure(
            resp, detail="search response lacked a 'results' field (response-shape drift; failing loudly per spec)"
        )
    return data, None


async def _fetch(
    client: GovInfoClient, url: str, source_field: str
) -> tuple[UpstreamResponse | None, dict[str, Any] | None]:
    """Fetch a download link verbatim. Returns (response, None) or (None, failure_outcome)."""
    try:
        resp = await client.fetch(url, source_field)
    except GovInfoURLPolicyError as exc:
        return None, {
            "outcome": "upstream_error",
            "http_status": None,
            "detail": str(exc),
        }
    except GovInfoTransportError as exc:
        return None, _transport_failure(exc)
    failure = _classify(resp)
    if failure is not None:
        return None, failure
    return resp, None


def _result_pointer(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": hit.get("title"),
        "package_id": hit.get("packageId"),
        "granule_id": hit.get("granuleId"),
        "date_issued": hit.get("dateIssued"),
        "collection": hit.get("collectionCode"),
        "last_modified": hit.get("lastModified"),
        "download": hit.get("download"),
        "result_link": hit.get("resultLink"),
    }


def _invalid_argument(detail: str) -> dict[str, Any]:
    return {"outcome": "invalid_argument", "detail": detail}


@dataclass(frozen=True)
class _CollectionClause:
    text: str
    value: str | None
    negated: bool
    whitespace_after_colon: bool
    inside_quoted_phrase: bool


def _group_end(query: str, start: int) -> int:
    """Return the exclusive end of a balanced parenthesized collection value."""
    depth = 0
    in_quote = False
    i = start
    while i < len(query):
        char = query[i]
        if in_quote and char == "\\":
            i += 2
            continue
        if char == '"':
            in_quote = not in_quote
        elif not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return len(query)


def _collection_clauses(query: str) -> list[_CollectionClause]:
    """Find every collection clause, without interpreting the surrounding query.

    R17 deliberately has no quote, parenthesis, or word-boundary exemptions: any
    parser the server applies to the surrounding query can disagree with GovInfo.
    Once the letters ``collection`` + optional whitespace + ``:`` occur, the
    server either proves the whole value names this tool's collection or refuses.
    """
    clauses: list[_CollectionClause] = []
    i = 0
    while i < len(query):
        if query[i : i + 10].lower() != "collection":
            i += 1
            continue

        word_end = i + 10
        colon = word_end
        while colon < len(query) and query[colon].isspace():
            colon += 1
        if colon >= len(query) or query[colon] != ":":
            i += 1
            continue

        clause_start = i - 1 if i > 0 and query[i - 1] == "-" else i
        value_start = colon + 1
        whitespace_after_colon = value_start < len(query) and query[value_start].isspace()
        token_start = value_start
        while token_start < len(query) and query[token_start].isspace():
            token_start += 1

        if token_start < len(query) and query[token_start] == '"':
            quote_end = query.find('"', token_start + 1)
            if quote_end == -1:
                clause_end = len(query)
                value = None
            else:
                clause_end = quote_end + 1
                boundary_ok = clause_end == len(query) or query[clause_end].isspace() or query[clause_end] == ")"
                if boundary_ok:
                    value = query[token_start + 1 : quote_end]
                else:
                    while clause_end < len(query) and not query[clause_end].isspace() and query[clause_end] != ")":
                        clause_end += 1
                    value = None
        elif token_start < len(query) and query[token_start] == "(":
            clause_end = _group_end(query, token_start)
            value = None
        else:
            clause_end = token_start
            while clause_end < len(query) and not query[clause_end].isspace() and query[clause_end] != ")":
                clause_end += 1
            value = query[token_start:clause_end] or None

        quotes_before = query[:i].count('"')
        inside_quoted_phrase = quotes_before % 2 == 1 and '"' in query[clause_end:]
        clauses.append(
            _CollectionClause(
                text=query[clause_start:clause_end],
                value=value,
                negated=clause_start != i,
                whitespace_after_colon=whitespace_after_colon,
                inside_quoted_phrase=inside_quoted_phrase,
            )
        )
        i += 1
    return clauses


def _scope_query(query: str, collection: str) -> tuple[str | None, dict[str, Any] | None]:
    clauses = _collection_clauses(query)
    tools_by_collection = {"USCODE": "search_us_code", "PLAW": "search_public_laws"}
    for clause in clauses:
        conforms = (
            not clause.negated
            and not clause.whitespace_after_colon
            and clause.value is not None
            and clause.value.casefold() == collection.casefold()
        )
        if conforms:
            continue
        suggested_tool = tools_by_collection.get(
            clause.value.upper() if clause.value is not None else ""
        )
        out: dict[str, Any] = {
            "outcome": "out_of_scope_collection",
            "offending_clause": clause.text,
            "collection": collection,
            "message": (
                f"No search was run. This tool is restricted to collection:{collection}; "
                f"the query's clause {clause.text!r} does not conform."
            ),
        }
        if clause.inside_quoted_phrase:
            out["message"] += " A phrase containing collection: must be written without the colon."
        if suggested_tool is not None and suggested_tool != tools_by_collection[collection]:
            out["suggested_tool"] = suggested_tool
        return None, out
    if not clauses:
        return f"collection:{collection} {query}", None
    return query, None


def _reject_blank_find(find: str | None) -> dict[str, Any] | None:
    """R12a takes a literal substring; an empty or whitespace-only one is a caller
    error, not a search that matches everywhere. Rejected before any upstream call."""
    if find is not None and not find.strip():
        return _invalid_argument(
            "find must be a non-empty literal substring (whitespace-only would match "
            "throughout the payload and locate nothing); omit it to skip locating."
        )
    return None


USCODE_RE_REQUEST = (
    "Re-request with `granule_id` taken from a candidate below (pass the same `citation` alongside it "
    "to keep the staleness check), or with `year` if the candidates differ by edition."
)
PLAW_RE_REQUEST = (
    "The number did not resolve to one public law; treat the candidates' package_id values as findings."
)


def _disambiguation_fields(count: Any, results: list[dict[str, Any]], re_request: str) -> dict[str, Any]:
    """Shared fields for an ambiguous outcome: the true total from the response's
    `count`, the shown candidates, and — stated, never implied — whether the list is
    capped, so 100 shown of 251 never reads as 100 of 100 (40-tools.md, O24). The
    message names the real re-request path for the tool (R16, O45c): never an input
    the tool does not accept."""
    shown = len(results)
    capped = isinstance(count, int) and count > shown
    message = f"Multiple matches ({count} total); not guessing. {re_request}"
    if capped:
        message += f" The candidate list is capped at one search page: showing {shown} of {count}."
    return {
        "count": count,
        "candidates_shown": shown,
        "capped": capped,
        "message": message,
        "candidates": [_result_pointer(r) for r in results],
    }


# ---------------------------------------------------------------------------
# possibly_superseded orchestration (R14, WO-1; contract and states in superseded.py)
# ---------------------------------------------------------------------------


class _Detector:
    """Drives one lookup's staleness detector around the text fetch.

    Life cycle: ``start_early`` may launch the query on a predicted bound (a
    remembered currentthrough for the requested edition) before the citation
    search, so it overlaps both upstream round trips; ``after_fetch`` verifies that
    prediction against the payload's own currentthrough — discarding and re-issuing
    on a mismatch, or issuing for the first time on a cold lookup; ``finish`` waits
    a bounded budget once the text is ready and renders the three-state object.
    Every path ends in a `possibly_superseded` object; none can fail the lookup.
    """

    def __init__(self, client: GovInfoClient, parsed: USCCitation | None, year: int | None) -> None:
        self._client = client
        self._parsed = parsed
        self._year = year
        self._task: asyncio.Task[superseded.DetectorOutcome] | None = None
        self._predicted: str | None = None
        self._issued: str | None = None
        self._discarded_prediction: str | None = None
        self._bound_error: str | None = None
        self.query: str | None = None
        self.since: str | None = None
        self.currentthrough: str | None = None

    @property
    def _citation(self) -> str | None:
        """The citation the check runs on: the resolved section after the mandatory
        strips, or the measured App. form for a numbered appendix section (O44d).
        Appendix rules and bare appendix citations have no measured form: None."""
        parsed = self._parsed
        if parsed is None:
            return None
        if parsed.appendix:
            if parsed.appendix_text and _NUMBERED_APPENDIX_RE.match(parsed.appendix_text):
                return f"{parsed.title} U.S.C. App. {parsed.appendix_text}"
            return None
        if parsed.section is None:
            return None
        return f"{parsed.title} U.S.C. {parsed.section}"

    def _launch(self, currentthrough: str) -> None:
        try:
            self.since = superseded.since_from_currentthrough(currentthrough)
        except ValueError as exc:
            # A currentthrough that parsed as eight digits but is not a real date:
            # no bound, so no query — reported, never raised out of the lookup.
            self._bound_error = f"currentthrough {currentthrough!r} is not a valid date ({exc})"
            self.since = None
            return
        assert self._citation is not None
        self.query = superseded.build_query(self._citation, self.since)
        self._task = asyncio.create_task(superseded.run_detector(self._client, self.query))

    async def _discard(self) -> None:
        if self._task is None:
            return
        task, self._task = self._task, None
        task.cancel()
        # gather(return_exceptions=True) absorbs the inner cancellation without
        # masking a cancellation of the lookup itself.
        await asyncio.gather(task, return_exceptions=True)

    def start_early(self) -> None:
        """Issue before the citation search when the requested edition's currentthrough
        has been observed before in this process (the prediction is verified later)."""
        if self._citation is None:
            return
        self._predicted = CURRENTTHROUGH_MEMORY.predict(self._year)
        if self._predicted is not None:
            self._issued = "before_search"
            self._launch(self._predicted)

    async def abandon(self) -> None:
        """The lookup is failing before any success object exists; drop the query."""
        await self._discard()

    async def after_fetch(self, edition_year: int | None, currentthrough: str | None) -> None:
        """Bind the check to the fetched payload's own currentthrough."""
        self.currentthrough = currentthrough
        CURRENTTHROUGH_MEMORY.observe(edition_year, currentthrough)
        if self._citation is None:
            return
        if self._task is not None and currentthrough != self._predicted:
            # The speculative bound was wrong for this payload: never use its result.
            self._discarded_prediction = self._predicted
            await self._discard()
            self._issued = None
        if self._task is None and currentthrough is not None:
            self._issued = "after_fetch"
            self._launch(currentthrough)

    async def finish(self, stripped_note: bool, budget: float | None = None) -> dict[str, Any]:
        """Called once the text is ready. Waits at most ``budget`` seconds (default
        ``superseded.DETECTOR_BUDGET_SECONDS``, read at call time)."""
        if budget is None:
            budget = superseded.DETECTOR_BUDGET_SECONDS
        citation = self._citation
        common = dict(query=self.query, since=self.since, currentthrough=self.currentthrough, checked_citation=citation)
        if self._parsed is None:
            out = superseded.not_checked(
                "no_citation_for_detector",
                "the lookup was by granule_id and no citation was supplied; the detector needs a "
                "'{title} U.S.C. {section}' form and the granule summary's usCodeCitation is null (O9). "
                "Pass `citation` alongside `granule_id` to get the staleness check.",
                **common,
            )
        elif citation is None:
            out = superseded.not_checked(
                "no_measured_citation_form",
                "appendix rules and bare appendix citations have no measured uscodecitation form (O44d: "
                "0 hits for '28 U.S.C. App.' and '28 U.S.C. App. Rule 9'); only numbered appendix sections "
                "have one, so the detector was not run.",
                **common,
            )
        elif self.currentthrough is None or self._bound_error is not None:
            out = superseded.not_checked(
                "no_bound",
                (
                    self._bound_error
                    or "currentthrough could not be parsed from the payload"
                )
                + ", so the detector's publishdate bound could not be derived and the query was not sent.",
                **common,
            )
        else:
            assert self._task is not None and self.query is not None and self.since is not None
            outcome = await superseded.await_with_budget(self._task, budget)
            self._task = None
            if outcome is None:
                out = superseded.not_checked(
                    "timeout",
                    f"the detector query had not returned within the {budget:g} s budget after the section "
                    "text was ready; the text is not held for it.",
                    **common,
                )
            else:
                out = superseded.render(
                    outcome,
                    query=self.query,
                    since=self.since,
                    currentthrough=self.currentthrough,
                    checked_citation=citation,
                )
                if outcome.elapsed_ms is not None:
                    out["detector_ms"] = round(outcome.elapsed_ms)
            out["issued"] = self._issued
            if self._discarded_prediction is not None:
                out["prediction_note"] = (
                    f"a speculative query bounded by a remembered currentthrough of {self._discarded_prediction} "
                    f"was issued before the citation search, then discarded because this payload's currentthrough "
                    f"is {self.currentthrough}; the result above is from the re-issued, correctly bounded query."
                )
        if stripped_note and self._parsed is not None:
            out["note_statement"] = superseded.note_statement(citation or self._parsed.normalized)
        return out


# ---------------------------------------------------------------------------
# get_us_code_section
# ---------------------------------------------------------------------------


async def _resolve_granule(
    client: GovInfoClient,
    parsed: USCCitation,
    year: int | None,
    normalization: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any] | None]:
    """Resolve a parsed citation to exactly one granule with a txtLink.

    Returns ``(hit, download, txt_link, None)`` on success, or ``(None, None, None,
    outcome)`` for every early outcome: upstream failure, not_found,
    appendix_redirect, ambiguous, or a hit without a txtLink."""
    query = f'collection:USCODE citation:"{parsed.normalized}"'
    body = {
        "query": query,
        "pageSize": MAX_PAGE_SIZE,
        "offsetMark": "*",
        "historical": year is not None,
    }
    data, failure = await _search(client, body)
    if failure is not None:
        return None, None, None, failure
    assert data is not None
    results = data["results"] or []
    if year is not None:
        results = [r for r in results if str(r.get("dateIssued", "")).startswith(str(year))]

    if not results:
        if parsed.appendix:
            terms = f' "{parsed.appendix_text}"' if parsed.appendix_text else ""
            return None, None, None, {
                "outcome": "appendix_redirect",
                "citation": parsed.normalized,
                "query": query,
                "year": year,
                "message": (
                    "The appendix citation resolved to zero granules — real for appendix material that no "
                    "longer exists in the current edition (e.g. the eliminated title 50 Appendix, O24). "
                    "Appendix granules are full-text indexed, so retry with search_us_code and the "
                    "suggested query."
                ),
                "suggested_tool": "search_us_code",
                "suggested_query": f"collection:USCODE usctitlenum:{parsed.title}{terms}",
            }
        return None, None, None, {
            "outcome": "not_found",
            "normalized_citation": parsed.normalized,
            "query": query,
            "year": year,
            "normalization": normalization,
            "message": (
                "The search succeeded but the citation resolved to zero granules"
                + (f" for edition year {year}" if year is not None else "")
                + ". The exact upstream query is echoed above; retry with search_us_code for full-text discovery."
            ),
        }
    if len(results) > 1:
        return None, None, None, {
            "outcome": "ambiguous",
            "normalized_citation": parsed.normalized,
            "query": query,
            "year": year,
            **_disambiguation_fields(data.get("count"), results, USCODE_RE_REQUEST),
        }

    hit = results[0]
    download = hit.get("download") or {}
    txt_link = download.get("txtLink")
    if not txt_link:
        return None, None, None, {
            "outcome": "upstream_error",
            "http_status": None,
            "detail": (
                "search result carried no txtLink in its download map (response-shape drift; failing loudly "
                "per spec rather than constructing a URL)"
            ),
            "result": _result_pointer(hit),
        }

    return hit, download, txt_link, None


_USCODE_GRANULE_ID_RE = re.compile(
    r"^(?P<package>USCODE-(?P<year>\d{4})-title(?P<title>\d+[a-z]?))-\S+$", re.IGNORECASE
)
_USCODE_PACKAGE_ID_RE = re.compile(r"^USCODE-\d{4}-title\d+[a-z]?$", re.IGNORECASE)


def _normalization_block(parsed: USCCitation) -> dict[str, Any]:
    normalization: dict[str, Any] = {
        "normalized_citation": parsed.normalized,
        "stripped_subsection": parsed.stripped_subsection,
        "stripped_note": parsed.stripped_note,
    }
    notes: list[str] = []
    if parsed.stripped_subsection:
        notes.append(
            f"Subsection suffix {parsed.stripped_subsection!r} was stripped: the granule is the retrieval "
            f"unit, so the whole containing section {parsed.normalized} is returned; navigate within it."
        )
    if parsed.stripped_note:
        notes.append(
            f"Trailing 'note' was stripped: the containing section {parsed.normalized} was resolved instead, "
            "and its statutory notes are included in the returned payload."
        )
    if notes:
        normalization["messages"] = notes
    return normalization


async def _fetch_and_deliver(
    client: GovInfoClient,
    detector: _Detector,
    parsed: USCCitation | None,
    hit: dict[str, Any],
    download: dict[str, Any],
    txt_link: str,
    max_chars: int,
    start_char: int,
    find: str | None,
    head: dict[str, Any],
) -> dict[str, Any]:
    """Everything downstream of granule selection, shared by the citation and id
    paths (R16: the id path is the citation path's code, not a copy): fetch the
    txtLink verbatim, provenance, currentthrough, structure, windowing, the banner,
    `find`, and the bounded wait for the staleness detector. ``head`` is the
    path-specific leading part of the success object."""
    package_id = hit.get("packageId")
    edition_year = edition_year_from_package_id(package_id)
    resp, failure = await _fetch(client, txt_link, "txtLink")
    if failure is not None:
        await detector.abandon()
        return failure
    assert resp is not None
    html = resp.text

    currentthrough = extract_currentthrough(html)
    await detector.after_fetch(edition_year, currentthrough)
    granule_id = hit.get("granuleId")
    provenance: dict[str, Any] = {
        "package_id": package_id,
        "granule_id": granule_id,
        "edition_year": edition_year,
        "currentthrough": currentthrough,
        "last_modified": hit.get("lastModified"),
        "pdf_link": download.get("pdfLink"),
        # WO-7: the keyless content-path PDF, built from the ids above and nothing else;
        # details_link is the granule summary's detailsLink verbatim — present on the
        # granule_id path, null on the citation path, whose search hit carries none
        # (measured 2026-09-19: search hits have resultLink/relatedLink, no detailsLink).
        "public_pdf_link": public_pdf_link(package_id, granule_id),
        "details_link": hit.get("detailsLink"),
    }
    if currentthrough is None:
        provenance["currentthrough_note"] = (
            "currentthrough could not be parsed from the payload; staleness relative to enactment is unknown."
        )

    text, structure = html_to_text_with_structure(html)
    if start_char:
        # R13a: the block is invariant per (section, year); a reading call has no use
        # for it and paid ~15x a small window to carry it (O38).
        structure = structure_omitted_for_reading_call(start_char)
    try:
        window = window_text(text, start_char=start_char, max_chars=max_chars)
    except ValueError as exc:
        await detector.abandon()
        return _invalid_argument(str(exc))
    add_audience_sentence(window, provenance["public_pdf_link"], provenance["details_link"])

    # The text is ready: wait the bounded budget for the detector, never longer.
    stripped_note = parsed.stripped_note if parsed is not None else False
    possibly_superseded = await detector.finish(stripped_note=stripped_note)

    out: dict[str, Any] = {
        "outcome": "success",
        **head,
        "provenance": provenance,
        "possibly_superseded": possibly_superseded,
        "structure": structure,
        "text": window,
    }
    if find is not None:
        out["find"] = find_occurrences(text, find)
    return out


async def _get_section_by_id(
    client: GovInfoClient,
    granule_id: str,
    package_id: str | None,
    parsed: USCCitation | None,
    year: int | None,
    max_chars: int,
    start_char: int,
    find: str | None,
) -> dict[str, Any]:
    """R16 by-id path (40-tools.md, "By-id behavior"): no URL is constructed from the
    id; the granule summary (O9) is fetched and its txtLink used verbatim."""
    granule_id = granule_id.strip()
    m = _USCODE_GRANULE_ID_RE.match(granule_id)
    if not m:
        return _invalid_argument(
            f"granule_id {granule_id!r} is not a USCODE granule id (expected the form "
            "USCODE-{year}-title{n}-..., exactly as a disambiguation list or search_us_code result carried it)."
        )
    derived = package_id is None or not package_id.strip()
    if derived:
        package_id = m.group("package")
    else:
        package_id = package_id.strip()
        if not _USCODE_PACKAGE_ID_RE.match(package_id):
            return _invalid_argument(
                f"package_id {package_id!r} is not a USCODE package id (expected USCODE-{{year}}-title{{n}})."
            )
    assert package_id is not None

    head: dict[str, Any] = {
        "citation": parsed.normalized if parsed is not None else None,
        "granule_id": granule_id,
        "package_id": package_id,
        "package_id_derived": derived,
    }
    if derived:
        head["package_id_note"] = (
            f"package_id was derived from the granule id's leading USCODE-{{year}}-title{{n}} segments "
            f"({package_id}); pass package_id explicitly to override."
        )
    if parsed is not None:
        head["normalization"] = _normalization_block(parsed)
    if year is not None:
        head["warnings"] = [
            f"year={year} was ignored: granule_id names its edition (USCODE-{m.group('year')}-...). "
            "Omit granule_id to select an edition by year."
        ]

    # The id names its edition, so the detector can predict its bound from the
    # remembered currentthrough of that edition year (verified after the fetch).
    detector = _Detector(client, parsed, int(m.group("year")))
    detector.start_early()

    try:
        summary_resp = await client.granule_summary(package_id, granule_id)
    except GovInfoTransportError as exc:
        await detector.abandon()
        return _transport_failure(exc)
    # Measured not-found shapes (WO-3 verification run, 2026-09-15): a nonexistent
    # package answers 404; a nonexistent granule under an existing package — or a
    # granule id that belongs to a different package — answers 400 with the body
    # {"message":"invalid granuleId"}. Both are 'not found', never upstream failure;
    # any other 400 is left as the upstream failure it is.
    not_found_kind = None
    if summary_resp.status == 404:
        not_found_kind = "package"
    elif summary_resp.status == 400 and "invalid granuleid" in summary_resp.text.lower():
        not_found_kind = "granule"
    if not_found_kind is not None:
        await detector.abandon()
        what = (
            f"no package {package_id!r} (HTTP 404)"
            if not_found_kind == "package"
            else f"package {package_id!r} exists but has no granule {granule_id!r} (HTTP 400 'invalid granuleId', "
            "the measured shape for a nonexistent granule or an id from a different package)"
        )
        return {
            "outcome": "not_found",
            **head,
            "not_found_kind": not_found_kind,
            "http_status": summary_resp.status,
            "url": summary_resp.url,
            "body": summary_resp.text[:2000],
            "message": (
                f"GovInfo has {what}. This is 'not found', not an upstream failure. Check the id against a "
                "disambiguation list or search_us_code result; if package_id was derived, pass it explicitly."
            ),
        }
    failure = _classify(summary_resp)
    if failure is not None:
        await detector.abandon()
        return failure
    try:
        summary = summary_resp.json()
    except ValueError:
        await detector.abandon()
        return _upstream_failure(summary_resp, detail="granule summary was not valid JSON")
    if not isinstance(summary, dict):
        await detector.abandon()
        return _upstream_failure(summary_resp, detail="granule summary was not a JSON object (response-shape drift)")
    download = summary.get("download") or {}
    txt_link = download.get("txtLink")
    if not txt_link:
        await detector.abandon()
        return {
            "outcome": "upstream_error",
            "http_status": None,
            "detail": (
                "granule summary carried no txtLink in its download map (response-shape drift; failing loudly "
                "per spec rather than constructing a URL)"
            ),
            **head,
            "available_formats": sorted(download.keys()),
        }
    hit = {
        "packageId": summary.get("packageId") or package_id,
        "granuleId": summary.get("granuleId") or granule_id,
        "lastModified": summary.get("lastModified"),
        "detailsLink": summary.get("detailsLink"),
    }
    return await _fetch_and_deliver(
        client, detector, parsed, hit, download, txt_link, max_chars, start_char, find, head
    )


async def get_us_code_section(
    client: GovInfoClient,
    citation: str | None = None,
    title: str | None = None,
    section: str | None = None,
    year: int | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    start_char: int = 0,
    find: str | None = None,
    granule_id: str | None = None,
    package_id: str | None = None,
) -> dict[str, Any]:
    """Resolve a US Code citation (or select a granule by id, R16) and return the
    section's text, notes included."""
    bad_find = _reject_blank_find(find)
    if bad_find is not None:
        return bad_find

    if granule_id is not None and granule_id.strip():
        parsed: USCCitation | None = None
        if (citation is not None and citation.strip()) or title is not None or section is not None:
            try:
                parsed = parse_usc(citation=citation, title=title, section=section)
            except CitationParseError as exc:
                return _invalid_argument(str(exc))
        return await _get_section_by_id(
            client, granule_id, package_id, parsed, year, max_chars, start_char, find
        )
    if package_id is not None and package_id.strip():
        return _invalid_argument("package_id is only meaningful alongside granule_id; pass granule_id too.")

    try:
        parsed = parse_usc(citation=citation, title=title, section=section)
    except CitationParseError as exc:
        return _invalid_argument(str(exc))
    normalization = _normalization_block(parsed)

    # R14: with a remembered bound the detector goes out before the citation
    # search, overlapping both upstream round trips; it is verified after the fetch.
    detector = _Detector(client, parsed, year)
    detector.start_early()
    hit, download, txt_link, early = await _resolve_granule(client, parsed, year, normalization)
    if early is not None:
        await detector.abandon()
        return early
    assert hit is not None and download is not None and txt_link is not None
    head = {"citation": parsed.normalized, "normalization": normalization}
    return await _fetch_and_deliver(
        client, detector, parsed, hit, download, txt_link, max_chars, start_char, find, head
    )


# ---------------------------------------------------------------------------
# search_us_code / search_public_laws
# ---------------------------------------------------------------------------


async def _scoped_search(
    client: GovInfoClient,
    collection: str,
    query: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    offset_mark: str = "*",
    historical: bool = False,
) -> dict[str, Any]:
    if not query or not query.strip():
        return _invalid_argument("query must be a non-empty govinfo query string")
    query = query.strip()
    query, scope_failure = _scope_query(query, collection)
    if scope_failure is not None:
        return scope_failure
    assert query is not None

    effective_page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    body = {
        "query": query,
        "pageSize": effective_page_size,
        "offsetMark": offset_mark or "*",
        "historical": bool(historical),
    }
    data, failure = await _search(client, body)
    if failure is not None:
        return failure
    assert data is not None
    results = data["results"] or []
    out: dict[str, Any] = {
        "outcome": "success",
        "query": query,
        "count": data.get("count"),
        "offset_mark": data.get("offsetMark"),
        "page_size": effective_page_size,
        "results": [_result_pointer(r) for r in results],
    }
    if effective_page_size != page_size:
        out["page_size_note"] = f"page_size {page_size} was clamped to {effective_page_size} (allowed range 1-100)."
    if not results:
        out["message"] = (
            "Zero results. The search itself succeeded — this is 'found nothing', not a failure; "
            "the exact query sent upstream is in 'query'."
        )
    return out


async def search_us_code(
    client: GovInfoClient,
    query: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    offset_mark: str = "*",
    historical: bool = False,
) -> dict[str, Any]:
    """Full-text and fielded search over the USCODE collection. Returns pointers, not text."""
    return await _scoped_search(
        client, "USCODE", query, page_size=page_size, offset_mark=offset_mark, historical=historical
    )


# WO-5 change 4: every search_public_laws success carries a recall caveat — the
# measured field gap when the query uses uscodecitation:, and otherwise the
# measured full-text gap (O49c) — so no result set here reads as complete.
RECALL_CAVEAT_USCODECITATION = (
    "The uscodecitation field's recall gap is measured and structural (O21, O17/O18): 25/33 sampled "
    "recall against packages' own references arrays, with misses in every congress sampled from the "
    "115th on, varying per (law, section). Absence of a law from these results is never evidence it "
    "doesn't touch the section; this result set must not be presented as complete."
)
RECALL_CAVEAT_FULLTEXT = (
    "Full-text matching on the public-law collection has unmeasured gaps: a quoted phrase was measured "
    "missing a law whose text contains it verbatim (the unquoted terms found it), so absence of a law "
    "from these results is never evidence of absence. This result set must not be presented as "
    "complete; to test one law for a term, scope with packageid: or use `find` on get_public_law."
)


async def search_public_laws(
    client: GovInfoClient,
    query: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    offset_mark: str = "*",
) -> dict[str, Any]:
    """As search_us_code but scoped collection:PLAW (public laws only, R6)."""
    result = await _scoped_search(client, "PLAW", query, page_size=page_size, offset_mark=offset_mark)
    if result.get("outcome") == "success":
        if "uscodecitation:" in result.get("query", ""):
            result["recall_caveat"] = RECALL_CAVEAT_USCODECITATION
        else:
            result["recall_caveat"] = RECALL_CAVEAT_FULLTEXT
    return result


# ---------------------------------------------------------------------------
# get_public_law
# ---------------------------------------------------------------------------


async def get_public_law(
    client: GovInfoClient,
    congress: int | None = None,
    law_number: int | None = None,
    citation: str | None = None,
    format: str = "text",
    max_chars: int = DEFAULT_MAX_CHARS,
    start_char: int = 0,
    find: str | None = None,
) -> dict[str, Any]:
    """Resolve a public law and return its text (or USLM XML) with provenance."""
    if format not in ("text", "uslm"):
        return _invalid_argument(f"format must be 'text' or 'uslm', got {format!r}")
    bad_find = _reject_blank_find(find)
    if bad_find is not None:
        return bad_find

    if citation is not None and citation.strip():
        if congress is not None or law_number is not None:
            return _invalid_argument("pass either 'citation' or 'congress'+'law_number', not both")
        try:
            parsed = parse_public_law(citation)
        except CitationParseError as exc:
            return _invalid_argument(str(exc))
        if parsed.law_type == "private":
            return {
                "outcome": "out_of_scope_private_law",
                "citation": citation.strip(),
                "message": (
                    "Private laws are out of scope for this server (R6): this is a scope boundary, not a "
                    "failed lookup. Only public laws are served."
                ),
            }
        congress, law_number = parsed.congress, parsed.number
    elif congress is None or law_number is None:
        return _invalid_argument("provide 'citation', or both 'congress' and 'law_number'")

    query = f"collection:PLAW lawtype:public congress:{congress} docnumber:{law_number}"
    body = {"query": query, "pageSize": MAX_PAGE_SIZE, "offsetMark": "*"}
    data, failure = await _search(client, body)
    if failure is not None:
        return failure
    assert data is not None
    results = data["results"] or []
    if not results:
        return {
            "outcome": "not_found",
            "congress": congress,
            "law_number": law_number,
            "query": query,
            "message": (
                "The search succeeded but resolved zero packages for this public law. "
                "The exact upstream query is echoed above."
            ),
        }
    if len(results) > 1:
        return {
            "outcome": "ambiguous",
            "congress": congress,
            "law_number": law_number,
            "query": query,
            **_disambiguation_fields(data.get("count"), results, PLAW_RE_REQUEST),
        }

    package_id = results[0].get("packageId")
    if not package_id:
        return {
            "outcome": "upstream_error",
            "http_status": None,
            "detail": "search result carried no packageId (response-shape drift; failing loudly per spec)",
            "result": _result_pointer(results[0]),
        }

    expected_package_id = f"PLAW-{congress}publ{law_number}"
    if package_id != expected_package_id:
        return {
            "outcome": "upstream_error",
            "http_status": None,
            "detail": (
                f"public-law resolution expected packageId {expected_package_id!r}, "
                f"but the search result carried {package_id!r}"
            ),
            "result": _result_pointer(results[0]),
        }

    try:
        summary_resp = await client.package_summary(package_id)
    except GovInfoTransportError as exc:
        return _transport_failure(exc)
    failure = _classify(summary_resp)
    if failure is not None:
        return failure
    try:
        summary = summary_resp.json()
    except ValueError:
        return _upstream_failure(summary_resp, detail="package summary was not valid JSON")
    download = summary.get("download") or {}

    if format == "uslm":
        link = download.get("uslmLink")
        if not link:
            return {
                "outcome": "format_not_available",
                "format": "uslm",
                "package_id": package_id,
                "available_formats": sorted(download.keys()),
                "message": (
                    "This package offers no uslmLink. USLM has a measured boundary in the PLAW collection "
                    "(O25): absent for congresses 104-112, present from the 113th (2013) on — so absence is "
                    "an expected, reportable outcome for early congresses, not an error. Retry with "
                    "format='text' or use one of the available formats' links."
                ),
            }
        content_is_html = False
        source_field = "uslmLink"
    else:
        link = download.get("txtLink")
        if not link:
            return {
                "outcome": "upstream_error",
                "http_status": None,
                "detail": (
                    "package summary carried no txtLink in its download map (response-shape drift; failing "
                    "loudly per spec rather than constructing a URL)"
                ),
                "package_id": package_id,
                "available_formats": sorted(download.keys()),
            }
        content_is_html = True
        source_field = "txtLink"

    resp, failure = await _fetch(client, link, source_field)
    if failure is not None:
        return failure
    assert resp is not None
    # PLAW payloads are flat — no field markers upstream (O36) — so there is no
    # structure block here; `find` is the structure-free locator that R12a specifies.
    content = html_to_text_with_structure(resp.text)[0] if content_is_html else resp.text

    try:
        window = window_text(content, start_char=start_char, max_chars=max_chars)
    except ValueError as exc:
        return _invalid_argument(str(exc))
    provenance: dict[str, Any] = {
        "package_id": package_id,
        "date_issued": summary.get("dateIssued"),
        "last_modified": summary.get("lastModified"),
        "pdf_link": download.get("pdfLink"),
        # WO-7: keyless content-path PDF for the package, and the package summary's
        # detailsLink verbatim.
        "public_pdf_link": public_pdf_link(package_id),
        "details_link": summary.get("detailsLink"),
    }
    add_audience_sentence(window, provenance["public_pdf_link"], provenance["details_link"])

    out: dict[str, Any] = {
        "outcome": "success",
        "congress": congress,
        "law_number": law_number,
        "format": format,
        "provenance": provenance,
        "text": window,
    }
    if find is not None:
        out["find"] = find_occurrences(content, find)
    return out
