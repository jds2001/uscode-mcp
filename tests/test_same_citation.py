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

NOTE = (
    "This provision shares its citation with {n} other result(s) on this page: {titles}. The person asking "
    "should be told which is meant, or shown each as a distinct provision."
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
        assert civ["note"] == NOTE.format(n=1, titles="Rule 9. Arrest Warrant")
        assert crim["same_citation_on_page"] == {
            "count": 2,
            "others": [{"granule_id": CIV_RULE9, "title": "Rule 9. Pleading Special Matters"}],
        }
        assert crim["note"] == NOTE.format(n=1, titles="Rule 9. Pleading Special Matters")

    async def test_note_is_the_contract_text_character_for_character(self):
        assert tools.SAME_CITATION_ON_PAGE_NOTE == NOTE

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
        assert a["note"] == NOTE.format(n=2, titles="Rule 8. Criminal; Rule 8. Bankruptcy")
        assert b["same_citation_on_page"]["count"] == 3
        assert [o["granule_id"] for o in b["same_citation_on_page"]["others"]] == [RULE8_A, RULE8_C]
        assert b["note"] == NOTE.format(n=2, titles="Rule 8. Civil; Rule 8. Bankruptcy")
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
