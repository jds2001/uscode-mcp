"""WO-31 (R36; documentation/40-tools.md, "A window ends where a paragraph does"):
`max_chars` is an upper bound on `text.content`. A window that would stop short of
the payload's end is ended by the first of four steps that applies — as asked when
the requested end already sits at a paragraph break; at the last paragraph break
inside the window when that keeps at least half of `max_chars`; at the last
whitespace inside the window; as asked when the window holds no whitespace. A
paragraph break is two or more consecutive newlines; punctuation is never a boundary.
No window is lengthened and no character is skipped or served twice.
"""

from __future__ import annotations

import random

import fx
import httpx
import pytest

from uscode_mcp import tools
from uscode_mcp.htmltext import _window_end, window_text

# "aaaa bbbb" is chars 0–8, the blank line's two newlines are 9 and 10, "cccc" opens at 11.
TWO_PARAGRAPHS = "aaaa bbbb\n\ncccc dddd eeee ffff"
# The break ends at 10; the rest is five-character words with no further break.
BREAK_AT_TEN = "abcdefgh\n\n" + "word " * 10


def walk(text: str, max_chars: int, start_char: int = 0) -> list[dict]:
    """Every window from `start_char` to the payload's end, following next_start_char."""
    windows = []
    start: int | None = start_char
    while start is not None:
        w = window_text(text, start_char=start, max_chars=max_chars)
        windows.append(w)
        assert len(windows) <= len(text) + 1, "a walk must terminate"
        start = w["next_start_char"]
    return windows


class TestStepOneAsAskedAtAParagraphBreak:
    def test_requested_end_just_before_a_blank_line_is_unchanged(self):
        w = window_text(TWO_PARAGRAPHS, max_chars=9)
        assert w["content"] == "aaaa bbbb"
        assert w["returned_chars"] == 9 and w["next_start_char"] == 9
        assert _window_end(TWO_PARAGRAPHS, 0, 9) == (9, "paragraph")

    def test_requested_end_just_after_a_blank_line_is_unchanged(self):
        w = window_text(TWO_PARAGRAPHS, max_chars=11)
        assert w["content"] == "aaaa bbbb\n\n"
        assert w["returned_chars"] == 11 and w["next_start_char"] == 11
        assert _window_end(TWO_PARAGRAPHS, 0, 11) == (11, "paragraph")

    def test_requested_end_between_the_two_newlines_is_unchanged(self):
        # The end sits at the break either way; nothing is gained by moving it.
        assert _window_end(TWO_PARAGRAPHS, 0, 10) == (10, "paragraph")
        assert window_text(TWO_PARAGRAPHS, max_chars=10)["content"] == "aaaa bbbb\n"

    def test_a_field_read_by_its_own_coordinates_is_returned_whole(self):
        # Every `structure` field ends at a paragraph break (O121d): max_chars =
        # end_char - start_char returns the field, not a shortened window.
        text = "head\n\n" + "statute text of some length. " * 4 + "\n\nsourcecredit\n\nnotes follow here"
        start = text.index("statute")
        end = text.index("sourcecredit")
        w = window_text(text, start_char=start, max_chars=end - start)
        assert w["content"] == text[start:end]
        assert w["truncated"] is True and w["next_start_char"] == end

    def test_a_requested_end_one_past_the_break_is_not_step_one(self):
        # Asked for 12: one character into the second paragraph. The break at 11
        # keeps more than half, so the window is shortened to it.
        w = window_text(TWO_PARAGRAPHS, max_chars=12)
        assert w["content"] == "aaaa bbbb\n\n"
        assert w["next_start_char"] == 11


