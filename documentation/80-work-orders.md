# Work orders for the implementation session

Each order is self-contained: what to build, the contract it implements, the evidence it rests on, and the artifacts the spec session will ask for before recording it as done. An order is closed only when its verification artifacts are in `90-observations.md`; the implementation session's own report is a claim until then. The implementation session does not write in `documentation/`; deliver artifacts by commit message, trace files outside this directory, or by handing them to the maintainer.

## WO-1 — `possibly_superseded` on `get_us_code_section` (R14a/b/c; contract in `40-tools.md`, "Staleness indicator"; measured basis O43)

**Status:** CLOSED 2026-09-15 — built at implementation commit 1d42c52, verified O44 (artifact review, black-box probe, and the two ratification measurements). Disposition of the order's own error: its premise that the detector is independent of the text fetch was wrong (the bound needs `currentthrough` from the fetched HTML); the implementation's cold/warm two-regime design is ratified and the contract corrected (O44c). Both implementation decisions submitted for ratification are ratified as interim behavior and superseded by WO-2 below: appendix `not_checked`/`no_measured_citation_form` stays as the fallback for appendix rules, and the private-law question is answered by measurement (O44e), not by leaving the query alone. The order text below is kept as issued, for the record.

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

## WO-2 — detector follow-ups from O44: `lawtype:public`, and numbered appendix sections (contract in `40-tools.md`, "Staleness indicator"; measured basis O44d/O44e)

**Status:** CLOSED 2026-09-15 — built at implementation commit faa9974, verified O45 (artifact review and black-box probe; the pinned caveat compares equal character for character). Two deviations from the artifact list accepted, one of them the order's own error: the tool has no by-id input, so "disambiguated by ids" was impossible — filed as Q14. The order text below is kept as issued, for the record.

**Change 1 — add `lawtype:public` to the pinned detector query.** New shape, exactly:

```
collection:PLAW lawtype:public publishdate:range({since},) uscodecitation:"{title} U.S.C. {section}"
```

Why: a live section fires today on a 119th-Congress private law — `10 U.S.C. 7274` → [PLAW-119pvtl2, PLAW-119publ60] on the WO-1 shape — and `get_public_law` refuses `pvtl` packages under R6, so the consumer would be handed an id it cannot retrieve. `lawtype:public` composes with the pinned shape, drops exactly the private package (O44e: 7274 → 1, 8298 → 2, 8300 → 1), leaves the public cases unchanged (42/2210 → 1, 20/1070a → 1), and partitions the collection exactly (60 + 5,939 = 5,999). `count` stays upstream's count for the query actually sent; the caveat text does not change. Everything else about the object is unchanged. Also a precision fix, not only a retrievability one: the private laws in the index cite sections to *waive* them for a named person ("Notwithstanding the time limitations specified in section 7274 of title 10 …"), never to amend them (O44f), so a private-law hit is a listing that cannot mean the section's text changed.

**Change 2 — run the detector for numbered appendix sections.** When the resolved granule is an appendix *section* (the citation normalized to `{title} U.S.C. App. {section}` with a numeric-led section, e.g. `18 U.S.C. App. 1201`), build the detector on the measured form:

```
collection:PLAW lawtype:public publishdate:range({since},) uscodecitation:"{title} U.S.C. App. {section}"
```

Measured basis (O44d): the field carries this form (`"50 U.S.C. App. 2012"` → 19 all-time, 1 since 2025-01-07; `"5 U.S.C. App. 3"` → 29; MODS witness on PLAW-119publ75). Appendix *rules* (`28 U.S.C. App. Rule N`, and any appendix citation whose qualifier is not a numbered section) keep the WO-1 fallback — `not_checked`, `reason: no_measured_citation_form`, `query: null` — because no form is measured for them (0 hits on `"28 U.S.C. App."` and `"28 U.S.C. App. Rule 9"`). The `checked_citation` field carries the App. form actually queried.

**Change 3 — pin the `laws_indexed` caveat to the contract wording.** Replace the current `laws_indexed` caveat with the text now pinned verbatim in `40-tools.md` ("INDICATOR ONLY — NOT A FINDING THAT THE TEXT CHANGED. A listed law MENTIONS this section … YOU MUST READ THE LISTED LAW TO FIND OUT — get_public_law with its package_id, then search its text for this section. …"). Basis: the maintainer's R14a addendum, and two measurements — private laws cite sections only to waive them (O44f), and the verification set's own fire, Public Law 119-74 against 42 U.S.C. 2210, is a single parenthetical citation in an appropriations rider with no amendment (O44g). The tool description's staleness sentence gets the same point in one line: a listing means the law mentions the section, and only reading the law says whether the text changed. The `none_indexed` and `not_checked` caveats are unchanged.

**Do not.** Change the three-state shape, the regimes, or the budget; change the `none_indexed`/`not_checked` caveats. Filter `pvtl` client-side after an unfiltered query — the filter goes in the query so `count` stays honest. Guess a form for appendix rules.

**Unit tests.** The `laws_indexed` caveat equals the pinned wording (a literal comparison, so a drift fails loudly); the query builder emits `lawtype:public` in every query; the App. form for a numbered appendix section; the fallback for a rule; existing WO-1 tests updated to the new string, not loosened.

**Verification artifacts** (real upstream, traced, as for WO-1): (1) `10 U.S.C. 7274` → `laws_indexed` listing PLAW-119publ60 only, query string shown with `lawtype:public`; (2) `42 U.S.C. 2210` → still publ74 only; (3) `18 U.S.C. App. 1201` → a real detector outcome on the App. form (expected `none_indexed`, O44d measured 0 all-time), `checked_citation: 18 U.S.C. App. 1201`; (4) an appendix section expected to fire — find one by probing `uscodecitation:"{t} U.S.C. App. {s}"` with the open-ended `publishdate` bound for a section that resolves to a single current-edition granule, and record which; (5) `28 U.S.C. App. Rule 9` disambiguated to one granule by ids → `not_checked`/`no_measured_citation_form` unchanged; (6) the exact query strings for all of the above; (7) the `laws_indexed` object from (2) showing the pinned caveat verbatim, and the tools/list description text.
