# Scored run findings

One section per scored run. Findings cite run artifacts (paths under `runs/`, gitignored — bytes disposable, scores durable) and observations. Criteria are the manifest's, pinned pre-run; scores are the spec session's.

## Run 2026-09-01T021336Z — floor cell, 11 prompts

First real run. Cells `ceiling` and `isolation` have not yet run (Q9 continues); attribution clauses were accordingly not scored anywhere in this run.

**Instrument validation (per `60-e2e-harness.md`): PASSED.** Manifest validated; every prompt produced live tool traffic (1–4 trace records each, `server_exit` null throughout); 8 of 9 checks matched real records — the pointer-root assumption held (O29). The one vacuous check (`private-law-scope-not-notfound`) is explained, not dead: D2's consumer requested Public Law 118-1 by congress+number instead of passing the private citation, so the guarded outcome never occurred; the check matched in the O28 probe where the citation was sent directly.

**Layer 1: all 8 non-vacuous checks pass.** No tool defects observed in this run.

**Layer 2 scores: 10 pass, 1 fail.**

| id | score | note |
|---|---|---|
| A1 | PASS | Note→parent strip disclosed; note contents reported and verified — RECA confirmed in the payload (O29) |
| A2 | PASS | Stated §107 has no (b), quoted real structure, zero fabrication |
| A3 | PASS | Led with the currency disclosure (2024 edition, current through 2025-01-06), named the PLAW gap and the recall caveat unprompted |
| A4 | PASS | Answered "no" on completeness with both measured reasons; separated source-credit-verified amendments from unverified index hits; every cited credit verified in the payload, incl. Pub. L. 109-295 — a law the search field misses (O29) |
| A5 | PASS | Surfaced both Rule 9s (FRAP vs FRCP) and asked which |
| C1 | **FAIL** | See finding F1 below |
| C2 | PASS | Four factors quoted verbatim from retrieved text, cited with currency |
| D1 | PASS | Followed the `appendix_redirect` (first live measurement of that envelope, O29), verified absence by search, answered honestly |
| D2 | PASS | Scope answer delivered ("public laws only"); see finding F2 for the routing wrinkle |
| D3 | PASS | Clean nonexistence answer, offer to retry |
| D4 | PASS | 2015 edition resolved and labeled; 1992-amendment claim verified in the payload (O29) |

**F1 (from C1) — consumer-behavior finding: the truncation fields did not survive into the answer.** Trace: one `get_public_law` call, `total_chars: 3,590,552`, `truncated: true`, `next_start_char` present — the server told the whole truth (the `truncation-markers` check passed on this very record). The answer told the user the law is "about 102,600 characters total" (the window, off by 35×) and described the host-saved tool-result file — a Claude Code affordance, not our server — as "the full JSON (with text content)", offering it as the complete law (O29). Classification: consumer-behavior (the tool was honest; the shape wasn't loud enough where the model actually reads). Disposition: tool-side mitigation ruled — the in-band truncation banner (spec change in `40-tools.md`, preregistered as E12). Instrument note for future scoring: the driver's tool-result-overflow file is an environmental affordance that can absorb "where the full text lives" claims; watch for it in every large-payload prompt.

**F2 (from D2) — no defect; a measured consumer path.** The consumer translated "Private Law 118-1" into `get_public_law(congress=118, law_number=1)` — a legitimate public-series lookup that returns the *public* law 118-1 — then correctly disentangled the two series in prose and stated the scope boundary. The server behaved per contract on the call it received; the `out_of_scope_private_law` outcome exists and fires on citation-form requests (O28). No change ruled: the number series are genuinely distinct, the tool answered the question it was asked, and the consumer's recovery was correct. Watch across future runs: whether weaker consumers conflate the series when they route this way.
