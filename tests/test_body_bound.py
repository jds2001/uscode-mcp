"""WO-26 part B (S32 finding 2; documentation/40-tools.md, "Failure bodies are bounded
only out loud"): wherever an upstream body is relayed — `upstream_error`, the
rate-limited outcome, `not_checked` inside `possibly_superseded`, and the by-id
`not_found` — a body within the bound is relayed verbatim, and a longer one is
relayed as its opening characters with the envelope saying it was cut and giving
the full length. A body at or under the bound is served exactly as before.
"""

from __future__ import annotations

import fx
import httpx
import pytest

from uscode_mcp import govinfo, tools

GID = "USCODE-2024-title17-chap1-sec107"
PID = "USCODE-2024-title17"


def body_of(length: int, seed: str = "x") -> str:
    # Distinct characters at the cut so a wrong slice cannot pass by accident.
    return ("".join(chr(ord("a") + i % 26) for i in range(length)) if seed == "x" else seed * length)[:length]


def assert_verbatim(out: dict, text: str) -> None:
    assert out["body"] == text
    for key in ("body_cut", "body_total_chars", "body_shown_chars", "body_note"):
        assert key not in out, f"{key} must not appear on an uncut body"


def assert_cut(out: dict, text: str, bound: int) -> None:
    assert out["body"] == text[:bound]
    assert out["body_cut"] is True
    assert out["body_total_chars"] == len(text)
    assert out["body_shown_chars"] == bound
    assert out["body_note"] == (
        f"The upstream body was cut: 'body' is its first {bound:,} characters of {len(text):,}; "
        "nothing after that point is relayed."
    )


class TestRelayBodyHelper:
    def test_under_bound_is_the_text_alone(self):
        assert govinfo.relay_body("abc", 5) == {"body": "abc"}

    def test_at_bound_is_the_text_alone(self):
        assert govinfo.relay_body("abcde", 5) == {"body": "abcde"}

    def test_one_over_is_cut_and_says_so(self):
        out = govinfo.relay_body("abcdef", 5)
        assert_cut(out, "abcdef", 5)

    def test_empty_body_is_relayed_as_empty(self):
        assert govinfo.relay_body("", 5) == {"body": ""}

    def test_bounds_are_the_ones_served_before_this_order(self):
        # The order changes disclosure, not the bound.
        assert govinfo.UPSTREAM_ERROR_BODY_BOUND == 5000
        assert govinfo.RATE_LIMITED_BODY_BOUND == 2000
        assert govinfo.NOT_FOUND_BODY_BOUND == 2000


def search_failure_handler(status: int, text: str, headers: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=text, headers=headers)

    return handler


class TestUpstreamErrorBody:
    BOUND = 5000

    @pytest.mark.parametrize("length", [BOUND - 1, BOUND])
    async def test_within_bound_is_verbatim(self, make_client, length):
        text = body_of(length)
        out = await tools.search_us_code(make_client(search_failure_handler(500, text)), "fair use")
        assert out["outcome"] == "upstream_error" and out["http_status"] == 500
        assert_verbatim(out, text)

    @pytest.mark.parametrize("length", [BOUND + 1, 6000])
    async def test_over_bound_is_cut_out_loud(self, make_client, length):
        text = body_of(length)
        out = await tools.search_us_code(make_client(search_failure_handler(500, text)), "fair use")
        assert out["outcome"] == "upstream_error" and out["http_status"] == 500
        assert_cut(out, text, self.BOUND)

    async def test_review_case_6000_char_500(self, make_client):
        text = body_of(6000)
        out = await tools.get_public_law(make_client(search_failure_handler(500, text)), congress=118, law_number=31)
        assert out["outcome"] == "upstream_error"
        assert out["body_total_chars"] == 6000 and len(out["body"]) == 5000

    async def test_shape_drift_failure_relays_the_body_by_the_same_rule(self, make_client):
        text = "[" + body_of(6000) + "]"  # valid-length JSON but not an object: shape drift
        out = await tools.search_us_code(make_client(search_failure_handler(200, text)), "fair use")
        assert out["outcome"] == "upstream_error" and "detail" in out
        assert_cut(out, text, self.BOUND)


