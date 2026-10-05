"""Server wiring: the four tools are registered, their descriptions carry the
spec-mandated caveats, and calls route through to the tool layer."""

import hashlib
import json
import re

import fx
import httpx
import pytest

from uscode_mcp.govinfo import UpstreamResponse
from uscode_mcp.server import create_server

INTERNAL_IDENTIFIER = re.compile(r"\b[OREFSQ]\d{1,3}[a-z]?\b|WO-\d+")

EXPECTED_TOOLS = {"get_us_code_section", "search_us_code", "get_public_law", "search_public_laws"}


class _LifecycleClient:
    def __init__(self, *, close_error=False):
        self.close_calls = 0
        self.search_calls = 0
        self.close_error = close_error

    async def search(self, body):
        self.search_calls += 1
        return UpstreamResponse(
            status=200,
            headers={},
            text=json.dumps(fx.search_response([])),
            url="https://api.govinfo.gov/search",
        )

    async def aclose(self):
        self.close_calls += 1
        if self.close_error:
            raise RuntimeError("close failed")


def _lifespan(server):
    assert server.settings.lifespan is not None
    return server.settings.lifespan(server)


def _payload(result):
    """Extract the tool's dict payload from a CallToolResult."""
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    return json.loads(result.content[0].text)


async def test_exactly_four_tools_registered():
    server = create_server()
    listed = await server.list_tools()
    assert {t.name for t in listed} == EXPECTED_TOOLS


async def test_served_surface_has_no_internal_identifiers_or_source_indentation():
    from uscode_mcp.server import SERVER_INSTRUCTIONS

    listed = await create_server().list_tools()
    served_strings = [SERVER_INSTRUCTIONS]
    for tool in listed:
        served_strings.append(tool.description or "")
        served_strings.extend(_strings(tool.input_schema))
        served_strings.extend(_strings(tool.output_schema))

    assert not [value for value in served_strings if INTERNAL_IDENTIFIER.search(value)]
    assert all("YOU MUST READ" not in value for value in served_strings)
    assert all("  " not in (tool.description or "") for tool in listed)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


async def test_search_public_laws_description_carries_recipe_and_recall_caveat():
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["search_public_laws"]
    assert "uscodecitation" in tool.description
    assert "never evidence" in tool.description
    assert "25/33" in tool.description
    assert "structural" in tool.description
    assert "complete" in tool.description


async def test_get_public_law_description_states_private_law_scope():
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["get_public_law"]
    assert "private-law" in tool.description
    assert "out-of-scope" in tool.description


async def test_get_public_law_description_says_numbered_path_is_the_public_series():
    """WO-5 change 3 (F4): congress + law_number names the public series only."""
    server = create_server()
    flat = " ".join({t.name: t for t in await server.list_tools()}["get_public_law"].description.split())
    assert "PUBLIC-law series only" in flat
    assert "Private Law 118-1" in flat
    assert "out-of-scope outcome" in flat


async def test_search_descriptions_carry_the_packageid_recipe():
    """WO-5 change 2 (F6b, O30): within-title / within-law scoping by package, with the
    presence-not-location caveat on both."""
    server = create_server()
    by_name = {t.name: t for t in await server.list_tools()}
    usc = " ".join(by_name["search_us_code"].description.split())
    plaw = " ".join(by_name["search_public_laws"].description.split())
    assert "packageid:USCODE-2024-title17" in usc
    assert "packageid:PLAW-118publ31" in plaw
    assert "`find`" in usc and "`find`" in plaw
    assert "not where" in usc and "not where" in plaw


async def test_search_descriptions_state_the_collection_boundary():
    server = create_server()
    by_name = {t.name: " ".join(t.description.split()) for t in await server.list_tools()}
    assert "collection:USCODE" in by_name["search_us_code"]
    assert "any other collection clause is refused before searching" in by_name["search_us_code"]
    assert "collection:PLAW" in by_name["search_public_laws"]
    assert "any other collection clause is refused before searching" in by_name["search_public_laws"]


