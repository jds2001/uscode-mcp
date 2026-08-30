# Open questions

## For the maintainer (requirements — do not guess)

Q1. Pre-1995 law: PLAW starts at the 104th Congress (S4). Is the STATUTE (Statutes at Large) collection in scope for older enacted law, or is "US Code + PLAW from 1995" the product?

Q2. Navigation: is a browse/table-of-contents tool (list a title's chapters/sections via the granules listing) wanted in v1, or is search-only discovery enough? The granules listing is paginated and Title 42-scale titles will need many pages; cost is real.

Q3. Appendices: USCODE has appendix granule trees (e.g. `USCODE-2008-title28-app`, S3). Should `get_us_code_section` resolve "28 U.S.C. App." citations in v1, or report them as out of scope?

Q4. Repo hygiene, outside my write authority: `CONTRIBUTING.md` and `documentation/CLAUDE.md` carry congressMCP/bill-text content (fulltext/, KNOWN_FAILURES, "Contributing to CongressMCP") that doesn't describe this repo. Update or intentional?

Q5. Private laws: `lawtype:private` exists (S4). In scope for `get_public_law`, or public-only?

## Preregistered experiments — not yet run

E1. Citation variant tolerance: `citation:"17 U.S.C. § 107"` and `citation:"17 U.S.C. 107(b)"`. Expect: `§` variant resolves (matching looked tolerant in O7a); subsection variant returns 0 (granule metadata is section-level, O9). Falsifiers: the reverse.

E2. PLAW resolution: `collection:PLAW congress:118 docnumber:31` should return exactly package `PLAW-118publ31`. Falsifier: 0 hits or multiple (e.g. private-law collision → then `lawtype` becomes mandatory in the recipe).

E3. `resultLevel:"package"` behavior on a USCODE citation query — does it return the title package instead of the section granule? Determines whether the flag is useful for edition-level questions.

E4. Reverse lookup recall: `collection:PLAW uscodecitation:"17 U.S.C. 107"` — measure hits and spot-check against a known amending law. E4a: USLM availability across congresses 104–119 (sample summaries per congress).

E5. Rate limits with the real key: read `X-RateLimit-Limit`/`Remaining` headers off a normal response; verify `X-Api-Key` header auth works as an alternative to the query param.

E6. USCODE USLM via bulkdata (www.govinfo.gov/bulkdata): exists? current? If yes it changes the format story in `20-govinfo-api.md` — v2 question either way.
