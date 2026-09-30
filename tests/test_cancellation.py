"""WO-26 part A (S32 finding 1; documentation/40-tools.md, "A cancelled call leaves
nothing running"): when a `get_us_code_section` call is cancelled by its caller,
every upstream request started for it ends with it — the speculative staleness
query included — and none is issued on its behalf afterwards.

Each test cancels the call at a different point, then asserts two things once the
cancellation has been handled: no task started for the call is still pending, and
the mock transport recorded no request begun after the cancellation. The mock
transport stands in for the socket: a handler that is sleeping when its task is
cancelled is a request that was in flight when the call ended.
"""

from __future__ import annotations

import asyncio

import fx
import httpx
import pytest

from uscode_mcp import tools

# The speculative detector query goes out before the citation search only once the
# edition's currentthrough has been observed in this process; every warm test
# starts by completing one plain lookup.
WARM_UP_SEARCH = fx.json_response(fx.search_response([fx.usc_hit()]))


def is_detector(request: httpx.Request) -> bool:
    return request.url.path == "/search" and "collection:PLAW" in fx.request_body(request)["query"]


def kind(request: httpx.Request) -> str:
    if request.url.path == "/search":
        return "detector" if is_detector(request) else "search"
    if request.url.path.endswith("/htm"):
        return "htm"
    if request.url.path.endswith("/summary"):
        return "summary"
    return request.url.path


class Recorder:
    """A mock transport that records every request begun, can hold any request kind
    open until told otherwise, and signals when a given kind has begun."""

    def __init__(self, hold: dict[str, float] | None = None) -> None:
        self.seen: list[str] = []
        self.hold = hold or {}
        self.began: dict[str, asyncio.Event] = {}

    def event(self, request_kind: str) -> asyncio.Event:
        return self.began.setdefault(request_kind, asyncio.Event())

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        k = kind(request)
        self.seen.append(k)
        self.event(k).set()
        if k in self.hold:
            await asyncio.sleep(self.hold[k])
        if k == "detector":
            return fx.json_response(fx.search_response([], count=0))
        if k == "search":
            return fx.json_response(fx.search_response([fx.usc_hit()]))
        if k == "htm":
            return httpx.Response(200, text=fx.SECTION_HTML)
        if k == "summary":
            return fx.json_response(fx.granule_summary())
        raise AssertionError(f"unexpected request: {request.method} {request.url}")


async def warm_up(make_client) -> None:
    out = await tools.get_us_code_section(make_client(Recorder()), citation="17 U.S.C. 107")
    assert out["outcome"] == "success"
    assert tools.CURRENTTHROUGH_MEMORY.predict(2024) == "2025-01-06"


async def cancel_and_settle(call: asyncio.Task, recorder: Recorder) -> tuple[set[asyncio.Task], int]:
    """Cancel the call, wait for it to finish, then let the loop run long enough for
    any orphaned task to have issued a request. Returns the tasks still pending
    that were not pending before the call began, and the number of requests the
    transport had recorded at the moment of cancellation."""
    requests_at_cancel = len(recorder.seen)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    # Long enough for an orphaned detector task to have started and been recorded
    # (its handler runs on the next loop iteration), short enough that a held
    # request (0.5 s) is still in flight if nothing cancelled it.
    await asyncio.sleep(0.05)
    return requests_at_cancel


def pending_tasks() -> set[asyncio.Task]:
    return {t for t in asyncio.all_tasks() if not t.done() and t is not asyncio.current_task()}


