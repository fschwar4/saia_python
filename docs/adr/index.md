# Architecture Decision Records

This section captures the significant architectural decisions for
`saia-python` as **Architecture Decision Records (ADRs)**, written in the
[MADR](https://adr.github.io/madr/) (Markdown ADR) format.

An ADR records a single decision: the context that forced it, the options
considered, the option chosen, and the consequences. ADRs are append-only —
if a decision is later revisited, a new ADR supersedes the old one (which is
kept for history and marked as such). The [CHANGELOG](../CHANGELOG.md) records
*what* changed per release; ADRs record *why* a design is the way it is.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0000](0000-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0001](0001-openai-as-an-optional-extra.md) | `openai` as an optional extra | Accepted |
| [0002](0002-rate-limit-metadata-on-responses.md) | Rate-limit metadata on responses | Accepted |
| [0003](0003-pyproject-single-source-of-dependency-truth.md) | `pyproject.toml` as the single source of dependency truth | Accepted |
| [0004](0004-non-blocking-operations-via-futures.md) | Non-blocking operations via Futures and dedicated Sessions | Accepted |
| [0005](0005-arcana-reference-parsing-in-the-core.md) | ARCANA reference parsing in the core (transport-agnostic) | Accepted |

```{toctree}
:hidden:
:maxdepth: 1

0000-record-architecture-decisions
0001-openai-as-an-optional-extra
0002-rate-limit-metadata-on-responses
0003-pyproject-single-source-of-dependency-truth
0004-non-blocking-operations-via-futures
0005-arcana-reference-parsing-in-the-core
```
