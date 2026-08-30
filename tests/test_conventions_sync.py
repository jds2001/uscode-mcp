"""Guards AGENTS.md and .claude/CLAUDE.md against drifting apart (see CONTRIBUTING.md)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_agents_md_and_claude_md_are_byte_identical():
    agents = (REPO_ROOT / "AGENTS.md").read_bytes()
    claude = (REPO_ROOT / ".claude" / "CLAUDE.md").read_bytes()
    assert agents == claude, (
        "AGENTS.md and .claude/CLAUDE.md must stay byte-identical; edit both together (see CONTRIBUTING.md)"
    )
