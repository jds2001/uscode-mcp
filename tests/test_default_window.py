"""WO-4: the default `max_chars` is 20,000 on both text tools (O47b — larger windows
were measured not to reach the model inline). Nothing else about windowing changes."""

from __future__ import annotations

import fx
import httpx

from uscode_mcp import tools
from uscode_mcp.server import SERVER_INSTRUCTIONS, create_server

BIG_SECTION_HTML = fx.SECTION_HTML.replace(
    "<p>Effective date note text lives here and must never be dropped.</p>",
    "<p>" + ("statutory note filler. " * 2000) + "must never be dropped.</p>",
)
BIG_PLAW_HTML = fx.PLAW_HTML.replace("SEC. 2.", "<p>" + ("law text filler. " * 3000) + "</p>SEC. 2.")


def section_client(make_client):
    def handler(request):
        if request.url.path == "/search":
            if "collection:PLAW" in fx.request_body(request)["query"]:
                return fx.json_response(fx.search_response([], count=0))
            return fx.json_response(fx.search_response([fx.usc_hit()]))
        return httpx.Response(200, text=BIG_SECTION_HTML)

    return make_client(handler)


def plaw_client(make_client):
    def handler(request):
        if request.url.path == "/search":
            return fx.json_response(fx.search_response([fx.plaw_hit()]))
        if request.url.path.endswith("/summary"):
            return fx.json_response(fx.plaw_summary())
        return httpx.Response(200, text=BIG_PLAW_HTML)

    return make_client(handler)


def test_default_constant_is_twenty_thousand():
    assert tools.DEFAULT_MAX_CHARS == 20_000


class TestSectionDefault:
    async def test_default_window_is_20000_with_banner_and_continuation(self, make_client):
        out = await tools.get_us_code_section(section_client(make_client), citation="17 U.S.C. 107")
        text = out["text"]
        assert text["total_chars"] > 20_000
        assert text["returned_chars"] == 20_000
        assert text["truncated"] is True
        assert text["next_start_char"] == 20_000
        expected = f"[WINDOW chars 0–19,999 of {text['total_chars']:,} — truncated; continue with start_char=20000]"
        assert text["banner"] == expected
        assert not text["content"].startswith("[WINDOW")
        assert len(text["content"]) == text["returned_chars"]
        assert "start_char=20000" in text["message"]

    async def test_explicit_larger_max_chars_is_honored(self, make_client):
        out = await tools.get_us_code_section(section_client(make_client), citation="17 U.S.C. 107", max_chars=100_000)
        text = out["text"]
        assert text["truncated"] is False
        assert text["returned_chars"] == text["total_chars"] > 20_000
        assert "banner" not in text

    async def test_default_applies_on_the_by_id_path_too(self, make_client):
        def handler(request):
            if request.url.path.endswith("/summary"):
                return fx.json_response(fx.granule_summary())
            if request.url.path == "/search":
                return fx.json_response(fx.search_response([], count=0))
            return httpx.Response(200, text=BIG_SECTION_HTML)

        out = await tools.get_us_code_section(make_client(handler), granule_id="USCODE-2024-title17-chap1-sec107")
        assert out["text"]["returned_chars"] == 20_000
        assert out["text"]["next_start_char"] == 20_000

    async def test_find_still_searches_the_full_payload(self, make_client):
        out = await tools.get_us_code_section(
            section_client(make_client), citation="17 U.S.C. 107", find="must never be dropped"
        )
        assert out["text"]["truncated"] is True
        assert out["find"]["total_occurrences"] == 1
        assert out["find"]["occurrences"][0]["start_char"] >= 20_000


class TestPublicLawDefault:
    async def test_default_window_is_20000_with_banner_and_continuation(self, make_client):
        out = await tools.get_public_law(plaw_client(make_client), congress=118, law_number=31)
        text = out["text"]
        assert text["total_chars"] > 20_000
        assert text["returned_chars"] == 20_000
        assert text["truncated"] is True
        assert text["next_start_char"] == 20_000
        assert text["banner"].startswith("[WINDOW chars 0–19,999 of ")
        assert not text["content"].startswith("[WINDOW")
        assert len(text["content"]) == text["returned_chars"]

    async def test_explicit_larger_max_chars_is_honored(self, make_client):
        out = await tools.get_public_law(plaw_client(make_client), congress=118, law_number=31, max_chars=100_000)
        assert out["text"]["truncated"] is False
        assert out["text"]["returned_chars"] > 20_000


class TestDescriptions:
    async def test_tool_schemas_default_to_20000(self):
        server = create_server()
        by_name = {t.name: t for t in await server.list_tools()}
        for name in ("get_us_code_section", "get_public_law"):
            assert by_name[name].input_schema["properties"]["max_chars"]["default"] == 20_000, name

    async def test_descriptions_name_the_default_and_why(self):
        server = create_server()
        by_name = {t.name: t for t in await server.list_tools()}
        for name in ("get_us_code_section", "get_public_law"):
            flat = " ".join(by_name[name].description.split())
            assert "`max_chars` defaults to 20,000" in flat, name
            assert "not to reach the model inline" in flat, name

    def test_instructions_name_the_default(self):
        flat = " ".join(SERVER_INSTRUCTIONS.split())
        assert "default to 20,000 characters" in flat
        assert "not to reach the model inline" in flat
