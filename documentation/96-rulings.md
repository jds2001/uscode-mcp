# Maintainer rulings — 2026-08-29

Q1–Q5 from `95-open-questions.md` were answered by the maintainer on 2026-08-29. The rulings are summarized here; the maintainer's verbatim answers are in git history (commit "spec: maintainer answers Q1-Q5"), and the Q1 Claude Desktop exchange is preserved verbatim below as source S5.

## Rulings

R1 (from Q1) — **No STATUTE collection; no OLRC release-point ingestion. The product is GovInfo USCODE + GovInfo PLAW, searched via GovInfo's own search service.** The maintainer considered and declined the alternative of ingesting OLRC release-point USLM and building a local index: "The index already exists at GovInfo (of PLAW), so I'm not certain that I want to rebuild the thing that already exists of a later codification of the code where it's not available." Consequence accepted knowingly: the codified layer is as stale as GovInfo's newest annual edition (18+ months against enactment, S5), and PLAW carries everything since — which makes the PLAW side and the staleness provenance first-class, not a patch. Elaborated 2026-09-15 at the maintainer's direction: `10-product.md` "What this is" now states currency as an explicit non-goal — OLRC is declined for three compounding reasons (title-level retrieval mechanics, USLM markup, still behind enactment), and PLAW is the layer that fills the gap either way.

R2 (from Q1, via S5) — **Not all enacted law is ever codified, and notes are where whole statutes can live.** S5 claims ~20 of the first 37 public laws of the 119th Congress produced zero US Code text (CRA disapprovals, namings, conveyances), and that freestanding provisions in positive-law titles are classified only as statutory notes. These are claims from another model's report, not measurements of ours — but the product consequence is a maintainer decision regardless: PLAW is permanently the only home for a legally operative class of law, and notes must not be dropped.

R3 (from Q2) — **Search-only discovery in v1. No browse/TOC tool.** Maintainer: build it when a consumer stumbles over its absence, not before. This joins the settled list.

R4 (from Q3) — **Appendices and notes are in scope, emphatically.** The law that motivated this project is codified only as a note: 42 U.S.C. 2210 note. `get_us_code_section` must handle "note" citations (contract in `40-tools.md`, shaped by E7) and appendix material (E8).

R5 (from Q4) — **The carried-over congressMCP boilerplate gets fixed.** The maintainer authorized the spec session to modify `CONTRIBUTING.md` (outside `documentation/`) and `documentation/CLAUDE.md` for this specific purpose: "both are documentation." This is a one-time scoped exception to the write restriction, not a repeal of it.

R6 (from Q5) — **Public laws only in the MVP.** `lawtype:private` is out; may return later.

Deferred, explicitly not rejected: a `N Stat. M` citation resolver returning a GovInfo pointer without ingestion (S5 suggestion), OLRC classification tables / per-section pending updates as a bridge layer, and any use of OLRC release points for current-text fetch-by-citation. All are v2 questions at most (see `95-open-questions.md`).

## S5 — the Q1 Claude Desktop exchange, verbatim

Everything below is quoted from the maintainer's file edit of 2026-08-29. Empirical statements inside are S5 claims: another model's report, to be trusted only where independently measured (the classification-table count, the OLRC coverage dates, and the release-point mechanics have NOT been re-measured here).

Well this is interesting. I posed this question (with some further questions that would decide it) to Claude Desktop:

The first prompt:

I'm starting to write a US Code MCP (all the existing stuff I found was way too bloated and didn't appear to search full text, only offer a download link to it, ugh).

My spec session asked me a genuinely hard question that I need your help answering, do not guess at the answers to my questions and provide empirical evidence,


```markdown
Q1. Pre-1995 law: PLAW starts at the 104th Congress (S4). Is the STATUTE (Statutes at Large) collection in scope for older enacted law, or is "US Code + PLAW from 1995" the product?
```

The reason for including PLAW was recently enacted statutes that haven't made it into US Code yet. Do they all eventually wind up there? If so, antique Statutes at Large probably aren't useful since they:

1) May have been repealed/modified by later law, and not currently useful (though may be for historical research, but that's not the initial point of this)
2) Are obviously already codified into USC

The answer to the first prompt:

## Short answer

No, they don't all eventually wind up there. That premise is the thing to fix in your spec, and it's fixable without adding STATUTE.

