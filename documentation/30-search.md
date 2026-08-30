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
| `resultLevel` | `package` vs default mixed granule/package | documented (S1); untested (E3) |

Responses carry `count`, next `offsetMark`, and `results[]` with `title`, `packageId`, `granuleId`, `dateIssued`, `collectionCode`, `lastModified`, a `download` link map, and a `resultLink` to the granule/package summary (O4). The service self-describes as public preview (S1) — the implementation should treat response-shape drift as a live risk and fail loudly, not coerce.

## Query operators (S2 — govinfo.gov/help/search-operators, fetched 2026-08-29)

Boolean `AND`/`OR`/`NOT` and prefix `-`; exact phrases in double quotes; proximity `adj`, `near/#`, `before/#`; wildcards `?` (one char) and `*` (one or more); fielded search `field:value`; ranges `field:range(start,end)`; MODS fields via `mods:field:value`. Quotes inside the JSON body are escaped with `\` (S1).

## Fields this spec relies on

USCODE (S3 — govinfo.gov/help/uscode): `citation`, `usctitlenum`, `uscchnum`, `uscsectionnum`, `shorttitle`, `plawcitation`, `uscdisposition`, `uscsourcecredit`, `usceffectivedate`, heading fields (`uscchheading`, `uscchtitle`, `uscpartheading`).

PLAW (S4 — govinfo.gov/help/plaw): `congress`, `docnumber`, `lawtype`, `approveddate`, `publishdate`, `billscitation`, `uscodecitation`, `statutecitation`, `title`, `committee`.

Exercised against the live service so far: `citation` (O4, O7a, O10, O11, O16), `congress`+`docnumber` (O12), `uscodecitation` (O17 — including its recall gap), `usctitlenum` (O19). The rest are documented intent until measured; a tool contract may cite them, but a defect against them needs a measurement first.

## Citation resolution — the core recipe

To resolve a US Code citation: `collection:USCODE citation:"{title} U.S.C. {section}"`, `historical:false`. Measured: exactly one hit, the current-edition leaf granule (O4, O14).

What the matcher tolerates and what it doesn't — all measured:

- Missing periods (`17 USC 107`): tolerated (O7a, a falsified preregistration).
- Section symbol (`17 U.S.C. § 107`): tolerated (O10).
- Subsection suffix (`17 U.S.C. 107(b)`): zero hits (O11). The server MUST strip parenthetical suffixes; the granule is the retrieval unit, so the caller gets section 107 whole and navigates within it.
- Trailing "note" (`42 U.S.C. 2210 note`): zero hits (O16). The server MUST strip a trailing "note" and resolve the parent section — the notes are inside its payload (O15), so nothing further is required to serve note citations.

Normalization therefore has two mandatory strips (subsection, "note") and otherwise canonicalizes to `{title} U.S.C. {section}` as hygiene, since the observed tolerance covers only the variants above.

Edition-year requests add `historical:true` and select the hit whose `dateIssued` falls in the requested year; all annual editions come back as distinct granules (31 editions of §107, 1994–2024, O7b — denominator: `count` field of that response).

To resolve a public law: `collection:PLAW congress:{n} docnumber:{m}` — measured: exactly one hit for 118/31 (O12). `lawtype:public` joins the query only if a collision is ever observed; none has been.

Reverse lookup — which public laws touch a US Code section — is `collection:PLAW uscodecitation:"{title} U.S.C. {section}"`. It works (14 hits for 42 U.S.C. 2210, O17) but has a measured recall gap: PLAW-119publ21 is absent from those hits even though its own summary `references` array lists the section (O18). Every surface that exposes this recipe must carry the incompleteness caveat; see `40-tools.md` and E9.
