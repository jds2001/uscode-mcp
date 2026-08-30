# Product

## What this is

An MCP server that gives a model search and retrieval over the United States Code as published by GPO on GovInfo, extended to the Public Laws (PLAW) collection for enacted law that is newer than — or was never destined for — the codified Code.

## Why it exists

The US Code answers "what is the law as codified in edition year Y". GovInfo's annual editions lag hard: the 2024 edition is current through 2025-01-06 (O5, O15) and was the newest edition at measurement time (O4, 2026-08-29) — a working lag of 18+ months against enactment. The PLAW collection carries everything since.

PLAW is not just a time-lag patch. Much enacted law never enters the Code at all (CRA disapprovals, namings, conveyances — S5 claims ~20 of the first 37 laws of the 119th Congress produced zero Code text), and whole statutes can be codified only as statutory notes under an existing section (R2). The law that motivated this project is exactly that: codified only as 42 U.S.C. 2210 note (R4).

It is designed to work two ways:

- Independently: a user asks about a statute, the model resolves the citation and reads the section — notes included (O15).
- In conjunction with congressMCP: congressMCP surfaces a bill; this server provides what that bill modifies as codified, and conversely which public laws touch a given US Code section — with the recall caveat measured in O17/O18.

## Core interaction

Given a citation (e.g. "17 U.S.C. 107", "42 U.S.C. 2210 note"), search it by metadata — never by full-text guessing. Retrieval is then mechanical: the search result carries the exact download URLs (O4). Given a topic instead of a citation, full-text and fielded search over the collection, which reaches appendix material too (O19).

## Non-goals (v1) — all ruled, see 96-rulings.md

- No local corpus, mirror, index, or bulk download; every answer comes from live GovInfo API calls. This explicitly includes not ingesting OLRC release-point USLM, the considered-and-declined alternative (R1).
- No STATUTE (Statutes at Large) collection (R1); a `N Stat. M` resolver is a parked v2 idea (Q6).
- No browse/TOC navigation tool (R3).
- No private laws (R6).
- No editorial interpretation layered onto the text: the server returns GPO's text with provenance, and analysis is the calling model's job.
- No automated PLAW→USC join: the `uscodecitation` recipe is documented with its measured recall gap (O17/O18), not automated over (R2, E9).
