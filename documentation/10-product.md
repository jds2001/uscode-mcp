# Product

## What this is

An MCP server that gives a model search and retrieval over the United States Code as published by GPO on GovInfo, extended to the Public and Private Laws (PLAW) collection for legislation more recent than the latest codification.

## Why it exists

The US Code answers "what is the law as codified today (or as of edition year Y)". Annual editions lag reality: the 2024 edition of Title 17 is current only through 2025-01-06 (O5). The PLAW collection fills the gap between the latest edition's currency date and now.

It is designed to work two ways:

- Independently: a user asks about a statute, the model resolves the citation and reads the section.
- In conjunction with congressMCP: congressMCP surfaces a bill; this server provides what that bill modifies as codified today, and conversely which recent public laws touch a given US Code section (via PLAW's `uscodecitation` field, S4).

## Core interaction

Given a citation (e.g. "17 U.S.C. 107"), search it by metadata — never by full-text guessing. Retrieval is then mechanical: the search result carries the exact download URLs (O4). Given a topic instead of a citation, full-text and fielded search over the collection.

## Non-goals (v1)

- No local corpus, mirror, or bulk download; every answer comes from live GovInfo API calls.
- No editorial interpretation layered onto the text: the server returns GPO's text with provenance, and analysis is the calling model's job.
- No OLRC classification tables; the PLAW→USC linkage in v1 is GovInfo's own `uscodecitation` metadata (S4), whatever its limits turn out to be (see 95-open-questions.md Q5/E4).
