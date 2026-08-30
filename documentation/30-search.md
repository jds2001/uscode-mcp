# Search

## The search service

`POST https://api.govinfo.gov/search` with a JSON body (S1, verified by O4):

| Field | Meaning | Notes |
|---|---|---|
| `query` | govinfo query syntax (operators below) | required |
| `pageSize` | results per page | documented max 1000 (S1); server default 20, cap 100 |
| `offsetMark` | pagination cursor; `*` to start, echo back the returned value | opaque string (O4) |
| `sorts` | array of `{field, sortOrder}` | fields seen: `score`, `publishdate`; `title`, `lastModified` documented (S1) |
| `historical` | include superseded editions | default false; behavior measured in O7b |
| `resultLevel` | `package` vs default mixed granule/package | documented (S1); untested |

Responses carry `count`, next `offsetMark`, and `results[]` with `title`, `packageId`, `granuleId`, `dateIssued`, `collectionCode`, `lastModified`, a `download` link map, and a `resultLink` to the granule/package summary (O4). The service self-describes as public preview (S1) — the implementation should treat response-shape drift as a live risk and fail loudly, not coerce.

## Query operators (S2 — govinfo.gov/help/search-operators, fetched 2026-08-29)

Boolean `AND`/`OR`/`NOT` and prefix `-`; exact phrases in double quotes; proximity `adj`, `near/#`, `before/#`; wildcards `?` (one char) and `*` (one or more); fielded search `field:value`; ranges `field:range(start,end)`; MODS fields via `mods:field:value`. Quotes inside the JSON body are escaped with `\` (S1).

## Fields this spec relies on

USCODE (S3 — govinfo.gov/help/uscode): `citation`, `usctitlenum`, `uscchnum`, `uscsectionnum`, `shorttitle`, `plawcitation`, `uscdisposition`, `uscsourcecredit`, `usceffectivedate`, heading fields (`uscchheading`, `uscchtitle`, `uscpartheading`).

PLAW (S4 — govinfo.gov/help/plaw): `congress`, `docnumber`, `lawtype`, `approveddate`, `publishdate`, `billscitation`, `uscodecitation`, `statutecitation`, `title`, `committee`.

Of these, only `citation` has been exercised against the live service (O4, O7a). The rest are documented intent until measured; a tool contract may cite them, but a defect against them needs a measurement first.

## Citation resolution — the core recipe

To resolve a US Code citation: `collection:USCODE citation:"{title} U.S.C. {section}"`, `historical:false`. Measured: exactly one hit for `17 U.S.C. 107`, the current-edition leaf granule (O4).

Matching is tolerant of at least the periods: `citation:"17 USC 107"` resolved to the same granule (O7a — a falsified preregistration; the expectation was zero hits). Tolerance of `§`, "Sec.", and subsection suffixes like `107(b)` is unmeasured (E1). Until then the server normalizes input to the canonical `{title} U.S.C. {section}` form before searching: strip `§`/"Sec."/"USC"→"U.S.C.", and strip any parenthetical subsection suffix — the granule is the retrieval unit, so `17 U.S.C. 107(b)` fetches section 107 whole and the caller navigates within it.

Edition-year requests add `historical:true` and select the hit whose `dateIssued` falls in the requested year; all annual editions come back as distinct granules (31 editions of §107, 1994–2024, O7b — denominator: `count` field of that response).

To resolve a public law: `collection:PLAW congress:{n} docnumber:{m}` with `lawtype:public` when disambiguation is needed (S4; unmeasured, E2). Reverse lookup — which public laws touch a US Code section — is `collection:PLAW uscodecitation:"{title} U.S.C. {section}"` (S4; unmeasured, E4).
