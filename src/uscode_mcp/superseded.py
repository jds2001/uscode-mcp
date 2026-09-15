"""The `possibly_superseded` staleness indicator on get_us_code_section (R14, WO-1).

Contract (documentation/40-tools.md, "Staleness indicator"; 80-work-orders.md, WO-1):

- One detector query against the PLAW collection, bounded by the returned
  edition's own ``currentthrough`` plus one day (WO-2 shape)::

      collection:PLAW lawtype:public publishdate:range({since},) uscodecitation:"{title} U.S.C. {section}"

  ``publishdate``, never ``approveddate`` — ``approveddate`` ranges return HTTP 500
  upstream in every form tried (O43f). No hard-coded congress or date.
  ``lawtype:public`` because a live section was measured firing on a private law
  (O44e) whose package get_public_law refuses under R6, and because a private
  law's citation is by construction a named-party waiver, never an amendment
  (O44f). The filter is in the query, never applied client-side, so ``count``
  stays upstream's count for the query actually sent. Numbered appendix sections
  use the measured ``"{title} U.S.C. App. {section}"`` form (O44d); appendix rules
  have no measured form and are ``not_checked``.
- Three states on a ``status`` discriminator, never two: ``laws_indexed``,
  ``none_indexed``, ``not_checked``. A detector failure of any kind is
  ``not_checked`` with the failure surfaced verbatim; it is never collapsed into
  ``none_indexed`` and never fails the lookup.
- Every state echoes the exact ``query`` sent and the ``since`` bound.
- An indicator in both directions, never a certification (R14a): a fire says a
  later law is indexed against the section, not that the text is stale; silence
  says nothing about currency, because the index misses about one in seven listed
  (law, section) pairs (O43b) and one in four in an earlier sample (O21).

Concurrency (the "since depends on the payload" problem). The bound is parsed from
the granule HTML, so on the first lookup of an edition the detector cannot start
until the text fetch returns; it is then issued concurrently with the local
HTML-to-text work. Once an edition's ``currentthrough`` has been observed in this
process it is remembered per edition year, and later lookups of that edition issue
the detector on that predicted bound before the citation search, overlapping both
upstream round trips. The prediction is verified against the fetched payload's own
``currentthrough`` before the result is used: a mismatch discards the speculative
result and re-runs the detector on the exact bound. Nothing else is cached — in particular no detector
result is reused across lookups, so two editions of one section always get their
own bounded query.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta
from typing import Any

from .govinfo import GovInfoClient, GovInfoTransportError, UpstreamResponse

# The laws[] list is capped at one search page of this size; the true upstream
# count is always carried, and capping is stated whenever it happened.
LAWS_CAP = 20

# Wall-clock budget, in seconds, that a lookup waits for the detector *after the
# section text is ready*. Fresh-connection detector round trips measured 406 ms to
# 1,026 ms with a p95 of 607 ms (O43e); this bounds a pathological wait at roughly
# twice the worst measured case without turning ordinary latency into `timeout`.
DETECTOR_BUDGET_SECONDS = 2.0

STATUS_LAWS_INDEXED = "laws_indexed"
STATUS_NONE_INDEXED = "none_indexed"
STATUS_NOT_CHECKED = "not_checked"

# Pinned verbatim in documentation/40-tools.md (R14a addendum, O44f/O44g); the
# unit test compares it literally so any drift fails loudly.
CAVEAT_LAWS_INDEXED = (
    "INDICATOR ONLY — NOT A FINDING THAT THE TEXT CHANGED. A listed law MENTIONS this section; that is "
    "all the index records. It may amend the section, amend something else and merely cite this one, "
    "waive it for a named party, or not yet be in effect. The verification set's own example: Public "
    "Law 119-74 is listed against 42 U.S.C. 2210 because one appropriations rider cites it in a "
    "parenthetical, and it amends nothing in the section. This server does not read enacting laws. "
    "YOU MUST READ THE LISTED LAW TO FIND OUT — get_public_law with its package_id, then search its "
    "text for this section. The list may also be incomplete: the index misses about one in seven "
    "listed (law, section) pairs."
)

CAVEAT_NONE_INDEXED = (
    "THIS IS NOT A CURRENCY CHECK. No public law published after this edition's currentthrough date is "
    "indexed against this section in GovInfo's uscodecitation field — but absence of a match is not "
    "evidence the text is current: the index misses about one in seven listed (law, section) pairs "
    "(O43b) and one in four in an earlier sample (O21). A law that amended this section may exist and "
    "simply not be indexed against it."
)

CAVEAT_NOT_CHECKED = (
    "The staleness check could not be completed, so this response says NOTHING either way about "
    "whether later public laws touch this section. It is not a 'none found' result. The failure is "
    "surfaced below verbatim; search_public_laws with the echoed query retries it by hand."
)


def since_from_currentthrough(currentthrough: str) -> str:
    """The detector's lower bound: ``currentthrough`` (ISO ``YYYY-MM-DD``) plus one day."""
    return (date.fromisoformat(currentthrough) + timedelta(days=1)).isoformat()


