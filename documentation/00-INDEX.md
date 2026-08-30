# uscode-mcp spec — index

This directory is the spec for an MCP server that searches and retrieves the United States Code (and, as an extension, Public Laws) from GovInfo. The spec session owns this directory and nothing else; the implementation session owns everything else and must not write here.

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

## Conventions — these bind

Measurement over assertion. No spec file states an empirical fact about GovInfo without citing an observation in `90-observations.md` (cited as O1, O2, …) or flagging it as unverified. Claims sourced from GovInfo's own help pages are secondary — cite the URL and fetch date, and mark them (S1, S2, …); they are documentation of intent, not measurements.

Preregister before a spec change driven by an experiment: expected result and the observation that would falsify it. Record the outcome either way, including falsifications (see O7).

A scan that errors must not look like one that found nothing. This binds the spec's own experiments and every tool contract in `40-tools.md`: zero results, upstream error, and rate-limit are three distinct outcomes, never collapsed.

Identity over string-matching: resolve documents by `packageId`/`granuleId`, never by comparing titles or citation strings after the initial metadata search.

Assert a non-zero denominator: any claim of the form "N of M" or "all editions" must state where M came from.

One line per paragraph, no hard wrapping. Structural lines (tables, fences, headings, blockquotes) follow the rules in `CLAUDE.md`.

Durable state lives in files here, never in conversation. Commit each ruling as it is made.

## Settled — do not reopen

Section text is retrieved from the granule-level `txtLink` (an `/htm` endpoint returning HTML), settled by O5/O6 (2026-08-29). The link field is named `txtLink` but the path segment is `htm` and the payload is HTML — both names appear in the wild; do not "fix" one to match the other.

Citation resolution goes through the search service's metadata fields (`collection:USCODE citation:"…"`), not through constructing granule IDs by hand, settled by O4 (2026-08-29). Granule IDs encode chapter structure (`-chap1-sec107`) that a citation alone does not determine.

Historical editions are reached with `historical:true` on the search request, settled by O7b (2026-08-29): all annual editions of a section come back as distinct granules with distinct `dateIssued` years.
