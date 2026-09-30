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
- No silent truncation: max_chars/start_char windows with explicit markers and a
  separate banner while content remains payload text only.
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
from .govinfo import (
    NOT_FOUND_BODY_BOUND,
    RATE_LIMITED_BODY_BOUND,
    UPSTREAM_ERROR_BODY_BOUND,
    GovInfoClient,
    GovInfoTransportError,
    GovInfoURLPolicyError,
    UpstreamResponse,
    relay_body,
)
from .htmltext import (
    add_audience_sentence,
    edition_year_from_package_id,
    extract_currentthrough,
    find_occurrences,
    html_to_text_with_structure,
    occurrence_offsets,
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
        **relay_body(resp.text, UPSTREAM_ERROR_BODY_BOUND),
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
        **relay_body(resp.text, RATE_LIMITED_BODY_BOUND),
    }


def _classify(resp: UpstreamResponse) -> dict[str, Any] | None:
    """Return a failure outcome for a non-2xx response, or None if the response is usable."""
    if resp.rate_limited:
        return _rate_limited(resp)
    if not resp.ok:
        return _upstream_failure(resp)
    return None


async def _search(
    client: GovInfoClient, body: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, UpstreamResponse | None]:
    """Run and shape-check a search, retaining the response for path-specific checks."""
    try:
        resp = await client.search(body)
    except GovInfoTransportError as exc:
        return None, _transport_failure(exc), None
    failure = _classify(resp)
    if failure is not None:
        return None, failure, resp
    try:
        data = resp.json()
    except ValueError:
        return (
            None,
            _upstream_failure(
                resp, detail="search response was not valid JSON (response-shape drift; failing loudly per spec)"
            ),
            resp,
        )
    if not isinstance(data, dict):
        return (
            None,
            _upstream_failure(
                resp,
                detail=f"search response expected a JSON object, got {type(data).__name__}",
            ),
            resp,
        )
    if "results" not in data:
        return (
            None,
            _upstream_failure(resp, detail="search response expected a 'results' field, but it was absent"),
            resp,
        )
    results = data["results"]
    if not isinstance(results, list):
        return (
            None,
            _upstream_failure(
                resp,
                detail=f"search response expected 'results' to be a list of objects, got {type(results).__name__}",
            ),
            resp,
        )
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            return (
                None,
                _upstream_failure(
                    resp,
                    detail=(
                        f"search response expected 'results' to be a list of objects, but item {index} "
                        f"was {type(result).__name__}"
                    ),
                ),
                resp,
            )
    return data, None, resp


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
        suggested_tool = tools_by_collection.get(clause.value.upper() if clause.value is not None else "")
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


def _validate_window_arguments(start_char: Any, max_chars: Any) -> dict[str, Any] | None:
    """Reject argument-only window errors before any upstream request."""
    if not isinstance(start_char, int) or isinstance(start_char, bool):
        return _invalid_argument(f"start_char must be an integer, got {start_char!r}")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool):
        return _invalid_argument(f"max_chars must be an integer, got {max_chars!r}")
    if start_char < 0:
        return _invalid_argument(f"start_char must be >= 0, got {start_char}")
    if max_chars <= 0:
        return _invalid_argument(
            f"max_chars must be at least 1, got {max_chars}. For a locating call that returns "
            "`structure` or `find`, pass `max_chars: 1`."
        )
    return None


def _past_end_failure(start_char: int, total_chars: int) -> dict[str, Any] | None:
    if start_char == 0 or start_char < total_chars:
        return None
    detail = f"no text exists at start_char={start_char}; the document was retrieved and has total_chars={total_chars}"
    if total_chars > 0:
        detail += " (the document is not empty)"
    return {"outcome": "invalid_argument", "detail": detail, "total_chars": total_chars}


# The two `get_us_code_section` disambiguation templates, contractual character for
# character (40-tools.md, "The `ambiguous` message names its reader"). Each names its
# reader first: what to tell the person asking, then — marked as such — what the tool
# caller does next. Every floor consumer measured on the old caller-only wording read a
# list of both same-citation provisions and presented one as the answer.
USCODE_COLLISION_MESSAGE = (
    "{n} DISTINCT PROVISIONS SHARE THIS CITATION — this is not a lookup failure and there is no single "
    "answer. Tell the person asking that {n} provisions match and name each by its title below; if you go "
    "on to read one or more of them, present each as a distinct provision by its title and say which you "
    "did not read. Do not present one as the only match. What follows is for the tool caller, not the "
    "person asking: to read a candidate, re-request with its `granule_id` (pass the same `citation` "
    "alongside it to keep the staleness check)."
)
USCODE_EDITIONS_MESSAGE = (
    "{n} EDITIONS OF THIS PROVISION MATCH. Tell the person asking which edition you are quoting; the "
    "current edition is {year} unless they asked for another. What follows is for the tool caller, not the "
    "person asking: re-request with `year` to choose an edition, or with a candidate's `granule_id`."
)
PLAW_RE_REQUEST = "The number did not resolve to one public law; treat the candidates' package_id values as findings."

