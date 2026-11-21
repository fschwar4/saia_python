"""Tests for saia_python.arcana_references — GWDG ARCANA reference parsing."""

from dataclasses import fields

import pytest

from saia_python import (
    ArcanaReference,
    ParsedReferences,
    ReferencesSplitter,
    is_arcana_event,
    parse_arcana_references,
    parse_reference_entries,
    split_compound_anchors,
)
from saia_python.arcana_references import REFERENCES_ANCHOR_RE

# A realistic ARCANA-routed reply: answer prose, the GWDG horizontal-rule
# line, the ``References:`` marker, then one ``[RREFn]`` entry per chunk
# (each followed by chunk body, which the parser ignores).
_SAMPLE = (
    "Die Immunchemotherapie ist Standard [RREF1].\n\n"
    "Diese Rechercheunterstützung ersetzt keinen ärztlichen Rat.\n"
    "-----------------------------------------\n"
    "References:\n\n"
    "[RREF1] onkopedia_dlbcl_5-1-1_immunchemotherapie__ID0E.md (0.319)\n"
    "## Immunchemotherapie\nChunk body text...\n"
    "[RREF2] awmf-leitlinie_dlbcl-kurzversion_3-2_diagnostik.md (0.452)\n"
    "More chunk body...\n"
)


def test_parse_splits_prose_and_references():
    parsed = parse_arcana_references(_SAMPLE)
    assert parsed.matched is True
    # Prose keeps the answer + the HR line, but NOT the References block.
    assert "Diese Rechercheunterstützung" in parsed.prose
    assert "References:" not in parsed.prose
    assert "[RREF1] onkopedia" not in parsed.prose
    # Two distinct sources parsed, ordered by n, with distances.
    assert [r.n for r in parsed.references] == [1, 2]
    assert parsed.references[0].filename.startswith("onkopedia_dlbcl")
    assert parsed.references[0].distance == 0.319
    assert parsed.references[1].distance == 0.452


def test_no_marker_returns_content_unchanged():
    parsed = parse_arcana_references("Just an answer, no retrieval.")
    assert parsed.matched is False
    assert parsed.prose == "Just an answer, no retrieval."
    assert parsed.references == []
    assert parsed.references_block == ""


def test_parse_reference_entries_dedupes_by_filename_lowest_n():
    block = (
        "[RREF1] a.md (0.1)\n"
        "[RREF2] b.md (0.2)\n"
        "[RREF3] a.md (0.3)\n"  # same file as RREF1, higher n → dropped
    )
    refs = parse_reference_entries(block)
    assert [(r.n, r.filename) for r in refs] == [(1, "a.md"), (2, "b.md")]


def test_parse_reference_entries_no_dedupe_keeps_all_in_order():
    block = "[RREF1] a.md (0.1)\n[RREF3] a.md (0.3)\n[RREF2] b.md (0.2)\n"
    refs = parse_reference_entries(block, dedupe=False)
    assert [(r.n, r.filename) for r in refs] == [
        (1, "a.md"),
        (3, "a.md"),
        (2, "b.md"),
    ]


def test_unparseable_distance_yields_none():
    # `[\d.]+` matches "1.2.3" so the line parses, but float() rejects it.
    refs = parse_reference_entries("[RREF1] a.md (1.2.3)\n")
    assert len(refs) == 1
    assert refs[0].distance is None


def test_is_arcana_event():
    assert is_arcana_event({"function": {"name": "arcana.event.accessing"}}) is True
    assert is_arcana_event({"function": {"name": "get_weather"}}) is False
    assert is_arcana_event({}) is False
    assert is_arcana_event({"function": {}}) is False


def test_arcana_reference_is_hashable_frozen():
    # frozen dataclass → usable in sets / as dict keys
    r = ArcanaReference(n=1, filename="a.md", distance=0.1)
    assert {r, r} == {r}


# --- anchors -----------------------------------------------------------------------

# A generic ARCANA answer: four anchors, one of them compound and one the block
# does not list. RREF3 and RREF4 name files that RREF2 and RREF1 already name.
_ANSWER = (
    "The first option is preferred [RREF1]. A second source agrees [RREF4], "
    "and the details come from two sections [RREF2, RREF5]. One sentence "
    "cites a chunk that was never retrieved [RREF7].\n\n"
    "-----\n"
    "References:\n\n"
    "[RREF1] doc-a.md (0.21)\n## Part one\nChunk body...\n"
    "[RREF2] doc-b.md (0.30)\nChunk body...\n"
    "[RREF3] doc-b.md (0.31)\nChunk body...\n"
    "[RREF4] doc-a.md (0.33)\nChunk body...\n"
    "[RREF5] doc-c.md (0.41)\nChunk body...\n"
)


