"""MCP-level request tracing (R8; documentation/40-tools.md, "Trace emission").

Tracing is enabled iff the USCODE_MCP_TRACE_DIR environment variable names a
directory — absence is the off switch; there is no half-enabled state. Every MCP
tool call the server handles is appended as one JSONL line carrying the verbatim
request (tool name and arguments as received) and the verbatim response (as
returned, including error outcomes), plus a timestamp. Nothing is truncated.

The trace is a measurement instrument, so its failure modes follow instrument
rules, not availability rules: an unusable trace directory fails the server at
startup, and a per-request write failure fails that request loudly — a trace
missing lines poisons every conclusion a harness draws from it.

Under R7 the API key lives only in the upstream X-Api-Key header, which is not
part of any MCP request or response, so trace lines are key-free by construction.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TRACE_DIR_ENV_VAR = "USCODE_MCP_TRACE_DIR"


class TraceWriteError(Exception):
    """A trace line could not be written; the traced request must fail loudly."""


class Tracer:
    """Appends one JSONL line per handled tool call to a per-run file in the trace
    directory (trace-{utc timestamp}-{pid}.jsonl; harnesses glob for *.jsonl)."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        root = Path(directory)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"{TRACE_DIR_ENV_VAR}={root} is unusable: {exc}") from exc
        if not root.is_dir():
            raise RuntimeError(f"{TRACE_DIR_ENV_VAR}={root} is not a directory")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.path = root / f"trace-{stamp}-{os.getpid()}.jsonl"
        # R8: an unusable trace directory fails the server at startup, not on the
        # first traced request — probe writability now.
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.close(fd)
        except OSError as exc:
            raise RuntimeError(f"{TRACE_DIR_ENV_VAR}={root} is not writable: {exc}") from exc

    def record(self, tool: str, arguments: dict[str, Any], response: Any) -> None:
        """Append one trace line; raises TraceWriteError on any failure."""
        try:
            line = json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "request": {"tool": tool, "arguments": arguments},
                    "response": response,
                },
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            raise TraceWriteError(f"trace line for tool {tool!r} is not JSON-serializable: {exc}") from exc
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            raise TraceWriteError(
                f"failed to append trace line to {self.path}: {exc}. Failing this request loudly rather than "
                "leaving a silently incomplete trace (R8)."
            ) from exc


def tracer_from_env() -> Tracer | None:
    """Build a Tracer iff USCODE_MCP_TRACE_DIR is set; None (tracing off) only when
    the variable is UNSET. Set-but-blank fails at startup like any other unusable
    directory (maintainer ruling, 2ebab5b): a typo like TRACE_DIR=$TYPOED_VAR must
    not silently disable the instrument — an errored scan must not look like one
    that found nothing."""
    directory = os.environ.get(TRACE_DIR_ENV_VAR)
    if directory is None:
        return None
    if not directory.strip():
        raise RuntimeError(
            f"{TRACE_DIR_ENV_VAR} is set but blank — it must name a usable directory. "
            "Unset the variable to disable tracing; a blank value is treated as an unusable "
            "directory so a typo cannot silently turn the instrument off."
        )
    return Tracer(directory)


def _jsonable(result: Any) -> Any:
    """Convert a handler result (HandlerResult: BaseModel | dict | None) to its JSON
    form for the trace line; anything else is a loud failure, not a guess."""
    if result is None or isinstance(result, dict | list | str | int | float | bool):
        return result
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", by_alias=True, exclude_none=True)
    raise TraceWriteError(f"cannot serialize handler result of type {type(result).__name__} for the trace")


class TracingMiddleware:
    """ServerMiddleware recording every tools/call the server handles (R8, Q7a:
    MCP-level tool calls, not upstream HTTP). It reads the raw pre-validation
    params, so the traced request is the tool name and arguments exactly as
    received on the wire — not rebound with defaults. A raised protocol-level
    failure is still a handled request: it is traced as an error, then re-raised.
    A trace-write failure propagates and fails the request loudly."""

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        if getattr(ctx, "method", None) != "tools/call":
            return await call_next(ctx)
        params = dict(ctx.params or {})
        tool = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            result = await call_next(ctx)
        except TraceWriteError:
            raise
        except Exception as exc:
            self._tracer.record(tool, arguments, {"error": {"type": type(exc).__name__, "message": str(exc)}})
            raise
        self._tracer.record(tool, arguments, _jsonable(result))
        return result
