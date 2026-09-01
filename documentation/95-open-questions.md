# Open questions

Q1–Q5 are answered — rulings in `96-rulings.md`. E1, E2, E7, E8 and most of E4 were run 2026-08-29; outcomes in `90-observations.md` O10–O19. Numbering continues.

## For the maintainer

Q6. v2 candidates deferred by R1/R2, parked here so they aren't lost: (a) a `N Stat. M` citation resolver that returns a GovInfo STATUTE pointer without ingesting anything; (b) a higher-recall PLAW→USC join — the package-summary `references` array demonstrably beats the `uscodecitation` search field (25/33 sampled recall, O21), and OLRC classification tables sit above both; (c) OLRC release points for current-text fetch-by-citation without an index. None are v1. Additions from later measurements: (d) the bulkdata COMPS repository (Statute Compilations in USLM — certain laws maintained as amended, O26) as a possible laws-as-amended source. No maintainer action needed until a v2 conversation starts.

Q7 (E2E harness) is answered and ruled — R10 in `96-rulings.md`, maintainer answers verbatim in commit 198cd0c, contract in `60-e2e-harness.md`, manifest at `e2e-manifest.json`. Remaining threads:

Q7e-completion — CLOSED by R11 (2026-08-31): the harness became the standalone mcp-e2e project, the suite (manifest, groundings, scored findings) is spec-owned here, cadence is manual. Nothing left to confirm.

Q9. First run of the suite: after `mcp-e2e validate` passes, run the smoke cell for instrument validation (60-e2e-harness.md, "First-run instrument validation"), then the three gating cells. The spec session scores. Awaiting the maintainer running the harness (the spec session doesn't have mcp-e2e).

Q8. Group F needs 8–12 **verbatim** questions from real research sessions — congressMCP's sourcing rule, adopted whole: they must not be written by anyone who knows the internals, and the spec session is disqualified from authoring them by construction. The manifest ships with Group F empty and carries the caveat. Paste originals when available.

## Preregistered experiments — pending

E11 (hand-over — needs Codex CLI with both auth modes, which the spec session does not have). Claim from congressMCP work: ChatGPT-authenticated Codex cannot have web fetching disabled; the maintainer suspects a way to do it was found only after switching to API auth. Measurement: attempt to fully disable web/network tools under (a) ChatGPT auth and (b) API-key auth, verifying with a prompt that can only be answered by fetching (expected: fetch succeeds or tool remains available under (a); disabled verifiably under (b)). Expected: the claim holds → the harness MUST refuse cross-vendor cells without API-key auth (R10). Falsifier: a ChatGPT-auth configuration that verifiably disables fetching → the mandate relaxes to requiring that configuration.

## Run — see observations

E5's remainder ran 2026-08-29 (O22): `X-Api-Key` header auth confirmed with a 401 no-credential control — and promoted from alternative to the only permitted transport by R7.

E9 ran 2026-08-29 (protocol in commit a455a66, outcome O21): 25/33 recall, recency hypothesis falsified — the gap is structural. Q6(b) is now measured and awaits a maintainer ruling on whether a v2 references-array-based join gets designed.

## Preregistered experiments

None pending. E1–E10 have all run; outcomes are O10–O26 (see `90-observations.md`). New experiments get preregistered here before running, per convention.

Closed 2026-08-30: E3 — `resultLevel:"package"` zero-hits granule-field queries, a hazard not a tool (O23). E4a — PLAW USLM boundary at the 113th Congress (O25). E6 — bulkdata has no USCODE repository; GovInfo's USCODE format story is complete as measured (O26). E10 — direct appendix citation forms exist; the appendix redirect upgraded to direct resolution with the redirect demoted to zero-hit fallback (O24).
