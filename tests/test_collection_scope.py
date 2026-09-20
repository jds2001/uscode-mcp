"""WO-8/R17: caller queries cannot move either search tool to another collection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import fx
import pytest

from uscode_mcp import tools

Search = Callable[..., Awaitable[dict[str, Any]]]


@pytest.fixture(params=[(tools.search_us_code, "USCODE"), (tools.search_public_laws, "PLAW")])
def scoped_search(request) -> tuple[Search, str]:
    return request.param


async def _run(search: Search, make_client, query: str) -> tuple[dict[str, Any], list[Any]]:
    seen = []

    def handler(request):
        seen.append(request)
        return fx.json_response(fx.search_response([]))

    return await search(make_client(handler), query), seen


class TestConformingCollectionClauses:
    async def test_absent_clause_is_prepended(self, scoped_search, make_client):
        search, collection = scoped_search
        out, seen = await _run(search, make_client, "fair use")

        assert out["outcome"] == "success"
        assert fx.request_body(seen[0])["query"] == f"collection:{collection} fair use"

    @pytest.mark.parametrize(
        "template",
        [
            "collection:{collection} fair use",
            "collection:{lower} fair use",
            "COLLECTION:{collection} fair use",
            'collection:"{collection}" fair use',
            "collection \t:{collection} fair use",
            "collection:{collection} collection:{lower} fair use",
        ],
    )
    async def test_matching_clause_is_sent_byte_for_byte(self, scoped_search, make_client, template):
        search, collection = scoped_search
        query = template.format(collection=collection, lower=collection.lower())
        out, seen = await _run(search, make_client, query)

        assert out["outcome"] == "success"
        assert fx.request_body(seen[0])["query"] == query

    async def test_collection_text_inside_phrase_is_not_a_clause(self, scoped_search, make_client):
        search, collection = scoped_search
        query = 'title:"the collection: of duties"'
        out, seen = await _run(search, make_client, query)

        assert out["outcome"] == "success"
        assert fx.request_body(seen[0])["query"] == f"collection:{collection} {query}"

    async def test_live_detector_query_is_accepted_unchanged_by_plaw(self, make_client):
        query = (
            'collection:PLAW lawtype:public publishdate:range(2025-01-07,) '
            'uscodecitation:"42 U.S.C. 2210"'
        )
        out, seen = await _run(tools.search_public_laws, make_client, query)

        assert out["outcome"] == "success"
        assert fx.request_body(seen[0])["query"] == query


class TestOutOfScopeCollectionClauses:
    @pytest.mark.parametrize(
        ("query", "offending"),
        [
            ("collection:{other} fair use", "collection:{other}"),
            ("collection:BILLS congress:118", "collection:BILLS"),
            ("collection:({collection} OR {other}) fair use", "collection:({collection} OR {other})"),
            ("collection:{collection} collection:{other} fair use", "collection:{other}"),
            ("collection:{collection} (collection:{other} fair use)", "collection:{other}"),
            ("collection: {collection} fair use", "collection: {collection}"),
            ("-collection:{collection} fair use", "-collection:{collection}"),
            ("fair use collection:", "collection:"),
            ("Collection:{other_lower} fair use", "Collection:{other_lower}"),
        ],
    )
    async def test_refused_before_upstream(self, scoped_search, make_client, query, offending):
        search, collection = scoped_search
        other = "PLAW" if collection == "USCODE" else "USCODE"
        query = query.format(collection=collection, other=other, other_lower=other.lower())
        offending = offending.format(collection=collection, other=other, other_lower=other.lower())

        out, seen = await _run(search, make_client, query)

        assert seen == []
        assert out["outcome"] == "out_of_scope_collection"
        assert out["offending_clause"] == offending
        assert out["collection"] == collection
        assert "No search was run" in out["message"]
        assert "recall_caveat" not in out

    async def test_other_served_collection_points_to_its_tool(self, scoped_search, make_client):
        search, collection = scoped_search
        other = "PLAW" if collection == "USCODE" else "USCODE"
        out, seen = await _run(search, make_client, f"collection:{other} fair use")

        assert seen == []
        assert out["suggested_tool"] == {
            "USCODE": "search_us_code",
            "PLAW": "search_public_laws",
        }[other]

    async def test_third_collection_has_no_tool_pointer(self, scoped_search, make_client):
        search, _ = scoped_search
        out, seen = await _run(search, make_client, "collection:BILLS congress:118")

        assert seen == []
        assert "suggested_tool" not in out
