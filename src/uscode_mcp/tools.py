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
- No silent truncation: max_chars/start_char windows with explicit markers.
- Locating content in large payloads (R12): an optional `find` on both text tools,
  and a marker-derived `structure` block on get_us_code_section successes.
- Links are data: download URLs come from search results and summaries verbatim.
- Response-shape drift fails loudly (the search service is a public preview), never
  coerced into a guess.
"""

from __future__ import annotations

import re
from typing import Any

from .citations import CitationParseError, parse_public_law, parse_usc
from .govinfo import GovInfoClient, GovInfoTransportError, UpstreamResponse
from .htmltext import (
    edition_year_from_package_id,
    extract_currentthrough,
    find_occurrences,
    html_to_text_with_structure,
    window_text,
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
DEFAULT_MAX_CHARS = 100_000

_COLLECTION_TERM_RE = re.compile(r"\bcollection:", re.IGNORECASE)


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


async def _fetch(client: GovInfoClient, url: str) -> tuple[UpstreamResponse | None, dict[str, Any] | None]:
    """Fetch a download link verbatim. Returns (response, None) or (None, failure_outcome)."""
    try:
        resp = await client.fetch(url)
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


def _reject_blank_find(find: str | None) -> dict[str, Any] | None:
    """R12a takes a literal substring; an empty or whitespace-only one is a caller
    error, not a search that matches everywhere. Rejected before any upstream call."""
    if find is not None and not find.strip():
        return _invalid_argument(
            "find must be a non-empty literal substring (whitespace-only would match "
            "throughout the payload and locate nothing); omit it to skip locating."
        )
    return None


def _disambiguation_fields(count: Any, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Shared fields for an ambiguous outcome: the true total from the response's
    `count`, the shown candidates, and — stated, never implied — whether the list is
    capped, so 100 shown of 251 never reads as 100 of 100 (40-tools.md, O24)."""
    shown = len(results)
    capped = isinstance(count, int) and count > shown
    message = f"Multiple matches ({count} total); not guessing. Pick one and re-request by ids or year."
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
# get_us_code_section
# ---------------------------------------------------------------------------


async def get_us_code_section(
    client: GovInfoClient,
    citation: str | None = None,
    title: str | None = None,
    section: str | None = None,
    year: int | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    start_char: int = 0,
    find: str | None = None,
) -> dict[str, Any]:
    """Resolve a US Code citation and return the section's text, notes included."""
    bad_find = _reject_blank_find(find)
    if bad_find is not None:
        return bad_find
    try:
        parsed = parse_usc(citation=citation, title=title, section=section)
    except CitationParseError as exc:
        return _invalid_argument(str(exc))

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

    query = f'collection:USCODE citation:"{parsed.normalized}"'
    body = {
        "query": query,
        "pageSize": MAX_PAGE_SIZE,
        "offsetMark": "*",
        "historical": year is not None,
    }
    data, failure = await _search(client, body)
    if failure is not None:
        return failure
    assert data is not None
    results = data["results"] or []
    if year is not None:
        results = [r for r in results if str(r.get("dateIssued", "")).startswith(str(year))]

    if not results:
        if parsed.appendix:
            terms = f' "{parsed.appendix_text}"' if parsed.appendix_text else ""
            return {
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
        return {
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
        return {
            "outcome": "ambiguous",
            "normalized_citation": parsed.normalized,
            "query": query,
            "year": year,
            **_disambiguation_fields(data.get("count"), results),
        }

    hit = results[0]
    download = hit.get("download") or {}
    txt_link = download.get("txtLink")
    if not txt_link:
        return {
            "outcome": "upstream_error",
            "http_status": None,
            "detail": (
                "search result carried no txtLink in its download map (response-shape drift; failing loudly "
                "per spec rather than constructing a URL)"
            ),
            "result": _result_pointer(hit),
        }

    resp, failure = await _fetch(client, txt_link)
    if failure is not None:
        return failure
    assert resp is not None
    html = resp.text

    currentthrough = extract_currentthrough(html)
    package_id = hit.get("packageId")
    provenance: dict[str, Any] = {
        "package_id": package_id,
        "granule_id": hit.get("granuleId"),
        "edition_year": edition_year_from_package_id(package_id),
        "currentthrough": currentthrough,
        "last_modified": hit.get("lastModified"),
        "pdf_link": download.get("pdfLink"),
    }
    if currentthrough is None:
        provenance["currentthrough_note"] = (
            "currentthrough could not be parsed from the payload; staleness relative to enactment is unknown."
        )

    text, structure = html_to_text_with_structure(html)
    try:
        window = window_text(text, start_char=start_char, max_chars=max_chars)
    except ValueError as exc:
        return _invalid_argument(str(exc))

    out: dict[str, Any] = {
        "outcome": "success",
        "citation": parsed.normalized,
        "normalization": normalization,
        "provenance": provenance,
        "structure": structure,
        "text": window,
    }
    if find is not None:
        out["find"] = find_occurrences(text, find)
    return out


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
    if not _COLLECTION_TERM_RE.search(query):
        query = f"collection:{collection} {query}"

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


async def search_public_laws(
    client: GovInfoClient,
    query: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    offset_mark: str = "*",
) -> dict[str, Any]:
    """As search_us_code but scoped collection:PLAW (public laws only, R6)."""
    result = await _scoped_search(client, "PLAW", query, page_size=page_size, offset_mark=offset_mark)
    if result.get("outcome") == "success" and "uscodecitation:" in result.get("query", ""):
        result["recall_caveat"] = (
            "The uscodecitation field's recall gap is measured and structural (O21, O17/O18): 25/33 sampled "
            "recall against packages' own references arrays, with misses in every congress sampled from the "
            "115th on, varying per (law, section). Absence of a law from these results is never evidence it "
            "doesn't touch the section; this result set must not be presented as complete."
        )
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

    query = f"collection:PLAW congress:{congress} docnumber:{law_number}"
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
            **_disambiguation_fields(data.get("count"), results),
        }

    package_id = results[0].get("packageId")
    if not package_id:
        return {
            "outcome": "upstream_error",
            "http_status": None,
            "detail": "search result carried no packageId (response-shape drift; failing loudly per spec)",
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

    resp, failure = await _fetch(client, link)
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

    out: dict[str, Any] = {
        "outcome": "success",
        "congress": congress,
        "law_number": law_number,
        "format": format,
        "provenance": {
            "package_id": package_id,
            "date_issued": summary.get("dateIssued"),
            "last_modified": summary.get("lastModified"),
            "pdf_link": download.get("pdfLink"),
        },
        "text": window,
    }
    if find is not None:
        out["find"] = find_occurrences(content, find)
    return out