class TestStepTwoTheLastParagraphBreakThatKeepsHalf:
    def test_a_break_at_exactly_half_is_taken(self):
        assert _window_end(BREAK_AT_TEN, 0, 20) == (10, "paragraph")
        w = window_text(BREAK_AT_TEN, max_chars=20)
        assert w["content"] == "abcdefgh\n\n"
        assert w["returned_chars"] == 10 and w["next_start_char"] == 10

    def test_a_break_one_character_under_half_is_not_taken_and_the_word_fallback_runs(self):
        assert _window_end(BREAK_AT_TEN, 0, 21) == (20, "word")
        w = window_text(BREAK_AT_TEN, max_chars=21)
        assert w["content"] == "abcdefgh\n\nword word "
        assert w["returned_chars"] == 20 and w["next_start_char"] == 20

    def test_half_of_an_odd_max_chars_is_not_rounded_down(self):
        # 9 kept of 19 asked is under half (9.5); 10 kept of 19 is not.
        text = "abcdefg\n\n" + "word " * 10
        assert _window_end(text, 0, 19) == (19, "word")
        assert _window_end(BREAK_AT_TEN, 0, 19) == (10, "paragraph")

    def test_the_last_break_inside_the_window_is_the_one_taken(self):
        text = "one\n\ntwo\n\nthree\n\nfour five six seven eight"
        w = window_text(text, max_chars=22)
        assert w["content"] == "one\n\ntwo\n\nthree\n\n"
        assert text[w["next_start_char"] :].startswith("four")

    def test_the_next_window_opens_on_a_paragraphs_first_character(self):
        first = window_text(TWO_PARAGRAPHS, max_chars=14)
        assert first["content"] == "aaaa bbbb\n\n"
        second = window_text(TWO_PARAGRAPHS, start_char=first["next_start_char"], max_chars=100)
        assert second["content"] == "cccc dddd eeee ffff"

    def test_half_is_measured_from_start_char_not_from_zero(self):
        text = "x" * 50 + " " + BREAK_AT_TEN
        assert _window_end(text, 51, 20) == (61, "paragraph")
        assert _window_end(text, 51, 21) == (71, "word")

    def test_a_break_before_start_char_is_not_inside_the_window(self):
        text = "aaaa\n\nbbbb cccc dddd eeee ffff"
        assert _window_end(text, 6, 12) == (16, "word")

    def test_a_run_of_three_newlines_is_one_break_and_the_window_ends_after_all_of_it(self):
        # A public law served as plain text can carry longer runs.
        text = "aaa\n\n\nbbb ccc ddd eee"
        assert _window_end(text, 0, 8) == (6, "paragraph")
        assert window_text(text, start_char=6, max_chars=100)["content"] == "bbb ccc ddd eee"


class TestStepThreeTheLastWhitespace:
    def test_a_single_newline_with_no_blank_line_is_not_a_paragraph_boundary(self):
        # In a public law a single newline is a line wrap inside a sentence (O121b).
        text = "line one\nline two\nline three and more"
        assert _window_end(text, 0, 20) == (18, "word")
        assert window_text(text, max_chars=20)["content"] == "line one\nline two\n"

    def test_no_word_is_split(self):
        text = "in accordance with the applicable procedures of the court"
        w = window_text(text, max_chars=37)  # as asked: "…the applicable pro"
        assert w["content"] == "in accordance with the applicable "
        assert text[w["next_start_char"] :].startswith("procedures")

    def test_punctuation_is_never_a_boundary(self):
        # A period and a space is a citation more often than a sentence end (O121e):
        # the cut is the last whitespace, not the last sentence end.
        text = "Alpha beta. Gamma delta epsilon zeta eta theta"
        assert window_text(text, max_chars=20)["content"] == "Alpha beta. Gamma "
        cite = "as provided in 42 U.S.C. 2210 and elsewhere in this title"
        assert window_text(cite, max_chars=27)["content"] == "as provided in 42 U.S.C. "

    def test_a_requested_end_just_after_whitespace_is_returned_at_full_length(self):
        text = "aaaa bbbb cccc dddd"
        assert _window_end(text, 0, 10) == (10, "word")
        assert window_text(text, max_chars=10)["content"] == "aaaa bbbb "


