# Open questions

Q1–Q5 are answered — rulings in `96-rulings.md`. E1, E2, E7, E8 and most of E4 were run 2026-08-29; outcomes in `90-observations.md` O10–O19. Numbering continues.

## For the maintainer

Q6. v2 candidates deferred by R1/R2, parked here so they aren't lost: (a) a `N Stat. M` citation resolver that returns a GovInfo STATUTE pointer without ingesting anything; (b) a higher-recall PLAW→USC join — the package-summary `references` array demonstrably beats the `uscodecitation` search field (O17 vs O18), and OLRC classification tables sit above both; (c) OLRC release points for current-text fetch-by-citation without an index. None are v1. No maintainer action needed until v1 ships.

## Preregistered experiments — not yet run

E3. `resultLevel:"package"` behavior on a USCODE citation query — does it return the title package instead of the section granule? Determines whether the flag is useful for edition-level questions.

E4a. USLM availability across PLAW congresses 104–119 (sample one package summary per congress for `uslmLink` presence). Bounds the `get_public_law` `format:"uslm"` story.

E5 (remainder). `X-Api-Key` header auth as an alternative to the `api_key` query parameter. Expect it works (api.data.gov standard); falsifier: 403.

E6. USCODE USLM via bulkdata (www.govinfo.gov/bulkdata): exists? current? If yes it changes the format story in `20-govinfo-api.md` — v2 question either way.

E9. Characterize the `uscodecitation` recall gap (O17/O18) before anyone automates over that field: for a sample of recent public laws, compare each package's `references` array against what `uscodecitation` queries return. Expected shape: search-field recall strictly ≤ references-array recall, with the gap concentrated in recent laws. Required before Q6(b) graduates to a design.

E10. Appendix citation forms: does any `citation:`-style field match appendix granules ("28 U.S.C. App.", rule-number forms)? O19 established full-text reachability only. Outcome decides whether `get_us_code_section`'s appendix redirect (see `40-tools.md`) can be upgraded to direct resolution.
