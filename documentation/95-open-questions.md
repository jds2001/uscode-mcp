# Open questions

Q1–Q5 are answered — rulings in `96-rulings.md`. E1, E2, E7, E8 and most of E4 were run 2026-08-29; outcomes in `90-observations.md` O10–O19. Numbering continues.

## For the maintainer

Q6. v2 candidates deferred by R1/R2, parked here so they aren't lost: (a) a `N Stat. M` citation resolver that returns a GovInfo STATUTE pointer without ingesting anything; (b) a higher-recall PLAW→USC join — the package-summary `references` array demonstrably beats the `uscodecitation` search field (25/33 sampled recall, O21), and OLRC classification tables sit above both; (c) OLRC release points for current-text fetch-by-citation without an index. None are v1. Additions from later measurements: (d) the bulkdata COMPS repository (Statute Compilations in USLM — certain laws maintained as amended, O26) as a possible laws-as-amended source. No maintainer action needed until a v2 conversation starts.

Q7. E2E test harness: the maintainer floated building a harness that drives the server through a real consumer model and verifies behavior from the R8 traces (the congressMCP pattern). The trace facility it needs is now specced (`40-tools.md`); the harness itself is unscoped — awaits a maintainer go-ahead and a design conversation. (Q7a — whether traces record MCP-level tool calls or upstream HTTP — was confirmed as MCP-level by the maintainer, 2026-08-29; R8 stands as written.)

## Run — see observations

E5's remainder ran 2026-08-29 (O22): `X-Api-Key` header auth confirmed with a 401 no-credential control — and promoted from alternative to the only permitted transport by R7.

E9 ran 2026-08-29 (protocol in commit a455a66, outcome O21): 25/33 recall, recency hypothesis falsified — the gap is structural. Q6(b) is now measured and awaits a maintainer ruling on whether a v2 references-array-based join gets designed.

## Preregistered experiments

None pending. E1–E10 have all run; outcomes are O10–O26 (see `90-observations.md`). New experiments get preregistered here before running, per convention.

Closed 2026-08-30: E3 — `resultLevel:"package"` zero-hits granule-field queries, a hazard not a tool (O23). E4a — PLAW USLM boundary at the 113th Congress (O25). E6 — bulkdata has no USCODE repository; GovInfo's USCODE format story is complete as measured (O26). E10 — direct appendix citation forms exist; the appendix redirect upgraded to direct resolution with the redirect demoted to zero-hit fallback (O24).