def test_the_anchor_pattern_matches_single_and_compound_anchors():
    found = [m.group(0) for m in REFERENCES_ANCHOR_RE.finditer(_ANSWER)]
    assert found[:4] == ["[RREF1]", "[RREF4]", "[RREF2, RREF5]", "[RREF7]"]


def test_anchors_lists_each_cited_number_once_in_order():
    assert parse_arcana_references(_ANSWER).anchors == [1, 4, 2, 5, 7]
    repeated = ParsedReferences(matched=False, prose="a [RREF2] b [RREF1] c [RREF2]")
    assert repeated.anchors == [2, 1]


def test_by_number_maps_every_number_to_its_own_entry():
    parsed = parse_arcana_references(_ANSWER)
    assert [ref.n for ref in parsed.references] == [1, 2, 5]  # one per file
    assert {n: ref.filename for n, ref in parsed.by_number.items()} == {
        1: "doc-a.md",
        2: "doc-b.md",
        3: "doc-b.md",
        4: "doc-a.md",
        5: "doc-c.md",
    }
    assert parsed.by_number[4] == ArcanaReference(4, "doc-a.md", 0.33)


def test_dangling_lists_cited_numbers_the_block_does_not_list():
    assert parse_arcana_references(_ANSWER).dangling == [7]
    assert parse_arcana_references("No retrieval here [RREF1].").dangling == [1]


# The shape GWDG sends for PDF sources (seen 2026-11-21): the rule right under
# the last line, and entries with the page and the position on it.
_PDF_ANSWER = (
    "The report recommends option B [RREF1], see also [RREF2].\n"
    "-----------------------------------------\n"
    "References:\n\n"
    "[RREF1] annual report.pdf p.21,y:413 (0.688)\n## Results\nChunk body...\n"
    "[RREF2] annual report.pdf p.24,y:728 (0.716)\nChunk body...\n"
)


def test_pdf_entries_keep_their_page_and_position():
    parsed = parse_arcana_references(_PDF_ANSWER)
    first = ArcanaReference(1, "annual report.pdf", 0.688, page=21, y=413)
    assert parsed.references == [first]  # one entry per file
    assert parsed.by_number == {
        1: first,
        2: ArcanaReference(2, "annual report.pdf", 0.716, page=24, y=728),
    }
    assert parsed.dangling == []


def test_the_entry_pattern_takes_any_file_type_and_spaces():
    refs = parse_reference_entries(
        "[RREF1] v1.2 final notes.pdf p.3 (0.5)\n"
        "[RREF2] slides.pptx (0.6)\n"
        "[RREF3] a.md (0.1)\n"
    )
    assert [(r.filename, r.page, r.y) for r in refs] == [
        ("v1.2 final notes.pdf", 3, None),
        ("slides.pptx", None, None),
        ("a.md", None, None),
    ]
    assert refs[2] == ArcanaReference(3, "a.md", 0.1)  # markdown as before


# --- answer and separator ---------------------------------------------------------


def test_answer_leaves_out_the_separator_before_the_block():
    gwdg = parse_arcana_references(_PDF_ANSWER)
    assert gwdg.answer == "The report recommends option B [RREF1], see also [RREF2]."
    assert gwdg.separator == "\n-----------------------------------------"
    assert gwdg.answer + gwdg.separator == gwdg.prose
    assert parse_arcana_references(_ANSWER).separator == "\n\n-----"
    bare = parse_arcana_references("Answer.\n\nReferences:\n\n[RREF1] a.md (0.1)\n")
    assert (bare.answer, bare.separator) == ("Answer.", "\n")


def test_a_rule_inside_the_answer_stays_in_it():
    content = "One.\n---\nTwo.\n-----\nReferences:\n\n[RREF1] a.md (0.1)\n"
    assert parse_arcana_references(content).answer == "One.\n---\nTwo."


def test_without_a_block_the_answer_is_the_prose():
    parsed = parse_arcana_references("Answer.\n-----\n")
    assert (parsed.answer, parsed.separator) == ("Answer.\n-----\n", "")


def test_by_number_falls_back_to_the_references_without_a_block():
    ref = ArcanaReference(3, "doc-c.md")
    parsed = ParsedReferences(matched=True, prose="x [RREF3]", references=[ref])
    assert parsed.by_number == {3: ref}
    assert parsed.dangling == []


