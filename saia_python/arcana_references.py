"""Parse GWDG ARCANA reference blocks from chat-completion content.

When a request is routed through GWDG SAIA's ARCANA (RAG) gateway, the
gateway appends a verbose ``References:`` block to the assistant's reply —
one ``[RREFn] <filename>.md (<distance>)`` line per retrieved chunk,
followed by that chunk's body. This module turns that GWDG-specific wire
shape into structured data, leaving *rendering* and *filename
interpretation* to the caller: a filename's meaning depends on your own
corpus, and presentation depends on your own UI, so neither belongs here.

The module is **pure and dependency-free** (no HTTP, no I/O), so it is safe
to import into any environment — including an async server — without
pulling in a transport layer.

Example::

    from saia_python import parse_arcana_references

    parsed = parse_arcana_references(message_content)
    if parsed.matched:
        print(parsed.prose)            # the answer, References block removed
        for ref in parsed.references:  # structured citations
            print(ref.n, ref.filename, ref.distance)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "ArcanaReference",
    "ParsedReferences",
    "parse_arcana_references",
    "parse_reference_entries",
    "is_arcana_event",
    "REFERENCES_MARKER_RE",
    "REFERENCES_ENTRY_RE",
    "REFERENCES_MARKER_MAX_LEN",
]


# The gateway appends the dump as a paragraph-isolated ``References:`` line
# immediately followed by the first ``[RREFn]`` entry. We anchor on the
# stable suffix ``\nReferences:\n+\s*[RREF<digit>]`` and stay permissive on
# whatever precedes it (a horizontal rule, blank lines, both, or neither).
REFERENCES_MARKER_RE = re.compile(r"\nReferences:\s*\n+\s*\[RREF\d+\]")

# Longest plausible wire form of the marker (e.g. ``\nReferences:\n\n\n[RREF999]``).
# Streaming consumers use this to size a lag buffer so the marker is still
# detected when it straddles SSE chunk boundaries.
REFERENCES_MARKER_MAX_LEN = 40

# One per-entry header line, e.g.::
#     [RREF1] onkopedia_dlbcl_5-1-1_immunchemotherapie__ID0E.md (0.319)
REFERENCES_ENTRY_RE = re.compile(
    r"^\[RREF(?P<n>\d+)\]\s+(?P<filename>\S+\.md)\s+\((?P<distance>[\d.]+)\)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ArcanaReference:
    """A single parsed ARCANA citation.

    Attributes:
        n: The ``RREFn`` reference number emitted by the gateway.
        filename: The retrieved chunk's source filename (e.g.
            ``"onkopedia_....md"``). Deriving a label or URL from it is the
            caller's responsibility — it depends on your corpus.
        distance: The retrieval distance score the gateway reports in
            parentheses, or ``None`` if it could not be parsed as a float.
    """

    n: int
    filename: str
    distance: float | None = None


@dataclass(frozen=True)
class ParsedReferences:
    """The result of splitting assistant content around the References block.

    Attributes:
        matched: Whether a ``References:`` block was found.
        prose: The assistant content with the References block removed (the
            substring before the marker). Equal to the full input when
            ``matched`` is ``False``. Note this still includes any trailing
            horizontal-rule line the gateway inserts before ``References:`` —
            stripping that is a rendering concern left to the caller.
        references: Parsed, de-duplicated citations, ordered by ``n``.
        references_block: The raw References block (marker to end of input),
            or ``""`` when ``matched`` is ``False``.
    """

    matched: bool
    prose: str
    references: list[ArcanaReference] = field(default_factory=list)
    references_block: str = ""


def parse_reference_entries(
    block: str, *, dedupe: bool = True
) -> list[ArcanaReference]:
    """Parse ``[RREFn] <filename>.md (<distance>)`` entries from ``block``.

    Args:
        block: Text containing one or more reference entry lines (typically
            the References block, but any text works — non-matching lines
            are ignored).
        dedupe: When ``True`` (default), collapse repeated filenames to a
            single entry keeping the lowest ``n`` (the gateway lists a
            filename once per retrieved chunk, so one document can appear
            several times); the result is ordered by ``n``. When ``False``,
            every matching entry is returned in document order.

    Returns:
        A list of :class:`ArcanaReference`.
    """
    entries: list[ArcanaReference] = []
    for m in REFERENCES_ENTRY_RE.finditer(block):
        try:
            n = int(m.group("n"))
        except (TypeError, ValueError):
            continue
        try:
            distance: float | None = float(m.group("distance"))
        except (TypeError, ValueError):
            distance = None
        entries.append(
            ArcanaReference(n=n, filename=m.group("filename"), distance=distance)
        )

    if not dedupe:
        return entries

    best: dict[str, ArcanaReference] = {}
    for ref in entries:
        existing = best.get(ref.filename)
        if existing is None or ref.n < existing.n:
            best[ref.filename] = ref
    return sorted(best.values(), key=lambda r: r.n)


def parse_arcana_references(content: str) -> ParsedReferences:
    """Split assistant ``content`` into prose and structured references.

    Locates the GWDG ``References:`` marker; everything before it is prose,
    everything from it onward is parsed into :class:`ArcanaReference` entries.
    Conservative: if no marker is present, returns the content unchanged as
    ``prose`` with ``matched=False`` and no references.

    Args:
        content: The assistant message content from an ARCANA-routed reply.

    Returns:
        A :class:`ParsedReferences`.
    """
    m = REFERENCES_MARKER_RE.search(content)
    if m is None:
        return ParsedReferences(matched=False, prose=content)
    idx = m.start()
    block = content[idx:]
    return ParsedReferences(
        matched=True,
        prose=content[:idx],
        references=parse_reference_entries(block),
        references_block=block,
    )


def is_arcana_event(tool_call: dict) -> bool:
    """Return ``True`` if ``tool_call`` is a GWDG ``arcana.event`` beacon.

    GWDG ARCANA streams retrieval-lifecycle markers (``accessing`` /
    ``done``) as ``tool_calls`` whose function name starts with
    ``arcana.event``. These are status signals, not real citations (the
    actual references are baked into the message content as ``[RREFn]``
    markers), so consumers typically filter them out before rendering.
    """
    fn = tool_call.get("function") or {}
    return (fn.get("name") or "").startswith("arcana.event")
