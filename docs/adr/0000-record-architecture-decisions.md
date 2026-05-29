# Record architecture decisions

- Status: Accepted
- Date: 2026-05-29
- Deciders: saia-python maintainers

## Context and Problem Statement

`saia-python` is small but makes non-obvious design choices (optional
integrations, response shapes, concurrency). New contributors — and our future
selves — need to know *why* a thing is the way it is, not just *what* it does.
How do we capture that rationale durably and close to the code?

## Decision Drivers

- Rationale should live in the repository and be versioned with the code.
- The format should be lightweight (Markdown) and render in the Sphinx docs.
- Decisions should be append-only history, not silently edited away.

## Considered Options

- **MADR** (Markdown ADRs) committed under `docs/adr/`.
- A single freeform `DECISIONS.md`.
- An external wiki.
- No formal record (rely on commit messages and the CHANGELOG).

## Decision Outcome

Chosen option: **MADR under `docs/adr/`**, because it keeps rationale next to
the code, versions it through Git, renders in the existing MyST/Sphinx docs,
and gives each decision a stable, citable ID.

### Consequences

- Good — rationale is discoverable from the rendered docs and reviewable in PRs.
- Good — superseding is explicit (a new ADR references the one it replaces).
- Neutral — a small per-decision authoring overhead; only *significant*
  decisions warrant an ADR.

### Confirmation

The `docs/adr/` tree is part of the Sphinx toctree and built under
`sphinx-build -W`, so a malformed or orphaned ADR fails CI.

## More Information

- [MADR](https://adr.github.io/madr/) — the template this project follows.
- [Michael Nygard, *Documenting Architecture Decisions*](https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
