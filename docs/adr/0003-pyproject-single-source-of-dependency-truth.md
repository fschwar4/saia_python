# `pyproject.toml` as the single source of dependency truth

- Status: Accepted
- Date: 2026-05-29
- Deciders: saia-python maintainers

## Context and Problem Statement

The project carried both a `pyproject.toml` (full dependency metadata and
extras) and a `requirements.txt`. The two had already drifted: `requirements.txt`
listed only `requests` + `tqdm`, omitting `openai` and `tomlkit`, so a
`pip install -r requirements.txt` produced an importable-but-broken environment.
Which file owns dependencies?

## Decision Drivers

- `saia-python` is a distributable **library**, not a deployed application.
- A single source of truth prevents the drift we already hit.
- CI installs via `pip install -e ".[test|docs]"` (pyproject extras).

## Considered Options

- **Delete `requirements.txt`** — `pyproject.toml` is authoritative.
- **Keep both in sync** — maintain `requirements.txt` alongside pyproject.

## Decision Outcome

Chosen option: **delete `requirements.txt`**. For a library, `pyproject.toml` is
the modern, standard single source of truth: it expresses flexible version
ranges and optional-dependency groups, and it is what `pip install` consumes.
`requirements.txt` is meant for applications that need pinned, reproducible
deploys — not for this package, and nothing referenced it except the README.

### Consequences

- Good — one place to edit dependencies; no drift.
- Good — extras (`test`, `docs`, `dev`, `openai`) give a dev/prod separation a
  flat requirements file cannot.
- Trade-off — there is no hand-maintained pinned manifest. If a reproducible
  environment is ever needed, generate a *pinned lockfile* on demand
  (`uv pip compile`, `pip-compile`, or `pip freeze`) rather than reviving a
  loose `requirements.txt`.

### Confirmation

CI installs from pyproject extras and is unaffected; the README repository-layout
listing no longer mentions `requirements.txt`.

## More Information

- [PyPA: writing `pyproject.toml`](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).
- Relates to ADR-0001 — the `[openai]` extra lives in `pyproject.toml`.
