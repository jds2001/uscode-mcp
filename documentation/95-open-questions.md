# Open questions

Q1–Q5 are answered — rulings in `96-rulings.md`. E1, E2, E7, E8 and most of E4 were run 2026-08-29; outcomes in `90-observations.md` O10–O19. Numbering continues.

## For the maintainer

Q6. v2 candidates deferred by R1/R2, parked here so they aren't lost: (a) a `N Stat. M` citation resolver that returns a GovInfo STATUTE pointer without ingesting anything; (b) a higher-recall PLAW→USC join — the package-summary `references` array demonstrably beats the `uscodecitation` search field (O17 vs O18), and OLRC classification tables sit above both; (c) OLRC release points for current-text fetch-by-citation without an index. None are v1. No maintainer action needed until v1 ships.

## Preregistered experiments — not yet run

E3. `resultLevel:"package"` behavior on a USCODE citation query — does it return the title package instead of the section granule? Determines whether the flag is useful for edition-level questions.

E4a. USLM availability across PLAW congresses 104–119 (sample one package summary per congress for `uslmLink` presence). Bounds the `get_public_law` `format:"uslm"` story.

E5 (remainder). `X-Api-Key` header auth as an alternative to the `api_key` query parameter. Expect it works (api.data.gov standard); falsifier: 403.

E6. USCODE USLM via bulkdata (www.govinfo.gov/bulkdata): exists? current? If yes it changes the format story in `20-govinfo-api.md` — v2 question either way.

E9. Characterize the `uscodecitation` recall gap (O17/O18) before anyone automates over that field. Protocol, fixed before running: sample = ten public laws chosen deterministically across congresses 115–119 (115publ97, 115publ232, 116publ92, 116publ136, 117publ58, 117publ169, 118publ5, 118publ31, 119publ4, 119publ21); for each, read the package summary's `references` array, flatten USCODE entries to (title, section) pairs, and membership-test the first, middle, and last pair — plus (42, 2210) where present — via `collection:PLAW uscodecitation:"{t} U.S.C. {s}" congress:{c} docnumber:{n}`, where `count≥1` = indexed and `count:0` = miss. Instrument control: any law whose sampled pairs all miss gets a `congress`+`docnumber`-only query to distinguish a field miss from the law being absent from the index entirely. Preregistered expectations: overall search-field recall < 100% of references-array entries; misses concentrated in the 119th Congress; the known 119publ21×42 U.S.C. 2210 miss reproduces. Falsifier: recall is 100% everywhere except 119publ21 — then the gap is a one-off ingestion artifact rather than a field property, and Q6(b) loses its urgency. Required before Q6(b) graduates to a design.

E10. Appendix citation forms: does any `citation:`-style field match appendix granules ("28 U.S.C. App.", rule-number forms)? O19 established full-text reachability only. Outcome decides whether `get_us_code_section`'s appendix redirect (see `40-tools.md`) can be upgraded to direct resolution.
