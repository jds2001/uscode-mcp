# GovInfo API surface

The server depends on api.govinfo.gov. Everything here is either measured (O-refs) or flagged.

## Authentication

An api.data.gov API key, read from the `GOVINFO_API_KEY` environment variable and sent **only as the `X-Api-Key` request header** (verified with a 401 no-credential control, O22) — never as the `api_key` query parameter, although that also works (O1–O19). Ruled in R7 after a maintainer-observed leak: URL-borne keys end up in HTTP-client logs (httpx logs request URLs), and this spec's own error contracts require surfacing upstream URLs verbatim, so a key in the URL would be surfaced by a compliant implementation. Header transport keeps every URL the server touches, logs, or surfaces key-free by construction. An absent or blank `GOVINFO_API_KEY` fails the server at startup with a message naming the variable (stderr, nonzero exit) — ruled 2026-09-01 (`96-rulings.md`, keyless-startup contract) after congressMCP's F31, where a keyless server came up wearing a misleading per-request error: a server that can serve nothing must be unmistakably down. The key must never be committed; locally it lives in the repo-root `.env`, which is gitignored.

Authentication is done by the api.data.gov gateway (API Umbrella — it names itself in `Via` and `X-Api-Umbrella-Request-Id`, O72d), in front of GovInfo's application. Measured rejections: no key → 401 `API_KEY_MISSING` (O22, O70g); a wrong key → 401 `API_KEY_INVALID`, identically for a malformed key and a well-formed random one, on any endpoint (E24, O72). Both depart from the gateway manual's 403 (S21, O71c). The two differ only in `error.code`, never in status; the error body does not echo the submitted key (O72e), and rejected requests carry no `x-ratelimit-*` headers, so those headers are read when present and never assumed. Both are outcome (2) in `40-tools.md` — upstream failure, status and body surfaced.

Rate limit, measured on a registered key: `x-ratelimit-limit: 36000` per hour (O13) — generous, but the contract stands regardless: HTTP 429 surfaces as a distinct rate-limited outcome (`40-tools.md`), and current headroom is read from `x-ratelimit-remaining`, never assumed.

## Endpoints the server uses

| Endpoint | Purpose | Evidence |
|---|---|---|
| `POST /search` | All discovery: citations by metadata, topics by full text | O4, O10–O12, S1 |
| `GET /packages/{packageId}/summary` | Package metadata + download link map + `references` array (PLAW) | O2, O8, O18 |
| `GET /packages/{packageId}/granules/{granuleId}/summary` | Granule metadata + download link map | O9 |
| `GET /packages/{packageId}/granules/{granuleId}/htm` | Section text incl. notes (HTML payload) | O5, O15 |
| Download links (`pdfLink`, `modsLink`, `uslmLink`, …) | Taken verbatim from summaries/search results, never constructed | O4 |

The `/collections`, `/published`, and `/related` endpoints exist but no v1 tool depends on them; `/collections` was used only as an instrument (O1). `/related` is measured not to be a law↔section bridge (E23, O70): a PLAW package relates only to BILLS, HOB, CRPT and CPD, no relationship to or from USCODE is defined, and a USCODE granule id draws a 500. It signals absence with a 404, where `/search` uses a 200 with `count: 0`.

GovInfo publishes an OpenAPI 3.0.1 description at `https://api.govinfo.gov/api-docs` (S20, O69), keyless. It is a description, not evidence: the table above still rests on the O-measurements, and where the two disagree the measurement governs. Three things about it bear on this file — it lists no content-download path, so the `/htm` row is documented nowhere upstream (O69b); it documents only the `api_key` query parameter, but that is an omission in GovInfo's document and not a gap in the record: authentication belongs to the api.data.gov gateway in front of GovInfo, whose developer manual (S21) gives the `X-Api-Key` header as its primary, unconditional method and hedges the query parameter as supported "in some cases" — so the header transport R7 requires is both measured (O22) and documented upstream (O71); and its `404` for a search with no results is wrong — a zero-hit is HTTP 200 with `count: 0` and a null `offsetMark` (O69e).

