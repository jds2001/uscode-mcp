"""R8 trace emission: JSONL lines with verbatim request/response, absence-is-off,
unusable directory fails at startup, write failure fails the request loudly."""

import json
import os

import pytest

from uscode_mcp.trace import TRACE_DIR_ENV_VAR, Tracer, TraceWriteError, tracer_from_env


class TestTracerFromEnv:
    def test_absent_env_var_means_off(self, monkeypatch):
        monkeypatch.delenv(TRACE_DIR_ENV_VAR, raising=False)
        assert tracer_from_env() is None

    def test_blank_env_var_fails_at_startup_not_silently_off(self, monkeypatch):
        """Ruled in 2ebab5b: only UNSET disables. Set-but-blank (e.g. a typoed shell
        variable expanding to nothing) must fail loudly, not read as 'tracing off'."""
        for blank in ("", "  "):
            monkeypatch.setenv(TRACE_DIR_ENV_VAR, blank)
            with pytest.raises(RuntimeError, match="set but blank"):
                tracer_from_env()

    def test_set_env_var_builds_tracer(self, monkeypatch, tmp_path):
        monkeypatch.setenv(TRACE_DIR_ENV_VAR, str(tmp_path / "traces"))
        tracer = tracer_from_env()
        assert tracer is not None
        assert tracer.path.parent == tmp_path / "traces"


class TestTracerStartup:
    def test_creates_missing_directory(self, tmp_path):
        tracer = Tracer(tmp_path / "a" / "b")
        assert tracer.path.parent.is_dir()

    def test_path_that_is_a_file_fails_at_startup(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        with pytest.raises(RuntimeError, match=TRACE_DIR_ENV_VAR):
            Tracer(blocker)

    def test_unwritable_directory_fails_at_startup(self, tmp_path):
        locked = tmp_path / "locked"
        locked.mkdir()
        os.chmod(locked, 0o500)
        try:
            with pytest.raises(RuntimeError, match=TRACE_DIR_ENV_VAR):
                Tracer(locked)
        finally:
            os.chmod(locked, 0o700)


class TestTracerRecord:
    def test_one_jsonl_line_per_request_verbatim(self, tmp_path):
        tracer = Tracer(tmp_path)
        request_args = {"citation": "17 U.S.C. 107", "max_chars": 50}
        response = {"outcome": "success", "text": {"content": "x" * 10}}
        tracer.record("get_us_code_section", request_args, response)
        tracer.record("search_us_code", {"query": "fair use"}, {"outcome": "upstream_error", "http_status": 500})

        lines = tracer.path.read_text().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["request"] == {"tool": "get_us_code_section", "arguments": request_args}
        assert first["response"] == response
        assert "timestamp" in first
        second = json.loads(lines[1])
        assert second["response"]["outcome"] == "upstream_error"  # error outcomes traced too

    def test_large_payload_not_truncated(self, tmp_path):
        tracer = Tracer(tmp_path)
        big = {"outcome": "success", "text": {"content": "y" * 500_000}}
        tracer.record("get_public_law", {"congress": 118, "law_number": 31}, big)
        line = json.loads(tracer.path.read_text().splitlines()[0])
        assert line["response"]["text"]["content"] == "y" * 500_000

    def test_write_failure_raises_loudly(self, tmp_path):
        tracer = Tracer(tmp_path)
        tracer.path.unlink()
        os.chmod(tmp_path, 0o500)  # writing a new file will now fail
        try:
            with pytest.raises(TraceWriteError, match="silently incomplete"):
                tracer.record("search_us_code", {"query": "x"}, {"outcome": "success"})
        finally:
            os.chmod(tmp_path, 0o700)

    def test_unserializable_response_raises_loudly(self, tmp_path):
        tracer = Tracer(tmp_path)
        with pytest.raises(TraceWriteError, match="not JSON-serializable"):
            tracer.record("search_us_code", {"query": "x"}, {"bad": object()})


class _Ctx:
    """Stand-in for ServerRequestContext: the middleware reads only method/params."""

    def __init__(self, method, params):
        self.method = method
        self.params = params


class TestTracingMiddleware:
    async def test_tools_call_traced_with_wire_arguments_verbatim(self, tmp_path):
        from uscode_mcp.trace import TracingMiddleware

        tracer = Tracer(tmp_path)
        mw = TracingMiddleware(tracer)
        wire_params = {"name": "get_us_code_section", "arguments": {"citation": "17 U.S.C. 107"}}
        response = {"outcome": "not_found", "query": "..."}

        async def call_next(ctx):
            return response

        result = await mw(_Ctx("tools/call", wire_params), call_next)
        assert result is response
        line = json.loads(tracer.path.read_text().splitlines()[0])
        # Verbatim as received: only the argument sent on the wire, no rebound defaults.
        assert line["request"] == {"tool": "get_us_code_section", "arguments": {"citation": "17 U.S.C. 107"}}
        assert line["response"] == response

    async def test_non_tool_calls_not_traced(self, tmp_path):
        from uscode_mcp.trace import TracingMiddleware

        tracer = Tracer(tmp_path)
        mw = TracingMiddleware(tracer)

        async def call_next(ctx):
            return {"tools": []}

        await mw(_Ctx("tools/list", {}), call_next)
        assert tracer.path.read_text() == ""

    async def test_pydantic_result_serialized(self, tmp_path):
        from pydantic import BaseModel

        from uscode_mcp.trace import TracingMiddleware

        class FakeResult(BaseModel):
            isError: bool = False
            structuredContent: dict = {}

        tracer = Tracer(tmp_path)
        mw = TracingMiddleware(tracer)

        async def call_next(ctx):
            return FakeResult(structuredContent={"outcome": "success"})

        await mw(_Ctx("tools/call", {"name": "search_us_code", "arguments": {"query": "x"}}), call_next)
        line = json.loads(tracer.path.read_text().splitlines()[0])
        assert line["response"]["structuredContent"] == {"outcome": "success"}

    async def test_protocol_failure_traced_then_reraised(self, tmp_path):
        from uscode_mcp.trace import TracingMiddleware

        tracer = Tracer(tmp_path)
        mw = TracingMiddleware(tracer)

        async def call_next(ctx):
            raise ValueError("no such tool")

        with pytest.raises(ValueError, match="no such tool"):
            await mw(_Ctx("tools/call", {"name": "bogus", "arguments": {}}), call_next)
        line = json.loads(tracer.path.read_text().splitlines()[0])
        assert line["request"]["tool"] == "bogus"
        assert line["response"]["error"]["type"] == "ValueError"

    async def test_trace_write_failure_fails_the_request(self, tmp_path):
        from uscode_mcp.trace import TracingMiddleware

        tracer = Tracer(tmp_path)
        tracer.path.unlink()
        mw = TracingMiddleware(tracer)

        async def call_next(ctx):
            return {"outcome": "success"}

        os.chmod(tmp_path, 0o500)
        try:
            with pytest.raises(TraceWriteError):
                await mw(_Ctx("tools/call", {"name": "search_us_code", "arguments": {"query": "x"}}), call_next)
        finally:
            os.chmod(tmp_path, 0o700)