def build_query(checked_citation: str, since: str) -> str:
    """The exact detector query pinned by WO-2: the measured O43c/O43d/O43f form plus
    ``lawtype:public`` (O44e). ``checked_citation`` is ``"{title} U.S.C. {section}"``
    or, for a numbered appendix section, ``"{title} U.S.C. App. {section}"`` (O44d)."""
    return f'collection:PLAW lawtype:public publishdate:range({since},) uscodecitation:"{checked_citation}"'


def _law_pointer(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_id": hit.get("packageId"),
        "title": hit.get("title"),
        "date_issued": hit.get("dateIssued"),
    }


class DetectorOutcome:
    """The raw result of one detector round trip, before it is rendered into the
    response object. Exactly one of ``response``/``error_reason`` is meaningful."""

    __slots__ = ("response", "error_reason", "error_detail", "elapsed_ms")

    def __init__(
        self,
        response: UpstreamResponse | None = None,
        error_reason: str | None = None,
        error_detail: str | None = None,
        elapsed_ms: float | None = None,
    ) -> None:
        self.response = response
        self.error_reason = error_reason
        self.error_detail = error_detail
        self.elapsed_ms = elapsed_ms


async def run_detector(client: GovInfoClient, query: str) -> DetectorOutcome:
    """One POST /search for the detector. Never raises: a transport failure or any
    unexpected exception becomes an outcome, because a detector failure of any kind
    must never fail the lookup."""
    started = time.perf_counter()
    body = {"query": query, "pageSize": LAWS_CAP, "offsetMark": "*"}
    try:
        resp = await client.search(body)
    except GovInfoTransportError as exc:
        return DetectorOutcome(
            error_reason="transport_error",
            error_detail=f"no HTTP response received from GovInfo: {exc}",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — the lookup must survive anything the detector does
        return DetectorOutcome(
            error_reason="internal_error",
            error_detail=f"{type(exc).__name__}: {exc}",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    return DetectorOutcome(response=resp, elapsed_ms=(time.perf_counter() - started) * 1000)


def _base(
    query: str | None, since: str | None, currentthrough: str | None, checked_citation: str | None
) -> dict[str, Any]:
    return {
        "status": None,
        "checked_citation": checked_citation,
        "query": query,
        "since": since,
        "since_basis": (
            f"currentthrough {currentthrough} of the returned edition, plus one day"
            if since is not None and currentthrough is not None
            else "no bound could be derived (see reason)"
        ),
    }


def not_checked(
    reason: str,
    detail: str | None = None,
    *,
    query: str | None,
    since: str | None,
    currentthrough: str | None,
    checked_citation: str | None,
    response: UpstreamResponse | None = None,
) -> dict[str, Any]:
    """The `not_checked` state: the failure surfaced verbatim, 429 named as rate-limit
    and kept distinct from other failures (the three-outcomes rule)."""
    out = _base(query, since, currentthrough, checked_citation)
    out["status"] = STATUS_NOT_CHECKED
    out["reason"] = reason
    if detail:
        out["detail"] = detail
    if response is not None:
        out["http_status"] = response.status
        out["url"] = response.url
        out["body"] = response.text[:5000]
        if response.rate_limited:
            out["rate_limit"] = response.rate_limit_info()
    out["caveat"] = CAVEAT_NOT_CHECKED
    return out


def render(
    outcome: DetectorOutcome,
    *,
    query: str,
    since: str,
    currentthrough: str,
    checked_citation: str,
) -> dict[str, Any]:
    """Classify a completed detector round trip into one of the three states."""
    if outcome.response is None:
        return not_checked(
            outcome.error_reason or "internal_error",
            outcome.error_detail,
            query=query,
            since=since,
            currentthrough=currentthrough,
            checked_citation=checked_citation,
        )
    resp = outcome.response
    if resp.rate_limited:
        return not_checked(
            "rate_limited",
            "GovInfo answered HTTP 429 (rate limit) to the detector query; rate-limit headers are carried.",
            query=query,
            since=since,
            currentthrough=currentthrough,
            checked_citation=checked_citation,
            response=resp,
        )
    if not resp.ok:
        return not_checked(
            "upstream_error",
            f"GovInfo answered HTTP {resp.status} to the detector query; status and body are carried verbatim.",
            query=query,
            since=since,
            currentthrough=currentthrough,
            checked_citation=checked_citation,
            response=resp,
        )
    try:
        data = resp.json()
    except ValueError:
        return not_checked(
            "malformed_response",
            "the detector response was not valid JSON (response-shape drift); body carried verbatim.",
            query=query,
            since=since,
            currentthrough=currentthrough,
            checked_citation=checked_citation,
            response=resp,
        )
    count = data.get("count") if isinstance(data, dict) else None
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(count, int) or not isinstance(results, list):
        return not_checked(
            "malformed_response",
            "the detector response lacked an integer 'count' or a 'results' list (response-shape drift); "
            "body carried verbatim.",
            query=query,
            since=since,
            currentthrough=currentthrough,
            checked_citation=checked_citation,
            response=resp,
        )

    out = _base(query, since, currentthrough, checked_citation)
    out["count"] = count
    if count == 0:
        out["status"] = STATUS_NONE_INDEXED
        out["caveat"] = CAVEAT_NONE_INDEXED
        out["message"] = (
            f"Checked: no public law published on or after {since} is indexed against "
            f"{checked_citation}. See caveat — this is not evidence the text is current."
        )
        return out

    laws = [_law_pointer(r) for r in results]
    shown = len(laws)
    capped = count > shown
    out["status"] = STATUS_LAWS_INDEXED
    out["laws"] = laws
    out["laws_shown"] = shown
    out["laws_cap"] = LAWS_CAP
    out["capped"] = capped
    out["caveat"] = CAVEAT_LAWS_INDEXED
    message = (
        f"{count} public law(s) published on or after {since} are indexed against {checked_citation}. "
        "See caveat — a listing means the law mentions the section; only reading the law says whether "
        "the text changed."
    )
    if capped:
        message += f" The list is capped at one page of {LAWS_CAP}: showing {shown} of {count}."
    out["message"] = message
    return out


def note_statement(parent_citation: str) -> str:
    """The in-band statement carried when the lookup stripped a trailing 'note'."""
    return (
        f"This check ran against the parent section {parent_citation}, not the note. Note-codified "
        "material is where the index is measured weakest (O17/O18, O43b): a law affecting only the "
        "note may be indexed against neither citation, so neither state here speaks to the note."
    )


class CurrentthroughMemory:
    """Remembers the ``currentthrough`` observed per edition year in this process, so
    later lookups of the same edition can issue the detector concurrently with the
    text fetch. A prediction is only ever used after it is verified against the
    fetched payload; see the module docstring."""

    def __init__(self) -> None:
        self._by_edition: dict[int, str] = {}

    def predict(self, edition_year: int | None) -> str | None:
        """The remembered currentthrough for ``edition_year``; for ``None`` (a lookup
        with no ``year``, which resolves to the newest edition) the newest edition
        remembered. Either is a prediction to be verified, never a fact."""
        if edition_year is None:
            if not self._by_edition:
                return None
            return self._by_edition[max(self._by_edition)]
        return self._by_edition.get(edition_year)

    def observe(self, edition_year: int | None, currentthrough: str | None) -> None:
        if edition_year is not None and currentthrough is not None:
            self._by_edition[edition_year] = currentthrough

    def clear(self) -> None:
        self._by_edition.clear()


async def await_with_budget(task: asyncio.Task[DetectorOutcome], budget: float) -> DetectorOutcome | None:
    """Wait up to ``budget`` seconds for an in-flight detector; ``None`` on timeout,
    with the request cancelled so nothing dangles."""
    try:
        return await asyncio.wait_for(task, timeout=budget)
    except TimeoutError:
        return None
