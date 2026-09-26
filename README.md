# uscode-mcp

An MCP server that gives a model search and retrieval over the United States Code as published by GPO on GovInfo, extended to the Public Laws (PLAW) collection for enacted law that is newer than — or was never destined for — the codified Code.

The spec lives in `documentation/` and is the requirements document for everything here; see `documentation/00-INDEX.md`.

## Setup

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/). An api.data.gov API key goes in a repo-root `.env` (gitignored; see `.env.example`):

```
GOVINFO_API_KEY=...
```

The `.env` is a development convenience: the server reads it only when it runs from a repository checkout, and only the file at that checkout's root — it never walks up from the working directory, and an installed copy (a wheel or any layout without the checkout root) reads no `.env` at all, so production configuration is the process environment alone.

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

> **Security warning:** The HTTP transport is unauthenticated. Anyone who can reach its port can call every tool and spend the configured GovInfo API key's quota. Keep it bound to loopback unless its network accessibility is otherwise restricted; for remote access, put it behind something that authenticates callers, such as an API Gateway or an authenticating reverse proxy.

Example Claude Code / Claude Desktop stdio config:

```json
{
  "mcpServers": {
    "uscode": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/uscode-mcp", "uscode-mcp"]
    }
  }
}
```

## Tools

- `get_us_code_section` — resolve a citation ("17 U.S.C. 107", "42 U.S.C. 2210 note", …) and return the section's text, statutory notes included, with provenance (`currentthrough` staleness date, edition year, PDF link). Every success also carries `possibly_superseded`, a three-state staleness indicator (see below). When a citation matches several granules (the two "28 U.S.C. App. Rule 9"s, say) the response is `ambiguous` with a candidate list; re-request with `granule_id` from that list, passing the same `citation` alongside so the staleness check still runs. The id is never turned into a URL: the server fetches the granule summary and follows its `txtLink` verbatim.
- `search_us_code` — full-text and fielded search over the USCODE collection; returns pointers, not text.
- `get_public_law` — resolve "Pub. L. 118-31" (or congress + number) and return the law's text, or USLM XML where offered.
- `search_public_laws` — as above, scoped to PLAW; documents the `uscodecitation` reverse-lookup recipe and its measured recall gap.

Text windows default to 20,000 characters (`max_chars`); larger windows were measured not to reach the model inline on the current driver, so a bigger default would spend the first call discovering that. An explicit larger `max_chars` is honored as before.

All tools distinguish three outcomes — success (including explicit zero results), upstream failure (status + body surfaced), and rate-limited (429 with headers passed through) — and window large payloads with explicit truncation markers, never silently: a truncated response carries a bracketed banner line in `text.banner` stating the window bounds, the true total and the continuation offset, while `text.content` is payload text only, so offsets from `find` and `structure` stay in one coordinate system (F1/E12, then R13c). The API key travels only in the `X-Api-Key` header, never in a URL; absent or blank, the server exits at startup rather than coming up unable to serve anything.

### Staleness indicator (R14)

Annual editions lag enactment, so every `get_us_code_section` success carries a `possibly_superseded` object answering one narrow question: does GovInfo's public-law index list any law published after this edition's `currentthrough` against this section? The query it runs is echoed verbatim, bounded by the returned edition's own `currentthrough` plus one day (so a `year`-selected edition gets its own bound). Three states, never two: `laws_indexed` (the true upstream `count` plus a capped `laws` list, capping stated), `none_indexed`, and `not_checked` (the upstream failure, rate limit, timeout, or malformed body surfaced verbatim — never folded into "none"). It is an indicator in both directions and never a certification: a listed law may amend a different part of the section, only cite it, or not yet be effective, and the index misses about one in seven real (law, section) pairs, so `none_indexed` is not evidence the text is current. When a "note" citation was stripped, the object says the check ran against the parent section. A detector failure never fails the lookup, and the lookup never waits more than a bounded budget for it once the text is ready.

### Locating content in large payloads (R12)

Both text tools take an optional `find` — a case-insensitive literal substring searched across the *whole* payload, not just the returned window — and report the true occurrence count with offsets and context snippets. Offsets share the `start_char`/`total_chars` coordinate system, so one call locates and the next reads. `get_us_code_section` carries a `structure` block on the locating call (`start_char` 0 or omitted): the payload's fields in order (`statute`, `sourcecredit`, each typed note with its heading) with a `start_char` and an exclusive `end_char` apiece, read from the granule's own upstream field markers — so `end_char - start_char` is both the field's extent and the `max_chars` needed to read it. A reading call gets the `omitted` form pointing back, since the block is invariant for the section. It is also `omitted`, with a reason, when a granule's markers are absent or don't balance — never guessed from headings.

Headings are upstream labels reported verbatim, and they describe where a field *opens*, not everything it contains: one 38,154-character "Findings" note holds an entire Act. Judge a field by its extent and search it with `find`; absence of a heading naming something is not evidence it isn't there.

## Tracing (R8)

Set `USCODE_MCP_TRACE_DIR` to a directory to record every handled MCP tool call as one JSONL line (verbatim request and response, including error outcomes) in a per-run `trace-*.jsonl` file. Only an unset variable disables tracing — set-but-blank fails the server at startup like any other unusable directory, so a typo cannot silently turn the instrument off. An unusable directory fails the server at startup; a failed trace write fails that request loudly rather than leaving a silently incomplete trace.

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

See `CONTRIBUTING.md` for conventions, including the two-session model for `documentation/`.
