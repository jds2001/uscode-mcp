"""Keyless startup fails fast (96-rulings.md, R10 third amendment, from congressMCP's
F31; contract in 20-govinfo-api.md).

The load-bearing assertion is not just "it exits nonzero" — it is that the failure
happens at *startup*, before a server object exists, so a keyless server can never
come up and wear a misleading per-request error. Every case here asserts that
`create_server` was never reached.
"""

import pytest

from uscode_mcp import __main__ as entry
from uscode_mcp.govinfo import client_from_env


@pytest.fixture
def isolated_env(monkeypatch):
    """Neutralize .env discovery so the repo's own key can't leak into these tests."""
    monkeypatch.setattr(entry, "find_dotenv", lambda *a, **k: "")
    monkeypatch.setattr(entry, "load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("GOVINFO_API_KEY", raising=False)


@pytest.fixture
def spy_server(monkeypatch):
    """Record whether the server was ever built, and never actually run one."""
    calls = {"created": 0, "ran": []}

    class _FakeServer:
        def run(self, **kwargs):
            calls["ran"].append(kwargs)

    def _create_server():
        calls["created"] += 1
        return _FakeServer()

    monkeypatch.setattr(entry, "create_server", _create_server)
    return calls


class TestKeylessStartup:
    def test_absent_key_exits_before_the_server_is_built(self, isolated_env, spy_server, capsys):
        assert entry.main([]) == 2
        assert spy_server["created"] == 0, "the server must not be built without a key"
        assert spy_server["ran"] == []

    def test_absent_key_names_the_variable_on_stderr(self, isolated_env, spy_server, capsys):
        entry.main([])
        captured = capsys.readouterr()
        assert "GOVINFO_API_KEY" in captured.err
        assert captured.out == "", "stdout belongs to the stdio transport"

    @pytest.mark.parametrize("blank", ["", " ", "\t", "   \n"])
    def test_blank_key_is_treated_as_absent(self, isolated_env, spy_server, capsys, monkeypatch, blank):
        monkeypatch.setenv("GOVINFO_API_KEY", blank)
        assert entry.main([]) == 2
        assert spy_server["created"] == 0
        assert "GOVINFO_API_KEY" in capsys.readouterr().err

    def test_the_failure_is_not_deferred_to_the_first_request(self, isolated_env, spy_server):
        # There is no server to make a request against: the guard runs before
        # create_server, so no MCP session can be established at all.
        entry.main([])
        assert spy_server["created"] == 0

    def test_a_present_key_starts_the_server(self, isolated_env, spy_server, monkeypatch):
        # Positive control: the guard rejects keylessness, not everything.
        monkeypatch.setenv("GOVINFO_API_KEY", "a-key")
        assert entry.main([]) == 0
        assert spy_server["created"] == 1
        assert spy_server["ran"] == [{"transport": "stdio"}]

    def test_a_key_that_is_only_surrounded_by_whitespace_still_starts(
        self, isolated_env, spy_server, monkeypatch
    ):
        monkeypatch.setenv("GOVINFO_API_KEY", "  a-key  ")
        assert entry.main([]) == 0
        assert spy_server["created"] == 1


class TestClientFromEnvBackstop:
    """The startup guard is primary; client_from_env is the backstop for embedders
    that build a client directly. Blank counts as absent there too."""

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_blank_key_is_rejected(self, monkeypatch, blank):
        monkeypatch.setenv("GOVINFO_API_KEY", blank)
        with pytest.raises(RuntimeError, match="GOVINFO_API_KEY"):
            client_from_env()

    def test_surrounding_whitespace_is_stripped_from_a_real_key(self, monkeypatch):
        monkeypatch.setenv("GOVINFO_API_KEY", "  a-key  ")
        client = client_from_env()
        assert client._api_key == "a-key"