class TestStepFourNoWhitespace:
    def test_a_window_with_no_whitespace_is_returned_as_asked(self):
        assert _window_end("x" * 50, 0, 10) == (10, "character")
        assert window_text("x" * 50, max_chars=10)["content"] == "x" * 10

    def test_max_chars_one(self):
        w = window_text("abc def\n\nghi", max_chars=1)
        assert w["content"] == "a"
        assert w["returned_chars"] == 1 and w["next_start_char"] == 1 and w["truncated"] is True
        assert _window_end("abc def\n\nghi", 0, 1) == (1, "character")

    def test_max_chars_one_on_every_offset_returns_exactly_one_character(self):
        text = "ab cd\n\nef\ng"
        for start in range(len(text) - 1):
            assert window_text(text, start_char=start, max_chars=1)["content"] == text[start]


class TestMarkersFollowTheWindowReturned:
    def test_returned_chars_next_start_char_banner_and_size_sentence(self):
        text = "abcdefgh\n\n" + "word " * 10
        w = window_text(text, max_chars=20)
        assert w["total_chars"] == 60 and w["start_char"] == 0
        assert w["returned_chars"] == len(w["content"]) == 10
        assert w["next_start_char"] == 10
        assert w["banner"] == "[WINDOW chars 0–9 of 60 — truncated; continue with start_char=10]"
        assert w["message"].startswith("Payload is 60 chars; returned chars 0-9.")
        assert w["message"].endswith("Continue with start_char=10.")

    def test_a_continuation_window_states_its_own_bounds(self):
        text = "abcdefgh\n\n" + "word " * 10
        w = window_text(text, start_char=10, max_chars=12)
        assert w["content"] == "word word "
        assert w["next_start_char"] == 20
        assert w["banner"] == "[WINDOW chars 10–19 of 60 — truncated; continue with start_char=20]"
        assert w["message"].startswith("Payload is 60 chars; returned chars 10-19.")

    def test_the_last_window_of_a_payload_is_untruncated_and_unchanged(self):
        w = window_text(TWO_PARAGRAPHS, start_char=11, max_chars=100)
        assert w == {
            "total_chars": len(TWO_PARAGRAPHS),
            "start_char": 11,
            "returned_chars": len(TWO_PARAGRAPHS) - 11,
            "truncated": False,
            "next_start_char": None,
            "content": "cccc dddd eeee ffff",
        }

    def test_a_window_that_reaches_the_end_exactly_is_untruncated(self):
        # Asked for precisely the remainder: nothing is cut back, mid-word or not.
        w = window_text("aaaa bbbb", max_chars=9)
        assert w["truncated"] is False and w["content"] == "aaaa bbbb"

    def test_no_window_is_lengthened(self):
        # One character short of a break: the window does not reach forward for it.
        text = "aaaa bbbb cccc\n\ndddd eeee"
        w = window_text(text, max_chars=13)
        assert w["returned_chars"] <= 13
        assert w["content"] == "aaaa bbbb "


MULTI = "\n\n".join(
    [
        "Rule 9. Release in a Criminal Case",
        "(a) Release Before Judgment of Conviction.",
        "(1) The district court must state in writing, or orally on the record, the reasons for an order "
        "regarding the release or detention of a defendant in a criminal case. " * 3,
        "(b) Release After Judgment of Conviction. A party entitled to do so may obtain review.",
        "x" * 300,
        "Notes of Advisory Committee on Rules—1967\nSubdivision (a). The appealability of release orders "
        "entered prior to a judgment of conviction is determined by 18 U.S.C. 3147.",
        "short",
    ]
)