A PLAW package summary carries a `references` array enumerating the US Code citations the law touches, by title and section (O18); its entries carry only the labels `Stat.` and `U.S.C` and bare section strings — nothing marks a citation as a note (O43a), and 39 of the 119th Congress's first 102 public laws carry no U.S.C. entry at all (O43a, corroborating R2). No v1 tool reads it, but it is the measured higher-recall alternative to the `uscodecitation` search field (O17 vs O18) and the designated v2 bridge source (Q6, E9). Measured limit: the array omits appendix citations that the same package's MODS carries as `USC citation` identifiers (`50 U.S.C. App. 2012` on PLAW-119publ75, O44d) — so it under-counts a law's Code footprint for appendix material, and any ground truth built from it inherits that.

## Formats, per collection — measured 2026-08-29

USCODE: package-level downloads are PDF, text (`/htm`), MODS, PREMIS, ZIP (O2). Granule-level: PDF, text (`/htm`), MODS only — `zipLink`/`premisLink` on a granule point back at the package (O9). No USLM/XML link at either level (O2, O9). GovInfo bulkdata carries no USCODE repository at all (repository list measured, O26) — within GovInfo, PDF/text/MODS is the complete USCODE format story; USLM for the Code exists only at OLRC, out of scope by R1.

PLAW: package-level downloads include `uslmLink` in addition to PDF, text, MODS, PREMIS, ZIP — observed on PLAW-118publ31 (O8). Coverage across congresses unmeasured (E4a). This falsifies the working assumption that XML is unavailable for PLAW; it is USCODE that lacks an XML download link on the API.

## Structure of the USCODE collection

Packages are one per title per edition year: `USCODE-{year}-title{n}` (O2, S3). Granules subdivide a package hierarchically down to leaf sections and can nest five levels deep (`USCODE-2024-title42-chap23-divsnA-subchapXIII-sec2210`, O14); leaves carry `granuleClass:"LEAF"` and a `leafRange` (O9). Appendix material is a granule subtree of the title package (`USCODE-2024-title28-app-federalru-rule9`, O19) and is full-text indexed. The collection holds 1,552 packages and ~2.03M granules (O1). Editions are annual from 1994 forward (S3); `historical:false` (the default) confines search to the current edition (O4 vs O7b).

A section granule's `/htm` payload contains the statutory text, then the source credit, then the statutory notes — for 42 U.S.C. 2210 the notes portion is ~60% of a 142KB payload (O15). Observed payload sizes: 36KB (O5) to 142KB (O15); no upper bound established. The payload embeds a `currentthrough:YYYYMMDD` comment plus `documentid` and `itempath` (O5, O15); the spec treats `currentthrough` as required provenance (`40-tools.md`).

## Public links — no key required (O53)

Every `download.*Link` in package and granule summaries points at `api.govinfo.gov` and returns 401 without the key (O53a) — those links are for the server, never for a person. Two unauthenticated forms exist for the same documents: the website content path, `https://www.govinfo.gov/content/pkg/{packageId}/pdf/{packageId}.pdf` for a package and `https://www.govinfo.gov/content/pkg/{packageId}/pdf/{granuleId}.pdf` for a granule, measured 4 of 4 by hand (O53b) and 7 of 7 on the links the server actually served — including a 2015 edition and a 2014 appendix granule, the first measurements off the current edition (O54b/c); and the summaries' own `detailsLink` (`https://www.govinfo.gov/app/details/…`, the document page, O53d). GovInfo's Link Service (S14: `https://www.govinfo.gov/link/plaw/{congress}/public/{n}?link-type=pdf`, `…/link/uscode/{title}/{section}?link-type=pdf[&year=]`) redirects to the content path (O53c, 7 of 7); the server does not build its public links through it because it resolves by citation form rather than by the identifiers the server already holds.
