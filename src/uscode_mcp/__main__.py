"""CLI entry point: `uscode-mcp` (or `python -m uscode_mcp`).

Runs the MCP server over stdio by default, or streamable HTTP with --transport http.
Startup errors go to stderr — stdout belongs to the stdio transport.
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import find_dotenv, load_dotenv

from .govinfo import API_KEY_ENV_VAR
from .server import create_server


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

    load_dotenv(find_dotenv(usecwd=True))
    if not os.environ.get(API_KEY_ENV_VAR):
        print(
            f"error: {API_KEY_ENV_VAR} is not set. Put it in the repo-root .env (gitignored) or the environment.",
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