class TestRateLimitedBody:
    BOUND = 2000
    HEADERS = {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "0", "retry-after": "60"}

    @pytest.mark.parametrize("length", [BOUND - 1, BOUND])
    async def test_within_bound_is_verbatim(self, make_client, length):
        text = body_of(length)
        out = await tools.search_us_code(make_client(search_failure_handler(429, text, self.HEADERS)), "fair use")
        assert out["outcome"] == "rate_limited"
        assert out["rate_limit"]["retry-after"] == "60"
        assert_verbatim(out, text)

    @pytest.mark.parametrize("length", [BOUND + 1, 3000])
    async def test_over_bound_is_cut_out_loud(self, make_client, length):
        text = body_of(length)
        out = await tools.search_us_code(make_client(search_failure_handler(429, text, self.HEADERS)), "fair use")
        assert out["outcome"] == "rate_limited"
        assert out["rate_limit"]["retry-after"] == "60"
        assert_cut(out, text, self.BOUND)


def detector_handler(status: int, text: str, headers: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            if "collection:PLAW" in fx.request_body(request)["query"]:
                return httpx.Response(status, text=text, headers=headers)
            return fx.json_response(fx.search_response([fx.usc_hit()]))
        if request.url.path.endswith("/htm"):
            return httpx.Response(200, text=fx.SECTION_HTML)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


class TestNotCheckedBody:
    BOUND = 5000

    @pytest.mark.parametrize("status,reason", [(500, "upstream_error"), (429, "rate_limited")])
    @pytest.mark.parametrize("length", [BOUND - 1, BOUND])
    async def test_within_bound_is_verbatim(self, make_client, status, reason, length):
        text = body_of(length)
        out = await tools.get_us_code_section(make_client(detector_handler(status, text)), citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked" and ps["reason"] == reason
        assert_verbatim(ps, text)

    @pytest.mark.parametrize("status,reason", [(500, "upstream_error"), (429, "rate_limited")])
    @pytest.mark.parametrize("length", [BOUND + 1, 6000])
    async def test_over_bound_is_cut_out_loud(self, make_client, status, reason, length):
        text = body_of(length)
        out = await tools.get_us_code_section(make_client(detector_handler(status, text)), citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        ps = out["possibly_superseded"]
        assert ps["status"] == "not_checked" and ps["reason"] == reason
        assert_cut(ps, text, self.BOUND)

    async def test_review_case_3000_char_429_is_under_this_bound_and_verbatim(self, make_client):
        # 429 and other failures share the 5,000 bound inside not_checked, so the
        # review's 3,000-character 429 body is relayed whole here.
        text = body_of(3000)
        out = await tools.get_us_code_section(make_client(detector_handler(429, text)), citation="17 U.S.C. 107")
        ps = out["possibly_superseded"]
        assert ps["reason"] == "rate_limited"
        assert_verbatim(ps, text)

    async def test_malformed_json_body_is_relayed_by_the_same_rule(self, make_client):
        text = "<html>" + body_of(6000) + "</html>"
        out = await tools.get_us_code_section(make_client(detector_handler(200, text)), citation="17 U.S.C. 107")
        ps = out["possibly_superseded"]
        assert ps["reason"] == "malformed_response"
        assert_cut(ps, text, self.BOUND)


def by_id_not_found_handler(text: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/summary"):
            return httpx.Response(400, text=text)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


class TestByIdNotFoundBody:
    BOUND = 2000

    @pytest.mark.parametrize("length", [BOUND - 1, BOUND])
    async def test_within_bound_is_verbatim(self, make_client, length):
        text = ('{"message":"invalid granuleId","pad":"' + body_of(length))[:length]
        out = await tools.get_us_code_section(make_client(by_id_not_found_handler(text)), granule_id=GID)
        assert out["outcome"] == "not_found" and out["not_found_kind"] == "granule"
        assert_verbatim(out, text)

    @pytest.mark.parametrize("length", [BOUND + 1, 6000])
    async def test_over_bound_is_cut_out_loud(self, make_client, length):
        text = ('{"message":"invalid granuleId","pad":"' + body_of(length))[:length]
        out = await tools.get_us_code_section(make_client(by_id_not_found_handler(text)), granule_id=GID)
        assert out["outcome"] == "not_found" and out["not_found_kind"] == "granule"
        assert_cut(out, text, self.BOUND)
