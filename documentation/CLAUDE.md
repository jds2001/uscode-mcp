# Working in `documentation/` — the uscode-mcp spec

## Role and scope

This directory **is** the spec. Write authority is here and nowhere else in the repo (exceptions only by recorded maintainer authorization — see `96-rulings.md` R5).

- **Do not read or modify implementation source.** The job is to specify, not to describe what was built.
- A separate implementation session owns the code. **Its reports are claims, not ground truth** — see "Rules that have earned their place" below.

Start at `00-INDEX.md`: the file map, **"Conventions — these bind"**, and **"Settled — do not reopen"** (check the latter before reopening anything).

## Markdown formatting

**One line per paragraph. No hard wrapping, no fixed column.** A mix of wrapped and unwrapped prose makes exact-match edits fragile and turns a one-word change into a reflow cascade; one line per paragraph keeps a prose edit to a single changed line.

- **Leave structural lines alone:** tables (one row per line), fenced code blocks, headings, horizontal rules.
- **Blockquotes follow the same rule inside:** one line per quoted paragraph, each line prefixed `> `. Preserve nesting indent — a quote inside a numbered list stays `   > `.
- **Join hazard — hyphens.** Never join a line that ends in a hyphen by inserting a space: `load-` + `bearing` is **`load-bearing`**, not `load- bearing`. Suspended hyphens (`word- and phrase-level`) are already correct and must keep their space.
- A reflow is content-preserving only if it passes: whitespace-stripped text identical (ignoring collapsed `>` prefixes), and table/fence/heading/blockquote-block counts unchanged.

## Routing a question

- **Requirements or product** → ask the maintainer. Never guess. Answers become rulings in `96-rulings.md`.
- **Empirical** → do not assert. State the measurement that would settle it, preregister the expectation in `95-open-questions.md`, run it or hand it over, and log the outcome in `90-observations.md` either way.
- **IR/technical judgment** → decide it, and record the rationale in the spec.

## Rules that have earned their place

Most of these were earned in the congressMCP bill-text spec, which this project's conventions descend from; the parenthetical incidents are from there unless marked local.

- **Measurement over assertion.** Never state a result as fact — cite an observation in `90-observations.md` or name the experiment. **A mocked test fixture is not evidence** (a fabricated `pcs2` date once got cited as an observation).
- **Preregister before a spec change:** the expected result *and* the observation that would falsify it. Record the outcome either way, including when it falsifies you (local example: O7a — citation matching turned out tolerant of missing periods, against the preregistered expectation).
- **Check dead-defensive first.** Before writing a contract for an edge case, confirm the design or the corpus can actually reach it. Several congressMCP rulings turned out to be machinery for cases that do not exist.
- **A finding is only as valid as the instrument that produced it.** An empty trace from an instrument that couldn't have captured the signal proves nothing. Local example: the `uscodecitation` search field misses laws whose own package metadata lists the section (O17/O18) — a "no laws affect this section" answer from that field is an instrument limit, not a fact about the law.
- **Demand observable artifacts** from implementation reports: failing input, before/after *sets* (not counts), traces, corpus scans. Agreement with a summary proves nothing; disagreement is the signal. This applies equally to other models' research reports — S5 was corroborated on one claim (O18) and is still quarantined as claims everywhere it hasn't been.
- **Non-vacuity proves test-fix coupling, not test-reality coupling.** Removing a fix and confirming the test fails shows the test is sensitive to *the fix*. It cannot show the test exercises the *real input shape*, because **a test and the fix it guards are usually authored from the same mental model** — perturbing one does not surface an assumption they share. (Quoted verbatim from the congressMCP documentation at the maintainer's direction, 2026-08-29. The escape hatch is inputs no mental model authored: real traces — see R8 — and live measurements.)
- **Durable state lives in files here, never in conversation** — assume compaction. Observations, preregistrations, open questions, rulings.
- **Commit each ruling as it is made.** The git history of this directory is the decision record; that is worth more than a tidy log.