## Evidence 1: OLRC says outright that most law doesn't get codified

From OLRC's own classification page: the Code contains only the general and permanent laws, so not every provision in a public law goes into the Code; OLRC attorneys read each enrolled bill and decide whether a provision is general and permanent in nature — a provision defining a federal crime is general, one naming a post office is not; a provision requiring an annual report forever is permanent, a one-year appropriation is not.

And the classification tables page states the constraint explicitly: the tables only include those provisions of law that have been classified to the Code.

## Evidence 2: I counted it for the 119th Congress

The public-law-order classification table for the 119th, 1st session (`tbl119pl_1st.htm`, prepared 2026-01-23) is sorted by PL number, so absences are meaningful. Across the range 119-1 through 119-37, only these laws appear at all: **1, 4, 12, 18, 21, 22, 23, 25, 26, 27, 29, 30, 31, 33, 34, 36, 37.**

That's 17 of 37. **20 of the first 37 public laws of the 119th Congress produced zero U.S. Code text.** (My fetch truncated at 119-37, so treat this as the first 37, not the full session of 73.)

The missing ones aren't random. 119-2, 119-3, 119-5, 119-6, 119-7 and many others at the start of the session are Congressional Review Act joint resolutions of disapproval. Those have real, ongoing legal effect (the rule is void and the agency can't reissue a substantially similar one), and they will never appear in the U.S. Code. Same for post office namings, land conveyances, commemorative acts, and private laws.

So "USC + recent PLAW" is not "USC plus a small time-lag patch." PLAW is permanently the only home for a large, legally operative class of enacted law.

## Evidence 3: even codified laws often land only in notes

Look at the tail of Pub. L. 119-21 in that same table: `42 2210 nt | 119-21 | 100201-100205`. Five sections of a major act, classified entirely as a statutory note under one section. OLRC explains why: a freestanding provision that belongs in a positive law title by subject matter can only be classified as a statutory note under a section of that title, because positive law titles can only get new sections by direct amendment; a statutory note can consist of as much as an entire law.

**Design consequence:** if your indexer walks USLM and only ingests `<section>` bodies, you will silently drop entire statutes. Notes have to be first-class searchable content with their own citation form (`42 U.S.C. § 2210 note`). This is probably the single highest-value thing to get right for a "search full text" product, and it's where the bloated tools you looked at tend to fail too.

## On dropping STATUTE: the format argument is stronger than the recency argument

Your instinct is right, but for a better reason than "it's antique." GovInfo's own help page: USLM XML is currently available for Statutes at Large back to volume 117 (2003); GPO plans to release USLM XML for volumes 116 (2002) back to volume 1 (1789) incrementally in an upcoming release cycle. Volumes 1-64 and 65-116 were made available through digitization and digital imaging efforts.

So the structured tier of STATUTE starts at 2003 (108th Congress), which is *later* than PLAW's start at the 104th (1995). Everything before that is scanned page images with OCR text keyed by page granule (`STATUTE-{vol}-Pg{page}`), with no section structure. Indexing that for BM25 gets you noisy OCR against a page-number identifier you can't map to anything a user would cite.

**PLAW strictly dominates the machine-readable portion of STATUTE for your use case.** Verify per-congress format availability in PLAW yourself before you commit, but the coverage floor is the point.

## The one real argument for Statutes at Large, and why it doesn't need indexing

Under 1 U.S.C. 204, the matter in a main edition of the Code plus its current supplement establishes the law prima facie, except that titles enacted into positive law are legal evidence of the law. For non-positive-law titles, if the Code and the underlying act conflict, the act controls. That is a genuine reason a serious user reaches for the Statutes at Large.

But that's a *fetch-one-citation* need, not a *search-the-corpus* need. The Code's credit lines already give you the Pub. L. and Stat. cite, and OLRC's own tables link straight to `statviewer.htm?volume=139&page=NNN`. Resolve on demand, don't ingest.

## Suggested scope answer for Q1

**Product = USC (current release point, sections *and* notes) + PLAW from the 104th.** STATUTE is out of scope for the index; add a citation resolver that returns a GovInfo pointer for any `N Stat. M`.

Two things to add that you may not have in the spec yet:

