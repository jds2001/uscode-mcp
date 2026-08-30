# Observation log

Instrument, unless stated otherwise: `curl` against `api.govinfo.gov` with `DEMO_KEY`, from this spec session, 2026-08-29. Raw response bodies for O2/O4/O5/O8 were saved to the session scratchpad (disposable); the load-bearing excerpts are inline here. S-refs are secondary sources: govinfo help pages fetched (via web-fetch summarization, same date) — documentation of intent, not measurement.

## Secondary sources

- S1: https://www.govinfo.gov/features/search-service-overview — search service request/response shape, pageSize max 1000, offsetMark protocol, historical/resultLevel flags, public-preview status.
- S2: https://www.govinfo.gov/help/search-operators — operator syntax.
- S3: https://www.govinfo.gov/help/uscode — USCODE fields, package/granule naming, edition structure.
- S4: https://www.govinfo.gov/help/plaw — PLAW fields, naming, coverage from 104th Congress.
- Note: https://api.govinfo.gov/docs/ is a JS app and yielded no content to the fetcher; no OpenAPI document was found at the guessed URLs (404/500). The endpoint table in `20-govinfo-api.md` rests on the O-measurements, not on that page.

## Measurements

O1 — `GET /collections`: USCODE has 1,552 packages / 2,027,914 granules; PLAW 5,999 packages (granuleCount null); BILLS 290,165 packages.

O2 — `GET /packages/USCODE-2023-title17/summary`: download map has `premisLink`, `txtLink` (path ends `/htm`), `zipLink`, `modsLink`, `pdfLink`. No `uslmLink`. `titleNumber:"17"`, `dateIssued:"2023-12-31"`, `lastModified:"2025-09-24T16:23:38Z"`.

O4 — `POST /search` body `{"query":"collection:USCODE citation:\"17 U.S.C. 107\"","pageSize":"3","offsetMark":"*"}`: `count:1`; the hit is granule `USCODE-2024-title17-chap1-sec107` in package `USCODE-2024-title17`, `dateIssued:"2024-12-31"`, with granule-level `txtLink`/`pdfLink`/`modsLink`, package-level `zipLink`/`premisLink`, and `resultLink` = the granule summary URL. Demonstrates: default search is current-edition only, and search results carry retrieval URLs directly.

O5 — `GET .../granules/USCODE-2024-title17-chap1-sec107/htm`: 35,757-byte HTML payload. Header lines identify "United States Code, 2024 Edition", title/chapter/section headings. Embedded comments: `documentid:17_107`, `currentthrough:20250106`, `documentPDFPage:26`, `itempath:/170/CHAPTER 1/Sec. 107`.

O6 — same fetch: payload is HTML despite the link field being named `txtLink` and the summary field naming convention suggesting text; path segment is `htm`.

O7a — preregistered: `citation:"17 USC 107"` (no periods) expected 0 hits, falsifier being resolution to sec107. FALSIFIED: `count:1`, same granule `USCODE-2024-title17-chap1-sec107`. Citation matching tolerates missing periods; normalization is therefore a convenience, not a requirement, for this variant.

O7b — preregistered: same citation query with `historical:true`, `pageSize:40`, sorted `publishdate DESC`, expected multiple editions. CONFIRMED: `count:31`; consecutive annual granules `USCODE-{2013..2024}-title17-chap1-sec107` observed in the first 12, `dateIssued` = Dec 31 of each edition year. Denominator for "31 editions": the response's `count` field.

O8 — `GET /packages/PLAW-118publ31/summary` (FY2024 NDAA): download map includes `uslmLink` alongside `premisLink`/`txtLink`/`zipLink`/`modsLink`/`pdfLink`. `congress:"118"`, `dateIssued:"2023-12-22"`, `lastModified:"2026-01-02T18:50:45Z"`. Single package — no coverage claim beyond it.

O9 — `GET .../granules/USCODE-2024-title17-chap1-sec107/summary`: `granuleClass:"LEAF"`, `leafRange:{from:"107",to:"107",type:"section"}`; granule download map has granule-level `txtLink`/`pdfLink`/`modsLink` and package-level `zipLink`/`premisLink`; no `uslmLink`; `usCodeCitation` field present but null on this granule.

## Measurements — 2026-08-29, second batch (real key via .env; preregistrations in commit fce3f03)

O10 — E1a CONFIRMED: `citation:"17 U.S.C. § 107"` → `count:1`, same granule as O4. The `§` symbol is tolerated.

O11 — E1b CONFIRMED: `citation:"17 U.S.C. 107(b)"` → `count:0`. Subsection suffixes must be stripped before searching; this is now a requirement, not a convenience.

O12 — E2 CONFIRMED: `collection:PLAW congress:118 docnumber:31` → `count:1`, exactly `PLAW-118publ31`. No `lawtype` needed for this case.

O13 — E5 (partial): response headers on a real-key search: `x-ratelimit-limit: 36000`, `x-ratelimit-remaining: 35999`. The earlier 1,000/hr assumption in `20-govinfo-api.md` was wrong by 36×. `X-Api-Key` header auth remains untested.

