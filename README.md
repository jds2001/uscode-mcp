# uscode-mcp

An MCP server that gives a model search and retrieval over the United States Code as published by GPO on GovInfo, extended to the Public Laws (PLAW) collection for enacted law that is newer than — or was never destined for — the codified Code.

The spec lives in `documentation/` and is the requirements document for everything here; see `documentation/00-INDEX.md`.

## Setup

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/). An api.data.gov API key goes in a repo-root `.env` (gitignored; see `.env.example`):

```
GOVINFO_API_KEY=...
```

```sh
uv sync
```

## Running

Stdio (the primary transport, for MCP hosts that launch the server as a subprocess):

```sh
uv run uscode-mcp
```

Streamable HTTP:

```sh
uv run uscode-mcp --transport http --host 127.0.0.1 --port 8000
```

Example Claude Code / Claude Desktop stdio config:

```json
{
  "mcpServers": {
    "uscode": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/uscde-mcp", "uscode-mcp"]
    }
  }
}
```

## Tools

- `get_us_code_section` — resolve a citation ("17 U.S.C. 107", "42 U.S.C. 2210 note", …) and return the section's text, statutory notes included, with provenance (`currentthrough` staleness date, edition year, PDF link).
- `search_us_code` — full-text and fielded search over the USCODE collection; returns pointers, not text.
- `get_public_law` — resolve "Pub. L. 118-31" (or congress + number) and return the law's text, or USLM XML where offered.
- `search_public_laws` — as above, scoped to PLAW; documents the `uscodecitation` reverse-lookup recipe and its measured recall gap.

All tools distinguish three outcomes — success (including explicit zero results), upstream failure (status + body surfaced), and rate-limited (429 with headers passed through) — and window large payloads with explicit truncation markers, never silently. The API key travels only in the `X-Api-Key` header, never in a URL.

### Locating content in large payloads (R12)

Both text tools take an optional `find` — a case-insensitive literal substring searched across the *whole* payload, not just the returned window — and report the true occurrence count with offsets and context snippets. Offsets share the `start_char`/`total_chars` coordinate system, so one call locates and the next reads. `get_us_code_section` successes additionally carry a `structure` block: the payload's fields in order (`statute`, `sourcecredit`, each typed note with its heading) with a `start_char` apiece, read from the granule's own upstream field markers — and explicitly `omitted` with a reason when a granule lacks them or they don't balance, never guessed from headings.

## Tracing (R8)

Set `USCODE_MCP_TRACE_DIR` to a directory to record every handled MCP tool call as one JSONL line (verbatim request and response, including error outcomes) in a per-run `trace-*.jsonl` file. Only an unset variable disables tracing — set-but-blank fails the server at startup like any other unusable directory, so a typo cannot silently turn the instrument off. An unusable directory fails the server at startup; a failed trace write fails that request loudly rather than leaving a silently incomplete trace.

## Development

```sh
uv run pytest
uv run ruff check .
```

See `CONTRIBUTING.md` for conventions, including the two-session model for `documentation/`.
