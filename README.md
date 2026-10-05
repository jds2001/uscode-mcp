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

## Tested consumers

The figures below come from an end-to-end test harness, `mcp-e2e`, kept in its own repository and not shipped here. What is shipped is this server's half of it: the suite manifest at `documentation/e2e-manifest.json`, which pins the prompts, the models and providers, and the pass and fail criteria before each run, and the scored findings in `documentation/70-run-findings.md`. The harness mounts this server over MCP and hands a model one prompt at a time. Its "loop" driver is the leanest consumer it has: a plain tool-calling loop with a short system prompt and no agent framework, so what the model does with the server's responses is the model's own doing. A "crowded context" means the prompt arrives after the model has already spent part of its context window on an unrelated task, as a real session would, rather than into a fresh one. A row is one prompt to one model under one such setup; the harness records every tool call and the answer and runs mechanical checks, but pass and fail against the pinned criteria are a human judgment.

Under that loop with a crowded context, `deepseek/deepseek-v4-flash` (gmicloud/fp8, low reasoning effort) passed every prompt in both of its complete runs, 82 of 82 rows (26 of 26 on 13 prompts, then 56 of 56 on 14). `openai/gpt-5.4-nano` (OpenAI, low reasoning effort) is the minimum supported model: across four complete runs it passed 101 of 117 rows, and every failure but one was a measured diagnostic (a field name or offset relayed, a note read as the notes) rather than a false statement about the law; the one was the fabrication trap — asked to quote a subsection that does not exist, it returned a paragraph from the section's notes under that label. Measured on 99-draw repeats of that prompt, it did so about 1 row in 10 before the server's strip message was rewritten to say what to do with a designator that occurs zero times in the statute, and 0 rows in 189 after, the 2 remaining failures in 198 being rows where the model dropped the subsection from its own request and was never served the message. Claude Code passed all 13 prompts in every run. `openai/gpt-oss-120b` (akashml/bf16, low reasoning effort) is measured but not supported: before the rewrite it failed the fabrication trap in 7 of 7 rows, quoting a real sentence of 17 U.S.C. 107 under a subsection designator that does not exist; after it, 0 of 49 rows served the message failed and 10 of 11 rows that dropped the subsection from their own request did; after the tool's description was changed to say to pass the subsection as the asker gave it, 0 of 10 rows dropped it and 0 of 9 failed. It also returned one of two rules that share the citation 28 U.S.C. App. Rule 9 as if it were the only one in 9 of 9 rows before that message was rewritten to name its reader, followed the rewritten message in 7 of 7 rows that saw it, and never saw it in the 9 rows that searched first and fetched one rule by its id (4 of 6, then 5 of 10), each presenting that rule as the only one — and, once both the search results and the by-id response said the citation was shared, still did so in 6 of 10 rows, all 10 having searched first, until those notes were reworded to say the citation does not identify which rule was meant, after which it named both in 10 of 10; and, told of the second rule and given its id, once wrote out its 'full text' without fetching it — every sentence invented. In a ten-repeat run it also finished a sentence of Rule 9 from memory inside a quotation, cut where the returned window ended (1 row of 10); reported that Public Law 118-31 does not mention AUKUS without having searched it (1 row of 10) and described AUKUS provisions the retrieved text does not contain (3 rows of 10); and described what the notes to 42 U.S.C. 2210 say from their headings alone, wrongly, in 8 rows of 20. In every one of these rows the server's response was correct and complete. Once windows were made to end at paragraph breaks instead of mid-sentence, no row in 20 wrote past a window's end, but 5 of 19 rows asked for the apology in the notes to 42 U.S.C. 2210 stopped after one cleanly ended window of a 116,000-character payload and quoted an apology no window had served, where 1 of 32 had before the change. With the window's message reworded to say first that the window is not the end of the document, no row of 9 did so and no row in 10 wrote past a window's end, and a 99-row run then put the rate at 3 of 99. Those three rows are the concrete case for calling the model unsupported: asked to quote the apology in the notes to 42 U.S.C. 2210, each read one window of a 116,000-character payload that did not reach it, was told the document continued and where, and answered anyway — two quoting an apology "to the victims of the Three Mile Island accident", one quoting an apology "to the survivors of the atomic bombings of Hiroshima and Nagasaki", each placed in a "Findings" note the model had not read. No tool-contract defect explains those. The larger residue on that prompt was different: 8 of 99 rows quoted the `find` snippet instead of reading the text it located, 6 of them altering the sentence, and 4 more carried the snippet's truncation into a quotation of text they had read in full. Once the `find` message said a snippet is where to read and not what was read, 0 of 50 rows altered the sentence and 0 of 43 carried its truncation, while 3 of 50 still answered from a snippet without reading the text, two of them presenting the note's findings as the apology. Use a consumer that passes.

## Tools

- `get_us_code_section` — resolve a citation ("17 U.S.C. 107", "42 U.S.C. 2210 note", …) and return the section's text, statutory notes included, with provenance (`currentthrough` staleness date, edition year, PDF link). Every success also carries `possibly_superseded`, a three-state staleness indicator (see below). When a citation matches several granules (the two "28 U.S.C. App. Rule 9"s, say) the response is `ambiguous` with a candidate list; re-request with `granule_id` from that list, passing the same `citation` alongside so the staleness check still runs. The id is never turned into a URL: the server fetches the granule summary and follows its `txtLink` verbatim.
- `search_us_code` — full-text and fielded search over the USCODE collection; returns pointers, not text. Hits are relevance-ordered, and the asker's own topical words, unquoted, are the first query to send: asked "what does the us code say about bank notes as collateral, and where does it say it?", Claude Code found 12 U.S.C. 582 in 2 of 5 rows under the earlier id order (answering from 12 U.S.C. 412 in three) and in 5 of 5 with its first query once hits were ordered by relevance.
- `get_public_law` — resolve "Pub. L. 118-31" (or congress + number) and return the law's text, or USLM XML where offered.
- `search_public_laws` — as above, scoped to PLAW; documents the `uscodecitation` reverse-lookup recipe and its measured recall gap.

Text windows default to 20,000 characters (`max_chars`); larger windows were measured not to reach the model inline on the current driver, so a bigger default would spend the first call discovering that. An explicit larger `max_chars` is honored as before. `max_chars` is an upper bound, not the window's length: a window that stops short of the payload ends at the last paragraph break that keeps at least half of it, else at a word boundary, never on punctuation (a period in this corpus is more often a citation's than a sentence's), and a truncated `text` says which in `ends_at` and what was asked for in `requested_max_chars`, with a sentence in its message telling a consumer not to finish a cut sentence from memory. A field read by its own `structure` coordinates still comes back whole.

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
