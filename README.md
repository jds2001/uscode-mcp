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

All tools distinguish three outcomes — success (including explicit zero results), upstream failure (status + body surfaced), and rate-limited (429 with headers passed through) — and window large payloads with explicit truncation markers, never silently.

## Development

```sh
uv run pytest
uv run ruff check .
```

See `CONTRIBUTING.md` for conventions, including the two-session model for `documentation/`.
