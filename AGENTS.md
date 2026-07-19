# AGENTS.md — saia-python

Shared, tool-neutral guidance for agents and developers working in this repo.
Read directly by tools that support `AGENTS.md`, and by Claude Code via the
`@AGENTS.md` import in `CLAUDE.md`. Keep it accurate; update when a convention
changes.

> **This is a PUBLIC repository** (AGPL-3.0-only; published to PyPI + Zenodo).
> This file is **committed and shared** — the single source of truth for project
> instructions; it travels to every clone/teammate via git. Therefore: **no
> secrets, no API keys, no private/downstream-internal details** here.
> Machine-specific residue goes in `CLAUDE.local.md` (gitignored, imported by
> `CLAUDE.md`; create your own per machine).

## What this is

A Python wrapper for the **GWDG SAIA** platform REST API (chat, ARCANA RAG,
documents, models, voice, responses, OpenAI-compat). Library only — **no HTTP
server of its own**. The **sync core uses `requests`**; a **native async layer**
(`saia_python.aio`, added in v0.9.0) is backed by `httpx.AsyncClient` and pulled
in only via the optional `[async]` extra.

- **Package:** `saia_python/` (services: `chat`, `arcana`, `documents`, `models`,
  `voice`, `responses`, `openai_compat`, `rate_limits`, `auth`; `client.py` is the
  entry point). Async twins live in `aio.py` + `_async_*.py`.
- **`arcana_references.py`** — the GWDG ARCANA reference-citation grammar;
  consumed by downstream RAG adapters. Treat its public shape as an API contract.
- **`tokenizer.py`** — tiktoken-based token counting (`[test]`/`dev` pull tiktoken).
- API key is auto-discovered from `SAIA_API_KEY` env → `.saia_api` → `.env`
  (all gitignored). **Never** hardcode or print a key.

## Environment & versions

- `requires-python = ">=3.10"`; CI runs the whole range. Code must parse/run on
  3.10 (e.g. no backslash in an f-string expression part — PEP 701 is 3.12+).
- Dev install: `pip install -e ".[dev]"` (bundles `test,docs,lint`). Async work:
  add the `[async]` extra. Version is in `pyproject.toml` (`version = "0.9.0"`).

## CI gates (must pass — `.github/workflows/`)

- **`ruff format --check`** and **`ruff check`** (`quality.yml`) — run
  `ruff format saia_python tests` before committing.
- **`mypy`** (`quality.yml`) — the package ships `py.typed`; keep it typed.
- **`pytest`** with coverage (`tests.yml`). Tests must not need a real key or the
  network — mock SAIA calls.

## Release process

Two-commit convention (code, then a standalone version bump), lightweight-tag the
release commit, SemVer. The changelog is **`docs/CHANGELOG.md`** (Keep a Changelog
format) and is the **source of truth**: at release, promote its `[Unreleased]`
entries into a dated section, then **copy that section verbatim into the GitHub
Release body** (`gh release create vX.Y.Z --notes-file …`) so the file and the
release note never drift. Full steps: `docs/dev_notes.rst`. **PyPI + Zenodo
publish only fires on a *published* GitHub Release** (`publish.yml` → `on:
release: [published]`, PyPI trusted publishing via OIDC, environment `pypi` —
**no stored token**). A plain `git tag`/push alone does **not** publish; you must
create + publish the Release.

## Conventions

- Conventional Commits; **no `Co-Authored-By` trailer**.
- Keep the pinned dependency of any downstream consumer explicit — never float a
  consumer to `@main`.
- More: `README.md` (Quick Start, Supported Services, Repository Structure) and
  the Sphinx docs under `docs/` (`pip install -e ".[docs]"`).