async def test_search_public_laws_description_names_publishdate_not_approveddate_ranges():
    """WO-5 change 1 (F6a, O43f/O49a): approveddate ranges return HTTP 500 upstream."""
    server = create_server()
    flat = " ".join({t.name: t for t in await server.list_tools()}["search_public_laws"].description.split())
    assert "publishdate:range(YYYY-MM-DD,)" in flat
    assert "approveddate:range(...)" not in flat.replace("do NOT use `approveddate:range(...)`", "")
    assert "do NOT use `approveddate:range(...)`" in flat
    assert "HTTP 500" in flat
    assert "not evidence of absence" in flat


async def test_search_us_code_description_says_historical_is_an_argument():
    """O49b: a consumer typed historical:true into the query string and got a 500."""
    server = create_server()
    flat = " ".join({t.name: t for t in await server.list_tools()}["search_us_code"].description.split())
    assert "`historical` ARGUMENT (not a query term)" in flat


RESULT_ORDER_SENTENCE = (
    "Results are relevance-ordered. Unquoted terms are all required, so start with the asker's own topical "
    "words, unquoted; double quotes match an exact phrase; `title:` searches section headings "
    "(e.g. `title:collateral usctitlenum:12`)."
)


async def test_search_us_code_description_says_how_to_query_in_place():
    """WO-24 part B: the result-order sentence, character for character, right after the
    fielded-search examples and before the `historical` sentence."""
    server = create_server()
    flat = " ".join({t.name: t for t in await server.list_tools()}["search_us_code"].description.split())
    assert (
        'Fielded search is available (e.g. `citation:"17 U.S.C. 107"`, `usctitlenum:28`, `shorttitle:...`). '
        f"{RESULT_ORDER_SENTENCE} The `historical` ARGUMENT (not a query term) includes superseded annual editions."
    ) in flat
    assert flat.count(RESULT_ORDER_SENTENCE) == 1


async def test_result_order_sentence_is_on_search_us_code_only():
    """WO-24 part B changes one description; search_public_laws keeps its own text."""
    server = create_server()
    by_name = {t.name: " ".join(t.description.split()) for t in await server.list_tools()}
    assert [name for name, flat in by_name.items() if "relevance-ordered" in flat] == ["search_us_code"]


async def test_get_us_code_section_description_promises_notes():
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["get_us_code_section"]
    assert "notes" in tool.description
    assert "currentthrough" in tool.description


async def test_get_us_code_section_description_teaches_that_notes_carry_law():
    """WO-18 (R29): the notes sentence gains the contract's addition, character for character,
    right after the sentence promising the notes."""
    server = create_server()
    flat = " ".join({t.name: t for t in await server.list_tools()}["get_us_code_section"].description.split())
    assert (
        'statutory notes included (note citations like "42 U.S.C. 2210 note" resolve to the containing section, '
        "whose payload contains the notes). Notes are not only editorial — statutory notes are enacted law placed "
        "under the section; a question about a section's notes is about all of them, so list them with structure "
        "before answering from one. Pass `citation`"
    ) in flat


async def test_get_us_code_section_description_states_the_indicator_contract():
    """R14a: the description names all three states and says the indicator certifies nothing."""
    server = create_server()
    tool = {t.name: t for t in await server.list_tools()}["get_us_code_section"]
    for token in ("possibly_superseded", "laws_indexed", "none_indexed", "not_checked"):
        assert token in tool.description
    assert "NEVER A CERTIFICATION" in tool.description
    assert "NOT" in tool.description and "evidence the text is current" in tool.description
    assert "one in seven" in tool.description


async def test_server_instructions_describe_the_indicator():
    from uscode_mcp.server import SERVER_INSTRUCTIONS

    assert "possibly_superseded" in SERVER_INSTRUCTIONS
    assert "not_checked" in SERVER_INSTRUCTIONS
    assert "never a certification" in SERVER_INSTRUCTIONS


