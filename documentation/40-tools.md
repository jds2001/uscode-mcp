# MCP tool surface

Four tools. Small on purpose: each maps to one recipe in `30-search.md`, and everything else (summaries, alternate formats) rides along as links in responses rather than as more tools.

## Cross-cutting contracts

These bind every tool:

**Three distinct outcomes, never collapsed.** (1) Success, possibly with zero results — a zero-hit search says so explicitly and echoes the exact query sent upstream. (2) Upstream failure — HTTP status and body surfaced; a failed call must never present as "not found". (3) Rate-limited — HTTP 429 surfaced as its own outcome with any `X-RateLimit-*`/`Retry-After` information passed through.

**Provenance on every text payload.** Any response containing statutory text states: `packageId`, `granuleId` (when granule-level), edition year, the `currentthrough` date parsed from the granule HTML comment (O5), `lastModified`, and the canonical PDF link. If `currentthrough` cannot be parsed, say so — do not omit silently.

**No silent truncation.** Text responses take an optional `max_chars` (default 100000) and `start_char` (default 0). When the payload exceeds the window, the response states total length, the window returned, and the `start_char` to continue from. Full text is never elided without these markers. (PLAW packages can be thousands of pages, O8 — this contract is load-bearing there, but it applies uniformly.)

**Links are data, never constructed.** Download URLs come from search results and summaries verbatim (settled, `00-INDEX.md`).

**Text derivation.** The `/htm` payload is HTML (O5). The server strips it to readable plain text (preserving the header block that identifies edition and hierarchy) and returns that; it does not return raw HTML by default. An implementation choice of HTML-to-text method is free so long as no statutory text is dropped — the leading metadata/header lines and trailing source-credit notes are part of the section and stay.

## `get_us_code_section`

Resolve a citation and return the section's text.

Arguments: `citation` (string — accepts "17 U.S.C. 107", "17 USC 107", "17 U.S.C. § 107(b)", or equivalently `title` + `section` as separate fields), optional `year` (edition year), optional `max_chars`/`start_char`.

Behavior: normalize per `30-search.md`; search `collection:USCODE citation:"…"` with `historical` set iff `year` given; on multiple hits after year filtering, return the disambiguation list (ids + titles) rather than guessing; fetch the winning granule's `txtLink`; return text + provenance. A citation that resolves to zero granules reports the normalized citation and the raw query so the caller can retry with `search_us_code`.

## `search_us_code`

Full-text and fielded search over the USCODE collection.

Arguments: `query` (govinfo query syntax; the server prepends `collection:USCODE` unless the query already contains a `collection:` term), optional `page_size` (default 20, max 100), `offset_mark` (default `*`), `historical` (default false).

Returns: `count`, next `offset_mark`, and per hit: `title`, `packageId`, `granuleId`, `dateIssued`, download links. It returns pointers, not text — the caller follows up with `get_us_code_section` (or the ids directly).

## `get_public_law`

Arguments: `congress` + `law_number`, or a `citation` string ("Pub. L. 118-31", "Public Law 118-31", "P.L. 118-31" — all normalize to congress/number); optional `law_type` (default public), `max_chars`/`start_char`, and `format` (`text` default; `uslm` returns the USLM XML when the package offers a `uslmLink`, O8, and is a distinct not-available outcome when it doesn't).

Behavior: resolve via `collection:PLAW congress:{n} docnumber:{m}` (E2 — resolution path unmeasured; first implementation report here needs a trace), fetch package text, return with provenance (packageId, `dateIssued`, `lastModified`, PDF link).

## `search_public_laws`

As `search_us_code` but scoped `collection:PLAW`. The tool description must document the reverse-lookup recipe — `uscodecitation:"17 U.S.C. 107"` finds public laws GovInfo has tagged as touching that section — because that recipe is the congressMCP-composition story (`10-product.md`).
