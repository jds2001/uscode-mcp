"""Keyless startup fails fast (96-rulings.md, R10 third amendment, from congressMCP's
F31; contract in 20-govinfo-api.md).

The load-bearing assertion is not just "it exits nonzero" — it is that the failure
happens at *startup*, before a server object exists, so a keyless server can never
come up and wear a misleading per-request error. Every case here asserts that
`create_server` was never reached.
"""

import os

import pytest

from uscode_mcp import __main__ as entry
from uscode_mcp.govinfo import client_from_env


@pytest.fixture
def isolated_env(monkeypatch):
    """Neutralize .env discovery so the repo's own key can't leak into these tests."""
    monkeypatch.setattr(entry, "checkout_root", lambda *a, **k: None)
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

    def test_a_key_that_is_only_surrounded_by_whitespace_still_starts(self, isolated_env, spy_server, monkeypatch):
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


# ---------------------------------------------------------------------------
# WO-15 G (R26 c): a .env is read only from a repository checkout's root
# ---------------------------------------------------------------------------


def _checkout(base, *, env=None):
    """A checkout layout: <root>/pyproject.toml naming this project and
    <root>/src/uscode_mcp/__main__.py. Returns (root, package file)."""
    root = base / "repo"
    (root / "src" / "uscode_mcp").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "uscode-mcp"\nversion = "0.1.0"\n', encoding="utf-8")
    package_file = root / "src" / "uscode_mcp" / "__main__.py"
    package_file.write_text("", encoding="utf-8")
    if env is not None:
        (root / ".env").write_text(env, encoding="utf-8")
    return root, package_file


def _installed(base):
    """An installed layout: the package under a site-packages directory, no src/,
    no pyproject.toml. Returns the package file."""
    package_dir = base / "venv" / "lib" / "python3.12" / "site-packages" / "uscode_mcp"
    package_dir.mkdir(parents=True)
    package_file = package_dir / "__main__.py"
    package_file.write_text("", encoding="utf-8")
    return package_file


@pytest.fixture
def clean_environ(monkeypatch):
    """A private copy of the process environment without the key, so a loaded .env
    cannot leak into other tests (python-dotenv writes to os.environ at call time)."""
    monkeypatch.setattr(os, "environ", dict(os.environ))
    os.environ.pop("GOVINFO_API_KEY", None)


class TestCheckoutRoot:
    def test_recognises_the_checkout_layout(self, tmp_path):
        root, package_file = _checkout(tmp_path)
        assert entry.checkout_root(package_file) == root

    def test_the_real_package_runs_from_this_checkout(self):
        # uv installs the project editable, so the package file sits under src/.
        root = entry.checkout_root()
        assert root is not None
        assert (root / "pyproject.toml").is_file()
        assert (root / "src" / "uscode_mcp" / "__main__.py").is_file()

    def test_installed_layout_is_not_a_checkout(self, tmp_path):
        assert entry.checkout_root(_installed(tmp_path)) is None

    def test_a_src_layout_of_another_project_is_not_a_checkout(self, tmp_path):
        root, package_file = _checkout(tmp_path)
        (root / "pyproject.toml").write_text('[project]\nname = "something-else"\n', encoding="utf-8")
        assert entry.checkout_root(package_file) is None

    def test_a_src_layout_without_pyproject_is_not_a_checkout(self, tmp_path):
        root, package_file = _checkout(tmp_path)
        (root / "pyproject.toml").unlink()
        assert entry.checkout_root(package_file) is None


class TestDotenvOnlyFromTheCheckoutRoot:
    def test_a_dotenv_in_a_parent_of_the_working_directory_is_not_loaded(
        self, tmp_path, monkeypatch, clean_environ, spy_server, capsys
    ):
        # (1) The checkout has no .env; one sits above the working directory. The old
        # find_dotenv(usecwd=True) walk would have found it. Nothing may.
        root, package_file = _checkout(tmp_path)
        (tmp_path / ".env").write_text("GOVINFO_API_KEY=parent-key\n", encoding="utf-8")
        monkeypatch.setattr(entry, "PACKAGE_FILE", package_file)
        work = root / "deep" / "er"
        work.mkdir(parents=True)
        monkeypatch.chdir(work)
        assert entry.main([]) == 2
        assert "GOVINFO_API_KEY" not in os.environ
        assert spy_server["created"] == 0
        assert "GOVINFO_API_KEY" in capsys.readouterr().err

    def test_an_installed_copy_loads_no_dotenv_even_from_the_working_directory(
        self, tmp_path, monkeypatch, clean_environ, spy_server
    ):
        # (2) Installed layout, a .env right in the working directory: not read.
        package_file = _installed(tmp_path)
        monkeypatch.setattr(entry, "PACKAGE_FILE", package_file)
        work = tmp_path / "work"
        work.mkdir()
        (work / ".env").write_text("GOVINFO_API_KEY=cwd-key\n", encoding="utf-8")
        monkeypatch.chdir(work)
        assert entry.load_checkout_dotenv() is None
        assert entry.main([]) == 2
        assert "GOVINFO_API_KEY" not in os.environ
        assert spy_server["created"] == 0

    def test_the_checkout_root_dotenv_loads_when_run_from_elsewhere(
        self, tmp_path, monkeypatch, clean_environ, spy_server
    ):
        # (3) The checkout's own .env is read regardless of the working directory.
        root, package_file = _checkout(tmp_path, env="GOVINFO_API_KEY=checkout-key\n")
        monkeypatch.setattr(entry, "PACKAGE_FILE", package_file)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / ".env").write_text("GOVINFO_API_KEY=elsewhere-key\n", encoding="utf-8")
        monkeypatch.chdir(elsewhere)
        assert entry.load_checkout_dotenv() == root / ".env"
        assert entry.main([]) == 0
        assert os.environ["GOVINFO_API_KEY"] == "checkout-key"
        assert spy_server["created"] == 1

    def test_the_process_environment_wins_over_the_checkout_dotenv(self, tmp_path, monkeypatch, clean_environ):
        root, package_file = _checkout(tmp_path, env="GOVINFO_API_KEY=checkout-key\n")
        monkeypatch.setattr(entry, "PACKAGE_FILE", package_file)
        os.environ["GOVINFO_API_KEY"] = "process-key"
        entry.load_checkout_dotenv()
        assert os.environ["GOVINFO_API_KEY"] == "process-key"

    @pytest.mark.parametrize("layout", ["checkout-without-dotenv", "checkout-with-blank-key", "installed"])
    def test_the_no_key_exit_is_unchanged_in_every_layout(
        self, tmp_path, monkeypatch, clean_environ, spy_server, capsys, layout
    ):
        # (4) Whatever the layout, no key means exit 2, the variable named on stderr,
        # nothing on stdout, and no server object built.
        if layout == "installed":
            package_file = _installed(tmp_path)
        else:
            _, package_file = _checkout(
                tmp_path, env=("GOVINFO_API_KEY=   \n" if layout == "checkout-with-blank-key" else None)
            )
        monkeypatch.setattr(entry, "PACKAGE_FILE", package_file)
        monkeypatch.chdir(tmp_path)
        assert entry.main([]) == 2
        captured = capsys.readouterr()
        assert "GOVINFO_API_KEY" in captured.err
        assert "is not set (or is blank)" in captured.err
        assert captured.out == ""
        assert spy_server["created"] == 0
