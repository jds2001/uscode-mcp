# GovInfo API surface

The server depends on api.govinfo.gov. Everything here is either measured (O-refs) or flagged.

## Authentication

An api.data.gov API key, read from the `GOVINFO_API_KEY` environment variable and sent **only as the `X-Api-Key` request header** (verified with a 401 no-credential control, O22) — never as the `api_key` query parameter, although that also works (O1–O19). Ruled in R7 after a maintainer-observed leak: URL-borne keys end up in HTTP-client logs (httpx logs request URLs), and this spec's own error contracts require surfacing upstream URLs verbatim, so a key in the URL would be surfaced by a compliant implementation. Header transport keeps every URL the server touches, logs, or surfaces key-free by construction. An absent or blank `GOVINFO_API_KEY` fails the server at startup with a message naming the variable (stderr, nonzero exit) — ruled 2026-09-01 (`96-rulings.md`, keyless-startup contract) after congressMCP's F31, where a keyless server came up wearing a misleading per-request error: a server that can serve nothing must be unmistakably down. The key must never be committed; locally it lives in the repo-root `.env`, which is gitignored.

Rate limit, measured on a registered key: `x-ratelimit-limit: 36000` per hour (O13) — generous, but the contract stands regardless: HTTP 429 surfaces as a distinct rate-limited outcome (`40-tools.md`), and current headroom is read from `x-ratelimit-remaining`, never assumed.

## Endpoints the server uses

| Endpoint | Purpose | Evidence |
|---|---|---|
| `POST /search` | All discovery: citations by metadata, topics by full text | O4, O10–O12, S1 |
| `GET /packages/{packageId}/summary` | Package metadata + download link map + `references` array (PLAW) | O2, O8, O18 |
| `GET /packages/{packageId}/granules/{granuleId}/summary` | Granule metadata + download link map | O9 |
| `GET /packages/{packageId}/granules/{granuleId}/htm` | Section text incl. notes (HTML payload) | O5, O15 |
| Download links (`pdfLink`, `modsLink`, `uslmLink`, …) | Taken verbatim from summaries/search results, never constructed | O4 |

The `/collections`, `/published`, and `/related` endpoints exist but no v1 tool depends on them; `/collections` was used only as an instrument (O1).

A PLAW package summary carries a `references` array enumerating the US Code citations the law touches, by title and section (O18). No v1 tool reads it, but it is the measured higher-recall alternative to the `uscodecitation` search field (O17 vs O18) and the designated v2 bridge source (Q6, E9).

## Formats, per collection — measured 2026-08-29

USCODE: package-level downloads are PDF, text (`/htm`), MODS, PREMIS, ZIP (O2). Granule-level: PDF, text (`/htm`), MODS only — `zipLink`/`premisLink` on a granule point back at the package (O9). No USLM/XML link at either level (O2, O9). GovInfo bulkdata carries no USCODE repository at all (repository list measured, O26) — within GovInfo, PDF/text/MODS is the complete USCODE format story; USLM for the Code exists only at OLRC, out of scope by R1.

PLAW: package-level downloads include `uslmLink` in addition to PDF, text, MODS, PREMIS, ZIP — observed on PLAW-118publ31 (O8). Coverage across congresses unmeasured (E4a). This falsifies the working assumption that XML is unavailable for PLAW; it is USCODE that lacks an XML download link on the API.

## Structure of the USCODE collection

Packages are one per title per edition year: `USCODE-{year}-title{n}` (O2, S3). Granules subdivide a package hierarchically down to leaf sections and can nest five levels deep (`USCODE-2024-title42-chap23-divsnA-subchapXIII-sec2210`, O14); leaves carry `granuleClass:"LEAF"` and a `leafRange` (O9). Appendix material is a granule subtree of the title package (`USCODE-2024-title28-app-federalru-rule9`, O19) and is full-text indexed. The collection holds 1,552 packages and ~2.03M granules (O1). Editions are annual from 1994 forward (S3); `historical:false` (the default) confines search to the current edition (O4 vs O7b).

A section granule's `/htm` payload contains the statutory text, then the source credit, then the statutory notes — for 42 U.S.C. 2210 the notes portion is ~60% of a 142KB payload (O15). Observed payload sizes: 36KB (O5) to 142KB (O15); no upper bound established. The payload embeds a `currentthrough:YYYYMMDD` comment plus `documentid` and `itempath` (O5, O15); the spec treats `currentthrough` as required provenance (`40-tools.md`).