1. **The classification tables as the bridge layer.** The Code is current through Public Law 119-102 (July 12, 2026), and today is August 29 — roughly a six-week lag, which fluctuates. The site also carries per-section "Pending Updates" listing the public laws affecting a section since its currency date. Ingesting the tables plus pending-updates lets you answer "this section is stale, and here's the PLAW section that changes it," which is the actual killer feature over a naive USC dump.

2. **The editorial classification change table.** You'll see `ed chg` markers in the tables (e.g. `54 320101 nt ed chg | 119-25`). Sections get moved and renumbered editorially between release points. If you cache across release points, you need that table or your citations rot.

One reproducible check for your spec session: for each session, diff the distinct PL numbers in `tbl{congress}pl_{session}.htm` against the OFR public law list at archives.gov. The delta is your "enacted law with no Code footprint" set, and it's a number you can put in the spec instead of arguing about it.

The followup prompt:

GovInfo only publishes the code every 2 years - I'm looking at published code. Is there more recent codification available via the API? That's why there's a HUGE time lag, not a short one like you cited. And the search is GovInfo search, not anything I invented this time.

And the response:

You're right and I was sloppy. Those are two different lags and I quoted the wrong one.

## What I actually cited vs. what you're hitting

"Current through Pub. L. 119-102 (July 12, 2026)" is **OLRC's** currency for uscode.house.gov, not GovInfo's USCODE collection. GovInfo's USCODE is a different artifact with a different cadence.

GovInfo publishes **annual edition packages**, IDs shaped `USCODE-{year}-title{n}` (e.g. `USCODE-2008-title28`, `USCODE-2006-title2`). The help page describes them as virtual main editions from 1994 forward, and explains the underlying print model: main editions every six years since 1934, with annual cumulative supplements in between.

I could confirm `USCODE-2023-*` and `USCODE-2024-*` packages exist; I did not confirm a 2025 or 2026 edition, so verify that yourself against `api.govinfo.gov`. Either way, your complaint holds: an annual edition is current only through the end of that session, *and* it ships months after that session closes. You're looking at something 18+ months behind on a good day.

Also worth noting: the GovInfo USCODE help page documents only PDF and HTM granule URLs. No XML format is documented for that collection. That's a second problem for a search product independent of staleness.

## The answer to your actual question: yes, but not through GovInfo

The current codification is published by OLRC as **release points**, and it's not in the GovInfo API at all.

From uscode.house.gov/download/download.shtml right now:

> Current Release Point — **Public Law 119-102 (07/12/2026)**. Each update of the United States Code is a release point. All files are current through Public Law 119-102. Titles in **bold** have been changed since the last release point.

All 54 titles plus appendices, each in XML / XHTML / PCC / PDF, per-title zips and an all-titles zip:

```
https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip
https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_usc26@119-102.zip
```

The XML is USLM, with the schema and User Guide linked from the same page. Prior release points go back to Pub. L. 113-21 (`priorreleasepoints.htm`), and older material is on the Annual Historical Archives page.

That's the same database OLRC prints from and serves on its own site. It is roughly six weeks behind enactment, not eighteen months, and it's structured XML rather than PDF/HTM. For a full-text USC search tool this is the source, not GovInfo USCODE.

## One gotcha before you build the ingester

Per-title currency is not always uniform with the release point label. A cached copy of that same download page shows:

> Public Law 119-73 (01/23/2026) **, except 119-60** ... Title 1 — General Provisions — `119-73not60`

So the page carries both a global release-point label *and* a per-title "Current Through" value that can encode exclusions. Model currency **per title**, not as one global watermark, or you'll assert freshness you don't have. The bolding of changed titles also gives you a cheap incremental-fetch signal: poll for the release-point PL number, and when it bumps, pull only the bolded titles.

## Revised source plan

| Layer | Source | Why |
|---|---|---|
| Codified text (sections + notes) | OLRC release points, USLM XML | Current to ~6 weeks, structured, versioned by PL |
| Gap since release point | GovInfo PLAW | Nothing else has it |
| Where the gap lands in the Code | OLRC classification tables + per-section Pending Updates | Maps unintegrated PLs onto USC sections |
| Historical USC versions | OLRC prior release points (113-21 forward) / GovInfo USCODE annual editions | Point-in-time "what did § X say in 2019" |
| Statutes at Large | Nothing ingested; resolve citations on demand | Unchanged from before |