async def test_call_tool_routes_to_injected_client(make_client):
    client = make_client(lambda request: fx.json_response(fx.search_response([fx.usc_hit()])))
    server = create_server(client=client)
    result = await server.call_tool("search_us_code", {"query": "fair use"})
    payload = _payload(result)
    assert payload["outcome"] == "success"
    assert payload["results"][0]["package_id"] == "USCODE-2024-title17"


async def test_call_tool_surfaces_upstream_error_as_data(make_client):
    client = make_client(lambda request: httpx.Response(500, text="err"))
    server = create_server(client=client)
    result = await server.call_tool("search_us_code", {"query": "fair use"})
    payload = _payload(result)
    assert payload["outcome"] == "upstream_error"
    assert payload["http_status"] == 500


async def test_call_tool_end_to_end_section_retrieval(make_client):
    def handler(request):
        if request.url.path == "/search":
            return fx.json_response(fx.search_response([fx.usc_hit()]))
        return httpx.Response(200, text=fx.SECTION_HTML)

    server = create_server(client=make_client(handler))
    result = await server.call_tool("get_us_code_section", {"citation": "17 U.S.C. 107"})
    payload = _payload(result)
    assert payload["outcome"] == "success"
    assert payload["provenance"]["currentthrough"] == "2025-01-06"
    assert "fair use of a copyrighted work" in payload["text"]["content"]


async def test_lifespan_closes_server_created_client_exactly_once(monkeypatch):
    client = _LifecycleClient()
    monkeypatch.setattr("uscode_mcp.server.client_from_env", lambda: client)
    server = create_server()

    async with _lifespan(server):
        await server.call_tool("search_us_code", {"query": "x"})
        assert client.close_calls == 0

    assert client.search_calls == 1
    assert client.close_calls == 1


async def test_lifespan_never_closes_injected_client():
    client = _LifecycleClient()
    server = create_server(client=client)

    async with _lifespan(server):
        await server.call_tool("search_us_code", {"query": "x"})

    assert client.search_calls == 1
    assert client.close_calls == 0


async def test_lifespan_does_not_create_client_only_to_close_it(monkeypatch):
    created = []
    monkeypatch.setattr("uscode_mcp.server.client_from_env", lambda: created.append(_LifecycleClient()))
    server = create_server()

    async with _lifespan(server):
        pass

    assert created == []


async def test_client_close_failure_does_not_mask_shutdown(monkeypatch, caplog):
    client = _LifecycleClient(close_error=True)
    monkeypatch.setattr("uscode_mcp.server.client_from_env", lambda: client)
    server = create_server()

    async with _lifespan(server):
        await server.call_tool("search_us_code", {"query": "x"})

    assert client.close_calls == 1
    assert "failed to close" in caplog.text


async def test_create_server_registers_tracing_middleware(tmp_path):
    from uscode_mcp.trace import Tracer, TracingMiddleware

    server = create_server(tracer=Tracer(tmp_path))
    assert any(isinstance(m, TracingMiddleware) for m in server.middleware)


async def test_create_server_without_tracer_registers_no_tracing_middleware(monkeypatch):
    from uscode_mcp.trace import TRACE_DIR_ENV_VAR, TracingMiddleware

    monkeypatch.delenv(TRACE_DIR_ENV_VAR, raising=False)
    server = create_server()
    assert not any(isinstance(m, TracingMiddleware) for m in server.middleware)


async def test_create_server_fails_at_startup_on_unusable_trace_dir(monkeypatch, tmp_path):
    from uscode_mcp.trace import TRACE_DIR_ENV_VAR

    blocker = tmp_path / "blocker"
    blocker.write_text("file, not dir")
    monkeypatch.setenv(TRACE_DIR_ENV_VAR, str(blocker))
    import pytest

    with pytest.raises(RuntimeError, match=TRACE_DIR_ENV_VAR):
        create_server()


