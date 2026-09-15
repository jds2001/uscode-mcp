# Work orders for the implementation session

Each order is self-contained: what to build, the contract it implements, the evidence it rests on, and the artifacts the spec session will ask for before recording it as done. An order is closed only when its verification artifacts are in `90-observations.md`; the implementation session's own report is a claim until then. The implementation session does not write in `documentation/`; deliver artifacts by commit message, trace files outside this directory, or by handing them to the maintainer.

## WO-1 — `possibly_superseded` on `get_us_code_section` (R14a/b/c; contract in `40-tools.md`, "Staleness indicator"; measured basis O43)

**Status:** OPEN, issued 2026-09-15. Q13 is answered: build fire-always with no opt-in argument. Nothing about this order is waiting on the maintainer.

**What it is.** Every successful `get_us_code_section` response carries a `possibly_superseded` object saying whether GovInfo's PLAW index lists any public law published after the returned edition's `currentthrough` date against this section. It is an indicator in both directions and never a certification (R14a): a fire does not mean the text is stale, and silence does not mean it is current.

**The detector query.** One `POST /search` against `collection:PLAW`, exactly this shape:

```
collection:PLAW publishdate:range({since},) uscodecitation:"{title} U.S.C. {section}"
```

- `{since}` is the response's own `currentthrough` plus one day, ISO `YYYY-MM-DD`, open-ended upper bound. `currentthrough` is the value already parsed from the granule HTML comment for provenance (O5, O15), so the bound is correct for `year`-selected editions too. Never hard-code `congress:119` or a fixed date.
- `publishdate`, never `approveddate`: `approveddate` ranges return HTTP 500 upstream in every form tried (O43f). The `publishdate` form was measured equal to the `congress:119` ground truth (104 = 104) and exact at the Congress boundary (O43f).
- `{title}` and `{section}` are the section actually resolved, after the mandatory strips (subsection parenthetical O11, trailing "note" O16). Citation string form is `"42 U.S.C. 2210"` — the form measured in O43c/O43d/O43f.
- Same authentication as every other call (R7, `X-Api-Key`).

**Three states on a `status` discriminator, never two.**

| `status` | when | must carry |
|---|---|---|
| `laws_indexed` | upstream 200, `count` ≥ 1 | true upstream `count`; `laws[]` of `{package_id, title, date_issued}`, capped, with the cap and the true total stated whenever capping happened (the disambiguation-totals rule); the fixed caveat that this indicates possible change, not that the text is stale |
| `none_indexed` | upstream 200, `count` = 0 | the fixed caveat that this is NOT a currency check and that absence of a match is not evidence the text is current — the index misses about one in seven listed (law, section) pairs (O43b) and one in four in an earlier sample (O21) |
| `not_checked` | anything else: non-200, HTTP 429, timeout, malformed body | the upstream HTTP status and body verbatim, or the local reason (timeout, parse failure); 429 named as rate-limit, distinct from other failures (the three-outcomes rule, `40-tools.md`) |

Every state, including `not_checked`, echoes the exact `query` string sent and the `since` date it was bounded by. When `stripped_note` is true on the lookup, the object states in-band that the check ran against the parent section and that a law affecting only the note may be indexed against neither citation (O17/O18, O43b).

**Concurrency and failure isolation.** Issue the detector query concurrently with the `txtLink` fetch, not after it; measured from the spec session's network position a keep-alive request costs ~200 ms and the detector 210–280 ms, so run in parallel with the text fetch it adds ~0 wall-clock in the common case (O43e). A detector failure of any kind never fails the lookup: the section text is returned and the object says `not_checked`. Bound the wait — if the detector has not returned within a small budget after the text is ready, report `not_checked` with reason `timeout`; do not hold the text for it. The budget value is the implementation's choice; state it in the report.

**Do not.** Retrieve or parse the listed laws to resolve effective dates (declined, R14a). Use `approveddate` ranges (O43f). Collapse `not_checked` into `none_indexed`, or omit the object on any success. Add an opt-in flag (Q13 closed it). Cache detector results across lookups without stating so — and if you do cache, the cache key must include `since`, because two editions of the same section have different bounds. Write anything under `documentation/`.

**Unit tests (repo rule: failure paths, not just the happy path).** Mock the upstream at the HTTP layer and cover at least: 200 with hits → `laws_indexed` with `count` and capping stated when hits exceed the cap; 200 with zero hits → `none_indexed` with the caveat text; 500 → `not_checked` carrying status and body; 429 → `not_checked` naming rate-limit; timeout → `not_checked` with `timeout`, and the lookup still succeeds with full text; malformed JSON → `not_checked`; `stripped_note` lookup → query built on the parent section and the in-band statement present; a `year`-selected edition → `since` derived from that edition's `currentthrough`, not the newest; `query` and `since` present in every state. Mocked fixtures are not evidence of upstream behavior — they prove the code's handling of each shape, which is what they are for.

**Verification artifacts the spec session will ask for** (traces, not summaries — the recorded request and the recorded response, from real upstream calls):

1. `42 U.S.C. 2210` → `laws_indexed`. Expected to list PLAW-119publ74 (O43d); ground truth also lists publ21, and the detector missing it is the measured instrument gap, not a defect.
2. `17 U.S.C. 107` → `none_indexed` (O43d: silent, and no 119th-Congress law lists it).
3. A forced upstream failure (bad key on the detector call only, or a stubbed 500) → `not_checked` with the status and body, and the section text delivered in full alongside it.
4. `42 U.S.C. 2210 note` → the `stripped_note` in-band statement, query built on `42 U.S.C. 2210`.
5. `17 U.S.C. 107` with `year: 2023` → `since` equal to the 2023 edition's `currentthrough` plus one day, so the bound is visibly edition-relative.
6. The exact query strings for 1–5, and the measured wall-clock of a lookup with the detector on versus off, n stated.

The spec session will then black-box the same five inputs against the running server (as it did for R12 in O37 and R13 in O39) before marking this order closed and adding the manifest checks.

**Out of this order.** E15's api-surface extension is harness-side (mcp-e2e), not this server. The A/D isolation-cell runs and Group F questions are spec-session and maintainer work.