GovInfo USCODE keeps a role, but it's the *historical* layer, not the current one. Its annual granularity is actually a feature there: `USCODE-2019-title42-...` is a clean point-in-time citation in a way a release-point snapshot isn't.

## On using GovInfo search as the backend

If the plan was to proxy `/search` with `collection:uscode`, that inherits the annual-edition staleness directly, and you can't fix it with query tuning. The GovInfo search index is only as current as the packages behind it.

You already have the alternative built. The FTS5/BM25 index and operative/quoted/header segment model from the congressMCP bill-text work maps onto USLM release-point XML with less rework than starting over, and it's the piece that lets you rank notes alongside sections instead of dropping them. Keep GovInfo `/search` for PLAW and for STATUTE citation resolution, where its index is the right one and its currency isn't the problem.

Me again:

The difficulty with this approach is ingesting ALL of the USLM and building an index of it. The index already exists at GovInfo (of PLAW), so I'm not certain that I want to rebuild the thing that already exists of a later codifciation of the code where it's not available.

## R7 — 2026-08-29, key transport

Maintainer-reported defect in the implementation: the API key was sent as the `api_key` query parameter, which leaks into URL logging (the maintainer has seen httpx do exactly this). Ruling: **the key travels only in the `X-Api-Key` header, never in a URL** — verified working with a 401 no-credential control (O22). This interacts with the error contracts, which require surfacing upstream URLs and bodies verbatim: a URL-borne key would make the spec's own transparency requirements into a leak. Header transport makes surfaced URLs key-free by construction; see the secret-hygiene contract in `40-tools.md`.

## R8 — 2026-08-29, trace directory

Maintainer requirement, ported from congressMCP where it earned its keep: the server emits a request trace controlled by an environment variable naming a directory — tracing enabled by the variable's presence, disabled by its absence — with **one JSONL line per request carrying the verbatim request and response**. Its consumer is an E2E test harness that verifies the implementation against a real consumer model (the harness itself is parked as Q7). Contract details in `40-tools.md` → "Trace emission". One reading was assumed rather than guessed silently, then confirmed by the maintainer (2026-08-29, closing Q7a): the trace records MCP-level tool calls and responses, not upstream GovInfo HTTP exchanges.

Two implementation choices flagged in the first R8 implementation report, ruled on 2026-08-29: (1) per-run trace files rather than one shared append file — accepted and promoted into the contract (`40-tools.md`): a harness globs `*.jsonl` and may rely on each request appearing exactly once across the directory. (2) Set-but-blank `USCODE_MCP_TRACE_DIR` treated as off — overruled: blank is a startup failure, only unset disables. Rationale in the contract text; the short version is that the instrument's off state must be unreachable by typo.

## R9 — 2026-08-30, dependency ceilings

Maintainer requirement, with the scar tissue attached: the implementation's `pyproject.toml` set only a floor on the `mcp` SDK. MCP 2.0 shipped breaking API changes — that breakage is what brought the maintainer to congressMCP in the first place — and 3.0 likely will too. Ruling: **runtime dependencies with breaking-change potential get a ceiling as well as a floor** (for the `mcp` SDK: cap below the next major, e.g. `>=2,<3`). An uncapped floor turns someone else's release day into this server's outage. Raising a ceiling is a deliberate, tested change committed on its own — never drift. This is a repo convention, so it lives in `CONTRIBUTING.md`; the maintainer's direction to establish it is the recorded authorization for the spec session to make that edit (R5 precedent). The immediate implementation action: cap `mcp` in `pyproject.toml`.

## R10 — 2026-08-30, the E2E harness (Q7b–Q7f)

Maintainer answers recorded verbatim in commit 198cd0c, including the congressMCP §17 prompt manifest as the format exemplar. The rulings:

Assertions (Q7b): all proposed trace assertions, except live rate-limit exercise (untriggerable at 36,000/hr with one consumer; stays unit-test territory). The load-bearing property is **non-vacuity of the error envelope**: errors returned as errors, zero hits as zero hits, all error responses structured rather than prose, and server-side normalization (the citation strips) disclosed so the consumer can diagnose what happened. New assertion classes get added as real consumers trip over things. The congressMCP completeness pressure (index-or-die on 1,100-page bills) mostly doesn't apply here — no indexer exists yet.

