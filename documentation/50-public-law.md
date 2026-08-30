# PLAW extension

## The recency-and-remainder story

A US Code edition is current through a stated date — the 2024 edition through 2025-01-06 (O5, O15) — and GovInfo's newest edition at measurement time was 2024 (O4), so the codified layer runs 18+ months behind enactment by design (R1 accepted this). Anything enacted since exists in PLAW.

Beyond recency, PLAW is the permanent and only home for enacted law that never enters the Code (R2, S5): CRA disapprovals, namings, conveyances, and — the motivating case — statutes classified entirely as notes under an existing section (42 U.S.C. 2210 note, R4). The collection covers public and private laws from the 104th Congress (1995) forward (S4), 5,999 packages at measurement time (O1). v1 serves public laws only (R6).

The composition this enables: resolve a section as codified (`get_us_code_section`), note its `currentthrough` date, then `search_public_laws` with `uscodecitation` for later laws touching it. The server documents this recipe; it does not automate the join, and the reason is now measured, not hypothetical: the `uscodecitation` search field misses at least one law (PLAW-119publ21) whose own package metadata lists the section (O17/O18). Automating over that field would launder its gaps as completeness. The package-summary `references` array is the designated higher-recall v2 source (Q6, E9).

## Formats

Package IDs: `PLAW-{congress}publ{n}` / `PLAW-{congress}pvtl{n}` (S4, O8, O12). Downloads observed on PLAW-118publ31: PDF, text (`/htm`), MODS, PREMIS, ZIP, and USLM XML (O8). USLM availability across the collection's range is unmeasured (E4a) — the `get_public_law` `format:"uslm"` contract therefore treats absence as an expected, reportable outcome, not an error.

Public laws have no granules the way USCODE does — retrieval is package-level, which is why the no-silent-truncation contract in `40-tools.md` matters most here (an NDAA is a single multi-thousand-page package, O8).

## Out of scope, recorded

Pre-104th-Congress law: STATUTE is out (R1); a `N Stat. M` on-demand resolver is parked (Q6). Private laws: out for MVP (R6). OLRC classification tables: parked as the eventual bridge layer (Q6), gated on E9.
