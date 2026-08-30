# MCP tool surface

Four tools. Small on purpose: each maps to one recipe in `30-search.md`, and everything else (summaries, alternate formats) rides along as links in responses rather than as more tools.

## Cross-cutting contracts

These bind every tool:

**Three distinct outcomes, never collapsed.** (1) Success, possibly with zero results — a zero-hit search says so explicitly and echoes the exact query sent upstream. (2) Upstream failure — HTTP status and body surfaced; a failed call must never present as "not found". (3) Rate-limited — HTTP 429 surfaced as its own outcome with `x-ratelimit-*`/`Retry-After` information passed through (limit measured at 36,000/hr, O13 — headroom is real but the contract doesn't depend on it).

**Provenance on every text payload.** Any response containing statutory text states: `packageId`, `granuleId` (when granule-level), edition year, the `currentthrough` date parsed from the granule HTML comment (O5, O15), `lastModified`, and the canonical PDF link. If `currentthrough` cannot be parsed, say so — do not omit silently. Given the backend ruling (R1), `currentthrough` is the staleness disclosure and is non-optional.

**No silent truncation.** Text responses take an optional `max_chars` (default 100000) and `start_char` (default 0). When the payload exceeds the window, the response states total length, the window returned, and the `start_char` to continue from. Full text is never elided without these markers. Load-bearing in both collections: a section granule reached 142KB (O15) and a public law is a single multi-thousand-page package (O8).

**Secret hygiene.** The API key is sent only via the `X-Api-Key` header (R7, O22) and must never appear in any URL the server builds, logs, echoes, or surfaces. The outcome contracts above require exposing upstream URLs, bodies, and queries verbatim — that exposure is safe if and only if this rule holds, so a key found in any surfaced string is a contract violation twice over, and redaction is a backstop, not the mechanism.

**Links are data, never constructed.** Download URLs come from search results and summaries verbatim (settled, `00-INDEX.md`).

**Text derivation.** The `/htm` payload is HTML (O5). The server strips it to readable plain text (preserving the header block that identifies edition and hierarchy) and returns that; it does not return raw HTML by default. No statutory content may be dropped — and after O15 "content" explicitly includes everything after the statutory text: source credits and statutory notes are the payload's majority for note-heavy sections and are the entire point for note citations (R4).

## `get_us_code_section`

Resolve a citation and return the section's text, notes included.

Arguments: `citation` (string — accepts "17 U.S.C. 107", "17 USC 107", "17 U.S.C. § 107(b)", "42 U.S.C. 2210 note", or equivalently `title` + `section` as separate fields), optional `year` (edition year), optional `max_chars`/`start_char`.

Behavior: normalize per `30-search.md` — mandatory strips: parenthetical subsection (O11) and trailing "note" (O16); when either strip fires, the response says so and names the containing section it resolved instead. Search `collection:USCODE citation:"…"` with `historical` set iff `year` given; on multiple hits after year filtering, return the disambiguation list (ids + titles) rather than guessing; fetch the winning granule's `txtLink`; return text + provenance. A citation that resolves to zero granules reports the normalized citation and the raw query so the caller can retry with `search_us_code`.

Appendix citations ("28 U.S.C. App. …"): no citation-field form is known to match appendix granules (O19 established full-text reachability only, E10 open). v1 contract: return a structured redirect — not an error, not zero-hits-silence — naming `search_us_code` and suggesting a query built from the appendix terms, since appendix granules are demonstrably full-text indexed (O19). If E10 later finds a direct form, this upgrades to resolution without an interface change.

## `search_us_code`

Full-text and fielded search over the USCODE collection — the discovery path for topics, appendix material (O19), and anything citation resolution redirects here.

Arguments: `query` (govinfo query syntax; the server prepends `collection:USCODE` unless the query already contains a `collection:` term), optional `page_size` (default 20, max 100), `offset_mark` (default `*`), `historical` (default false).

Returns: `count`, next `offset_mark`, and per hit: `title`, `packageId`, `granuleId`, `dateIssued`, download links. It returns pointers, not text — the caller follows up with `get_us_code_section` (or the ids directly).

## `get_public_law`

Public laws only (R6): a private-law request is a distinct out-of-scope outcome, not a failed lookup.

Arguments: `congress` + `law_number`, or a `citation` string ("Pub. L. 118-31", "Public Law 118-31", "P.L. 118-31" — all normalize to congress/number); optional `max_chars`/`start_char`, and `format` (`text` default; `uslm` returns the USLM XML when the package offers a `uslmLink`, O8, and is a distinct not-available outcome when it doesn't, coverage unmeasured, E4a).

Behavior: resolve via `collection:PLAW congress:{n} docnumber:{m}` (measured exact for 118/31, O12), fetch package text, return with provenance (packageId, `dateIssued`, `lastModified`, PDF link).

## `search_public_laws`

As `search_us_code` but scoped `collection:PLAW` (public laws only, R6). The tool description must document the reverse-lookup recipe — `uscodecitation:"42 U.S.C. 2210"` finds public laws tagged as touching that section — because that recipe is the congressMCP-composition story (`10-product.md`). The same description MUST state the measured incompleteness: the field's recall has a demonstrated, structural gap — 25/33 on the E9 sample, misses in every congress from the 115th on (O21, O17/O18) — so absence of a law from these results is never evidence it doesn't touch the section. Presenting this result set as complete is a spec violation, not a style issue.