def test_the_new_properties_leave_the_fields_unchanged():
    # ParsedReferences is an API contract: construction, equality and
    # dataclasses.asdict() see the same four fields as before.
    assert [f.name for f in fields(ParsedReferences)] == [
        "matched",
        "prose",
        "references",
        "references_block",
    ]


def test_split_compound_anchors():
    assert (
        split_compound_anchors("see [RREF2, RREF5] and [RREF1]")
        == "see [RREF2] [RREF5] and [RREF1]"
    )
    assert (
        split_compound_anchors("[RREF2,RREF3;\u202fRREF4]") == "[RREF2] [RREF3] [RREF4]"
    )
    untouched = "[note] [RREF] [rref1] [RREF1 and more]"
    assert split_compound_anchors(untouched) == untouched


# --- ReferencesSplitter ------------------------------------------------------------


def _split(deltas, *, strip_separator=True):
    """Feed ``deltas`` to a fresh splitter: (the non-empty pieces, the result)."""
    splitter = ReferencesSplitter(strip_separator=strip_separator)
    pieces = [splitter.feed(delta) for delta in deltas]
    pieces.append(splitter.flush())
    return [piece for piece in pieces if piece], splitter.result


@pytest.mark.parametrize("content", ["_ANSWER", "_PDF_ANSWER"])
@pytest.mark.parametrize("strip_separator", [True, False])
@pytest.mark.parametrize("size", [1, 2, 3, 5, 8, 13, 1000])
def test_splitter_gives_what_the_parser_gives_for_any_chunk_size(
    size, strip_separator, content
):
    content = globals()[content]
    deltas = [content[i : i + size] for i in range(0, len(content), size)]
    pieces, result = _split(deltas, strip_separator=strip_separator)
    expected = parse_arcana_references(content)
    assert result == expected
    assert "".join(pieces) == (expected.answer if strip_separator else expected.prose)


@pytest.mark.parametrize("content", ["_ANSWER", "_PDF_ANSWER"])
@pytest.mark.parametrize("strip_separator", [True, False])
def test_splitter_finds_the_marker_wherever_the_stream_splits(strip_separator, content):
    content = globals()[content]
    expected = parse_arcana_references(content)
    shown = expected.answer if strip_separator else expected.prose
    for cut in range(1, len(content)):
        deltas = [content[:cut], content[cut:]]
        pieces, result = _split(deltas, strip_separator=strip_separator)
        assert result == expected, cut
        assert "".join(pieces) == shown, cut


def test_splitter_strips_a_separator_that_arrives_in_pieces():
    deltas = ["Answer.", "\n", "-----", "\n", "References:\n\n[RREF1] a.md (0.1)\n"]
    pieces, result = _split(deltas)
    assert pieces == ["Answer."]
    assert result.separator == "\n-----"


def test_splitter_releases_a_rule_or_list_the_answer_goes_on_after():
    deltas = ["Intro\n", "---", "\nMore", "\n- ", "item"]
    pieces, result = _split(deltas)
    assert "".join(pieces) == "Intro\n---\nMore\n- item" == result.answer


def test_splitter_never_splits_an_anchor():
    pieces, _ = _split(_ANSWER)  # one character at a time
    for anchor in ("[RREF1]", "[RREF4]", "[RREF2, RREF5]", "[RREF7]"):
        assert any(anchor in piece for piece in pieces), anchor


def test_splitter_holds_back_only_what_could_still_be_the_marker_or_an_anchor():
    splitter = ReferencesSplitter()
    assert [splitter.feed(c) for c in "Plain text."] == list("Plain text.")
    assert splitter.feed("\n") == ""  # could start the marker
    assert splitter.feed("Next") == "\nNext"
    assert splitter.feed("\nRef") == ""  # still matches "\nReferences:"
    assert splitter.feed("und") == "\nRefund"
    assert splitter.feed(" [RR") == " "  # could become an anchor
    assert splitter.feed("EF3]") == "[RREF3]"
    assert splitter.feed(" [x") == " [x"  # cannot
    assert splitter.feed("\nReferences: see below") == "\nReferences: see below"
    assert splitter.flush() == ""
    assert splitter.result.matched is False


def test_splitter_returns_an_unfinished_anchor_at_the_end():
    pieces, result = _split(["see [RRE", "F"])
    assert pieces == ["see ", "[RREF"]
    assert result.prose == "see [RREF"
