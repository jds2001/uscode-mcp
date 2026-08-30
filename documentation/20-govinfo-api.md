# GovInfo API surface

The server depends on api.govinfo.gov. Everything here is either measured (O-refs) or flagged.

## Authentication

An api.data.gov API key, passed as the `api_key` query parameter (observed working, O1–O9) or the `X-Api-Key` header (documented by api.data.gov; untested here). The server reads it from the `GOVINFO_API_KEY` environment variable. The key must never be committed; locally it lives in the repo-root `.env`, which is gitignored.

Rate limits are api.data.gov's: `DEMO_KEY` is tightly limited; a registered key is documented as 1,000 requests/hour. Unverified — the implementation must surface HTTP 429 as a distinct rate-limited outcome (see `40-tools.md`), and the real limit should be read from `X-RateLimit-*` response headers rather than assumed (E5 in 95-open-questions.md).

## Endpoints the server uses

| Endpoint | Purpose | Evidence |
|---|---|---|
| `POST /search` | All discovery: citations by metadata, topics by full text | O4, S1 |
| `GET /packages/{packageId}/summary` | Package metadata + download link map | O2, O8 |
| `GET /packages/{packageId}/granules/{granuleId}/summary` | Granule metadata + download link map | O9 |
| `GET /packages/{packageId}/granules/{granuleId}/htm` | Section text (HTML payload) | O5 |
| Download links (`pdfLink`, `modsLink`, `uslmLink`, …) | Taken verbatim from summaries/search results, never constructed | O4 |

The `/collections`, `/published`, and `/related` endpoints exist but no v1 tool depends on them; `/collections` was used only as an instrument (O1).

## Formats, per collection — measured 2026-08-29

USCODE: package-level downloads are PDF, text (`/htm`), MODS, PREMIS, ZIP (O2). Granule-level: PDF, text (`/htm`), MODS only — `zipLink`/`premisLink` on a granule point back at the package (O9). No USLM/XML link at either level (O2, O9). GovInfo bulkdata may carry USCODE USLM separately — unverified, out of v1 scope (E6).

PLAW: package-level downloads include `uslmLink` in addition to PDF, text, MODS, PREMIS, ZIP — observed on PLAW-118publ31 (O8). One package observed; USLM coverage across congresses is an open measurement (E4). This falsifies the working assumption that XML is unavailable for PLAW; it is USCODE that lacks an XML download link on the API.

## Structure of the USCODE collection

Packages are one per title per edition year: `USCODE-{year}-title{n}` (O2, S3). Granules subdivide a package hierarchically down to leaf sections: `USCODE-2024-title17-chap1-sec107`, `granuleClass: "LEAF"`, with a `leafRange` giving the section span (O9). The collection holds 1,552 packages and ~2.03M granules (O1). Editions are annual from 1994 forward ("virtual main editions", S3); `historical:false` (the default) confines search to the current edition (O4 vs O7b).

The granule HTML embeds provenance the plain metadata does not carry: a `currentthrough:YYYYMMDD` comment stating the date the edition is current through, plus `documentid` and `itempath` comments (O5). The spec treats `currentthrough` as required provenance (see `40-tools.md`).