# The three subsection-strip messages, contractual character for character (40-tools.md,
# "The strip message names its reader", WO-19). The stripped designator is counted as a
# literal inside the `statute` field's extent and, separately, inside the `notes`
# field's extent, the way `find` counts. Zero in the statute says the subsection does
# not exist and what to do with that; nonzero states a count and claims nothing about
# which occurrence is the subsection (F8's rule); an unlocated statute extent asserts
# nothing — nonexistence is never stated without the mechanical zero. The predecessor
# ("… navigate within it.") presumed there was something to navigate to; eleven of 111
# nano rows navigated to a guideline in the notes and returned it as 17 U.S.C. 107(b).
SUBSECTION_ZERO_MESSAGE = (
    "Subsection suffix '{designator}' was stripped and the whole containing section {citation} is returned. "
    "'{designator}' occurs 0 times in the statute text of {citation} — {citation}{designator} does not exist "
    "in this edition. Tell the person asking that the section has no subsection {designator}, and say what "
    "the section does contain. Do not answer with other text labelled '{designator}'. {notes_sentence} A "
    "request for a provision that does not exist is answered by saying so, not by quoting the nearest label. "
    "If you quote one of those passages, name its own source and say it is not {citation}{designator}. What "
    "follows is for the tool caller, not the person asking: structure lists the section's fields and find "
    "locates text within the returned payload."
)
SUBSECTION_ZERO_NOTES_SENTENCE = (
    "The notes under this section contain {n_notes} such labels, but those are other material, not "
    "{citation}{designator}."
)
SUBSECTION_ZERO_NO_NOTES_SENTENCE = "The notes under this section contain no such label either."
SUBSECTION_NONZERO_MESSAGE = (
    "Subsection suffix '{designator}' was stripped and the whole containing section {citation} is returned; "
    "'{designator}' occurs {n_statute} times in its statute text. What follows is for the tool caller, not "
    "the person asking: use find with '{designator}' to locate it within the returned payload."
)
SUBSECTION_NOT_CHECKED_MESSAGE = (
    "Subsection suffix '{designator}' was stripped and the whole containing section {citation} is returned; "
    "whether the section has a subsection {designator} was not checked. What follows is for the tool caller, "
    "not the person asking: use find with '{designator}' to locate it within the returned payload."
)


def _count_in_field(text: str, needle: str, structure: dict[str, Any], field: str) -> int | None:
    """Occurrences of `needle` inside the extent(s) of `field` per the derived
    `structure`, matched the way `find` matches; None when the structure is omitted
    or lists no such field, so the caller can say "not checked" rather than "0"."""
    if structure.get("omitted") or not isinstance(structure.get("fields"), list):
        return None
    spans = [f for f in structure["fields"] if f.get("field") == field]
    if not spans:
        return None
    return sum(len(occurrence_offsets(text[f["start_char"] : f["end_char"]], needle)) for f in spans)


def _subsection_strip_message(designator: str, citation: str, text: str, structure: dict[str, Any]) -> str:
    """Choose among the three strip messages from the counts (WO-19, R30)."""
    n_statute = _count_in_field(text, designator, structure, "statute")
    if n_statute is None:
        return SUBSECTION_NOT_CHECKED_MESSAGE.format(designator=designator, citation=citation)
    if n_statute > 0:
        return SUBSECTION_NONZERO_MESSAGE.format(designator=designator, citation=citation, n_statute=n_statute)
    n_notes = _count_in_field(text, designator, structure, "notes") or 0
    if n_notes:
        notes_sentence = SUBSECTION_ZERO_NOTES_SENTENCE.format(
            designator=designator, citation=citation, n_notes=n_notes
        )
    else:
        notes_sentence = SUBSECTION_ZERO_NO_NOTES_SENTENCE
    return SUBSECTION_ZERO_MESSAGE.format(designator=designator, citation=citation, notes_sentence=notes_sentence)


# The note-strip disclosure, contractual character for character (40-tools.md, "Notes
# carry law", WO-18). Its predecessor said the statutory notes were "included in the
# returned payload" — true, and read by six of six nano rows as license to open the
# one field headed "Codification" and report it as the notes to 42 U.S.C. 2210.
NOTE_STRIP_MESSAGE = (
    "Trailing 'note' was stripped: the containing section {citation} was resolved instead, and ALL of its "
    "notes are in the returned payload. Notes carry law, not only editorial history: fields headed 'Statutory "
    "Notes and Related Subsidiaries', 'Findings', short-title and effective-date notes are enacted provisions "
    "Congress placed under the section rather than in it; 'Codification', 'Amendments' and 'References in "
    "Text' are editorial. A question about the note or notes to a section is about that whole body — list it "
    "with `structure` (the `notes` field and its typed children, each with its heading) and search it with "
    "`find`. The 'Codification' note alone is one editorial note, not the notes."
)


def _edition_year(hit: dict[str, Any]) -> str | None:
    """The four-digit year leading a hit's `dateIssued`, or None when there is none."""
    date_issued = hit.get("dateIssued")
    if isinstance(date_issued, str) and len(date_issued) >= 4 and date_issued[:4].isdigit():
        return date_issued[:4]
    return None


def _uscode_ambiguous_message(count: Any, results: list[dict[str, Any]]) -> str:
    """Choose between the collision and editions templates by the candidates' edition
    years: all equal (a same-citation collision within one edition) → collision;
    otherwise (the same provision across editions) → editions, naming the newest year
    as the current one. `{n}` is the true upstream total, not the shown count."""
    years = {_edition_year(r) for r in results}
    if len(years) <= 1:
        return USCODE_COLLISION_MESSAGE.format(n=count)
    current = max(y for y in years if y is not None)
    return USCODE_EDITIONS_MESSAGE.format(n=count, year=current)


