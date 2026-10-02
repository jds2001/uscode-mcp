"""WO-28 (R34a; documentation/40-tools.md, "Same-citation families are read from ids"):
two granules share a citation within an edition exactly when their ids are equal
once every `dup{N}` segment is removed. Part A: on a `search_us_code` page, every hit
with a family member on the same page carries `same_citation_on_page` and the
contract's note; hits without one carry neither. No upstream request is made for it.
"""

from __future__ import annotations

import fx
import httpx
import pytest

from uscode_mcp import tools

CIV_RULE9 = "USCODE-2024-title28-app-federalru-rule9"
CRIM_RULE9 = "USCODE-2024-title28-app-federalru-dup1-rule9"
RULE8_A = "USCODE-2024-title28-app-federalru-rule8"
RULE8_B = "USCODE-2024-title28-app-federalru-dup1-rule8"
RULE8_C = "USCODE-2024-title28-app-federalru-dup1-rule8-dup1"

# WO-30 A (R35): `{n}` is the object's `count`; the dash is U+2014.
NOTE = (
    "This is one of {n} distinct provisions on this page that share one citation; the other(s): {titles}. The "
    "citation does not say which one the person asking means \u2014 do not choose for them, and do not present one "
    "as the only match. Name each by its title as a distinct provision, and if you read only one, say which you "
    "did not read."
)


def rule_hit(granule_id: str, title: str) -> dict:
    return fx.usc_hit(package_id="USCODE-2024-title28", granule_id=granule_id, title=title)


