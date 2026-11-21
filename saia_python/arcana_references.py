"""Parse GWDG ARCANA reference blocks from chat-completion content.

When a request is routed through GWDG SAIA's ARCANA (RAG) gateway, the
gateway appends a verbose ``References:`` block to the assistant's reply —
one ``[RREFn] <filename> (<distance>)`` line per retrieved chunk (a PDF
chunk adds its page: ``p.21,y:413``), followed by that chunk's body. This module turns that GWDG-specific wire
shape into structured data, leaving *rendering* and *filename
interpretation* to the caller: a filename's meaning depends on your own
corpus, and presentation depends on your own UI, so neither belongs here.

The module is **pure and dependency-free** (no HTTP, no I/O), so it is safe
to import into any environment — including an async server — without
pulling in a transport layer.

The split has three parts: the model's ``answer``, a ``separator`` (the
horizontal rule GWDG puts under the last line) and the ``references_block``
from the marker on; together they give back the content. For a stream,
:class:`ReferencesSplitter` does the same on the text deltas as they
arrive; ``iter_text(stream, references=True)`` wraps it. The answer cites
chunks inline with anchors such as ``[RREF2]``, which
:class:`ParsedReferences` resolves and checks (``anchors``, ``by_number``,
``dangling``).

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
    "ReferencesSplitter",
    "parse_arcana_references",
    "parse_reference_entries",
    "split_compound_anchors",
    "is_arcana_event",
    "REFERENCES_MARKER_RE",
    "REFERENCES_ENTRY_RE",
    "REFERENCES_ANCHOR_RE",
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
# A PDF source adds the chunk's page and its vertical position on that page
# (seen 2026-11-21), and a file name may contain spaces::
#     [RREF2] annual report.pdf p.21,y:413 (0.688)
REFERENCES_ENTRY_RE = re.compile(
    r"^\[RREF(?P<n>\d+)\][ \t]+(?P<filename>\S.*?\.\w{1,8})"
    r"(?:[ \t]+p\.(?P<page>\d+)(?:,y:(?P<y>\d+))?)?"
    r"[ \t]+\((?P<distance>[\d.]+)\)[ \t]*$",
    re.MULTILINE,
)

# An inline citation in the answer: one chunk (``[RREF2]``) or several in one
# bracket (``[RREF2, RREF5]``), as models write now and then. Group 1 holds
# the ``RREF`` tokens.
REFERENCES_ANCHOR_RE = re.compile(r"\[(RREF\d+(?:[,;\s]+RREF\d+)*)\]")


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
        page: For a PDF source, the page the chunk is on, else ``None``.
        y: For a PDF source, the chunk's vertical position on that page
            (GWDG's ``y:`` value), else ``None``.
    """

    n: int
    filename: str
    distance: float | None = None
    page: int | None = None
    y: int | None = None


@dataclass(frozen=True)
class ParsedReferences:
    """The result of splitting assistant content around the References block.

    Besides its fields it offers read-only properties computed from them:
    :attr:`answer` and :attr:`separator`, which split the prose, and
    :attr:`anchors`, :attr:`by_number` and :attr:`dangling`, which resolve
    and check the inline citations.

    Attributes:
        matched: Whether a ``References:`` block was found.
        prose: The assistant content with the References block removed (the
            substring before the marker). Equal to the full input when
            ``matched`` is ``False``. Note this still includes any trailing
            horizontal-rule line the gateway inserts before ``References:``;
            :attr:`answer` leaves it out.
        references: Parsed, de-duplicated citations, ordered by ``n``.
        references_block: The raw References block (marker to end of input),
            or ``""`` when ``matched`` is ``False``.
    """

    matched: bool
    prose: str
    references: list[ArcanaReference] = field(default_factory=list)
    references_block: str = ""

    @property
    def answer(self) -> str:
        """The prose without the :attr:`separator` before the block.

        GWDG puts a horizontal rule right under the last line of the answer
        (seen 2026-11-21). Markdown renders a rule under a line as a heading
        underline, so the answer's last line would show as a heading.
        ``answer`` ends with the last line instead; ``answer + separator``
        gives back :attr:`prose`. Without a block it is the prose itself.
        """
        if not self.matched:
            return self.prose
        return self.prose[: _separator_start(self.prose, len(self.prose))]

    @property
    def separator(self) -> str:
        """The part of :attr:`prose` that :attr:`answer` leaves out: the rule
        and any blank lines before the block, from the newline that ends the
        last line of the answer. ``""`` without a block."""
        return self.prose[len(self.answer) :]

    @property
    def anchors(self) -> list[int]:
        """The ``RREF`` numbers the prose cites, each once, in order of first
        appearance. A compound anchor (``[RREF2, RREF5]``) adds each number."""
        numbers: dict[int, None] = {}
        for match in REFERENCES_ANCHOR_RE.finditer(self.prose):
            for digits in re.findall(r"\d+", match.group(1)):
                numbers.setdefault(int(digits), None)
        return list(numbers)

    @property
    def by_number(self) -> dict[int, ArcanaReference]:
        """Every ``RREF`` number the References block lists, mapped to its
        own entry.

        :attr:`references` keeps one entry per file, the one with the lowest
        number. Here each number keeps its own distance and, for a PDF, its
        own page: ``[RREF1]`` and ``[RREF4]`` may be two pages of one file.
        The file's entry in :attr:`references` has the same ``filename``.
        """
        entries = parse_reference_entries(self.references_block, dedupe=False)
        if not entries:
            return {ref.n: ref for ref in self.references}
        return {entry.n: entry for entry in entries}

    @property
    def dangling(self) -> list[int]:
        """The numbers the prose cites that the References block does not
        list, e.g. ``[RREF7]`` when five chunks were retrieved: a cheap hint
        at a made-up citation."""
        listed = self.by_number
        return [n for n in self.anchors if n not in listed]


