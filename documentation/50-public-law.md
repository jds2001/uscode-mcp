# PLAW extension

## The recency story

A US Code edition is current through a stated date — the 2024 edition of Title 17 through 2025-01-06 (O5). Anything enacted after the currency date of the newest edition exists only as slip law. The PLAW collection covers public and private laws from the 104th Congress (1995) forward (S4), 5,999 packages at measurement time (O1).

The composition this enables: resolve a section as codified (`get_us_code_section`), note its `currentthrough` date, then `search_public_laws` with `uscodecitation` for later laws touching it. The server documents this recipe; it does not automate the join in v1 (see `10-product.md` non-goals — the `uscodecitation` tag's recall is unmeasured, E4, and automating over an unmeasured instrument would launder its gaps as completeness).

## Formats

Package IDs: `PLAW-{congress}publ{n}` / `PLAW-{congress}pvtl{n}` (S4, O8). Downloads observed on PLAW-118publ31: PDF, text (`/htm`), MODS, PREMIS, ZIP, and USLM XML (O8). USLM availability across the collection's full range is unmeasured (E4a) — the `get_public_law` `format:"uslm"` contract therefore treats absence as an expected, reportable outcome, not an error.

Public laws have no granules in the way USCODE does — retrieval is package-level, which is why the no-silent-truncation contract in `40-tools.md` matters most here (an NDAA is a single multi-thousand-page package, O8).

## Out of scope, recorded

Laws before the 104th Congress: the STATUTE (Statutes at Large) collection would cover them; whether it is in scope is a maintainer question (Q1). OLRC classification tables as a higher-recall PLAW→USC join: v2 candidate at most (Q5).
