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