async def test_create_server_fails_at_startup_on_blank_trace_dir(monkeypatch):
    from uscode_mcp.trace import TRACE_DIR_ENV_VAR

    monkeypatch.setenv(TRACE_DIR_ENV_VAR, "")
    import pytest

    with pytest.raises(RuntimeError, match="set but blank"):
        create_server()


async def test_section_description_teaches_passing_the_subsection_immediately_after_strip_sentence():
    listed = await create_server().list_tools()
    description = next(tool.description for tool in listed if tool.name == "get_us_code_section")
    assert (
        "Subsection suffixes are stripped (the whole section is the retrieval unit). "
        "Pass the citation as the asker gave it, subsection included — the server strips the suffix "
        "and reports whether that subsection exists in the statute text. "
        "Optional `year` selects a historical annual edition."
    ) in " ".join(description.split())


# WO-34 (R40, Q36; O130d, F23): every property of every tool's input schema carries the
# description the contract's "Parameter descriptions" table pins, character for character.
# This is the test's own copy of that table, one entry per property; the served schema must
# carry exactly these properties and no other.
PINNED_PARAMETER_DESCRIPTIONS = {
    "get_us_code_section": {
        "citation": (
            'A US Code citation as the asker gave it — "17 U.S.C. 107", "17 USC 107", "17 U.S.C. § 107(b)", "42 '
            'U.S.C. 2210 note". A subsection suffix is stripped and reported; "note" resolves to the containing '
            "section. Pass this, or title with section."
        ),
        "title": 'US Code title number as a string ("17"), paired with section — an alternative to citation.',
        "section": 'Section number within the title ("107", "2210"), paired with title — an alternative to citation.',
        "year": (
            "Annual edition year to read instead of the latest (2023). Ignored with granule_id, which names its own "
            "edition."
        ),
        "granule_id": (
            "A granule id exactly as a search result or an ambiguous candidate list gives it "
            '("USCODE-2024-title28-app-federalru-rule9"), to read one provision when a citation matches several. Pass'
            " the same citation alongside so the staleness check still runs."
        ),
        "package_id": (
            'The package the granule belongs to ("USCODE-2024-title28"). Optional with granule_id, from which it is '
            "otherwise derived."
        ),
        "max_chars": (
            "Upper bound on the characters of text returned; default 20000. A truncated window ends at a paragraph "
            "break, carries explicit truncation markers and says where to continue. Pass 1 to receive the structure "
            "map and nothing else."
        ),
        "start_char": (
            "Character offset the window starts at, in the payload's own coordinates — the same ones find, structure "
            "and next_start_char use. Default 0."
        ),
        "find": (
            "An argument of this tool, not a tool. A case-insensitive literal substring searched across the FULL "
            "section, not only the returned window; the response reports the true occurrence count with offsets in "
            "the start_char coordinate system and short snippets. Snippets locate; they are not the text — read a "
            "window at an offset to quote."
        ),
    },
    "search_us_code": {
        "query": (
            "govinfo query syntax over the USCODE collection: the asker's topical words unquoted (all required); \"an "
            'exact phrase" in double quotes; fields such as citation:"17 U.S.C. 107", usctitlenum:28, '
            "title:collateral, packageid:USCODE-2024-title17. collection:USCODE is added when absent; any other "
            "collection is refused."
        ),
        "historical": (
            "Include superseded annual editions as well as the latest; default false. An argument, not a query term."
        ),
        "page_size": "Results per page; default 20.",
        "offset_mark": (
            'Pagination cursor: "*" for the first page (the default), then the offset_mark the previous response '
            "returned."
        ),
    },
    "get_public_law": {
        "citation": (
            'A public-law citation string — "Pub. L. 118-31", "Public Law 118-31", "P.L. 118-31". A private-law '
            'citation ("Private Law 118-1") is answered as out of scope, not as a failed lookup. Pass this, or '
            "congress with law_number."
        ),
        "congress": "Congress number (118), paired with law_number. Names the PUBLIC-law series only.",
        "law_number": (
            "Law number within the congress (31), paired with congress. Public laws only — not a private-law number."
        ),
        "format": (
            '"text" (the default) or "uslm" for USLM XML, which packages offer for the 113th Congress (2013) and '
            "later; its absence is reported as a distinct outcome."
        ),
        "max_chars": (
            "Upper bound on the characters of text returned; default 20000. A law can run to millions of characters, "
            "so a window is never the whole law; a truncated window ends at a paragraph break, carries explicit "
            "truncation markers and says where to continue."
        ),
        "start_char": (
            "Character offset the window starts at, in the payload's own coordinates — the same ones find, structure "
            "and next_start_char use. Default 0."
        ),
        "find": (
            "An argument of this tool, not a tool. A case-insensitive literal substring searched across the FULL law,"
            " not only the returned window; the response reports the true occurrence count with offsets in the "
            "start_char coordinate system and short snippets. Snippets locate; they are not the text — read a window "
            "at an offset to quote."
        ),
    },
    "search_public_laws": {
        "query": (
            'govinfo query syntax over the PLAW collection: uscodecitation:"42 U.S.C. 2210" for the laws that mention'
            " a section (recall is incomplete — absence is never evidence), congress:118 docnumber:31, "
            "publishdate:range(YYYY-MM-DD,), packageid:PLAW-118publ31 <terms> to test one law for terms. "
            "collection:PLAW is accepted; any other collection is refused."
        ),
        "page_size": "Results per page; default 20.",
        "offset_mark": (
            'Pagination cursor: "*" for the first page (the default), then the offset_mark the previous response '
            "returned."
        ),
    },
}

