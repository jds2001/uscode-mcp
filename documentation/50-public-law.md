# PLAW extension

## The recency-and-remainder story

A US Code edition is current through a stated date — the 2024 edition through 2025-01-06 (O5, O15) — and GovInfo's newest edition at measurement time was 2024 (O4), so the codified layer runs 18+ months behind enactment by design (R1 accepted this). Anything enacted since exists in PLAW.

Beyond recency, PLAW is the permanent and only home for enacted law that never enters the Code (R2, S5): CRA disapprovals, namings, conveyances, and — the motivating case — statutes classified entirely as notes under an existing section (42 U.S.C. 2210 note, R4). The collection covers public and private laws from the 104th Congress (1995) forward (S4), 5,999 packages at measurement time (O1). v1 serves public laws only (R6).

The composition this enables: resolve a section as codified (`get_us_code_section`), note its `currentthrough` date, then `search_public_laws` with `uscodecitation` for later laws touching it. The server documents this recipe and, since R14, runs it automatically as the `possibly_superseded` indicator on every section success (`40-tools.md`) — but only as an indicator, because the field's gap is measured, not hypothetical: `uscodecitation` misses ~a quarter of sampled (law, section) pairs that the laws' own package metadata lists on the cross-congress E9 sample (25/33, O21, O17/O18) and one in seven on the 119th-Congress-only E16 sample (120/140, O43b), structural rather than recency-driven. Automating over that field as a *check* would launder its gaps as completeness; automating it as a three-state indicator whose silence is explicitly not a check is what R14 rules. Twenty months after the 2024 edition's `currentthrough`, 3.8% of current-edition sections are listed by at least one 119th-Congress public law (O43c) — the measured size of the staleness R1 accepted. The package-summary `references` array is the designated higher-recall v2 source (Q6, E9).

## Formats

Package IDs: `PLAW-{congress}publ{n}` / `PLAW-{congress}pvtl{n}` (S4, O8, O12). Downloads observed on PLAW-118publ31: PDF, text (`/htm`), MODS, PREMIS, ZIP, and USLM XML (O8). USLM availability has a measured boundary: absent for congresses 104–112, present from the 113th (2013) on, sampled one package per congress (O25) — so the `get_public_law` `format:"uslm"` contract treats absence as an expected, reportable outcome for the collection's first nine congresses, not an error.

Public laws have no granules the way USCODE does — retrieval is package-level, which is why the no-silent-truncation contract in `40-tools.md` matters most here (an NDAA is a single multi-thousand-page package, O8). Package-only retrieval also leaves a measured capability question open: interior content questions ("what does this law say about X?") have no random-access path — the AUKUS needle in PLAW-118publ31 sits ~35% into 3.59M chars (E13 grounding). Whether that gap needs machinery, and how much, is E13's question; the disposition ladder is preregistered in `95-open-questions.md`.

## Out of scope, recorded

Pre-104th-Congress law: STATUTE is out (R1); a `N Stat. M` on-demand resolver is parked (Q6). Private laws: out for MVP (R6). OLRC classification tables: parked as the eventual bridge layer (Q6), gated on E9.