def parse_reference_entries(
    block: str, *, dedupe: bool = True
) -> list[ArcanaReference]:
    """Parse ``[RREFn] <filename> (<distance>)`` entries from ``block``.

    A PDF entry also carries the chunk's page and position
    (``[RREFn] <filename> p.<page>,y:<y> (<distance>)``).

    Args:
        block: Text containing one or more reference entry lines (typically
            the References block, but any text works — non-matching lines
            are ignored).
        dedupe: When ``True`` (default), collapse repeated filenames to a
            single entry keeping the lowest ``n`` (the gateway lists a
            filename once per retrieved chunk, so one document can appear
            several times, for a PDF once per page); the result is ordered
            by ``n``. When ``False``, every matching entry is returned in
            document order.

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
        page, y = m.group("page"), m.group("y")
        entries.append(
            ArcanaReference(
                n=n,
                filename=m.group("filename"),
                distance=distance,
                page=int(page) if page else None,
                y=int(y) if y else None,
            )
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


def _single_anchors(match: re.Match[str]) -> str:
    return " ".join(f"[{token}]" for token in re.findall(r"RREF\d+", match.group(1)))


def split_compound_anchors(text: str) -> str:
    """Rewrite each compound anchor as single ones.

    ``[RREF2, RREF5]`` becomes ``[RREF2] [RREF5]``, so every anchor can be
    linked on its own. Single anchors and other brackets stay as they are.
    It is safe on the pieces :class:`ReferencesSplitter` returns, since that
    never splits an anchor.
    """
    return REFERENCES_ANCHOR_RE.sub(_single_anchors, text)


# For ReferencesSplitter: text from a "[" that could still grow into an anchor,
# or into the first entry that completes the marker.
_ANCHOR_PREFIX_RE = re.compile(r"\[(?:RREF\d+[,;\s]+)*(?:RREF\d*|RRE|RR|R)?")
_ENTRY_PREFIX_RE = re.compile(r"\[(?:RREF\d*|RRE|RR|R)?")
_MARKER_HEAD = "\nReferences:"

# A Markdown horizontal rule: three or more of one of -, * or _, spaces allowed;
# and what an unfinished last line may still grow into.
_RULE_RE = re.compile(r"[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*")
_RULE_START_RE = re.compile(r"[ \t]*(?:([-*_])(?:[ \t]*\1)*)?[ \t]*")


def _separator_start(text: str, end: int, *, unfinished: bool = False) -> int:
    """Where the run of blank lines and rules that ends at ``end`` begins.

    The run starts at the newline that ends the last other line; ``end`` if
    there is none. With ``unfinished``, the line ending at ``end`` may still
    grow, so a few rule characters count too.
    """
    start = line_end = end
    while (newline := text.rfind("\n", 0, line_end)) != -1:
        line = text[newline + 1 : line_end]
        rule = _RULE_START_RE if unfinished and line_end == end else _RULE_RE
        if line.strip() and not rule.fullmatch(line):
            break
        start = line_end = newline
    return start


def _could_be_marker(text: str, start: int) -> bool:
    """Whether ``text[start:]`` could still grow into the References marker."""
    rest = text[start:]
    if len(rest) <= len(_MARKER_HEAD):
        return _MARKER_HEAD.startswith(rest)
    if not rest.startswith(_MARKER_HEAD):
        return False
    tail = rest[len(_MARKER_HEAD) :]
    entry = len(tail) - len(tail.lstrip())
    if entry == len(tail):
        return True  # whitespace so far; the first entry may follow
    return "\n" in tail[:entry] and _ENTRY_PREFIX_RE.fullmatch(tail, entry) is not None


def _hold_back_from(text: str, strip_separator: bool) -> int:
    """Where the end of ``text`` begins that must wait for the next delta,
    since it could still become the marker or an anchor, or with
    ``strip_separator`` the separator before the marker; ``len(text)`` if
    nothing has to wait."""
    anchor = text.rfind("[")
    if anchor == -1 or not _ANCHOR_PREFIX_RE.fullmatch(text, anchor):
        anchor = len(text)
    marker = len(text)
    newline = text.find("\n")
    while newline != -1 and newline < anchor:
        if _could_be_marker(text, newline):
            marker = newline
            break
        newline = text.find("\n", newline + 1)
    if anchor < marker:
        return anchor  # an open anchor continues the answer: no separator here
    if strip_separator:
        return _separator_start(text, marker, unfinished=marker == len(text))
    return marker


class ReferencesSplitter:
    """Split the References block off an ARCANA answer while it streams.

    Feed it the answer's text deltas in order. :meth:`feed` returns the part
    that is safe to show now. At the end, :meth:`flush` returns what it
    still held back and sets :attr:`result` to the :class:`ParsedReferences`
    that :func:`parse_arcana_references` gives for the complete answer.

    Text is held back only while it could still turn out to be the start of
    the ``References:`` marker or of an anchor. So the answer otherwise
    streams without delay, and no anchor (``[RREF2]``, ``[RREF2, RREF5]``)
    is split between two pieces: each piece can be rendered on its own, e.g.
    with :data:`REFERENCES_ANCHOR_RE` or :func:`split_compound_anchors`.
    Everything from the marker on is collected, not returned. With
    ``strip_separator`` (the default) the pieces also leave out the
    :attr:`~ParsedReferences.separator`, the rule GWDG puts before the
    block, and join to :attr:`~ParsedReferences.answer`; with ``False`` they
    join to :attr:`~ParsedReferences.prose`. :attr:`result` has all parts
    either way.

    Pure, like the rest of the module: a proxy that rewrites raw SSE lines
    can feed it each chunk's ``delta.content``.
    :func:`~saia_python.iter_text` uses it with ``references=True``.

    Example::

        splitter = ReferencesSplitter()
        for delta in deltas:
            print(splitter.feed(delta), end="")
        print(splitter.flush(), end="")
        for ref in splitter.result.references:
            print(ref.n, ref.filename)

    Attributes:
        result: The parsed answer once :meth:`flush` ran, else ``None``.
    """

    def __init__(self, *, strip_separator: bool = True) -> None:
        self.result: ParsedReferences | None = None
        self._strip = strip_separator
        self._pending = ""  # received, not returned yet
        self._prose: list[str] = []  # everything before the marker
        self._block: str | None = None  # from the marker on, once found

    def feed(self, delta: str) -> str:
        """Take the next text delta.

        Returns:
            The part of the answer that is safe to show now: ``""`` while
            text is held back, and once the References block has begun.
        """
        if self._block is not None:
            self._block += delta
            return ""
        self._pending += delta
        match = REFERENCES_MARKER_RE.search(self._pending)
        if match is not None:
            before = self._pending[: match.start()]
            self._block = self._pending[match.start() :]
            self._pending = ""
            self._prose.append(before)
            if self._strip:  # the separator waited in the pending text
                return before[: _separator_start(before, len(before))]
            return before
        hold = _hold_back_from(self._pending, self._strip)
        out, self._pending = self._pending[:hold], self._pending[hold:]
        self._prose.append(out)
        return out

    def flush(self) -> str:
        """End the answer: return the text still held back, set :attr:`result`."""
        out, self._pending = self._pending, ""
        self._prose.append(out)
        prose = "".join(self._prose)
        if self._block is None:
            self.result = ParsedReferences(matched=False, prose=prose)
        else:
            self.result = ParsedReferences(
                matched=True,
                prose=prose,
                references=parse_reference_entries(self._block),
                references_block=self._block,
            )
        return out