O14 — E7a CONFIRMED: `citation:"42 U.S.C. 2210"` → `count:1`, granule `USCODE-2024-title42-chap23-divsnA-subchapXIII-sec2210` ("Indemnification and limitation of liability"). Granule IDs can nest five levels deep — another reason IDs are data, never constructed.

O15 — E7b CONFIRMED: that granule's `/htm` payload is 142,544 bytes; the source credit (`(Aug. 1, 1946, …`) begins at byte 56,259, so ~60% of the payload is source credit plus statutory notes. Note-style headings present: "References in Text" ×1, "Amendments" ×5, "Effective Date" ×2, "Short Title" ×3. `currentthrough:20250106`. Notes ride along in the section granule; no separate fetch exists or is needed.

O16 — E7c CONFIRMED: `citation:"42 U.S.C. 2210 note"` → `count:0`. Note citations resolve by stripping the trailing "note" and fetching the parent section (whose payload contains the notes, O15).

O17 — E4: `collection:PLAW uscodecitation:"42 U.S.C. 2210"` → `count:14` (full list captured: 119publ74, 118publ47, 117publ328, 117publ286, 117publ169, 115publ248, 112publ10, 110publ140, 109publ58, 108publ375, 108publ7, 107publ314, 105publ362, 104publ134). `PLAW-119publ21` is ABSENT from all 14 — checked by packageId identity against the full result set (denominator: the response's own count). `uscodecitation:"42 U.S.C. 2210 note"` → `count:0`. Ingestion lag is not the explanation: a 2026-01-23 law (119publ74) is present.

O18 — `GET /packages/PLAW-119publ21/summary`: the package exists (`dateIssued:"2025-07-04"`) and its `references` array DOES list title 42 section `2210` (among 44 title-42 sections). Together with O17: the reverse-lookup recall gap is in the search index's `uscodecitation` field, not in GovInfo's package metadata. S5's claim that Pub. L. 119-21 touches 42 U.S.C. 2210 is thereby corroborated at the metadata level while the search field misses it.

O19 — E8: full-text query `collection:USCODE "Federal Rules of Appellate Procedure" usctitlenum:28` → `count:79`, hits mixing regular section granules and appendix granules of the shape `USCODE-2024-title28-app-federalru-rule9`. Appendix material lives as granules inside the title package and is full-text indexed. No citation-field form for "28 U.S.C. App." was found (untested beyond this).

## Measurements — 2026-08-29, third batch

O20 — Resolution of an implementation-session discrepancy report, re-measured rather than argued: a citation search response's top-level keys are exactly `count`, `offsetMark`, `results`; `count:1` at top level; a result object's keys are `collectionCode, dateIngested, dateIssued, download, governmentAuthor, granuleId, lastModified, packageId, relatedLink, resultLink, title` — no `count`. The implementation's "count=None on section retrievals" is therefore a wrong-level read in one of its code paths, not API shape variance; consistent with every prior observation (O4, O10, O14). No spec change; `30-search.md` gains a clarifying sentence.

O21 — E9 executed per the preregistered protocol (commit a455a66), 33 membership tests over the 10-law deterministic sample:

| Law | ref pairs | sampled results |
|---|---|---|
| PLAW-115publ97 | 17 | 12/1817 HIT, 37/310 HIT, 43/1629e HIT |
| PLAW-115publ232 | 601 | 10/7902 HIT, 2/192-194 HIT, 42/2210 MISS, 54/303102 HIT |
| PLAW-116publ92 | 686 | 10/7448 HIT, 2/1301 HIT, 54/320301 MISS |
| PLAW-116publ136 | 374 | 2/1070a HIT, 29/151 MISS, 54/300101 MISS |
| PLAW-117publ58 | 610 | 2/661c HIT, 42/10362 HIT, 54/306121 HIT |
| PLAW-117publ169 | 143 | 2/661a HIT, 42/1395w-104 HIT, 42/2210 HIT, 50/4501 HIT |
| PLAW-118publ5 | 29 | 2/621 MISS, 20/1001 MISS, 45/352 HIT |
| PLAW-118publ31 | 605 | 1/112b HIT, 10/9771 MISS, 51/50902 HIT |
| PLAW-119publ4 | 50 | 2/901a HIT, 42/1395m HIT, 50/3094 HIT |
| PLAW-119publ21 | 235 | 16/3839bb-2 HIT, 2/900 HIT, 42/2210 MISS, 51/50902 HIT |

Outcomes against preregistration: recall < 100% CONFIRMED — 25/33 (denominator: the 33 sampled membership tests, not the corpus). The 119publ21×42/2210 miss REPRODUCES. Concentration in the 119th Congress FALSIFIED: 7 of 8 misses are in congresses 115–118. The gap is per-(law, section), not per-section — 42 U.S.C. 2210 misses for 115publ232 and 119publ21 but hits for 117publ169. Instrument validity: 25 positives across all five congresses show the `uscodecitation`+`congress`+`docnumber` conjunction composes; no law needed the all-miss control. Side observation: `references` sections can be range strings ("192-194"), and the range form itself was a HIT as a quoted citation.
