# Contributing to uscode-mcp

This is the canonical source for repo conventions — humans and AI coding agents both read this file. `.claude/CLAUDE.md` and `AGENTS.md` (kept identical to each other; see [Keeping AGENTS.md and .claude/CLAUDE.md in sync](#keeping-agentsmd-and-claudeclaudemd-in-sync)) defer to it for anything not restated there; if you find a conflict between this file and one of those, this file wins. The commit-trailer rule and the `documentation/` write restriction below are also stated inline in `.claude/CLAUDE.md` / `AGENTS.md`, on purpose: those two are operative constraints an agent must see even if it only ever auto-loads its own CLAUDE.md/AGENTS.md and never opens this file.

Markdown in this repo is not hard-wrapped: one line per paragraph, long lines are fine. It keeps a one-word edit to a one-line diff instead of a reflow cascade. Structural content (tables, fenced code, headings) is exempt from that and formatted normally.

## Development

Every piece of built functionality gets unit tests covering failure surfacing, not just the happy path, and the suite stays green.

**Dependency versions get a ceiling, not just a floor.** Runtime dependencies with breaking-change potential are constrained on both ends — for the `mcp` SDK that means capping below the next major (e.g. `>=2,<3`), and the same shape applies to any dependency whose majors break APIs. The rule exists because MCP 2.0's breaking changes are what broke congressMCP (documentation/96-rulings.md R9): an uncapped floor turns someone else's release day into this server's outage. Raising a ceiling is a deliberate change — bump it in its own commit with the suite run against the new major, never as a side effect.

## Commit conventions

Commit each logical unit of work as you go, rather than batching unrelated changes into one commit — prefer several small, clear commits over one large one. Wrap commit message bodies at ~80 columns (commit messages are the one place in this repo that *does* get a column wrap, since they're read as fixed-width text by `git log`, not edited later).

**AI-assisted commits get a trailer.** If a commit was authored or materially assisted by an AI coding agent, add a trailer at the end of the message identifying the model, using that model's own vendor no-reply address (or equivalent identifier) if it isn't a Claude model:

```
Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

Git and GitHub both parse this trailer case-insensitively, and GitHub's own squash-merge button emits `Co-authored-by:` (lowercase) regardless of what the source commits used — don't hand-fix casing on squash-merged history. For commits you write directly, prefer the `Co-Authored-By:` casing above to match this repo's existing trailers.

This applies to work on this repository specifically — a contributor's own private/global tooling config (e.g. a personal `CLAUDE.md` outside this repo) does not override it for commits that land here.

Commits, just like code, should be wrapped at 80 columns for legibility.

## The two-session model for `documentation/`

Work is split across two kinds of session, and this split is an active, ongoing convention:

- **Spec session**: owns all of `documentation/`, and may not write anywhere else in the repo. It must not read implementation source — its job is to specify, not to describe what was built. Its detailed working rules — formatting, question routing, preregistration of experiments — are in `documentation/CLAUDE.md`; read that file before writing there.
- **Implementation session**: owns everything outside `documentation/`. It must not write into `documentation/` — that stays the spec session's exclusive domain — and it must write unit tests for everything it builds, keeping the applicable suite green. To the implementation session, `documentation/` is the requirements document; to report a discrepancy back, it hands the spec session observable artifacts (failing inputs, traces), not summaries.

Exceptions to the write boundaries happen only by explicit maintainer authorization, recorded in `documentation/96-rulings.md` (R5 is the precedent: a one-time grant to fix this file's own carried-over boilerplate).

## Keeping AGENTS.md and .claude/CLAUDE.md in sync

Different tools look for different filenames — Claude Code reads `.claude/CLAUDE.md`, most other agent CLIs read `AGENTS.md` — so this repo keeps two copies of the same content rather than picking one tool to favor. A symlink would collapse them to one file to maintain, but Git for Windows doesn't enable symlinks by default, which would turn `AGENTS.md` into a one-line text file containing a path instead of any actual conventions on a plain Windows clone — worse than the duplication it would "fix." Instead, `tests/test_conventions_sync.py` asserts the two files are byte-identical (the implementation session creates this test with its first test suite), so drift between them fails the suite instead of silently persisting. If you edit one, edit both, or let the test catch it.

## Pull requests

1. Fork the repository.
2. Create a feature branch.
3. Follow the conventions above.
4. Submit a pull request against `master`.