# The input schemas as served through WO-33: every key but `description` must still equal
# this, and the property order is the signature order these dicts are written in.


def _nullable(kind, title):
    return {"anyOf": [{"type": kind}, {"type": "null"}], "default": None, "title": title}


SCHEMAS_THROUGH_WO33 = {
    "get_us_code_section": {
        "properties": {
            "citation": _nullable("string", "Citation"),
            "title": _nullable("string", "Title"),
            "section": _nullable("string", "Section"),
            "year": _nullable("integer", "Year"),
            "max_chars": {"default": 20000, "title": "Max Chars", "type": "integer"},
            "start_char": {"default": 0, "title": "Start Char", "type": "integer"},
            "find": _nullable("string", "Find"),
            "granule_id": _nullable("string", "Granule Id"),
            "package_id": _nullable("string", "Package Id"),
        },
        "title": "get_us_code_sectionArguments",
        "type": "object",
    },
    "search_us_code": {
        "properties": {
            "query": {"title": "Query", "type": "string"},
            "page_size": {"default": 20, "title": "Page Size", "type": "integer"},
            "offset_mark": {"default": "*", "title": "Offset Mark", "type": "string"},
            "historical": {"default": False, "title": "Historical", "type": "boolean"},
        },
        "required": ["query"],
        "title": "search_us_codeArguments",
        "type": "object",
    },
    "get_public_law": {
        "properties": {
            "congress": _nullable("integer", "Congress"),
            "law_number": _nullable("integer", "Law Number"),
            "citation": _nullable("string", "Citation"),
            "format": {"default": "text", "title": "Format", "type": "string"},
            "max_chars": {"default": 20000, "title": "Max Chars", "type": "integer"},
            "start_char": {"default": 0, "title": "Start Char", "type": "integer"},
            "find": _nullable("string", "Find"),
        },
        "title": "get_public_lawArguments",
        "type": "object",
    },
    "search_public_laws": {
        "properties": {
            "query": {"title": "Query", "type": "string"},
            "page_size": {"default": 20, "title": "Page Size", "type": "integer"},
            "offset_mark": {"default": "*", "title": "Offset Mark", "type": "string"},
        },
        "required": ["query"],
        "title": "search_public_lawsArguments",
        "type": "object",
    },
}

