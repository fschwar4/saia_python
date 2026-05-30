# ARCANA reference parsing in the core (transport-agnostic)

- Status: Accepted
- Date: 2026-05-30
- Deciders: saia-python maintainers

## Context and Problem Statement

When a chat request is routed through GWDG SAIA's ARCANA (RAG) gateway, the
gateway appends a verbose `References:` block to the assistant content — one
`[RREFn] <filename>.md (<distance>)` line per retrieved chunk, followed by the
chunk body. Consumers that want clean citations must parse that GWDG-specific
wire shape.

Two kinds of consumer need it: `saia-python`'s own users (who call
`arcana.chat()` and get the raw dump back), and external OpenAI-compatible
services in front of SAIA — e.g. the `avor-adapter` that backs a LibreChat
deployment, which already carries ~750 lines of reference handling. Each was
re-deriving the same GWDG regex independently. Where should that knowledge live?

## Decision Drivers

- The GWDG reference format is a **moving target** (it has drifted across
  gateway/model versions); one versioned source of truth beats N copies.
- A key consumer is an **async** server. The parser must therefore not require
  the synchronous `requests`-based client, or even any HTTP transport.
- GWDG *structure* (the `[RREFn]` grammar) is generic; *filename meaning* (which
  corpus, which URL) and *rendering* (which UI) are application concerns that
  must stay out of the core.

## Considered Options

- **Pure, transport-agnostic module in the core** — `arcana_references.py`,
  no I/O, exported at top level (sibling to `rate_limits.py` / `responses.py`).
- **A method on `ArcanaService`** — couples parsing to a client instance and,
  by association, to the HTTP layer.
- **Leave it in each consumer** — status quo; every consumer re-derives it.

## Decision Outcome

Chosen option: **a pure `arcana_references` module**. It exposes
`parse_arcana_references()`, `parse_reference_entries()`, `is_arcana_event()`,
the `ArcanaReference` / `ParsedReferences` dataclasses, and the marker
regex/length constant for streaming consumers. It imports only `re` and
`dataclasses` — no `requests`, no `httpx`, no I/O — so any consumer (sync or
async) can import it without a transport.

The module parses **structure only**: it returns `(n, filename, distance)`. It
deliberately does **not** interpret filenames or render markdown — those remain
the caller's responsibility.

### Consequences

- Good — the GWDG wire quirks live in one place; a format drift is fixed once
  and every consumer picks it up via a version bump.
- Good — importable into an async event loop with zero transport baggage, so a
  forwarding adapter can drop its duplicated regex without adopting the SDK's
  HTTP client.
- Good — keeps a clean boundary: structure in the core, corpus/rendering in the
  consumer.
- Trade-off — the core now owns a GWDG *output-format* contract that can change
  upstream; mitigated by it being one tested module rather than scattered copies.

### Confirmation

`tests/test_arcana_references.py` covers prose/reference splitting, de-dup,
distance parsing, and the `arcana.event` filter. The `avor-adapter` frontend
consumes these functions in place of its former private regexes.

## More Information

This is the first piece of a broader "headless core + transport adapters"
direction. A complementary future layer — an `AsyncSAIAClient` on `httpx`
(an optional `[async]` extra, à la ADR-0001) — would let async consumers use
the *client* surface too; it is independent of this pure module and not
required by it.