class TestWalk:
    @pytest.mark.parametrize("max_chars", [1, 2, 3, 7, 40, 100, 250, 400, 1000, len(MULTI) - 1, len(MULTI)])
    def test_concatenated_windows_equal_the_payload_byte_for_byte(self, max_chars):
        windows = walk(MULTI, max_chars)
        assert "".join(w["content"] for w in windows) == MULTI
        position = 0
        for w in windows:
            assert w["start_char"] == position
            assert 1 <= w["returned_chars"] == len(w["content"]) <= max_chars
            position += w["returned_chars"]
            assert w["next_start_char"] == (position if w["truncated"] else None)
        assert windows[-1]["truncated"] is False
        assert all(w["truncated"] for w in windows[:-1])

    def test_property_over_random_texts_and_sizes(self):
        rng = random.Random(31)
        for _ in range(3000):
            n = rng.randint(1, 120)
            text = "".join(rng.choice("abc.  \n\n\n\t;") for _ in range(n))
            max_chars = rng.randint(1, 40)
            start = rng.randint(0, n - 1)
            windows = walk(text, max_chars, start_char=start)
            assert "".join(w["content"] for w in windows) == text[start:], (text, max_chars, start)
            for w in windows:
                assert 1 <= w["returned_chars"] == len(w["content"]) <= max_chars, (text, max_chars, start)
                if w["truncated"]:
                    assert w["next_start_char"] == w["start_char"] + w["returned_chars"]
                    assert w["next_start_char"] < len(text)
                else:
                    assert w["start_char"] + w["returned_chars"] == len(text)

    def test_property_every_shortened_window_ends_on_whitespace(self):
        # A window shorter than asked was cut at a break or a word boundary, never
        # inside a word and never because of punctuation.
        rng = random.Random(36)
        for _ in range(2000):
            text = "".join(rng.choice("abcde. \n\n") for _ in range(rng.randint(2, 100)))
            max_chars = rng.randint(1, 30)
            w = window_text(text, max_chars=max_chars)
            if w["truncated"] and w["returned_chars"] < max_chars:
                assert w["content"][-1].isspace(), (text, max_chars)

    def test_invalid_arguments_still_raise(self):
        with pytest.raises(ValueError):
            window_text(MULTI, start_char=-1)
        with pytest.raises(ValueError):
            window_text(MULTI, max_chars=0)


# ---------------------------------------------------------------------------
# Both text tools, at every start_char
# ---------------------------------------------------------------------------

PARAGRAPHS = [f"Paragraph {i} of the provision, with words enough to be a paragraph of its own." for i in range(12)]
PARAGRAPHS[5] = "A long paragraph: " + "the State agency shall provide timely and accurate service, " * 12
SECTION_HTML = fx.SECTION_HTML.replace(
    "<p>Effective date note text lives here and must never be dropped.</p>",
    "".join(f"<p>{p}</p>" for p in PARAGRAPHS),
)
PLAW_HTML = fx.PLAW_HTML.replace("SEC. 2.", "".join(f"<p>{p}</p>" for p in PARAGRAPHS) + "SEC. 2.")


def section_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/search":
        if "collection:PLAW" in fx.request_body(request)["query"]:
            return fx.json_response(fx.search_response([], count=0))
        return fx.json_response(fx.search_response([fx.usc_hit()]))
    if request.url.path.endswith("/summary"):
        return fx.json_response(fx.granule_summary())
    return httpx.Response(200, text=SECTION_HTML)


def plaw_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/search":
        return fx.json_response(fx.search_response([fx.plaw_hit()]))
    if request.url.path.endswith("/summary"):
        return fx.json_response(fx.plaw_summary())
    return httpx.Response(200, text=PLAW_HTML)


async def read_section(make_client, **kwargs):
    return await tools.get_us_code_section(make_client(section_handler), citation="17 U.S.C. 107", **kwargs)


async def read_section_by_id(make_client, **kwargs):
    return await tools.get_us_code_section(
        make_client(section_handler), granule_id="USCODE-2024-title17-chap1-sec107", **kwargs
    )


async def read_law(make_client, **kwargs):
    return await tools.get_public_law(make_client(plaw_handler), congress=118, law_number=31, **kwargs)