def page_handler(hits: list[dict], seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return fx.json_response(fx.search_response(hits, count=len(hits)))

    return handler


class TestNormalizedId:
    @pytest.mark.parametrize(
        "granule_id,expected",
        [
            (CIV_RULE9, CIV_RULE9),
            (CRIM_RULE9, CIV_RULE9),
            (RULE8_C, RULE8_A),
            ("USCODE-2024-title28-app-federalru-dup12-rule8", RULE8_A),
            # `dup` inside a segment, or without digits, is not the marker.
            ("USCODE-2024-title28-app-dupont-sec1", "USCODE-2024-title28-app-dupont-sec1"),
            ("USCODE-2024-title28-app-dup-sec1", "USCODE-2024-title28-app-dup-sec1"),
            ("USCODE-2024-title17-chap1-sec107", "USCODE-2024-title17-chap1-sec107"),
        ],
    )
    def test_every_dup_segment_is_removed_and_nothing_else(self, granule_id, expected):
        assert tools.normalized_granule_id(granule_id) == expected

    def test_different_editions_are_different_families(self):
        assert tools.normalized_granule_id(
            "USCODE-2023-title28-app-federalru-dup1-rule9"
        ) != tools.normalized_granule_id(CRIM_RULE9)


class TestSearchHitNote:
    async def test_the_rule_9_pair_each_names_the_other(self, make_client):
        seen = []
        hits = [rule_hit(CIV_RULE9, "Rule 9. Pleading Special Matters"), rule_hit(CRIM_RULE9, "Rule 9. Arrest Warrant")]
        out = await tools.search_us_code(make_client(page_handler(hits, seen)), '"Rule 9" usctitlenum:28')
        assert out["outcome"] == "success"
        assert len(seen) == 1, "the note costs no upstream request"
        civ, crim = out["results"]
        assert civ["same_citation_on_page"] == {
            "count": 2,
            "others": [{"granule_id": CRIM_RULE9, "title": "Rule 9. Arrest Warrant"}],
        }
        assert civ["note"] == NOTE.format(n=2, titles="Rule 9. Arrest Warrant")
        assert crim["same_citation_on_page"] == {
            "count": 2,
            "others": [{"granule_id": CIV_RULE9, "title": "Rule 9. Pleading Special Matters"}],
        }
        assert crim["note"] == NOTE.format(n=2, titles="Rule 9. Pleading Special Matters")

    async def test_note_is_the_contract_text_character_for_character(self):
        assert tools.SAME_CITATION_ON_PAGE_NOTE == NOTE

    async def test_the_served_note_for_a_family_of_two_is_pinned_whole(self, make_client):
        # WO-30 A: the string as served, written out — not built from the template under test.
        hits = [rule_hit(CIV_RULE9, "Rule 9. Pleading Special Matters"), rule_hit(CRIM_RULE9, "Rule 9. Arrest Warrant")]
        out = await tools.search_us_code(make_client(page_handler(hits)), '"Rule 9" usctitlenum:28')
        assert out["results"][0]["note"] == (
            "This is one of 2 distinct provisions on this page that share one citation; the other(s): "
            "Rule 9. Arrest Warrant. The citation does not say which one the person asking means \u2014 do not "
            "choose for them, and do not present one as the only match. Name each by its title as a distinct "
            "provision, and if you read only one, say which you did not read."
        )
        assert out["results"][1]["note"] == (
            "This is one of 2 distinct provisions on this page that share one citation; the other(s): "
            "Rule 9. Pleading Special Matters. The citation does not say which one the person asking means \u2014 "
            "do not choose for them, and do not present one as the only match. Name each by its title as a "
            "distinct provision, and if you read only one, say which you did not read."
        )

    async def test_the_served_note_for_a_family_of_three_is_pinned_whole(self, make_client):
        hits = [
            rule_hit(RULE8_A, "Rule 8. Civil"),
            rule_hit(RULE8_B, "Rule 8. Criminal"),
            rule_hit(RULE8_C, "Rule 8. Bankruptcy"),
            rule_hit(CIV_RULE9, "Rule 9. Civil"),
        ]
        out = await tools.search_us_code(make_client(page_handler(hits)), "Rule 8")
        assert out["results"][1]["note"] == (
            "This is one of 3 distinct provisions on this page that share one citation; the other(s): "
            "Rule 8. Civil; Rule 8. Bankruptcy. The citation does not say which one the person asking means \u2014 "
            "do not choose for them, and do not present one as the only match. Name each by its title as a "
            "distinct provision, and if you read only one, say which you did not read."
        )
        for hit in out["results"][:3]:
            assert hit["note"].startswith("This is one of 3 distinct provisions on this page")
            assert hit["same_citation_on_page"]["count"] == 3
        # A hit outside any family still carries no note.
        assert "note" not in out["results"][3] and "same_citation_on_page" not in out["results"][3]

    async def test_the_withdrawn_wording_is_gone(self, make_client):
        # R35: "told which is meant" is satisfied by the consumer choosing (E41, 6 of 10 rows).
        hits = [rule_hit(CIV_RULE9, "Rule 9. Civil"), rule_hit(CRIM_RULE9, "Rule 9. Criminal")]
        out = await tools.search_us_code(make_client(page_handler(hits)), "Rule 9")
        for hit in out["results"]:
            assert "which is meant" not in hit["note"] and "other result(s)" not in hit["note"]

    async def test_one_member_alone_carries_neither_field(self, make_client):
        hits = [rule_hit(CRIM_RULE9, "Rule 9. Arrest Warrant"), rule_hit(RULE8_A, "Rule 8. General Rules of Pleading")]
        out = await tools.search_us_code(make_client(page_handler(hits)), "Rule 9")
        for hit in out["results"]:
            assert "same_citation_on_page" not in hit
            assert "note" not in hit

    async def test_three_member_family_each_names_two_in_page_order(self, make_client):
        hits = [
            rule_hit(RULE8_A, "Rule 8. Civil"),
            rule_hit(CIV_RULE9, "Rule 9. Civil"),
            rule_hit(RULE8_B, "Rule 8. Criminal"),
            rule_hit(RULE8_C, "Rule 8. Bankruptcy"),
        ]
        out = await tools.search_us_code(make_client(page_handler(hits)), "Rule 8")
        a, nine, b, c = out["results"]
        assert "same_citation_on_page" not in nine and "note" not in nine
        assert a["same_citation_on_page"] == {
            "count": 3,
            "others": [
                {"granule_id": RULE8_B, "title": "Rule 8. Criminal"},
                {"granule_id": RULE8_C, "title": "Rule 8. Bankruptcy"},
            ],
        }
        assert a["note"] == NOTE.format(n=3, titles="Rule 8. Criminal; Rule 8. Bankruptcy")
        assert b["same_citation_on_page"]["count"] == 3
        assert [o["granule_id"] for o in b["same_citation_on_page"]["others"]] == [RULE8_A, RULE8_C]
        assert b["note"] == NOTE.format(n=3, titles="Rule 8. Civil; Rule 8. Bankruptcy")
        assert [o["granule_id"] for o in c["same_citation_on_page"]["others"]] == [RULE8_A, RULE8_B]

    async def test_a_page_of_sections_carries_no_field(self, make_client):
        hits = [
            fx.usc_hit(),
            fx.usc_hit(package_id="USCODE-2024-title42", granule_id="USCODE-2024-title42-chap23-sec2210"),
            fx.usc_hit(package_id="USCODE-2024-title12", granule_id="USCODE-2024-title12-chap6-sec582"),
        ]
        out = await tools.search_us_code(make_client(page_handler(hits)), "collateral")
        assert len(out["results"]) == 3
        for hit in out["results"]:
            assert "same_citation_on_page" not in hit and "note" not in hit

    async def test_same_id_in_two_editions_is_not_a_family(self, make_client):
        hits = [
            rule_hit(CRIM_RULE9, "Rule 9. Arrest Warrant"),
            fx.usc_hit(
                package_id="USCODE-2023-title28",
                granule_id="USCODE-2023-title28-app-federalru-dup1-rule9",
                date_issued="2024-01-01",
                title="Rule 9. Arrest Warrant",
            ),
        ]
        out = await tools.search_us_code(make_client(page_handler(hits)), "Rule 9", historical=True)
        for hit in out["results"]:
            assert "same_citation_on_page" not in hit

    async def test_hits_without_a_granule_id_are_left_alone(self, make_client):
        hits = [dict(rule_hit(CIV_RULE9, "a"), granuleId=None), dict(rule_hit(CRIM_RULE9, "b"), granuleId=None)]
        out = await tools.search_us_code(make_client(page_handler(hits)), "Rule 9")
        for hit in out["results"]:
            assert "same_citation_on_page" not in hit

    async def test_other_pointer_fields_are_unchanged(self, make_client):
        hits = [rule_hit(CIV_RULE9, "Rule 9. Civil"), rule_hit(CRIM_RULE9, "Rule 9. Criminal")]
        out = await tools.search_us_code(make_client(page_handler(hits)), "Rule 9")
        keys = set(out["results"][0])
        assert keys == set(tools._result_pointer(hits[0])) | {"same_citation_on_page", "note"}

    async def test_public_law_hits_carry_no_note(self, make_client):
        # No collision measured in PLAW; the note is a USCODE rule only.
        hits = [fx.plaw_hit(), fx.plaw_hit()]
        out = await tools.search_public_laws(make_client(page_handler(hits)), "defense")
        for hit in out["results"]:
            assert "same_citation_on_page" not in hit and "note" not in hit


# ---------------------------------------------------------------------------
# Part B — the by-id note
# ---------------------------------------------------------------------------

CANDIDATES_MESSAGE = "This provision shares its citation with {n} other(s): {titles}. The person asking should be told."
T28 = "USCODE-2024-title28"
RULE4_A = "USCODE-2024-title28-app-federalru-rule4"
RULE4_B = "USCODE-2024-title28-app-federalru-dup1-rule4"
RULE4_C = "USCODE-2024-title28-app-federalru-dup1-rule4-dup1"
RULE4_1 = "USCODE-2024-title28-app-federalru-dup1-rule4.1"

# The live Rule 4 page (runs/20260929-wo26-28/wo28c-before.json): citation:"28 U.S.C.
# App. Rule 4" returns Rule 4.1 beside the three Rule 4s.
RULE4_PAGE = [
    rule_hit(RULE4_A, "Appeal as of Right-When Taken"),
    rule_hit(RULE4_1, "Serving Other Process"),
    rule_hit(RULE4_C, "Answer; Motions; Time"),
    rule_hit(RULE4_B, "Summons"),
]
RULE9_PAGE = [rule_hit(CIV_RULE9, "Release in a Criminal Case"), rule_hit(CRIM_RULE9, "Pleading Special Matters")]
RULE8_PAGE = [
    rule_hit(RULE8_A, "Stay or Injunction Pending Appeal"),
    rule_hit(RULE8_C, "Reply Brief"),
    rule_hit(RULE8_B, "General Rules of Pleading"),
]


def by_id_handler(granule_id: str, family_page: list[dict] | None, seen: list, family_response=None):
    """Serve the summary and /htm for `granule_id`, the detector, and the family search."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/summary"):
            return fx.json_response(fx.granule_summary(package_id=T28, granule_id=granule_id))
        if request.url.path.endswith("/htm"):
            return httpx.Response(200, text=fx.SECTION_HTML)
        if request.url.path == "/search":
            body = fx.request_body(request)
            if "collection:PLAW" in body["query"]:
                return fx.json_response(fx.search_response([], count=0))
            if family_response is not None:
                return family_response
            assert family_page is not None, "no citation search was expected on this call"
            return fx.json_response(fx.search_response(family_page, count=len(family_page)))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


def family_searches(seen: list) -> list[dict]:
    return [
        fx.request_body(r)
        for r in seen
        if r.url.path == "/search" and "collection:USCODE" in fx.request_body(r)["query"]
    ]


class TestByIdNote:
    async def test_with_citation_family_of_two_names_the_other(self, make_client):
        seen = []
        out = await tools.get_us_code_section(
            make_client(by_id_handler(CRIM_RULE9, RULE9_PAGE, seen)),
            granule_id=CRIM_RULE9,
            citation="28 U.S.C. App. Rule 9",
        )
        assert out["outcome"] == "success"
        searches = family_searches(seen)
        assert len(searches) == 1
        assert searches[0] == {
            "query": 'collection:USCODE citation:"28 U.S.C. App. Rule 9"',
            "pageSize": 100,
            "offsetMark": "*",
            "historical": False,
        }
        assert out["same_citation_candidates"] == {
            "count": 2,
            "others": [{"granule_id": CIV_RULE9, "title": "Release in a Criminal Case"}],
            "message": CANDIDATES_MESSAGE.format(n=1, titles="Release in a Criminal Case"),
        }

    async def test_message_is_the_contract_text(self):
        assert tools.SAME_CITATION_CANDIDATES_MESSAGE == CANDIDATES_MESSAGE

    async def test_field_follows_possibly_superseded(self, make_client):
        out = await tools.get_us_code_section(
            make_client(by_id_handler(CRIM_RULE9, RULE9_PAGE, [])),
            granule_id=CRIM_RULE9,
            citation="28 U.S.C. App. Rule 9",
        )
        keys = list(out)
        assert keys.index("same_citation_candidates") == keys.index("possibly_superseded") + 1

    async def test_with_citation_family_of_three_names_two(self, make_client):
        out = await tools.get_us_code_section(
            make_client(by_id_handler(RULE8_B, RULE8_PAGE, [])), granule_id=RULE8_B, citation="28 U.S.C. App. Rule 8"
        )
        sc = out["same_citation_candidates"]
        assert sc["count"] == 3
        assert sc["others"] == [
            {"granule_id": RULE8_A, "title": "Stay or Injunction Pending Appeal"},
            {"granule_id": RULE8_C, "title": "Reply Brief"},
        ]
        assert sc["message"] == CANDIDATES_MESSAGE.format(n=2, titles="Stay or Injunction Pending Appeal; Reply Brief")

    async def test_without_citation_on_an_appendix_rule_id_derives_the_citation(self, make_client):
        seen = []
        out = await tools.get_us_code_section(
            make_client(by_id_handler(CRIM_RULE9, RULE9_PAGE, seen)), granule_id=CRIM_RULE9
        )
        assert out["outcome"] == "success"
        assert out["citation"] is None
        searches = family_searches(seen)
        assert len(searches) == 1
        assert searches[0]["query"] == 'collection:USCODE citation:"28 U.S.C. App. Rule 9"'
        assert out["same_citation_candidates"]["others"] == [
            {"granule_id": CIV_RULE9, "title": "Release in a Criminal Case"}
        ]
        # The detector still has no measured form for a rule and was not run.
        assert out["possibly_superseded"]["reason"] == "no_citation_for_detector"

    async def test_without_citation_a_trailing_dup_segment_still_names_the_rule(self, make_client):
        seen = []
        out = await tools.get_us_code_section(make_client(by_id_handler(RULE8_C, RULE8_PAGE, seen)), granule_id=RULE8_C)
        assert family_searches(seen)[0]["query"] == 'collection:USCODE citation:"28 U.S.C. App. Rule 8"'
        assert [o["granule_id"] for o in out["same_citation_candidates"]["others"]] == [RULE8_A, RULE8_B]

    async def test_section_id_without_citation_runs_no_search_and_serves_no_field(self, make_client):
        seen = []
        gid = "USCODE-2024-title17-chap1-sec107"

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path.endswith("/summary"):
                return fx.json_response(fx.granule_summary())
            if request.url.path.endswith("/htm"):
                return httpx.Response(200, text=fx.SECTION_HTML)
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        out = await tools.get_us_code_section(make_client(handler), granule_id=gid)
        assert out["outcome"] == "success"
        assert "same_citation_candidates" not in out
        assert not any(r.url.path == "/search" for r in seen)

    async def test_appendix_section_id_without_citation_runs_no_search(self, make_client):
        # `-app-` without a trailing rule segment is not an appendix rule.
        seen = []
        gid = "USCODE-2024-title18-app-sec1201"

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path.endswith("/summary"):
                return fx.json_response(fx.granule_summary(package_id="USCODE-2024-title18", granule_id=gid))
            if request.url.path.endswith("/htm"):
                return httpx.Response(200, text=fx.SECTION_HTML)
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        out = await tools.get_us_code_section(make_client(handler), granule_id=gid)
        assert out["outcome"] == "success"
        assert "same_citation_candidates" not in out
        assert not any(r.url.path == "/search" for r in seen)

    async def test_section_id_with_citation_family_of_one_serves_no_field(self, make_client):
        seen = []
        gid = "USCODE-2024-title17-chap1-sec107"

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path.endswith("/summary"):
                return fx.json_response(fx.granule_summary())
            if request.url.path.endswith("/htm"):
                return httpx.Response(200, text=fx.SECTION_HTML)
            body = fx.request_body(request)
            if "collection:PLAW" in body["query"]:
                return fx.json_response(fx.search_response([], count=0))
            return fx.json_response(fx.search_response([fx.usc_hit()]))

        out = await tools.get_us_code_section(make_client(handler), granule_id=gid, citation="17 U.S.C. 107")
        assert out["outcome"] == "success"
        assert len(family_searches(seen)) == 1
        assert "same_citation_candidates" not in out

    async def test_rule_4_names_two_others_never_rule_4_1(self, make_client):
        out = await tools.get_us_code_section(
            make_client(by_id_handler(RULE4_B, RULE4_PAGE, [])), granule_id=RULE4_B, citation="28 U.S.C. App. Rule 4"
        )
        sc = out["same_citation_candidates"]
        assert sc["count"] == 3
        assert [o["granule_id"] for o in sc["others"]] == [RULE4_A, RULE4_C]
        assert "Serving Other Process" not in sc["message"]
        assert sc["message"] == CANDIDATES_MESSAGE.format(
            n=2, titles="Appeal as of Right-When Taken; Answer; Motions; Time"
        )

    async def test_a_page_with_the_fetched_granule_missing_still_names_its_family(self, make_client):
        # The family is read from ids, not from the fetched granule's presence on the page.
        out = await tools.get_us_code_section(
            make_client(by_id_handler(CRIM_RULE9, RULE9_PAGE[:1], [])),
            granule_id=CRIM_RULE9,
            citation="28 U.S.C. App. Rule 9",
        )
        assert out["same_citation_candidates"]["others"] == [
            {"granule_id": CIV_RULE9, "title": "Release in a Criminal Case"}
        ]

    @pytest.mark.parametrize(
        "response,expect",
        [
            (httpx.Response(500, text="boom"), ("upstream_error", 500)),
            (httpx.Response(429, text="slow down", headers={"retry-after": "9"}), ("rate_limited", 429)),
            (httpx.Response(200, text="not json"), ("upstream_error", 200)),
        ],
    )
    async def test_a_failed_family_search_is_disclosed_and_never_fails_the_lookup(self, make_client, response, expect):
        out = await tools.get_us_code_section(
            make_client(by_id_handler(CRIM_RULE9, None, [], family_response=response)),
            granule_id=CRIM_RULE9,
            citation="28 U.S.C. App. Rule 9",
        )
        assert out["outcome"] == "success"
        sc = out["same_citation_candidates"]
        assert sc["count"] is None and sc["others"] is None
        assert sc["not_checked"]["outcome"] == expect[0]
        assert sc["not_checked"]["http_status"] == expect[1]
        assert sc["message"] == tools.SAME_CITATION_NOT_CHECKED_MESSAGE

    async def test_an_id_from_another_edition_is_disclosed_not_read_as_a_family_of_one(self, make_client):
        # The search covers the current edition; a 2018 id finds no 2018 granule on
        # the page, so nothing can be said about its family — and that is said.
        old_id = "USCODE-2018-title28-app-federalru-dup1-rule9"
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path.endswith("/summary"):
                return fx.json_response(fx.granule_summary(package_id="USCODE-2018-title28", granule_id=old_id))
            if request.url.path.endswith("/htm"):
                return httpx.Response(200, text=fx.SECTION_HTML)
            body = fx.request_body(request)
            if "collection:PLAW" in body["query"]:
                return fx.json_response(fx.search_response([], count=0))
            return fx.json_response(fx.search_response(RULE9_PAGE, count=2))

        out = await tools.get_us_code_section(make_client(handler), granule_id=old_id, citation="28 U.S.C. App. Rule 9")
        assert out["outcome"] == "success"
        assert len(family_searches(seen)) == 1
        sc = out["same_citation_candidates"]
        assert sc["count"] is None and sc["others"] is None
        assert sc["not_checked"]["reason"] == "edition_not_on_page"
        assert sc["not_checked"]["query"] == 'collection:USCODE citation:"28 U.S.C. App. Rule 9"'
        assert "USCODE-2018-title28" in sc["not_checked"]["detail"]
        assert sc["message"] == tools.SAME_CITATION_EDITION_NOT_ON_PAGE_MESSAGE.format(package_id="USCODE-2018-title28")

    async def test_a_capped_family_page_says_so(self, make_client):
        page = fx.json_response(fx.search_response(RULE9_PAGE, count=178))
        out = await tools.get_us_code_section(
            make_client(by_id_handler(CRIM_RULE9, None, [], family_response=page)),
            granule_id=CRIM_RULE9,
            citation="28 U.S.C. App. Rule 9",
        )
        sc = out["same_citation_candidates"]
        assert sc["count"] == 2 and sc["capped"] is True
        assert sc["message"].startswith(CANDIDATES_MESSAGE.format(n=1, titles="Release in a Criminal Case"))
        assert "178" in sc["message"] and "2 of" in sc["message"]

    async def test_family_search_failure_on_a_failed_lookup_serves_the_lookup_failure(self, make_client):
        # A by-id call that fails upstream is the failure it is; no family field rides on it.
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/summary"):
                return httpx.Response(404, text="no such package")
            return fx.json_response(fx.search_response(RULE9_PAGE))

        out = await tools.get_us_code_section(
            make_client(handler), granule_id=CRIM_RULE9, citation="28 U.S.C. App. Rule 9"
        )
        assert out["outcome"] == "not_found"
        assert "same_citation_candidates" not in out


# ---------------------------------------------------------------------------
# Part C — the family filter on resolution (F20)
# ---------------------------------------------------------------------------


def resolution_handler(page: list[dict], count: int | None = None, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/search":
            body = fx.request_body(request)
            if "collection:PLAW" in body["query"]:
                return fx.json_response(fx.search_response([], count=0))
            return fx.json_response(fx.search_response(page, count=count))
        if request.url.path.endswith("/htm"):
            return httpx.Response(200, text=fx.SECTION_HTML)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


class TestResolutionFamilyFilter:
    async def test_rule_4_four_hit_page_is_ambiguous_with_three(self, make_client):
        out = await tools.get_us_code_section(
            make_client(resolution_handler(RULE4_PAGE)), citation="28 U.S.C. App. Rule 4"
        )
        assert out["outcome"] == "ambiguous"
        assert out["count"] == 3
        assert out["count_unfiltered"] == 4
        assert out["candidates_shown"] == 3 and out["capped"] is False
        assert [c["granule_id"] for c in out["candidates"]] == [RULE4_A, RULE4_C, RULE4_B]
        assert out["message"] == tools.USCODE_COLLISION_MESSAGE.format(n=3)

    async def test_rule_4_1_on_the_same_page_resolves_to_itself(self, make_client):
        seen = []
        out = await tools.get_us_code_section(
            make_client(resolution_handler(RULE4_PAGE, seen=seen)), citation="28 U.S.C. App. Rule 4.1", max_chars=1
        )
        assert out["outcome"] == "success"
        assert out["provenance"]["granule_id"] == RULE4_1
        assert fx.request_body(seen[0])["query"] == 'collection:USCODE citation:"28 U.S.C. App. Rule 4.1"'

    async def test_rule_9_pair_is_unchanged(self, make_client):
        out = await tools.get_us_code_section(
            make_client(resolution_handler(RULE9_PAGE)), citation="28 U.S.C. App. Rule 9"
        )
        # Nothing filtered and a complete page: the envelope is byte-identical to before.
        assert out["outcome"] == "ambiguous" and out["count"] == 2
        assert "count_unfiltered" not in out
        assert out["message"] == tools.USCODE_COLLISION_MESSAGE.format(n=2)
        assert set(out) == {
            "outcome",
            "normalized_citation",
            "query",
            "year",
            "count",
            "candidates_shown",
            "capped",
            "message",
            "candidates",
        }

    async def test_rule_8_three_members_are_unchanged(self, make_client):
        out = await tools.get_us_code_section(
            make_client(resolution_handler(RULE8_PAGE)), citation="28 U.S.C. App. Rule 8"
        )
        assert out["outcome"] == "ambiguous" and out["count"] == 3
        assert [c["granule_id"] for c in out["candidates"]] == [RULE8_A, RULE8_C, RULE8_B]

    async def test_a_family_of_one_after_the_filter_is_success(self, make_client):
        page = [rule_hit(RULE4_1, "Serving Other Process"), rule_hit(RULE4_B, "Summons")]
        out = await tools.get_us_code_section(
            make_client(resolution_handler(page)), citation="28 U.S.C. App. Rule 4", max_chars=1
        )
        assert out["outcome"] == "success"
        assert out["provenance"]["granule_id"] == RULE4_B

    async def test_only_over_matches_is_a_redirect_not_a_wrong_success(self, make_client):
        # A citation whose only token matches are other rules names nothing that exists.
        page = [rule_hit(RULE4_1, "Serving Other Process")]
        out = await tools.get_us_code_section(make_client(resolution_handler(page)), citation="28 U.S.C. App. Rule 4")
        assert out["outcome"] == "appendix_redirect"

    async def test_section_citations_are_untouched(self, make_client):
        seen = []
        out = await tools.get_us_code_section(
            make_client(resolution_handler([fx.usc_hit()], seen=seen)), citation="17 U.S.C. 107", max_chars=1
        )
        assert out["outcome"] == "success" and "count_unfiltered" not in out

    async def test_numbered_appendix_section_is_untouched(self, make_client):
        hit = fx.usc_hit(package_id="USCODE-2024-title18", granule_id="USCODE-2024-title18-app-sec1201")
        out = await tools.get_us_code_section(
            make_client(resolution_handler([hit])), citation="18 U.S.C. App. 1201", max_chars=1
        )
        assert out["outcome"] == "success"

    async def test_year_and_rule_filters_compose(self, make_client):
        page = [dict(h, dateIssued="2024-01-08") for h in RULE4_PAGE] + [
            fx.usc_hit(
                package_id="USCODE-2023-title28",
                granule_id="USCODE-2023-title28-app-federalru-dup1-rule4",
                date_issued="2023-01-03",
                title="Summons",
            )
        ]
        out = await tools.get_us_code_section(
            make_client(resolution_handler(page, count=119)), citation="28 U.S.C. App. Rule 4", year=2024
        )
        assert out["outcome"] == "ambiguous"
        assert out["count"] == 3 and out["count_all_editions"] == 119
        assert [c["granule_id"] for c in out["candidates"]] == [RULE4_A, RULE4_C, RULE4_B]

    async def test_a_capped_page_under_the_rule_filter_says_so(self, make_client):
        out = await tools.get_us_code_section(
            make_client(resolution_handler(RULE4_PAGE, count=250)), citation="28 U.S.C. App. Rule 4"
        )
        assert out["outcome"] == "ambiguous"
        assert out["count"] == 3 and out["count_unfiltered"] == 250 and out["capped"] is True
        assert out["message"].startswith(tools.USCODE_COLLISION_MESSAGE.format(n=3))
        assert "250" in out["message"]


# ---------------------------------------------------------------------------
# WO-29 B — the second-section marker joins the family rule (F21, O116e)
# ---------------------------------------------------------------------------

SEC1932 = "USCODE-2024-title28-partV-chap123-sec1932"
SEC1932_2 = "USCODE-2024-title28-partV-chap123-sec1932_2"
SEC1932_PAGE = [
    rule_hit(SEC1932, "Judicial Panel on Multidistrict Litigation"),
    rule_hit(SEC1932_2, "1932.1 Revocation of earned release credit"),
]


class TestSecondSectionMarker:
    @pytest.mark.parametrize(
        "granule_id,expected",
        [
            (SEC1932_2, SEC1932),
            (SEC1932, SEC1932),
            (
                "USCODE-2024-title5-partIII-subpartB-chap35-subchapVII-sec3598_2",
                "USCODE-2024-title5-partIII-subpartB-chap35-subchapVII-sec3598",
            ),
            ("USCODE-2024-title28-app-federalru-dup1-rule9_2", "USCODE-2024-title28-app-federalru-rule9"),
            # Only a trailing `_{N}` on the last segment; an underscore elsewhere stays.
            ("USCODE-2024-title28-partV-chap123_2-sec1932", "USCODE-2024-title28-partV-chap123_2-sec1932"),
            ("USCODE-2024-title28-partV-chap123-sec1932_a", "USCODE-2024-title28-partV-chap123-sec1932_a"),
            (CRIM_RULE9, CIV_RULE9),
        ],
    )
    def test_trailing_underscore_number_is_removed_from_the_last_segment(self, granule_id, expected):
        assert tools.normalized_granule_id(granule_id) == expected

    async def test_a_page_holding_both_1932s_annotates_both(self, make_client):
        out = await tools.search_us_code(make_client(page_handler(SEC1932_PAGE)), 'citation:"28 U.S.C. 1932"')
        first, second = out["results"]
        assert first["same_citation_on_page"] == {
            "count": 2,
            "others": [{"granule_id": SEC1932_2, "title": "1932.1 Revocation of earned release credit"}],
        }
        assert first["note"] == NOTE.format(n=2, titles="1932.1 Revocation of earned release credit")
        assert second["same_citation_on_page"]["others"] == [
            {"granule_id": SEC1932, "title": "Judicial Panel on Multidistrict Litigation"}
        ]

    async def test_1932_alone_on_a_page_carries_nothing(self, make_client):
        out = await tools.search_us_code(make_client(page_handler(SEC1932_PAGE[:1])), "multidistrict")
        assert "same_citation_on_page" not in out["results"][0] and "note" not in out["results"][0]

    async def test_by_id_on_the_second_section_with_citation_names_the_first(self, make_client):
        seen = []
        out = await tools.get_us_code_section(
            make_client(by_id_handler(SEC1932_2, SEC1932_PAGE, seen)), granule_id=SEC1932_2, citation="28 U.S.C. 1932"
        )
        assert out["outcome"] == "success"
        assert family_searches(seen)[0]["query"] == 'collection:USCODE citation:"28 U.S.C. 1932"'
        assert out["same_citation_candidates"] == {
            "count": 2,
            "others": [{"granule_id": SEC1932, "title": "Judicial Panel on Multidistrict Litigation"}],
            "message": CANDIDATES_MESSAGE.format(n=1, titles="Judicial Panel on Multidistrict Litigation"),
        }

    async def test_by_id_on_the_second_section_without_citation_runs_no_search(self, make_client):
        # A section id names no citation the server derives; only appendix rules do.
        seen = []
        out = await tools.get_us_code_section(make_client(by_id_handler(SEC1932_2, None, seen)), granule_id=SEC1932_2)
        assert out["outcome"] == "success"
        assert family_searches(seen) == [] and "same_citation_candidates" not in out

    async def test_the_rule_9_cases_are_unchanged(self, make_client):
        out = await tools.search_us_code(make_client(page_handler(RULE9_PAGE)), "Rule 9")
        assert [h["same_citation_on_page"]["count"] for h in out["results"]] == [2, 2]
        out = await tools.get_us_code_section(
            make_client(by_id_handler(CRIM_RULE9, RULE9_PAGE, [])),
            granule_id=CRIM_RULE9,
            citation="28 U.S.C. App. Rule 9",
        )
        assert out["same_citation_candidates"]["others"] == [
            {"granule_id": CIV_RULE9, "title": "Release in a Criminal Case"}
        ]
