# Search

## The search service

`POST https://api.govinfo.gov/search` with a JSON body (S1, verified by O4):

| Field | Meaning | Notes |
|---|---|---|
| `query` | govinfo query syntax (operators below) | required |
| `pageSize` | results per page | documented max 1000 (S1), measured honored at 1000 (O43g); the uscode-mcp tools default to 20 and cap at 100 |
| `offsetMark` | pagination cursor; `*` to start, echo back the returned value | opaque string (O4) |
| `sorts` | array of `{field, sortOrder}` | fields seen: `score`, `publishdate`; `title`, `lastModified` documented (S1) |
| `historical` | include superseded editions | default false; behavior measured in O7b |
| `resultLevel` | `package` vs default mixed granule/package | do not use with granule-level fields: silently zero-hits a matching citation query (O23) |

Responses carry exactly three top-level fields — `count`, next `offsetMark`, and `results[]` (O20; result objects carry no `count` of their own) — with `title`, `packageId`, `granuleId`, `dateIssued`, `collectionCode`, `lastModified`, a `download` link map, and a `resultLink` to the granule/package summary (O4). The service self-describes as public preview (S1) — the implementation should treat response-shape drift as a live risk and fail loudly, not coerce.

## Query operators (S2 — govinfo.gov/help/search-operators, fetched 2026-08-29)

Boolean `AND`/`OR`/`NOT` and prefix `-`; exact phrases in double quotes; proximity `adj`, `near/#`, `before/#`; wildcards `?` (one char) and `*` (one or more); fielded search `field:value`; ranges `field:range(start,end)`; MODS fields via `mods:field:value`. Quotes inside the JSON body are escaped with `\` (S1).

## Fields this spec relies on

USCODE (S3 — govinfo.gov/help/uscode): `citation`, `usctitlenum`, `uscchnum`, `uscsectionnum`, `shorttitle`, `plawcitation`, `uscdisposition`, `uscsourcecredit`, `usceffectivedate`, heading fields (`uscchheading`, `uscchtitle`, `uscpartheading`).

PLAW (S4 — govinfo.gov/help/plaw): `congress`, `docnumber`, `lawtype`, `approveddate`, `publishdate`, `billscitation`, `uscodecitation`, `statutecitation`, `title`, `committee`.

Exercised against the live service so far: `citation` (O4, O7a, O10, O11, O16), `congress`+`docnumber` (O12), `uscodecitation` (O17 — including its recall gap), `usctitlenum` (O19), `publishdate` ranges including the open-ended `range(date,)` form, composed with `uscodecitation` (O43f), `lawtype:public` (O43f), and `approveddate` — which works as a single-day value but returns HTTP 500 for every range form tried (O43f), so no contract may use an `approveddate` range. The rest are documented intent until measured; a tool contract may cite them, but a defect against them needs a measurement first.

## Citation resolution — the core recipe

To resolve a US Code citation: `collection:USCODE citation:"{title} U.S.C. {section}"`, `historical:false`. Measured: exactly one hit, the current-edition leaf granule (O4, O14).

What the matcher tolerates and what it doesn't — all measured:

- Missing periods (`17 USC 107`): tolerated (O7a, a falsified preregistration).
- Section symbol (`17 U.S.C. § 107`): tolerated (O10).
- Subsection suffix (`17 U.S.C. 107(b)`): zero hits (O11). The server MUST strip parenthetical suffixes; the granule is the retrieval unit, so the caller gets section 107 whole and navigates within it.
- Trailing "note" (`42 U.S.C. 2210 note`): zero hits (O16). The server MUST strip a trailing "note" and resolve the parent section — the notes are inside its payload (O15), so nothing further is required to serve note citations.

Normalization therefore has two mandatory strips (subsection, "note") and otherwise canonicalizes to `{title} U.S.C. {section}` as hygiene, since the observed tolerance covers only the variants above.

Appendix citations resolve directly through the same field: `citation:"{title} U.S.C. App."` matches the appendix granule set (251 for title 28) and `citation:"28 U.S.C. App. Rule 9"` pins individual rules, sometimes to multiple granules — a measured disambiguation case (O24). Historical appendix forms that no longer exist in the current edition (e.g. the eliminated title 50 Appendix) return zero (O24); that falls through to full-text search like any other zero-hit.

Edition-year requests add `historical:true` and select the hit whose `dateIssued` falls in the requested year; all annual editions come back as distinct granules (31 editions of §107, 1994–2024, O7b — denominator: `count` field of that response).

To resolve a public law: `collection:PLAW congress:{n} docnumber:{m}` — measured: exactly one hit for 118/31 (O12). `lawtype:public` joins the query only if a collision is ever observed; none has been. Measured 2026-09-15: `lawtype` partitions PLAW exactly (private 60 + public 5,939 = 5,999) and composes with `publishdate` ranges and `uscodecitation` without changing public-law counts (O44e) — so it is safe to add wherever private packages must be excluded, as the R14 detector does.

Within-document scoping — measured (O30): `packageid:{id}` conjoins with full-text terms. On USCODE it returns granule-level hits inside the named package (within-title search at section resolution: `collection:USCODE packageid:USCODE-2024-title17 "fair use"` → 9 granules). On PLAW, packages have no granules, so it is a presence test for a phrase within a specific law — confirmation, not location; locating still means windowed reading, where the TOC region (early windows) is the map. Verified with a nonsense-phrase negative control.

Reverse lookup — which public laws touch a US Code section — is `collection:PLAW uscodecitation:"{title} U.S.C. {section}"`. It works (14 hits for 42 U.S.C. 2210, O17) but has a measured, structural recall gap: sampled recall against packages' own `references` arrays is 25/33, with misses in every congress sampled from the 115th on and varying per (law, section) — not an ingestion-lag artifact (O21, which falsified the recency hypothesis; see also O18). Every surface that exposes this recipe must carry the incompleteness caveat; see `40-tools.md` and E9. Private laws are indexed in the same field — 25 of 60 carry `U.S.C` references and a live section was measured firing on a 119th-Congress private law (O44e) — so a reverse lookup meant to feed `get_public_law` must add `lawtype:public`. Appendix material: the field carries numbered appendix sections as `"{title} U.S.C. App. {section}"` (MODS witness on PLAW-119publ75; `"50 U.S.C. App. 2012"` → 19 hits, `"5 U.S.C. App. 3"` → 29, O44d); appendix rules (`28 U.S.C. App. Rule N`) have no measured form (0 hits on the forms tried). The package-summary `references` array does NOT list appendix citations even when the MODS does (O44d) — an instrument limit for any references-based ground truth, E16's included.