@pytest.mark.parametrize("read", [read_section, read_section_by_id, read_law])
class TestBothTextTools:
    @pytest.mark.parametrize("max_chars", [1, 30, 150, 400])
    async def test_a_walk_by_next_start_char_reproduces_the_payload(self, make_client, read, max_chars):
        whole = (await read(make_client, max_chars=1_000_000))["text"]
        assert whole["truncated"] is False
        pieces, start, calls = [], 0, 0
        while start is not None:
            out = await read(make_client, start_char=start, max_chars=max_chars)
            assert out["outcome"] == "success"
            text = out["text"]
            assert text["start_char"] == start
            assert 1 <= text["returned_chars"] == len(text["content"]) <= max_chars
            if text["truncated"]:
                end = start + text["returned_chars"]
                assert text["next_start_char"] == end
                total = text["total_chars"]
                assert text["banner"] == (
                    f"[WINDOW chars {start:,}–{end - 1:,} of {total:,} — truncated; continue with start_char={end}]"
                )
                assert text["message"].startswith(f"Payload is {total} chars; returned chars {start}-{end - 1}.")
                assert f"Continue with start_char={end}." in text["message"]
            pieces.append(text["content"])
            start = text["next_start_char"]
            calls += 1
            assert calls <= whole["total_chars"] + 1
        assert "".join(pieces) == whole["content"]

    async def test_a_window_holding_a_paragraph_break_ends_just_after_it(self, make_client, read):
        whole = (await read(make_client, max_chars=1_000_000))["text"]["content"]
        start = whole.index("Paragraph 1 ")
        text = (await read(make_client, start_char=start, max_chars=200))["text"]
        assert text["truncated"] is True
        assert text["returned_chars"] < 200
        assert text["content"].endswith("\n\n")
        assert whole[text["next_start_char"] :].startswith("Paragraph ")

    async def test_a_window_inside_the_long_paragraph_ends_on_a_word(self, make_client, read):
        whole = (await read(make_client, max_chars=1_000_000))["text"]["content"]
        start = whole.index("A long paragraph: ")
        text = (await read(make_client, start_char=start, max_chars=100))["text"]
        assert "\n\n" not in text["content"]
        assert text["content"].endswith(" ") and text["returned_chars"] <= 100
        rest = whole[text["next_start_char"] :]
        assert rest[0].isalpha() and whole[text["next_start_char"] - 1] == " "

    async def test_the_last_window_is_untruncated_and_carries_no_markers(self, make_client, read):
        whole = (await read(make_client, max_chars=1_000_000))["text"]
        start = whole["total_chars"] - 25
        text = (await read(make_client, start_char=start, max_chars=1000))["text"]
        assert text["truncated"] is False and text["next_start_char"] is None
        assert text["content"] == whole["content"][start:]
        assert "banner" not in text and "message" not in text

    async def test_find_offsets_are_unchanged_by_the_cut(self, make_client, read):
        small = await read(make_client, max_chars=30, find="timely and accurate")
        full = await read(make_client, max_chars=1_000_000, find="timely and accurate")
        assert small["find"] == full["find"]
        assert small["find"]["total_occurrences"] == 12


class TestStructureCoordinates:
    async def test_a_structure_field_read_by_its_coordinates_equals_the_slice_of_a_full_read(self, make_client):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/search":
                if "collection:PLAW" in fx.request_body(request)["query"]:
                    return fx.json_response(fx.search_response([], count=0))
                return fx.json_response(fx.search_response([fx.usc_hit()]))
            return httpx.Response(200, text=fx.SECTION_HTML_WITH_FIELDS)

        full = await tools.get_us_code_section(make_client(handler), citation="17 U.S.C. 107", max_chars=1_000_000)
        content = full["text"]["content"]
        fields = full["structure"]["fields"]
        assert fields
        for field in fields:
            start, end = field["start_char"], field["end_char"]
            out = await tools.get_us_code_section(
                make_client(handler), citation="17 U.S.C. 107", start_char=start, max_chars=end - start
            )
            assert out["text"]["content"] == content[start:end], field["field"]
            assert out["text"]["returned_chars"] == end - start