Run model (Q7c): live consumer model per run — no replay tier. Runs are expensive and deliberately minimal: high-risk changes and pre-release. The harness executes prompts verbatim and records results beside pinned criteria; **it never scores**. Scoring is done by a human and/or the spec session against criteria pinned before the run (preregistration-of-scoring).

Driver (Q7d): Claude Code headless with web-fetch tools disabled, so every answer is attributable to priors or to the tools — nothing else. No memory, and no disclosure that a developer is watching or that the run is a test (a consumer that knows is a different consumer). Cross-vendor cells use Codex CLI, gated on E11: congressMCP experience suggests ChatGPT-authenticated Codex cannot disable web fetching; if E11 confirms that, the harness MUST refuse to run cross-vendor cells under anything but API-key auth.

Ownership (Q7e — the maintainer's answer was cut off mid-sentence at "Harness code lives in implementation,"; the rest is assumed from Q7c/Q7f and flagged in `95-open-questions.md` for correction): harness code implementation-side; the verification contract and the prompt manifest are spec-side — the manifest is normative at `documentation/e2e-manifest.json` and the harness loads it verbatim, never a copy. Cadence is manual-only (follows from Q7c); no CI gate.

Format (Q7f): the §17 manifest structure is adopted with adaptations for a live-API, no-corpus server, specified in `60-e2e-harness.md`. Its hardest-won rule is adopted whole: **groundings are written from the record, not from plausibility** — three congressMCP prompts (A3, B3, E3) were invalidated by exactly that, and every grounding here cites an O-observation or names its measurement with a date.

## R11 — 2026-08-31, the standalone harness and the suite

The maintainer extracted the harness into its own project (`mcp-e2e`) and delivered `SUITE-AUTHORING.md` — the suite-authoring contract, normative-by-distillation (the harness repo's own spec wins on conflict). This resolves the copy-vs-new-repo question in favor of extraction and closes Q7e's dangling half: executor code lives in the harness repo; this repo owns the suite — manifest, groundings, scored findings — and the suite is spec-session property ("the test spec is yours"). `60-e2e-harness.md` is accordingly rewritten as the suite spec; harness mechanics defer to `SUITE-AUTHORING.md`.

Boundary interpretation, made explicit rather than assumed: to author Layer-1 checks the spec session ran the built server as a **black box** over its public MCP wire and read its R8 trace (O28). Ruled in scope: the write restriction and the do-not-read-implementation rule exist so the spec specifies rather than describes; measuring the public wire contract of a running server is measurement, exactly like curling GovInfo — no source was read, and check selectors authored from imagination would have been guaranteed vacuous or erroring. Reading implementation *source* remains prohibited.

Outcome vocabulary: the measured members (`success`, `not_found`, `ambiguous`, `out_of_scope_private_law`) are pinned as spec vocabulary by O28. Members that exist by implementation claim only (`appendix_redirect`, the upstream-failure and rate-limited shapes, `format_not_available`) are not bound by any check until measured — an enum check containing guessed names would false-fail on legitimate outcomes, which is bad instrument design.

## R10 amendment — 2026-09-01, the cross-vendor gate, corrected by measurement

R10's original mandate ("the harness MUST refuse cross-vendor cells under anything but API-key auth") encoded the congressMCP-era belief that the auth mode was the fix. E11 falsified that: config knobs fail to disable web search under ChatGPT auth (O31) AND under API-key auth (O33); the facility that actually controls the surface is the wire-filtering custom provider, which works under either login and never receives the login credential (O32). Amended mandate: **a Codex cross-vendor cell runs only through a filtering-proxy model provider with the tool surface stripped and verified at the proxy wire, from an isolated CODEX_HOME, with the proxy's backend holding its own API key.** Login mode is irrelevant to tool control and no longer the gate; a cell relying on auth mode or config knobs alone must not run, because both are measured to leave web search live. Version caveat: all three observations are codex-cli 0.147.0; re-measure on upgrade.

## R10 second amendment — 2026-09-01, the noweb provider replaces the proxy

The first amendment inferred a filtering proxy from O31–O33. The maintainer then supplied congressMCP's actual mechanism (S6), which is cleaner and is now reproduced here (O34): the CLI registers the standalone web tool only for providers whose ModelProviderInfo declares `supports_standalone_web_search` — so a custom provider pointing at the SAME api.openai.com Responses API, which declares nothing, never grows the tool. No proxy. Corrected mandate: **a Codex cross-vendor cell runs with (1) a custom `openai-noweb`-style provider at api.openai.com, `wire_api="responses"`, key via process env only; (2) an isolated `CODEX_HOME` — ambient MCP servers are a measured, network-capable leak channel (O34: `node_repl` ran mid-probe); (3) effect-level verification per run: zero web-search events in the run record, and the harness's api-surface capture confirming the tool absent.** Config knobs and login mode remain non-gates (O31/O33). Version caveat unchanged: all of this is codex-cli 0.147.0 behavior; re-measure on upgrade.

## R10 third amendment + the keyless-startup contract — 2026-09-01

Two rulings from the congressMCP F29/F30/F31 postmortem (S7), the env claim corroborated here (O35):

**Codex cells need a key-injection spawn helper.** Codex spawns MCP servers with a sanitized env (O35), and every env channel it offers writes the key into a run artifact (S7) — so the harness's Codex driver must point codex's `mcp_servers` entry at a small helper that injects `GOVINFO_API_KEY` into the real server's process env at spawn, resolved from the operator's environment, never from any file that lands in artifacts. This joins the R10 gate alongside the noweb provider and isolated `CODEX_HOME`. Harness-side work (mcp-e2e), recorded here because the gate is this spec's.

**Keyless startup fails fast — a gap in this spec exposed by F31.** The spec never said what the server does when `GOVINFO_API_KEY` is absent or empty; F31 is what the unspecified case looks like (a keyless server up and wearing a misleading per-request error). Ruled: absent or blank `GOVINFO_API_KEY` fails the server at startup with a message naming the variable, stderr and nonzero exit — same instrument philosophy as R8's blank trace dir: a server that can serve nothing must be unmistakably down, not up and lying about why requests fail. Contract added to `20-govinfo-api.md`; implementation change queued.

## R12 — 2026-09-01, locating content in large payloads

Triggered by the first real-consumer symptom report (S8/O36): two calls and a blind offset guess to find known content in a resolved 116K-char section. The consumer's own framing binds the ruling — this is a payload-size problem, not a notes problem, and their suggestion was a symptom report, not a design. Measured first (O36): USCODE payloads carry upstream field delimiters; PLAW payloads are flat.

R12a — **`find` parameter on both text tools** (`get_us_code_section`, `get_public_law`): optional case-insensitive literal substring; the server searches the full text it already holds and returns occurrences as offsets in the same coordinate system as `start_char`/`total_chars`, with short context snippets, a capped list carrying the true total (the disambiguation-totals rule applies), and an explicit zero-match report. Composes with windowing: one call locates, one call reads. Structure-free, so it works identically on flat PLAW payloads — this is E13's rung 1 arriving via a measured consumer stumble rather than speculation.

R12b — **`structure` block on `get_us_code_section` successes**: an ordered list of the payload's fields — `{field, heading (for notes), start_char}` — derived ONLY from the upstream `field-start`/`field-end` markers, never from heading heuristics (the parser-ownership trap S8 warned about). Marker absence or imbalance in any granule degrades to "structure omitted, with a disclosure", never a retrieval failure — two granules measured is not a corpus guarantee. This makes "jump to the notes" one glance, serving the motivating note use case (R4) directly.

Deferred, recorded: a notes-only retrieval mode for `"… note"` citations — redundant once R12a+b exist (locate via structure, read via window); revisit only if E14 shows consumers still failing. Preregistration E14 in `95-open-questions.md`.

## R13 — 2026-09-02, structure refinements from the second field report

From S9/O38, all three additive to R12b's contract in `40-tools.md`:

R13a — **`structure` rides only on `start_char: 0` responses.** The locating call gets it; reading calls (nonzero `start_char`) carry `{omitted: true, reason: …}` pointing back to a zero-offset request. Rationale: the block is invariant per (section, year) and was measured at ~15× a small window's payload; "one call locates, one call reads" implies the reading call has no use for it. The `structure-present-or-disclosed` check is untouched — the omitted flag is present either way.

R13b — **Every field carries `end_char` (exclusive; the final field ends at `total_chars`), and `structure.note` states that headings come from upstream markers and describe a field's opening, not its contents.** The measured hazard: a 38K field labeled "Findings" containing the whole Radiation Exposure Compensation Act — the exact case `structure` exists to solve, with the label pointing away from the answer. Extent makes the mismatch self-evident (`end_char - start_char` is also precisely the `max_chars` a caller needs) and the note closes the residual trap. Upstream headings are reported faithfully, never editorialized — the extent is the mitigation, not relabeling. Amended after the implementation's flagged judgment, ratified on verification (O39): `end_char` derives from each field's own `field-end` marker, not next-field subtraction — so **fields nest** (a container like `notes` spans its typed children), the final field's extent is data rather than decree, and trailing content past the last marker reports honestly. The ruling's original 'final field ends at total_chars' is thereby a measured consequence, not a rule.

R13c — **the in-band coordinate disclosure is contractual.** The implementation's `text.message` stating the banner is not part of the payload and offsets start after it exists and is consumer-validated as correctly placed (O38); it is now required on every bannered response so it cannot regress away.

## R14 — 2026-09-11, the `possibly_superseded` flag (Q10)

Maintainer answers, verbatim from `95-open-questions.md` (written against Q10's three questions):

> 1) This is DEFINITELY WARNING only, not positive only even - something matched CANNOT assert that the modified section is not current. This is the effective date trap, and we have no way to know it without retrieval and parsing of hte enacted law. I don't think that's worth it, so it MUST be disclaimed as an indicator, not certifyiung that the section is not current.
>
> 2) I think it should fire on every lookup. Perhaps we should run an experiment on the roundtrip cost of the search, but if it's under say 100ms (which I suspect it's significantly under) we should do it every time. It's cheap and a correctness win.
>
> 3) Run E16 now, using the key in ../.env

