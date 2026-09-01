# E2E suite — uscode-mcp's half of the mcp-e2e contract

The harness is a standalone project, `mcp-e2e` (R11). Its mechanics — manifest loading, cells, drivers, checks engine, run artifacts, the four check outcomes — are `SUITE-AUTHORING.md`'s to define (with the harness repo's own spec normative on conflict). This file holds only what is uscode-mcp-specific: the suite.

The suite is spec-session property: the manifest (`e2e-manifest.json`, loaded verbatim by the harness — no copies), the groundings behind it, and the scored findings from runs. Two runs are comparable only on matching manifest hashes or an explained delta.

## Binding suite rules

**Preregistration-of-scoring** (inherited, restated because it binds this directory): `pass`/`fail` are pinned before a run and never edited after seeing a result they would score; criteria change only between runs with rationale committed. `watch` fields pin attention, not scoring, and may be edited freely.

**First-run instrument validation.** The Layer-1 checks were authored against the measured envelope (O28) plus one assumption — that the harness roots the tool response at `/response`, putting the structured payload at `/response/structuredContent/...`. Before any check outcome is scored: `mcp-e2e validate` must accept the manifest, and one smoke cell must show every check non-vacuous on a run that exercised its surface. A vacuous check is an instrument question, never a pass — if the pointer root is wrong, every check will be vacuous at once, which is the tripwire working.

**Outcome vocabulary.** Measured members are pinned (O28): `success`, `not_found`, `ambiguous`, `out_of_scope_private_law`. Implementation-claimed members (the appendix redirect shape, upstream-failure, rate-limited, `format_not_available`) are not bound by any check until measured — a check written against a guessed name false-fails legitimate outcomes. When a run's trace exhibits a new outcome shape, measure it there (the trace is the measurement) and extend the checks in the same commit as the observation.

**Attribution discipline.** Fabrication and answered-from-priors clauses (in A2, C2, D3) are scorable only in the `isolation` cell, where trace scope equals tool surface — SUITE-AUTHORING's rule, applied to the three prompts that need it. In `floor`/`ceiling` those clauses are watch items, never scores.

**Edition staleness.** Groundings marked edition-dependent are pinned to the 2024 edition (`currentthrough` 2025-01-06, O15). When GovInfo publishes a newer annual edition, those groundings are stale: re-measure before scoring any run. The harness's per-run upstream identifiers make staleness detectable after the fact; the fixture `content_hash_sha256_16` values (O28) make it checkable by re-fetch.

## What Layer 1 asserts, and why

Each check in the manifest maps to a `40-tools.md` contract: outcome discriminator present (three-outcomes taxonomy); zero-hits echo the upstream query; normalization strips disclosed (the diagnosability the maintainer named in Q7b); provenance blocks complete, `currentthrough` included (staleness disclosure, load-bearing after R1); truncation markers on every window (measured live against the 3.59M-char NDAA, O28); disambiguation true totals; `recall_caveat` on every successful `search_public_laws` response (O21's gap must not be laundered); private-law scope outcome distinct from not-found (R6). Rate-limit behavior stays unit-test territory (untriggerable live, O13).

## Layer 2 and classification

Layer 2 scoring is the human's and/or this session's, from artifacts, never summaries. Every failure is classified before filing — consumer-behavior finding vs tool defect vs instrument defect — and no finding of any class is recorded from a defective instrument; a zero-trace run is BROKEN, never abstention. Scored findings are committed here, each citing the run artifacts it was scored from.

## Cells and gating

Three gating cells: `floor` (Sonnet, no thinking, crowded via the harness-owned `neutral-file-triage@2` procedure — collision review attested in the manifest: statutory-law retrieval is disjoint from office notes-triage), `ceiling` (Opus, high thinking, fresh), `isolation` (the four server tools exactly, fresh — the attribution cell). The grid grows only when a question needs a new cell. Cross-vendor cells remain deferred behind E11: if it confirms ChatGPT-auth Codex cannot disable web fetching, cross-vendor cells run under API-key auth or not at all.

## Group F

Empty until Q8 delivers 8–12 `verbatim-original` questions. Nothing scored as a Group F measurement before then; `derived` stand-ins are not authored at all, having been quarantined as indicative-only in the ancestor suite.