def _disambiguation_fields(count: Any, results: list[dict[str, Any]], message: str) -> dict[str, Any]:
    """Shared fields for an ambiguous outcome: the true total from the response's
    `count`, the shown candidates, and — stated, never implied — whether the list is
    capped, so 100 shown of 251 never reads as 100 of 100 (40-tools.md, O24). The
    caller supplies the message, which names the real re-request path for the tool
    (R16, O45c): never an input the tool does not accept."""
    shown = len(results)
    capped = isinstance(count, int) and count > shown
    if capped:
        message += f" The candidate list is capped at one search page: showing {shown} of {count}."
    return {
        "count": count,
        "candidates_shown": shown,
        "capped": capped,
        "message": message,
        "candidates": [_result_pointer(r) for r in results],
    }


def _year_filtered_disambiguation_fields(
    count_all_editions: Any,
    page_size: int,
    year: int,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """The ambiguous fields when `year` filtered the candidates (WO-17 C, O93c).

    `count` is the number of candidates after the year filter — upstream's `count`
    spans every edition (78 for the two 2024 `Rule 9`s) and is not the total of what
    the filter kept — and rides beside as `count_all_editions`. The filter runs over
    the one page fetched, so the list is capped exactly when that page was itself
    incomplete: then the filtered figure is a floor, not a total, and the capping
    sentence says so. On a complete page the filtered count is the true total and
    nothing is capped."""
    count = len(results)
    message = _uscode_ambiguous_message(count, results)
    capped = isinstance(count_all_editions, int) and count_all_editions > page_size
    if capped:
        message += (
            f" The candidate list is capped at one search page: showing {count} of at least {count} for {year} — "
            f"the year filter ran over the first page only, of {count_all_editions} candidates across all editions."
        )
    return {
        "count": count,
        "count_all_editions": count_all_editions,
        "candidates_shown": count,
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

    Ownership (WO-26 A): the detector's task belongs to the tool call that created
    it. The call wraps everything after construction in ``try/finally: await
    detector.close()``, so a call that ends early — a failure outcome, a shape
    error, or the caller's cancellation arriving at any await — cancels the query
    before it returns or re-raises, and a task created but not yet started never
    runs at all.
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
        # WO-15 C: the bound-error state belongs to one launch. A failure on a
        # remembered bound must not outlive the launch that follows on the
        # payload's own date, or `no_bound` would be served beside a sent query.
        self._bound_error = None
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
        self._task = asyncio.create_task(self._run(self.query, asyncio.current_task()))

    async def _run(self, query: str, owner: asyncio.Task[Any] | None) -> superseded.DetectorOutcome:
        # WO-26 A: a cancellation requested of the owning call is delivered at the
        # call's next step, and a task created just before takes its first step in
        # that gap. A query that would go out in the gap is one the call will never
        # read: refuse to send it rather than send-and-cancel.
        if owner is not None and owner.cancelling():
            raise asyncio.CancelledError
        return await superseded.run_detector(self._client, query)

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

    async def close(self) -> None:
        """The call that owns this detector is ending — by a result, an exception or
        the caller's cancellation (WO-26 A). Whatever query is still in flight is
        cancelled and awaited here, so nothing started for the call outlives it and
        no request is issued on its behalf afterwards. A no-op once `finish` has
        consumed the task, so every completed call's response is unchanged."""
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
                "'{title} U.S.C. {section}' form and the granule summary's usCodeCitation is null. "
                "Pass `citation` alongside `granule_id` to get the staleness check.",
                **common,
            )
        elif citation is None:
            out = superseded.not_checked(
                "no_measured_citation_form",
                "appendix rules and bare appendix citations have no measured uscodecitation form: "
                "0 hits for '28 U.S.C. App.' and '28 U.S.C. App. Rule 9'; only numbered appendix sections "
                "have one, so the detector was not run.",
                **common,
            )
        elif self.currentthrough is None or self._bound_error is not None:
            # WO-15 C: `no_bound` says no query was sent on this payload's bound, so
            # none may be in flight, and no query is echoed. A speculative query on a
            # remembered bound may have gone out before the search: it is cancelled
            # here and accounted for in-band, never silently discarded.
            await self._discard()
            out = superseded.not_checked(
                "no_bound",
                (self._bound_error or "currentthrough could not be parsed from the payload")
                + ", so the detector's publishdate bound could not be derived and the query was not sent.",
                query=None,
                since=None,
                currentthrough=self.currentthrough,
                checked_citation=citation,
            )
            if self._discarded_prediction is not None:
                payload_date = (
                    f"is {self.currentthrough!r}, which is not a valid date"
                    if self.currentthrough is not None
                    else "could not be parsed"
                )
                out["prediction_note"] = (
                    f"a speculative query bounded by a remembered currentthrough of {self._discarded_prediction} "
                    f"was issued before the citation search, then cancelled because this payload's currentthrough "
                    f"{payload_date}; no result from it is used."
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


def _citation_query(parsed: USCCitation) -> str:
    """The citation search: the one query that selects a citation's granules."""
    return f'collection:USCODE citation:"{parsed.normalized}"'


# WO-28 B: the by-id note. The served message inside `same_citation_candidates`,
# contractual character for character (WO-17 part B's shape), and the disclosure
# served when the family search itself failed — the lookup never fails for it.
SAME_CITATION_CANDIDATES_MESSAGE = (
    "This provision shares its citation with {n} other(s): {titles}. The person asking should be told."
)
SAME_CITATION_NOT_CHECKED_MESSAGE = (
    "Whether other provisions share this citation was not checked: the citation search failed, and its "
    "failure is in 'not_checked'. Do not present this as the only provision with this citation."
)
SAME_CITATION_EDITION_NOT_ON_PAGE_MESSAGE = (
    "Whether other provisions share this citation was not checked: the citation search returned no granule of "
    "this provision's edition ({package_id}), so its family could not be read from the page — the search covers "
    "the current edition, and this granule is from another. Do not present this as the only provision with this "
    "citation."
)

# An appendix rule's id, after dup-segment removal: `-app-` and a trailing `-rule{n}`
# segment (the measured grammar, O115). The group is the rule number the citation names.
_APPENDIX_RULE_ID_RE = re.compile(r"-app-.*-rule(?P<rule>\d+(?:\.\d+)?)\Z")


# WO-28 C (F20): the citation field's match is token-based — `citation:"28 U.S.C.
# App. Rule 4"` returns Rule 4.1 beside the three Rule 4s (O115c) — so on an
# appendix-rule citation the candidate list is the family only: hits whose id's rule
# segment equals the requested rule number exactly.
_APPENDIX_RULE_TEXT_RE = re.compile(r"^rule\s+(?P<rule>\S+)$", re.IGNORECASE)


def _requested_rule(parsed: USCCitation) -> str | None:
    """The rule number an appendix-rule citation names ("Rule 4.1" → "4.1"); None
    for a section, a numbered appendix section or a bare appendix citation."""
    if not parsed.appendix:
        return None
    m = _APPENDIX_RULE_TEXT_RE.match(parsed.appendix_text)
    return m.group("rule") if m else None


def _rule_of_id(granule_id: Any) -> str | None:
    if not isinstance(granule_id, str):
        return None
    m = _APPENDIX_RULE_ID_RE.search(normalized_granule_id(granule_id))
    return m.group("rule") if m else None


def _filter_to_rule_family(results: list[dict[str, Any]], rule: str) -> list[dict[str, Any]]:
    return [r for r in results if _rule_of_id(r.get("granuleId")) == rule]


def _rule_filtered_disambiguation_fields(
    count_unfiltered: Any, page_size: int, results: list[dict[str, Any]]
) -> dict[str, Any]:
    """The ambiguous fields when the rule filter ran (WO-28 C): `count` is the family
    on the page, upstream's token-match total rides beside as `count_unfiltered`,
    and the list is capped exactly when the page itself was incomplete."""
    count = len(results)
    message = _uscode_ambiguous_message(count, results)
    capped = isinstance(count_unfiltered, int) and count_unfiltered > page_size
    if capped:
        message += (
            f" The candidate list is capped at one search page: showing {count} of at least {count} — the rule "
            f"filter ran over the first page only, of {count_unfiltered} hits matching the citation's tokens."
        )
    return {
        "count": count,
        "count_unfiltered": count_unfiltered,
        "candidates_shown": count,
        "capped": capped,
        "message": message,
        "candidates": [_result_pointer(r) for r in results],
    }


def _appendix_rule_citation_from_id(granule_id: str, package_title: str) -> USCCitation | None:
    """`28 U.S.C. App. Rule 9` from `USCODE-2024-title28-app-federalru-dup1-rule9`;
    None for any id that is not an appendix rule's."""
    m = _APPENDIX_RULE_ID_RE.search(normalized_granule_id(granule_id))
    if m is None:
        return None
    return parse_usc(citation=f"{package_title} U.S.C. App. Rule {m.group('rule')}")


class _FamilySearch:
    """The citation search a by-id call runs for its same-citation family (WO-28 B),
    owned by the call the way the detector is: started before the summary fetch so
    it overlaps the two upstream round trips, awaited only once the lookup has
    succeeded, and closed — cancelled if still in flight — when the call ends by
    any path. The request is the resolution path's without a year (`historical`
    false): one edition per page (O93b), so the current edition's family is never
    beyond the page — `historical` true was measured to return 119 hits across
    editions for Rule 4 and cap at 100. An id from another edition finds no
    granule of its edition on the page, and that is disclosed, not read as a
    family of one."""

    def __init__(self, client: GovInfoClient, parsed: USCCitation | None) -> None:
        self._client = client
        self.query = _citation_query(parsed) if parsed is not None else None
        self._task: asyncio.Task[Any] | None = None

    def start(self) -> None:
        if self.query is None:
            return
        body = {"query": self.query, "pageSize": MAX_PAGE_SIZE, "offsetMark": "*", "historical": False}
        self._task = asyncio.create_task(self._run(body, asyncio.current_task()))

    async def _run(self, body: dict[str, Any], owner: asyncio.Task[Any] | None) -> Any:
        if owner is not None and owner.cancelling():
            raise asyncio.CancelledError
        return await _search(self._client, body)

    async def result(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """(data, None) or (None, failure); (None, None) when no search was started."""
        if self._task is None:
            return None, None
        task, self._task = self._task, None
        data, failure, _ = await task
        return data, failure

    async def close(self) -> None:
        if self._task is None:
            return
        task, self._task = self._task, None
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _same_citation_candidates(
    fetched_granule_id: str, query: str | None, data: dict[str, Any] | None, failure: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The `same_citation_candidates` object for a by-id success, or None for a
    family of one. Membership is normalized-id equality with the fetched granule,
    which also drops the dotted over-match (Rule 4.1 beside the Rule 4s)."""
    if failure is not None:
        return {"count": None, "others": None, "not_checked": failure, "message": SAME_CITATION_NOT_CHECKED_MESSAGE}
    if data is None:
        return None
    ids = [hit["granuleId"] for hit in data["results"] if isinstance(hit.get("granuleId"), str)]
    package_match = _USCODE_GRANULE_ID_RE.match(fetched_granule_id)
    edition_prefix = package_match.group("package") + "-" if package_match else None
    if edition_prefix is not None and not any(i.startswith(edition_prefix) for i in ids):
        package_id = edition_prefix[:-1]
        return {
            "count": None,
            "others": None,
            "not_checked": {
                "reason": "edition_not_on_page",
                "detail": (
                    f"the citation search returned {len(ids)} granule(s), none from {package_id}; "
                    "the page covers the current edition only."
                ),
                "query": query,
            },
            "message": SAME_CITATION_EDITION_NOT_ON_PAGE_MESSAGE.format(package_id=package_id),
        }
    family_key = normalized_granule_id(fetched_granule_id)
    others = [
        {"granule_id": hit.get("granuleId"), "title": hit.get("title")}
        for hit in data["results"]
        if isinstance(hit.get("granuleId"), str)
        and hit["granuleId"] != fetched_granule_id
        and normalized_granule_id(hit["granuleId"]) == family_key
    ]
    if not others:
        return None
    message = SAME_CITATION_CANDIDATES_MESSAGE.format(n=len(others), titles="; ".join(str(o["title"]) for o in others))
    size = len(others) + 1
    out: dict[str, Any] = {"count": size, "others": others, "message": message}
    shown = len(data["results"])
    count = data.get("count")
    if isinstance(count, int) and count > shown:
        out["capped"] = True
        out["message"] += (
            f" The citation search page was capped at {shown} of {count} hits, so a family member beyond it "
            f"is not seen: {size} is a floor, showing {size} of at least that many."
        )
    return out


def _insert_after(out: dict[str, Any], after: str, key: str, value: Any) -> dict[str, Any]:
    """The same mapping with `key` placed right after `after` (a new dict)."""
    rebuilt: dict[str, Any] = {}
    for k, v in out.items():
        rebuilt[k] = v
        if k == after:
            rebuilt[key] = value
    if key not in rebuilt:
        rebuilt[key] = value
    return rebuilt


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
    query = _citation_query(parsed)
    body = {
        "query": query,
        "pageSize": MAX_PAGE_SIZE,
        "offsetMark": "*",
        "historical": year is not None,
    }
    data, failure, search_resp = await _search(client, body)
    if failure is not None:
        return None, None, None, failure
    assert data is not None and search_resp is not None
    page = data["results"] or []
    results = page
    if year is not None:
        results = [r for r in page if str(r.get("dateIssued", "")).startswith(str(year))]
    requested_rule = _requested_rule(parsed)
    rule_filtered = False
    if requested_rule is not None:
        before = results
        results = _filter_to_rule_family(results, requested_rule)
        # The rule-filtered fields are served when the filter changed the list or
        # the page was incomplete (the filtered figure is then a floor); otherwise
        # the envelope is the one served before this filter existed.
        count = data.get("count")
        rule_filtered = len(results) != len(before) or (isinstance(count, int) and count > len(page))

    if not results:
        if parsed.appendix:
            terms = f' "{parsed.appendix_text}"' if parsed.appendix_text else ""
            return (
                None,
                None,
                None,
                {
                    "outcome": "appendix_redirect",
                    "citation": parsed.normalized,
                    "query": query,
                    "year": year,
                    "message": (
                        "The appendix citation resolved to zero granules — real for appendix material that no "
                        "longer exists in the current edition (e.g. the eliminated title 50 Appendix). "
                        "Appendix granules are full-text indexed, so retry with search_us_code and the "
                        "suggested query."
                    ),
                    "suggested_tool": "search_us_code",
                    "suggested_query": f"collection:USCODE usctitlenum:{parsed.title}{terms}",
                },
            )
        if parsed.stripped_subsection:
            normalization = _normalization_block(
                parsed,
                subsection_message=(
                    f"Subsection suffix '{parsed.stripped_subsection}' was stripped and the containing section "
                    f"{parsed.normalized} was looked up instead; it resolved to zero granules, so nothing was "
                    "returned or counted."
                ),
            )
        return (
            None,
            None,
            None,
            {
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
            },
        )
    if len(results) > 1:
        if year is not None:
            fields = _year_filtered_disambiguation_fields(data.get("count"), len(page), year, results)
        elif rule_filtered:
            fields = _rule_filtered_disambiguation_fields(data.get("count"), len(page), results)
        else:
            fields = _disambiguation_fields(
                data.get("count"), results, _uscode_ambiguous_message(data.get("count"), results)
            )
        return (
            None,
            None,
            None,
            {
                "outcome": "ambiguous",
                "normalized_citation": parsed.normalized,
                "query": query,
                "year": year,
                **fields,
            },
        )

    hit = results[0]
    raw_download = hit.get("download")
    if raw_download is not None and not isinstance(raw_download, dict):
        return (
            None,
            None,
            None,
            _upstream_failure(
                search_resp,
                detail=f"search result expected 'download' to be an object, got {type(raw_download).__name__}",
            ),
        )
    download = raw_download or {}
    txt_link = download.get("txtLink")
    if txt_link is not None and not isinstance(txt_link, str):
        return (
            None,
            None,
            None,
            _upstream_failure(
                search_resp,
                detail=f"search result expected 'download.txtLink' to be a string, got {type(txt_link).__name__}",
            ),
        )
    if not txt_link:
        return (
            None,
            None,
            None,
            {
                "outcome": "upstream_error",
                "http_status": None,
                "detail": (
                    "search result carried no txtLink in its download map (response-shape drift; failing loudly "
                    "per spec rather than constructing a URL)"
                ),
                "result": _result_pointer(hit),
            },
        )

    return hit, download, txt_link, None


# The accepted granule id grammar (40-tools.md "By-id behavior", WO-15 B, widened by
# WO-29 A from F21/O116): the leading USCODE-{year}-title{n} segments, then one or
# more hyphen-separated segments of letters and digits, in which a dot or an
# underscore may appear inside the segment but never lead it, never repeat and
# never sit beside a hyphen. The corpus has both — dotted appendix rules
# (`…-dup1-rule4.1`) and second sections of a number (`…-sec1932_2`), 52 of 19,947
# ids across eight 2024 titles — and the server hands those ids out in search
# results and candidate lists, so it must take them back. A character class, not a
# parse — nothing beyond the leading segments is interpreted. Anything else (a
# slash, `..`, a leading dot, a query character or whitespace included) is refused
# before any request, so no id can reach the summary URL (S26 finding 2: `/../`
# did, and its 404 read as "no package").
_USCODE_GRANULE_ID_RE = re.compile(
    r"^(?P<package>USCODE-(?P<year>\d{4})-title(?P<title>\d+[a-z]?))(?:-[A-Za-z0-9]+(?:[._][A-Za-z0-9]+)*)+\Z"
)
_USCODE_PACKAGE_ID_RE = re.compile(r"^USCODE-\d{4}-title(?P<title>\d+[a-z]?)\Z")


def _normalization_block(
    parsed: USCCitation, *, citation_basis: str = "resolved", subsection_message: str | None = None
) -> dict[str, Any]:
    """The normalization disclosure. On a success the subsection-strip message is one
    of the three counted messages (WO-19), computed once the text and structure are in
    hand and passed in. A `not_found` supplies its own disclosure (WO-20); before
    resolution, the pre-WO-19 wording stands."""
    normalization: dict[str, Any] = {
        "normalized_citation": parsed.normalized,
        "citation_basis": citation_basis,
        "stripped_subsection": parsed.stripped_subsection,
        "stripped_note": parsed.stripped_note,
    }
    notes: list[str] = []
    if parsed.stripped_subsection:
        notes.append(
            subsection_message
            or f"Subsection suffix {parsed.stripped_subsection!r} was stripped: the granule is the retrieval "
            f"unit, so the whole containing section {parsed.normalized} is returned; navigate within it."
        )
    if parsed.stripped_note:
        notes.append(NOTE_STRIP_MESSAGE.format(citation=parsed.normalized))
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
    if parsed is not None and parsed.stripped_subsection and "normalization" in head:
        # WO-19: the strip message is chosen by counting the designator inside the
        # statute and notes extents of the section actually returned. The derived
        # structure is used even on a reading call, where the served block is omitted.
        head["normalization"] = _normalization_block(
            parsed,
            citation_basis=head["normalization"]["citation_basis"],
            subsection_message=_subsection_strip_message(
                parsed.stripped_subsection, parsed.normalized, text, structure
            ),
        )
    past_end = _past_end_failure(start_char, len(text))
    if past_end is not None:
        return past_end
    if start_char:
        # R13a: the block is invariant per (section, year); a reading call has no use
        # for it and paid ~15x a small window to carry it (O38).
        structure = structure_omitted_for_reading_call(start_char)
    try:
        window = window_text(text, start_char=start_char, max_chars=max_chars)
    except ValueError as exc:
        return _invalid_argument(str(exc))
    add_audience_sentence(window, provenance["public_pdf_link"], provenance["details_link"])

    # The text is ready: wait the bounded budget for the detector, never longer.
    stripped_note = parsed.stripped_note if parsed is not None else False
    possibly_superseded = await detector.finish(stripped_note=stripped_note)
    if head.get("normalization", {}).get("citation_basis") == "caller_supplied":
        possibly_superseded["citation_statement"] = (
            "This check ran on the citation the caller supplied. The server did not verify that citation "
            "names this granule; if it does not, this result is about a different section."
        )

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
    # The grammar is matched against the id as given: surrounding whitespace is a
    # character outside the class, not a tolerance (a blank id was already routed
    # to the citation path by the caller).
    m = _USCODE_GRANULE_ID_RE.match(granule_id)
    if not m:
        return _invalid_argument(
            f"granule_id {granule_id!r} is not a USCODE granule id; nothing was fetched. Expected "
            "USCODE-{year}-title{n} followed by hyphen-separated segments of letters and digits (a dot or an "
            "underscore may appear inside a segment, never leading or repeated), exactly as a disambiguation "
            "list or search_us_code result carried it."
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

    package_match = _USCODE_PACKAGE_ID_RE.match(package_id)
    assert package_match is not None
    package_title = package_match.group("title")
    if parsed is not None and parsed.title.casefold() != package_title.casefold():
        return _invalid_argument(
            f"citation title {parsed.title!r} does not match package title {package_title!r}; nothing was fetched"
        )

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
        head["normalization"] = _normalization_block(parsed, citation_basis="caller_supplied")
    if year is not None:
        head["warnings"] = [
            f"year={year} was ignored: granule_id names its edition (USCODE-{m.group('year')}-...). "
            "Omit granule_id to select an edition by year."
        ]

    # The id names its edition, so the detector can predict its bound from the
    # remembered currentthrough of that edition year (verified after the fetch).
    detector = _Detector(client, parsed, int(m.group("year")))
    # WO-28 B: the family search runs on the caller's citation, or — without one —
    # on the citation an appendix-rule id names; on any other id there is none.
    family = _FamilySearch(
        client, parsed if parsed is not None else _appendix_rule_citation_from_id(granule_id, package_title)
    )
    try:
        detector.start_early()
        family.start()
        out = await _deliver_by_id(client, detector, parsed, granule_id, package_id, head, max_chars, start_char, find)
        if out.get("outcome") != "success":
            return out
        candidates = _same_citation_candidates(
            out["provenance"]["granule_id"] or granule_id, family.query, *await family.result()
        )
        if candidates is None:
            return out
        return _insert_after(out, "possibly_superseded", "same_citation_candidates", candidates)
    finally:
        await family.close()
        await detector.close()


async def _deliver_by_id(
    client: GovInfoClient,
    detector: _Detector,
    parsed: USCCitation | None,
    granule_id: str,
    package_id: str,
    head: dict[str, Any],
    max_chars: int,
    start_char: int,
    find: str | None,
) -> dict[str, Any]:
    """The by-id path's upstream work, run inside the detector's ownership scope."""
    try:
        summary_resp = await client.granule_summary(package_id, granule_id)
    except GovInfoTransportError as exc:
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
            **relay_body(summary_resp.text, NOT_FOUND_BODY_BOUND),
            "message": (
                f"GovInfo has {what}. This is 'not found', not an upstream failure. Check the id against a "
                "disambiguation list or search_us_code result; if package_id was derived, pass it explicitly."
            ),
        }
    failure = _classify(summary_resp)
    if failure is not None:
        return failure
    try:
        summary = summary_resp.json()
    except ValueError:
        return _upstream_failure(summary_resp, detail="granule summary was not valid JSON")
    if not isinstance(summary, dict):
        return _upstream_failure(
            summary_resp, detail=f"granule summary expected a JSON object, got {type(summary).__name__}"
        )
    raw_download = summary.get("download")
    if raw_download is not None and not isinstance(raw_download, dict):
        return _upstream_failure(
            summary_resp,
            detail=f"granule summary expected 'download' to be an object, got {type(raw_download).__name__}",
        )
    download = raw_download or {}
    txt_link = download.get("txtLink")
    if txt_link is not None and not isinstance(txt_link, str):
        return _upstream_failure(
            summary_resp,
            detail=f"granule summary expected 'download.txtLink' to be a string, got {type(txt_link).__name__}",
        )
    if not txt_link:
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
        client,
        detector,
        parsed,
        hit,
        download,
        txt_link,
        max_chars,
        start_char,
        find,
        head,
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
    bad_window = _validate_window_arguments(start_char, max_chars)
    if bad_window is not None:
        return bad_window
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
            client,
            granule_id,
            package_id,
            parsed,
            year,
            max_chars,
            start_char,
            find,
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
    try:
        detector.start_early()
        hit, download, txt_link, early = await _resolve_granule(client, parsed, year, normalization)
        if early is not None:
            return early
        assert hit is not None and download is not None and txt_link is not None
        head = {"citation": parsed.normalized, "normalization": normalization}
        return await _fetch_and_deliver(
            client,
            detector,
            parsed,
            hit,
            download,
            txt_link,
            max_chars,
            start_char,
            find,
            head,
        )
    finally:
        # WO-26 A: whatever ended the call, nothing started for it keeps running.
        await detector.close()


# ---------------------------------------------------------------------------
# search_us_code / search_public_laws
# ---------------------------------------------------------------------------


# Result order (40-tools.md): upstream's default order is string-descending by
# granule id, not relevance, so every request the two search tools send asks for
# score order. The queries the server builds itself (citation resolution, the
# staleness detector) select by citation and do not carry it.
RELEVANCE_SORTS: list[dict[str, str]] = [{"field": "score", "sortOrder": "DESC"}]

# The two empty-page messages. A first page with no hits is a search that found
# nothing. A continuation page — any `offset_mark` but "*" — with no hits is the walk
# reaching the end of a result set whose hits were all served already, and upstream's
# `count` on it is its value for a page past the end (0 in both orders, O112), not the
# set's size; the past-the-end sentence is contractual character for character
# (40-tools.md, "A page past the end is not zero results", WO-27). Without it, a walk
# of `bank notes as collateral` ended by saying "found nothing" after 134 hits (F19).
ZERO_RESULTS_MESSAGE = (
    "Zero results. The search itself succeeded — this is 'found nothing', not a failure; "
    "the exact query sent upstream is in 'query'."
)
PAST_END_MESSAGE = (
    "No more results: this continuation page is past the end of the result set. The search itself succeeded; "
    "'count' on this page is upstream's value for a page past the end, not the size of the result set, which "
    "the first page reported."
)


# Same-citation families (40-tools.md, "Same-citation families are read from ids";
# R34a, WO-28; measured E40/O115). Two granules share a citation within an edition
# exactly when their ids are equal once every `dup{N}` segment is removed:
# `…-app-federalru-rule9` and `…-app-federalru-dup1-rule9` are one family;
# `…-dup1-rule8-dup1` is a third member of Rule 8's. The segment marks a repeated
# rule set inside the appendix, not a collision by itself (145 of its 211 ids are
# singletons), so the family is the equality, never the segment. A comparison of
# ids the server already holds: no upstream request.
_DUP_SEGMENT_RE = re.compile(r"-dup\d+(?=-|$)")
# Section bodies carry their own marker (WO-29 B; F21, O116e): a second section of
# the same number has the suffix `_2` on its last segment — `…-chap123-sec1932_2`
# beside `…-sec1932`, a two-granule citation family under `citation:` in 3 of 3.
_SECOND_SECTION_RE = re.compile(r"_\d+\Z")

# The search-hit note, contractual character for character. The measured failure
# shape it answers: both Rule 9 titles on one page, one fetched by id and presented
# as the only provision — 4 of 5 gpt-oss rows at O107.
SAME_CITATION_ON_PAGE_NOTE = (
    "This provision shares its citation with {n} other result(s) on this page: {titles}. The person asking "
    "should be told which is meant, or shown each as a distinct provision."
)


def normalized_granule_id(granule_id: str) -> str:
    """The id with a trailing `_{N}` removed from its last segment and every
    `-dup{N}` segment removed: equal for every member of a same-citation family
    within an edition and for nothing else."""
    return _DUP_SEGMENT_RE.sub("", _SECOND_SECTION_RE.sub("", granule_id))


def _annotate_same_citation_on_page(pointers: list[dict[str, Any]]) -> None:
    """Mark every hit whose family has another member on this page (WO-28 A). A
    family member not on the page is not seen; hits without a granule id are left
    alone. `others` follow page order."""
    families: dict[str, list[dict[str, Any]]] = {}
    for pointer in pointers:
        granule_id = pointer.get("granule_id")
        if isinstance(granule_id, str) and granule_id:
            families.setdefault(normalized_granule_id(granule_id), []).append(pointer)
    for members in families.values():
        if len(members) < 2:
            continue
        for pointer in members:
            others = [{"granule_id": m["granule_id"], "title": m["title"]} for m in members if m is not pointer]
            pointer["same_citation_on_page"] = {"count": len(members), "others": others}
            pointer["note"] = SAME_CITATION_ON_PAGE_NOTE.format(
                n=len(others), titles="; ".join(str(o["title"]) for o in others)
            )


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
    offset_mark = offset_mark or "*"
    body = {
        "query": query,
        "pageSize": effective_page_size,
        "offsetMark": offset_mark,
        "historical": bool(historical),
        "sorts": [dict(sort) for sort in RELEVANCE_SORTS],
    }
    data, failure, _ = await _search(client, body)
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
    if collection == "USCODE":
        _annotate_same_citation_on_page(out["results"])
    if effective_page_size != page_size:
        out["page_size_note"] = f"page_size {page_size} was clamped to {effective_page_size} (allowed range 1-100)."
    if not results:
        out["message"] = PAST_END_MESSAGE if offset_mark != "*" else ZERO_RESULTS_MESSAGE
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
    "The uscodecitation field's recall gap is measured and structural: 25/33 sampled "
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
        if "uscodecitation:" in result.get("query", "").casefold():
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
    bad_window = _validate_window_arguments(start_char, max_chars)
    if bad_window is not None:
        return bad_window
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
                    "Private laws are out of scope for this server: this is a scope boundary, not a "
                    "failed lookup. Only public laws are served."
                ),
            }
        congress, law_number = parsed.congress, parsed.number
    elif congress is None or law_number is None:
        return _invalid_argument("provide 'citation', or both 'congress' and 'law_number'")

    query = f"collection:PLAW lawtype:public congress:{congress} docnumber:{law_number}"
    body = {"query": query, "pageSize": MAX_PAGE_SIZE, "offsetMark": "*"}
    data, failure, search_resp = await _search(client, body)
    if failure is not None:
        return failure
    assert data is not None and search_resp is not None
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
            **_disambiguation_fields(
                data.get("count"),
                results,
                f"Multiple matches ({data.get('count')} total); not guessing. {PLAW_RE_REQUEST}",
            ),
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
        return _upstream_failure(
            search_resp,
            detail=(
                f"public-law resolution expected packageId {expected_package_id!r}, "
                f"but the search result carried {package_id!r}"
            ),
        )

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
    if not isinstance(summary, dict):
        return _upstream_failure(
            summary_resp, detail=f"package summary expected a JSON object, got {type(summary).__name__}"
        )
    raw_download = summary.get("download")
    if raw_download is not None and not isinstance(raw_download, dict):
        return _upstream_failure(
            summary_resp,
            detail=f"package summary expected 'download' to be an object, got {type(raw_download).__name__}",
        )
    download = raw_download or {}

    if format == "uslm":
        link = download.get("uslmLink")
        if link is not None and not isinstance(link, str):
            return _upstream_failure(
                summary_resp,
                detail=f"package summary expected 'download.uslmLink' to be a string, got {type(link).__name__}",
            )
        if not link:
            return {
                "outcome": "format_not_available",
                "format": "uslm",
                "package_id": package_id,
                "available_formats": sorted(download.keys()),
                "message": (
                    "This package offers no uslmLink. USLM has a measured boundary in the PLAW collection "
                    "— absent for congresses 104-112, present from the 113th (2013) on — so absence is "
                    "an expected, reportable outcome for early congresses, not an error. Retry with "
                    "format='text' or use one of the available formats' links."
                ),
            }
        content_is_html = False
        source_field = "uslmLink"
    else:
        link = download.get("txtLink")
        if link is not None and not isinstance(link, str):
            return _upstream_failure(
                summary_resp,
                detail=f"package summary expected 'download.txtLink' to be a string, got {type(link).__name__}",
            )
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

    past_end = _past_end_failure(start_char, len(content))
    if past_end is not None:
        return past_end

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
