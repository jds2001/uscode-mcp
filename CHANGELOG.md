# Changelog

## Unreleased

### Added

- R8 trace emission: setting `USCODE_MCP_TRACE_DIR` appends one JSONL line per handled MCP tool call (verbatim request and response, including error outcomes); an unusable directory fails the server at startup and a per-request write failure fails that request loudly.
- Initial MCP server scaffolding (implementation session): `uscode-mcp` Python package (`uv`-managed, `mcp` SDK 2.x) serving the four tools specified in `documentation/40-tools.md` — `get_us_code_section`, `search_us_code`, `get_public_law`, `search_public_laws` — over stdio (default) and streamable HTTP (`--transport http`).
- GovInfo API client with the three-outcome contract (success / upstream failure / rate-limited, never collapsed), citation normalization with the two mandatory strips (subsection, trailing "note"), HTML-to-text derivation with `currentthrough` provenance, and explicit (never silent) truncation windows.
- Unit test suite (114 tests) covering failure surfacing alongside the happy paths.
- `CONTRIBUTING.md` as the canonical source for code style, commit conventions, and the `documentation/` two-session model — resolves the conflicting commit-trailer guidance between `.claude/CLAUDE.md` and the workspace-level `CLAUDE.md` (#46, #78).
- `tests/test_conventions_sync.py` guards `AGENTS.md` and `.claude/CLAUDE.md` against drifting apart.

### Changed

- The GovInfo API key now travels only in the `X-Api-Key` request header, never as the `api_key` query parameter (R7, O22) — every URL the server builds, logs, or surfaces is key-free by construction.
- The `search_public_laws` recall caveat now states the measured structural gap from O21 (25/33 sampled recall, misses in every congress sampled from the 115th on) instead of the single-miss example.
