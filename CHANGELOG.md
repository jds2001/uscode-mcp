# Changelog

## Unreleased

### Added

- R12 content location in large payloads: both text tools take an optional `find` (case-insensitive literal substring) reporting the true occurrence count with offsets in the `start_char`/`total_chars` coordinate system, context snippets, a capped list that states the true total, and an explicit zero-match outcome — one call locates, one call reads. `get_us_code_section` successes also carry a `structure` block listing the payload's fields in order (`statute`, `sourcecredit`, typed notes with their headings) with a `start_char` each, derived only from the granule's upstream `field-start`/`field-end` markers (O36) and degrading to a disclosed omission — never a retrieval failure — when those markers are absent or unbalanced.
- R8 trace emission: setting `USCODE_MCP_TRACE_DIR` appends one JSONL line per handled MCP tool call (verbatim request and response, including error outcomes); an unusable directory fails the server at startup and a per-request write failure fails that request loudly.
- Initial MCP server scaffolding (implementation session): `uscode-mcp` Python package (`uv`-managed, `mcp` SDK 2.x) serving the four tools specified in `documentation/40-tools.md` — `get_us_code_section`, `search_us_code`, `get_public_law`, `search_public_laws` — over stdio (default) and streamable HTTP (`--transport http`).
- GovInfo API client with the three-outcome contract (success / upstream failure / rate-limited, never collapsed), citation normalization with the two mandatory strips (subsection, trailing "note"), HTML-to-text derivation with `currentthrough` provenance, and explicit (never silent) truncation windows.
- Unit test suite (218 tests) covering failure surfacing alongside the happy paths.
- `CONTRIBUTING.md` as the canonical source for code style, commit conventions, and the `documentation/` two-session model — resolves the conflicting commit-trailer guidance between `.claude/CLAUDE.md` and the workspace-level `CLAUDE.md` (#46, #78).
- `tests/test_conventions_sync.py` guards `AGENTS.md` and `.claude/CLAUDE.md` against drifting apart.

### Changed

- R13a — the `structure` block now rides only on locating calls (`start_char` 0 or omitted). A reading call gets the `omitted` form pointing back to a zero-offset request: the block is invariant per (section, year), and on the measured case it was 2,504 bytes wrapping a small read (O38). The `omitted` key is present in both shapes, so structure-present-or-disclosed still holds everywhere.
- R13b — every `structure` field now carries an exclusive `end_char` (the final field ends at `total_chars`), so `end_char - start_char` is both a field's extent and the `max_chars` needed to read it. `structure.note` now states that headings are upstream labels describing where a field *opens*, not what it contains — the measured hazard is a 38,154-char "Findings" note holding an entire Act (O38), a label pointing away from the answer.
- R13c — the in-band statement that the banner sits outside the offset coordinate system is now contractual on every bannered response rather than an un-specced nicety, so it cannot regress away.
- E12 in-band truncation banner: a truncated text response now leads `content` with a single bracketed line stating the window bounds, the true total, and the continuation `start_char` — ruled from finding F1, where a consumer handed complete and correct structured truncation fields still presented the window as the whole law. The structured fields are unchanged, so `find` and `structure` offsets keep their coordinate system; the banner is also returned on its own `banner` key so a caller can strip it deterministically.
- An absent **or blank** `GOVINFO_API_KEY` now fails the server at startup with a message naming the variable (stderr, exit 2), before any server object exists — a server that can serve nothing must be unmistakably down rather than up and wearing a misleading per-request error (R10 third amendment, from congressMCP's F31).
- Runtime dependencies now carry ceilings as well as floors (R9): `mcp>=2,<3`, `httpx>=0.27,<1`, `python-dotenv>=1.0,<2`. Raising a ceiling is a deliberate, tested change committed on its own.
- Disambiguation (`ambiguous`) outcomes state capping explicitly: `count` (true total), `candidates_shown`, `capped`, and a "showing N of M" message when the candidate list is page-capped — and no capping claim when it isn't.
- Appendix citations now resolve directly (`citation:"28 U.S.C. App. Rule 9"`, O24/E10); multi-hit appendix citations use the standard disambiguation list (which now also reports the true total `count`), and the redirect to `search_us_code` survives only as the zero-hit fallback (real for eliminated appendices like title 50's).
- The `get_public_law` `format="uslm"` not-available outcome now states the measured boundary (absent for congresses 104–112, present from the 113th on, O25) instead of "unmeasured".
- A set-but-blank `USCODE_MCP_TRACE_DIR` now fails the server at startup instead of silently disabling tracing; only an unset variable is the off switch (maintainer ruling, spec commit 2ebab5b).
- The GovInfo API key now travels only in the `X-Api-Key` request header, never as the `api_key` query parameter (R7, O22) — every URL the server builds, logs, or surfaces is key-free by construction.
- The `search_public_laws` recall caveat now states the measured structural gap from O21 (25/33 sampled recall, misses in every congress sampled from the 115th on) instead of the single-miss example.
