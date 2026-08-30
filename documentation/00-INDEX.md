# uscode-mcp spec — index

This directory is the spec for an MCP server that searches and retrieves the United States Code (and Public Laws) from GovInfo. The spec session owns this directory and nothing else; the implementation session owns everything else and must not write here.

## Files

| File | Contents |
|---|---|
| `10-product.md` | What the server is for, who uses it, relationship to congressMCP |
| `20-govinfo-api.md` | The GovInfo API surface the server depends on: auth, endpoints, formats |
| `30-search.md` | Search service contract, query operators, USCODE/PLAW metadata fields, citation normalization |
| `40-tools.md` | The MCP tool surface: tools, arguments, behavior contracts, error taxonomy |
| `50-public-law.md` | The PLAW extension: recency story, formats, cross-referencing to US Code |
| `90-observations.md` | Measurement log — every empirical claim in this spec cites an entry here |
| `95-open-questions.md` | Maintainer questions and preregistered experiments not yet run |
| `96-rulings.md` | Maintainer rulings R1–R6 (2026-08-29) with the Q1 source exchange (S5) |

## Conventions — these bind

Measurement over assertion. No spec file states an empirical fact about GovInfo without citing an observation in `90-observations.md` (cited as O1, O2, …) or flagging it as unverified. Claims sourced from GovInfo's own help pages or from other models' reports are secondary — cite the source and date, mark them (S1, S2, …); they are documentation of intent or claims, not measurements.

Preregister before a spec change driven by an experiment: expected result and the observation that would falsify it. Record the outcome either way, including falsifications (see O7a).

A scan that errors must not look like one that found nothing. This binds the spec's own experiments and every tool contract in `40-tools.md`: zero results, upstream error, and rate-limit are three distinct outcomes, never collapsed.

Identity over string-matching: resolve documents by `packageId`/`granuleId`, never by comparing titles or citation strings after the initial metadata search. (O17's recall-gap check was done by packageId identity against the full result set — that is the pattern.)

Assert a non-zero denominator: any claim of the form "N of M" or "all editions" must state where M came from.

One line per paragraph, no hard wrapping. Structural lines (tables, fences, headings, blockquotes) follow the rules in `CLAUDE.md`.

Durable state lives in files here, never in conversation. Commit each ruling as it is made.

## Settled — do not reopen

Section text is retrieved from the granule-level `txtLink` (an `/htm` endpoint returning HTML), settled by O5/O6 (2026-08-29). The link field is named `txtLink` but the path segment is `htm` and the payload is HTML — both names appear in the wild; do not "fix" one to match the other.

Citation resolution goes through the search service's metadata fields (`collection:USCODE citation:"…"`), not through constructing granule IDs by hand, settled by O4 and reinforced by O14 (granule IDs nest five levels deep).

Historical editions are reached with `historical:true` on the search request, settled by O7b: all annual editions of a section come back as distinct granules with distinct `dateIssued` years.

Backend is GovInfo only — no STATUTE collection, no OLRC release-point ingestion, no local index (R1, 2026-08-29). The staleness consequence was accepted knowingly; do not reopen because the code is stale, that is the design.

Notes are in scope and retrieved via the parent section: strip a trailing "note" from the citation (O16), fetch the section granule, and the notes are in its payload (O15). Settled 2026-08-29.

Search-only discovery in v1 — no browse/TOC tool until a consumer demonstrably needs one (R3). Public laws only — no `lawtype:private` in the MVP (R6).