# sha256 of each tool's prose description and of the server instructions as served through
# WO-33, from a fresh-process dump; the schema descriptions change none of them.
DESCRIPTION_SHA256_THROUGH_WO33 = {
    "get_public_law": "220c1d6d4b78586dc42828487dfac08db55550cedbcbba40c5f50d4e81dde156",
    "get_us_code_section": "3244de9132c0faa14f68af64d9720b6d1323631e77d61668933cb0381b173b08",
    "search_public_laws": "f7ceded41770faa62c46281816e80a560e322082c0c134075f48bc7419605cf9",
    "search_us_code": "47ac538663329a0ebb79514ce18ad56af75eea1ff877e972fe8cc824740901d6",
}
INSTRUCTIONS_SHA256_THROUGH_WO33 = "3d7b1cb7ee688eacc7abd7b8f59815d711c7687118386150203d761a315774d2"


def _without_descriptions(schema):
    properties = {
        name: {key: value for key, value in prop.items() if key != "description"}
        for name, prop in schema["properties"].items()
    }
    return {**schema, "properties": properties}


async def test_every_tool_parameter_carries_its_pinned_description():
    by_name = {t.name: t for t in await create_server().list_tools()}
    assert set(by_name) == set(PINNED_PARAMETER_DESCRIPTIONS)
    for tool, pinned in PINNED_PARAMETER_DESCRIPTIONS.items():
        properties = by_name[tool].input_schema["properties"]
        # no served property is missing from the table, and the table names no unserved property
        assert set(properties) == set(pinned), tool
        for name, text in pinned.items():
            assert properties[name]["description"] == text, (tool, name)


def test_pinned_table_has_one_entry_per_property_and_says_find_is_an_argument():
    assert sum(len(params) for params in PINNED_PARAMETER_DESCRIPTIONS.values()) == 23
    for tool in ("get_us_code_section", "get_public_law"):
        assert PINNED_PARAMETER_DESCRIPTIONS[tool]["find"].startswith("An argument of this tool, not a tool. ")
    for tool, params in PINNED_PARAMETER_DESCRIPTIONS.items():
        for name, text in params.items():
            assert text == " ".join(text.split()) and not text.endswith(" "), (tool, name)


async def test_description_is_the_only_key_the_schemas_gained():
    by_name = {t.name: t for t in await create_server().list_tools()}
    for tool, before in SCHEMAS_THROUGH_WO33.items():
        served = by_name[tool].input_schema
        assert _without_descriptions(served) == before, tool
        assert list(served["properties"]) == list(before["properties"]), tool
        assert served.get("required") == before.get("required"), tool
        for name, prop in served["properties"].items():
            assert set(prop) == set(before["properties"][name]) | {"description"}, (tool, name)


async def test_schema_descriptions_leave_prose_descriptions_and_instructions_byte_identical():
    from uscode_mcp.server import SERVER_INSTRUCTIONS

    by_name = {t.name: t for t in await create_server().list_tools()}
    for tool, digest in DESCRIPTION_SHA256_THROUGH_WO33.items():
        assert hashlib.sha256(by_name[tool].description.encode()).hexdigest() == digest, tool
    assert hashlib.sha256(SERVER_INSTRUCTIONS.encode()).hexdigest() == INSTRUCTIONS_SHA256_THROUGH_WO33


def test_source_table_matches_the_pinned_table_and_an_unknown_parameter_fails_at_import():
    from uscode_mcp.server import PARAMETER_DESCRIPTIONS, _described

    assert PARAMETER_DESCRIPTIONS == PINNED_PARAMETER_DESCRIPTIONS
    assert (
        _described("get_us_code_section", "find").description
        == PINNED_PARAMETER_DESCRIPTIONS["get_us_code_section"]["find"]
    )
    with pytest.raises(KeyError):
        _described("get_us_code_section", "not_a_parameter")
    with pytest.raises(KeyError):
        _described("not_a_tool", "query")
