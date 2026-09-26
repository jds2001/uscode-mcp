"""CLI entry point: `uscode-mcp` (or `python -m uscode_mcp`).

Runs the MCP server over stdio by default, or streamable HTTP with --transport http.
Startup errors go to stderr — stdout belongs to the stdio transport.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from .govinfo import API_KEY_ENV_VAR
from .server import create_server

PACKAGE_FILE = Path(__file__).resolve()
_PROJECT_NAME_RE = re.compile(r'^name\s*=\s*"uscode-mcp"\s*$', re.MULTILINE)


def checkout_root(package_file: Path | None = None) -> Path | None:
    """The repository checkout this package runs from, or None when it is installed.

    R26 (c), WO-15 G: a `.env` is a development convenience, read only from a
    checkout's root — never found by walking up from the working directory, never
    when installed as a package. A checkout is recognised by its layout: this file at
    ``<root>/src/uscode_mcp/__main__.py`` with ``<root>/pyproject.toml`` naming this
    project. A wheel or site-packages install has neither, so it reads no `.env`.
    """
    if package_file is None:
        package_file = PACKAGE_FILE
    package_dir = package_file.parent
    if package_dir.name != "uscode_mcp" or package_dir.parent.name != "src":
        return None
    root = package_dir.parent.parent
    try:
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return None
    if not _PROJECT_NAME_RE.search(pyproject):
        return None
    return root


def load_checkout_dotenv() -> Path | None:
    """Load ``<checkout root>/.env`` when running from a checkout; otherwise nothing.
    Returns the path consulted, or None. The process environment always wins over
    the file (python-dotenv's default: no override)."""
    root = checkout_root()
    if root is None:
        return None
    path = root / ".env"
    load_dotenv(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="uscode-mcp",
        description="MCP server for searching and retrieving the US Code and Public Laws from GovInfo.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio (default) or http (streamable HTTP)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host for --transport http (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="bind port for --transport http (default 8000)")
    args = parser.parse_args(argv)

    load_checkout_dotenv()
    # Keyless startup fails fast (96-rulings.md, R10 third amendment, from F31): a
    # server that can serve nothing must be unmistakably down, not up and wearing a
    # misleading per-request error. Blank counts as absent — a whitespace-only value
    # is a broken config, not a key.
    if not os.environ.get(API_KEY_ENV_VAR, "").strip():
        print(
            f"error: {API_KEY_ENV_VAR} is not set (or is blank). Every GovInfo request needs it, so "
            f"the server exits now rather than starting and failing every call. Put it in the "
            f"repo-root .env (gitignored) or the environment.",
            file=sys.stderr,
        )
        return 2

    try:
        server = create_server()
    except RuntimeError as exc:
        # e.g. an unusable USCODE_MCP_TRACE_DIR — R8 says fail at startup, loudly.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.transport == "http":
        server.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
