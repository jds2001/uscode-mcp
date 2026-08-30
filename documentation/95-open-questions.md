# Open questions

Q1–Q5 are answered — rulings in `96-rulings.md`. Numbering continues from there.

## For the maintainer

Q6. v2 candidates deferred by R1/R2, parked here so they aren't lost: (a) a `N Stat. M` citation resolver that returns a GovInfo STATUTE pointer without ingesting anything; (b) OLRC classification tables / per-section pending updates as the PLAW→USC bridge; (c) OLRC release points for current-text fetch-by-citation without an index. None are v1. No maintainer action needed until v1 ships.

## Preregistered experiments — not yet run

E1. Citation variant tolerance: `citation:"17 U.S.C. § 107"` and `citation:"17 U.S.C. 107(b)"`. Expect: `§` variant resolves (matching looked tolerant in O7a); subsection variant returns 0 (granule metadata is section-level, O9). Falsifiers: the reverse.

E2. PLAW resolution: `collection:PLAW congress:118 docnumber:31` should return exactly package `PLAW-118publ31`. Falsifier: 0 hits or multiple (e.g. private-law collision → then `lawtype` becomes mandatory in the recipe).

E3. `resultLevel:"package"` behavior on a USCODE citation query — does it return the title package instead of the section granule? Determines whether the flag is useful for edition-level questions.

E4. Reverse lookup recall: `collection:PLAW uscodecitation:"17 U.S.C. 107"` — measure hits and spot-check against a known amending law. E4a: USLM availability across congresses 104–119 (sample summaries per congress).

E5. Rate limits with the real key: read `X-RateLimit-Limit`/`Remaining` headers off a normal response; verify `X-Api-Key` header auth works as an alternative to the query param.

E6. USCODE USLM via bulkdata (www.govinfo.gov/bulkdata): exists? current? If yes it changes the format story in `20-govinfo-api.md` — v2 question either way.

E7. Notes (load-bearing per R4). E7a: `citation:"42 U.S.C. 2210"` resolves to one leaf granule in the current edition. E7b: that granule's `/htm` payload contains the section's statutory notes after the statutory text (checkable: note-style headings and source credits present; payload much larger than bare section text). Expect yes — falsifier: payload ends at the statutory text, in which case notes live elsewhere and the whole retrieval contract for notes must be redesigned. E7c: `citation:"42 U.S.C. 2210 note"` expect 0 hits (falsifier: it resolves), in which case the tool contract strips a trailing "note" and resolves the parent section.

E8. Appendices (R4): find how appendix material is indexed. Probe: full-text search scoped `collection:USCODE` for a known appendix document (e.g. Federal Rules material under title 28 app) and observe whether hits are granules with `-app` in the ID and what their `citation`-style metadata looks like. Expect: appendix granules exist inside the title package's granule tree (S3 shows `USCODE-2008-title28-app` IDs). Unknown: whether a `citation:"28 U.S.C. App."`-form query matches anything.