R14a — **Indicator in both directions, never a certification.** When the flag fires it says only that a later public law is indexed against this section; it does not say the text returned is out of date (the effective-date trap — a matched law may amend a different subsection, may not yet be effective, or may only reference the section). When the flag is silent it does not say the text is current, because the instrument misses ~a quarter of real (law, section) pairs (O21, O42d). Three states, never two: laws found; checked and none found, with the recall caveat in the same object; could not check, with the upstream failure surfaced. Retrieving and parsing the enacting law to resolve effective dates is explicitly declined as not worth it. Addendum 2026-09-15 (maintainer, on O44f/O44g): "It likely also strengthens the 'this is advisory only' caveat. Imagine a public law, amending something else, that simply cites another section of the code. This strengthens the YOU MUST READ IT TO FIND OUT. Perhaps worth making the caveat super-explicit like that." Adopted: the `laws_indexed` caveat wording is pinned verbatim in `40-tools.md` and issued as WO-2 change 3; the measured example is the verification set's own fire (publ74 cites 42 U.S.C. 2210 once, parenthetically, amending nothing, O44g).

R14b — **Fires on every `get_us_code_section` success, gated on measured cost.** The maintainer's threshold: if the detector's search round trip measures under roughly 100 ms it runs unconditionally; E16 gains a latency arm to measure it. If the measurement comes in materially above that, the question returns to the maintainer with the number rather than the spec defaulting to on-request. Closed 2026-09-15: the maintainer answered Q13 on the measured numbers (O43e) — the search itself is under the threshold and concurrent issue makes the round trip near-free in wall-clock — so the indicator fires unconditionally; no opt-in argument.

R14c — **E16 runs now, as a spec-session measurement of the public API,** with the key in `../.env`. Protocol amendments pinned before the run in `95-open-questions.md`.

## R15 — 2026-09-11, `fields=["statute"]` deferred (Q12)

Maintainer: "Agreed" to the deferral recommendation, and relayed the consumer session's own concurrence (S12 in `90-observations.md`, verbatim). Ruling: **no `fields` request parameter.** The decisive argument is S12's — the field vocabulary is GovInfo's marker taxonomy reported verbatim in `structure`, and turning it into a request parameter would promise a vocabulary the server does not control, cannot version, and that some granules lack entirely (the `omitted` case has no correct answer for `fields=["statute"]`). Reopening trigger, narrowed per S12: a consumer that hits a section whose operative text alone exceeds a reasonable window, so that the whole payload cannot be fetched and `find` cannot help because the consumer does not yet know what to search for. If that ever shows in real traffic, the pre-committed direction is statute-first ordering with notes windowed behind it — no new request vocabulary — not `fields`.