class TestCancelledCallLeavesNothingRunning:
    async def test_i_cancelled_during_the_citation_search_with_a_speculative_detector_in_flight(self, make_client):
        await warm_up(make_client)
        recorder = Recorder(hold={"search": 0.5, "detector": 0.5})
        before = pending_tasks()
        call = asyncio.create_task(tools.get_us_code_section(make_client(recorder), citation="17 U.S.C. 107"))
        await recorder.event("search").wait()
        await asyncio.sleep(0)  # let the speculative detector task take its first step
        assert recorder.seen == ["search", "detector"], "precondition: both requests in flight"

        requests_at_cancel = await cancel_and_settle(call, recorder)

        assert pending_tasks() - before == set(), "a task started for the cancelled call is still running"
        assert recorder.seen[requests_at_cancel:] == [], "a request was begun after the cancellation"

    async def test_ii_cancelled_during_the_text_fetch(self, make_client):
        await warm_up(make_client)
        recorder = Recorder(hold={"htm": 0.5, "detector": 0.5})
        before = pending_tasks()
        call = asyncio.create_task(tools.get_us_code_section(make_client(recorder), citation="17 U.S.C. 107"))
        await recorder.event("htm").wait()
        assert "detector" in recorder.seen, "precondition: the speculative detector is in flight with the fetch"

        requests_at_cancel = await cancel_and_settle(call, recorder)

        assert pending_tasks() - before == set(), "a task started for the cancelled call is still running"
        assert recorder.seen[requests_at_cancel:] == [], "a request was begun after the cancellation"

    async def test_ii_cold_cancelled_during_the_text_fetch_issues_no_detector(self, make_client):
        # Cold: the detector would be issued after the fetch. A cancellation during
        # the fetch must mean it is never issued at all.
        recorder = Recorder(hold={"htm": 0.5})
        before = pending_tasks()
        call = asyncio.create_task(tools.get_us_code_section(make_client(recorder), citation="17 U.S.C. 107"))
        await recorder.event("htm").wait()
        assert recorder.seen == ["search", "htm"]

        requests_at_cancel = await cancel_and_settle(call, recorder)

        assert pending_tasks() - before == set()
        assert recorder.seen[requests_at_cancel:] == []
        assert "detector" not in recorder.seen

    async def test_iii_cancelled_while_the_detector_is_awaited(self, make_client):
        # Cold: the text is ready and the call is inside the bounded wait for the
        # detector, which is the one request still in flight.
        recorder = Recorder(hold={"detector": 0.5})
        before = pending_tasks()
        call = asyncio.create_task(tools.get_us_code_section(make_client(recorder), citation="17 U.S.C. 107"))
        await recorder.event("detector").wait()
        assert recorder.seen == ["search", "htm", "detector"]

        requests_at_cancel = await cancel_and_settle(call, recorder)

        assert pending_tasks() - before == set(), "the detector task outlived the cancelled call"
        assert recorder.seen[requests_at_cancel:] == []

    async def test_iv_cancelled_before_the_speculative_task_first_runs_issues_nothing(self, make_client):
        # The speculative task is created before the citation search is sent and
        # takes its first step only when the call next yields. Cancelling the call
        # from inside the search handler — before that yield — means the detector
        # request, if it goes out at all, goes out after the call was cancelled.
        await warm_up(make_client)
        holder: dict[str, asyncio.Task] = {}
        recorder = Recorder(hold={"detector": 0.5})
        inner = recorder.__call__

        async def handler(request: httpx.Request) -> httpx.Response:
            if kind(request) == "search":
                recorder.seen.append("search")
                holder["call"].cancel()
                await asyncio.sleep(0.5)
                return fx.json_response(fx.search_response([fx.usc_hit()]))
            return await inner(request)

        before = pending_tasks()
        holder["call"] = asyncio.create_task(tools.get_us_code_section(make_client(handler), citation="17 U.S.C. 107"))
        with pytest.raises(asyncio.CancelledError):
            await holder["call"]
        await asyncio.sleep(0.05)

        assert pending_tasks() - before == set()
        assert recorder.seen == ["search"], "the speculative detector request was issued after the cancellation"

    async def test_by_id_cancelled_during_the_summary_with_a_speculative_detector_in_flight(self, make_client):
        await warm_up(make_client)
        recorder = Recorder(hold={"summary": 0.5, "detector": 0.5})
        before = pending_tasks()
        call = asyncio.create_task(
            tools.get_us_code_section(
                make_client(recorder), granule_id="USCODE-2024-title17-chap1-sec107", citation="17 U.S.C. 107"
            )
        )
        await recorder.event("summary").wait()
        await asyncio.sleep(0)
        # WO-28 B: the same-citation family search is a third request the call owns.
        assert sorted(recorder.seen) == ["detector", "search", "summary"]

        requests_at_cancel = await cancel_and_settle(call, recorder)

        assert pending_tasks() - before == set(), "a task started for the cancelled call is still running"
        assert recorder.seen[requests_at_cancel:] == []

    async def test_by_id_cancelled_during_the_summary_with_the_family_search_in_flight(self, make_client):
        # Cold (no speculative detector): the family search is the one request
        # beside the summary, and it must not outlive the call either.
        recorder = Recorder(hold={"summary": 0.5, "search": 0.5})
        before = pending_tasks()
        call = asyncio.create_task(
            tools.get_us_code_section(
                make_client(recorder), granule_id="USCODE-2024-title17-chap1-sec107", citation="17 U.S.C. 107"
            )
        )
        await recorder.event("summary").wait()
        await asyncio.sleep(0)
        assert sorted(recorder.seen) == ["search", "summary"]

        requests_at_cancel = await cancel_and_settle(call, recorder)

        assert pending_tasks() - before == set(), "the family search outlived the cancelled call"
        assert recorder.seen[requests_at_cancel:] == []


class TestCompletedCallsAreUnchanged:
    async def test_warm_lookup_still_serves_the_speculative_result(self, make_client):
        # Ownership must not cost the overlap: the speculative query's result is
        # still the one served when the prediction holds.
        await warm_up(make_client)
        recorder = Recorder()
        out = await tools.get_us_code_section(make_client(recorder), citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        assert out["possibly_superseded"]["issued"] == "before_search"
        assert recorder.seen.count("detector") == 1

    async def test_completed_call_leaves_nothing_pending(self, make_client):
        await warm_up(make_client)
        before = pending_tasks()
        await tools.get_us_code_section(make_client(Recorder()), citation="17 U.S.C. 107")
        assert pending_tasks() - before == set()
