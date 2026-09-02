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

## Run 2026-09-01T023317Z — floor cell, C1 only

**Instrument: healthy, with one decisive reading — the E12 banner is NOT in this trace.** Both `get_public_law` responses carry correct structured truncation fields (`total_chars: 3,590,552`, `truncated: true`, `next_start_char`), but `text.content` opens with the raw GPO text, no banner line. The change E12 preregisters was not present in the server under test. Checks: 3 pass, 7 vacuous — all vacuous-by-construction for a single-prompt run that exercised only the public-law success surface; none dead.

**C1 score: PASS.** The answer states the true total (3,590,552 characters), makes no claim of having delivered or read the full text, and offers section-wise retrieval, a summary, or an explicitly-permission-gated file save. Every pinned pass element present; no fail element.

**But this pass does not close E12 — it reframes F1.** Two floor samples of C1 now exist, both against a banner-less server: one fail (run 021336Z), one pass (this run). So the F1 behavior is *variable at the floor*, not deterministic; the first run's FAIL and this run's PASS are both single-sample point estimates. E12 stays open exactly as preregistered: it is tested only by a run whose trace shows the banner at the head of `text.content`, and its expectation is now sharpened by this measurement — the banner's job is to eliminate the failing tail of a variable behavior, not to flip a deterministic failure.

**Standing scoring note (applies to all floor-cell findings):** a single floor sample is a point estimate of variable behavior. A PASS on one sample is weak evidence of reliability; a FAIL on one sample is a real exhibit of the failure mode but not a rate. Rate claims need repeated samples, which cost runs — order them only where a finding's disposition depends on the rate.

## Run 2026-09-01T024850Z — floor cell, C3 only (the E13 measurement)

**C3 score: PASS, clause (a) — located and grounded.** Nine tool calls, 99 seconds, ~135K of 3.59M chars retrieved (~4%). Every checkable claim matches the E13 grounding: Title XIII Subtitle B, the §1331 oversight framework, §1333 reporting, the AUKUS Submarine Transfer Authorization Act with the three-Virginia-class authorization. Floor cell, so strict attribution is unscorable, but the section numbers and structure appear in the windows the trace shows were read.

**The strategy is the finding.** The consumer: (1) read the TOC region in three windowed calls, (2) invented a within-law presence check the tool description never taught it — `packageid:PLAW-118publ31 "AUKUS partnership oversight and accountability framework"` → count 1, now verified with controls and pinned as a measured recipe (O30), (3) probed two offsets, then (4) jumped to ~1.26M–1.35M — the measured ~35% cluster — and read 90K of content. TOC-informed offset jumping, not sequential paging: E13's falsifier direction, at the floor, on the first attempt.

**E13 disposition: rung 0 — no machinery.** The preregistered falsifier ("consumer reliably locates the material cheaply via TOC-informed jumps") fired directionally; n=1 at the floor cannot establish "reliably", but the burden has flipped: the gap's best-constructed test failed to exhibit it. Per the R3 philosophy (build when a consumer stumbles, not before), no rung of the ladder is built now. Two spec actions instead: the `packageid:` recipe is documented in the search tool descriptions (`30-search.md`/`40-tools.md`, this commit) so future consumers get taught what this one had to invent, and E13 reopens only on a real exhibited failure — at which point rung 1 (transient within-law search) is the preregistered next step, not a fresh debate.

## Run 2026-09-02T035906Z — floor + ceiling + isolation over C1/C3/C4

**Instrument: clean across all nine cell×prompt combinations** (live traffic everywhere, no server exits). The three R12/E12 checks matched real records and passed on their first live outing (`banner-leads-truncated-content`, `structure-present-or-disclosed`, `find-reports-true-totals`); the vacuous checks are all prompt-selection artifacts (no zero-hit/ambiguous/PLAW-search surfaces in this prompt set).

**Scores: nine of nine PASS.**

**E12 CLOSED — confirmed per preregistration.** The banner is in every truncated trace record, and all three cells' C1 answers state the true total (3,590,552) and refuse to present a window as the whole; the falsifier (failure with banner present) did not occur. Floor C1 went from fail (021336Z, no banner) to pass-with-banner in 2 calls; the honest options framing appeared in every cell.

**E14 CLOSED — confirmed per preregistration.** Every cell on both locating tasks reached for `find` immediately; blind offset guessing appears nowhere in nine traces. C4: find('apolog…') → jump → verbatim quote, 3 calls at floor and isolation. All three cells quoted RECA §2(c) word-for-word as verified against the payload; the ceiling added the currency caveat and the restitution-not-gratuity framing unprompted. The non-note control (S8's caution): C3 at the floor took 4 calls against the 9-call pre-find baseline, with find(AUKUS)→66 hits replacing TOC-reading and offset triangulation entirely. The deferred notes-only retrieval mode stays dead — E14 was its reopening condition and the condition resolved against it.

**Small live validations worth keeping:** ceiling C3 sent a malformed needle (stray quote characters) and got the explicit zero-match envelope, then recovered — R12a's zero-match contract working in the wild. Ceiling C1 used `find` as a TOC probe (division headings → offsets), an unanticipated but legitimate use.

**Still unscored: the attribution clauses of A2/C2/D3** — the isolation cell now exists and behaved, but the A/D prompt groups have not yet run in it. The C4-isolation pass IS attribution-valid (trace scope = tool surface; quote verified against a trace-retrieved window).
