"""Tests for saia_python.arcana_references — GWDG ARCANA reference parsing."""

from saia_python import (
    ArcanaReference,
    is_arcana_event,
    parse_arcana_references,
    parse_reference_entries,
)

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
