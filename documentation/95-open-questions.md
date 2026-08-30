# Open questions

Q1–Q5 are answered — rulings in `96-rulings.md`. E1, E2, E7, E8 and most of E4 were run 2026-08-29; outcomes in `90-observations.md` O10–O19. Numbering continues.

## For the maintainer

Q6. v2 candidates deferred by R1/R2, parked here so they aren't lost: (a) a `N Stat. M` citation resolver that returns a GovInfo STATUTE pointer without ingesting anything; (b) a higher-recall PLAW→USC join — the package-summary `references` array demonstrably beats the `uscodecitation` search field (25/33 sampled recall, O21), and OLRC classification tables sit above both; (c) OLRC release points for current-text fetch-by-citation without an index. None are v1. Additions from later measurements: (d) the bulkdata COMPS repository (Statute Compilations in USLM — certain laws maintained as amended, O26) as a possible laws-as-amended source. No maintainer action needed until a v2 conversation starts.

Q7. E2E test harness — **green-lit 2026-08-30, now active spec work.** The harness drives the server through a real consumer model and verifies behavior from the R8 traces (the congressMCP pattern; Q7a confirmed traces are MCP-level). The maintainer has congressMCP examples to share — more than fit in conversation. Requirements questions below, for inline answers; the congressMCP material can be pasted under Q7f or dropped anywhere in `documentation/` and pointed to.

Q7b. What does the harness assert against a trace? Candidates, pick/rank/add: outcome-taxonomy correctness (zero-hit vs upstream-error vs rate-limited never collapsed), provenance completeness on text payloads (currentthrough, edition, links), truncation markers present whenever text was windowed, disambiguation totals (count vs capped list), secret hygiene (no key material anywhere in a trace), tool-selection sanity (did the consumer model reach the right tool for the prompt).

Q7c. Live model per run, recorded-session replay, or record-then-replay (live run captures a golden trace, CI replays it)? The non-vacuity rule pushes toward at least periodic live runs — replay of a recorded session is itself a fixture once recorded.

Q7d. Which consumer model(s), driven how (Claude via API tool-runner, Claude Code headless, something else), and what prompt set — hand-written scenarios, or derived from the spec's measured cases (17 U.S.C. 107, 42 U.S.C. 2210 note, Pub. L. 118-31, the appendix Rule 9 ambiguity, a known zero-hit)?

Q7e. Confirm the ownership split: harness code lives implementation-side; the verification contract — what a conforming trace looks like, pass/fail criteria — lives here in the spec. And is the harness a CI gate, an opt-in marker (the integration-marker idea from the v1 report), or manual-only?

Q7f. congressMCP examples land here.

## Run — see observations

E5's remainder ran 2026-08-29 (O22): `X-Api-Key` header auth confirmed with a 401 no-credential control — and promoted from alternative to the only permitted transport by R7.

E9 ran 2026-08-29 (protocol in commit a455a66, outcome O21): 25/33 recall, recency hypothesis falsified — the gap is structural. Q6(b) is now measured and awaits a maintainer ruling on whether a v2 references-array-based join gets designed.

## Preregistered experiments

None pending. E1–E10 have all run; outcomes are O10–O26 (see `90-observations.md`). New experiments get preregistered here before running, per convention.

Closed 2026-08-30: E3 — `resultLevel:"package"` zero-hits granule-field queries, a hazard not a tool (O23). E4a — PLAW USLM boundary at the 113th Congress (O25). E6 — bulkdata has no USCODE repository; GovInfo's USCODE format story is complete as measured (O26). E10 — direct appendix citation forms exist; the appendix redirect upgraded to direct resolution with the redirect demoted to zero-hit fallback (O24).
