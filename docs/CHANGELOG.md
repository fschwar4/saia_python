# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.0] — 2026-06-02

### Added

- Opt-in-by-default rate-limit handling: `SAIAClient(retry=...)` and the new
  exported `RetryPolicy` retry HTTP 429 at the session dispatch seam for
  idempotent calls (chat, ARCANA chat, `documents.convert`, voice, and ARCANA
  control-plane reads). They wait out a server reset within `max_waiting_time`
  (default 60 s) and fail fast on longer windows, with a bounded blind fallback
  (31 s ×2) when no reset header is present. Streaming retries only the opening
  429, never mid-stream. Per-call override via `retry=` (`False` disables, a
  `RetryPolicy` tunes). See ADR-0006 and `docs/proposals/rate-limit-handling.md`.

### Changed

- A 429 on an idempotent call is now **retried by default** instead of
  immediately raising `RateLimitError` (amends ADR-0002's passive default; opt
  out with `SAIAClient(retry=False)`). `RateLimitError` is still raised when
  retry is disabled, the budget is exhausted, or a long window is exhausted.
- Internal: unified the per-file batch executor. `sync_directory`'s apply pass
  now reuses the same `_run_file_batch` loop as `upload_directory` /
  `upload_files` / `delete_directory` instead of a parallel copy; the
  categorized sync report is derived as a grouped view of the shared per-file
  outcomes. No public API change. Two `verbose=True`-only output tweaks:
  skipped files are now listed during a sync, and per-file failures now include
  the error message across all batch helpers. See
  `docs/proposals/batch-executor-unification.md`.

## [0.5.1] — 2026-06-02

### Fixed

- Document-conversion images are now retrievable. `ConversionResult.images`
  documented the base64 payload under key `data`, but `/documents/convert`
  returns it under `image`, so callers following the docs hit a `KeyError`.
  The payload is now decoded at the API boundary.

### Changed

- `ConversionResult.images` is now a list of typed `ConversionImage`
  (`filename`, `data: bytes`, `type`) instead of raw API dicts; `data` holds
  the already-decoded image bytes. (Breaking: switch from dict-key access to
  attribute access.)

### Added

- `ConversionResult.save_images(directory)` and `save_all(directory)` write the
  extracted images (and, for `save_all`, the content) to disk — previously
  `save()` only wrote the text content.
- `ConversionImage` is exported from the top-level package.

## [0.5.0] — 2026-06-02

### Fixed

- `ArcanaService` HTTP calls no longer hang forever when the server accepts a
  request but never sends a response (common while an arcana is locked
  mid-(re)index). Every ARCANA management request now carries a default
  `(connect, read)` timeout of `(10, 60)` seconds, so a stalled call fails fast
  with `requests.Timeout` — which propagates to the caller (batch helpers
  record it per file and continue) — instead of blocking on the socket read.
  Previously only `heartbeat` and `generate_index` passed a timeout; `list`,
  `get`, `create`, `delete`, `list_files`, `delete_file`, `download_file`,
  `upload`, and the `delete_directory` loop could each wedge a batch operation
  (e.g. wiping a knowledge base before re-ingest) indefinitely.
- The same no-timeout guard now also covers the other quick control-plane calls
  on the shared session: `ModelsService.list()` / `list_raw()` (`GET /models`)
  and the `SAIAClient.get_rate_limits()` probe (`GET /chat/completions`), which
  could otherwise hang the same way.
- Type-checking: `_streaming.iter_sse` normalizes `iter_lines` output to `str`
  (also robust to the `bytes` the requests stub declares), and the
  `list_tool_capable` probe body is typed `dict[str, Any]` — silencing two
  errors a newer `mypy` / `types-requests` flags. No behavior change.

### Added

- `timeout` parameter on `SAIAClient(...)`, `ArcanaService(...)`, and
  `ModelsService(...)` (default `(10, 60)`; a single `float` applies to both the
  connect and read phases, `None` disables) to tune or opt out of the
  control-plane request timeouts above. The long-running data-plane paths (chat
  completions, voice, document conversion) are intentionally left uncapped.
- `on_result` per-file callback on `upload_files`, `upload_directory`,
  `delete_directory`, and `sync_directory` — invoked as
  `on_result(local_path, entry)` as each file is processed, so callers can
  record per-file provenance (e.g. a git SHA) or a transaction-log entry inline,
  without reimplementing the upload loop. (For `sync_directory`, fired for local
  uploads/replaces/skips, not for `prune` deletions.)

### Changed

- `generate_index(wait=True)` now tolerates a transient transport error
  (`requests.Timeout` / `ConnectionError`) on an individual poll and retries on
  the next interval instead of aborting a long, still-progressing reindex; only
  the overall `timeout` deadline ends the wait. Hardens the new default request
  timeout against long index waits. On deadline exhaustion the raised
  `TimeoutError` now includes the last-seen status and/or the last poll
  transport error, so a poll that kept timing out is diagnosable.
- Documented that ARCANA indexing is incremental — `generate_index` skips files
  already `INDEXED`, so "upload only the changed files, then index once"
  re-embeds just those. `sync_directory`'s single index pass and the library's
  recommended workflow rely on this server behavior.
- New "Extensions" docs section (between API Reference and Development), opening
  with an "ARCANA incremental sync" how-to (`docs/arcana_incremental_sync.rst`):
  two recipes — `sync_directory` with a SHA-256 `select`, and an explicit
  `upload_files` + single `generate_index` — plus the idempotent-upload,
  transport-drop, and one-reindex-at-a-time operational notes.

## [0.4.1] — 2026-06-01

First release published to PyPI as
[`saia-python`](https://pypi.org/project/saia-python/), together with
open-source project tooling and incremental-upload helpers for ARCANA.

### Added

- `ArcanaService.upload_files(name, paths, *, overwrite=True, verbose=False)` —
  upload an explicit, caller-chosen list of files. The *selection* of what to
  (re)upload is the caller's (e.g. from a checksum/manifest comparison); reuses
  the same per-file batch reporting as `upload_directory`.
- `ArcanaService.sync_directory(name, directory, *, select, pattern="*",
  recursive=False, prune=False, index=True, index_wait=True, verbose=False)` —
  sync a local directory under a caller-supplied
  `select(local_path, remote_or_None) -> "upload" | "replace" | "skip"` policy,
  then trigger a single `generate_index` only when something changed. Keeps
  change-detection (e.g. SHA-256 vs. your own manifest) outside the package,
  since the ARCANA API exposes no content hash. Optional `prune` deletes remote
  files with no local counterpart.
- PyPI packaging metadata in `pyproject.toml`: `readme`, `license-files`,
  `keywords`, trove `classifiers`, and an expanded `[project.urls]` table
  (Homepage, Documentation, Changelog, Issues) so the project page renders the
  README and is discoverable.
- `CITATION.cff` (Citation File Format 1.2.0) — enables GitHub's "Cite this
  repository" button and import into reference managers.
- `saia_python/py.typed` — PEP 561 marker so downstream type checkers consume
  the package's inline type hints; advertised via the `Typing :: Typed`
  classifier.
- `.github/workflows/publish.yml` — builds the sdist + wheel, runs
  `twine check --strict`, and publishes to PyPI via OIDC Trusted Publishing
  when a GitHub Release is published (no stored API token).
- README status badges (PyPI, Python versions, license, CI, docs) and a
  commented Zenodo DOI badge placeholder.
- Linting and type-checking: `ruff` (lint + format) and `mypy` configuration in
  `pyproject.toml`, a `lint` optional-dependency group, a
  `.pre-commit-config.yaml`, and a `Quality` CI workflow
  (`ruff check` + `ruff format --check` + `mypy`).
- Coverage reporting via `pytest-cov`; the Tests workflow now runs
  `pytest --cov`.

### Changed

- `ArcanaService.list_files()` now documents the full API `FileOutSchema`
  (`name`, `size`, `owner_user_name`, `created_at`, `updated_at`, `index_info`
  with per-file `index_status` / `chunks_indexed`, and `related_files`).
- Corrected the `license` field from the deprecated SPDX identifier `AGPL-3.0`
  to `AGPL-3.0-only`. The license terms are unchanged; only the SPDX expression
  is now valid for PEP 639 / PyPI. Bumped the build requirement to
  `setuptools>=77` (PEP 639 support).
- Applied `ruff` autofixes and the formatter across the package and tests
  (`Optional[X]` → `X | None`, import sorting, consistent formatting) plus minor
  `mypy` type-annotation fixes. No behavior change — all 92 tests pass. Known
  typing gaps (tomlkit's `Item | Container` in `auth.py`; the `.list` method
  shadowing the builtin in `models.py` / `arcana.py`) are scoped via documented
  per-module `mypy` overrides.

## [0.4.0] — 2026-05-30

### Added

- `examples/openai_compatible_proxy.ipynb` — a documented notebook that builds
  a small OpenAI-compatible proxy in front of SAIA from the library's building
  blocks (`models.list_raw()`, `arcana_references`, the native client), turning
  GWDG ARCANA's verbose `References:` dump into clean, numbered citations for
  any OpenAI-SDK client. Example only — not shipped in the package.
- `ArcanaService.version()` and `ArcanaService.heartbeat()` — ARCANA
  service-health checks now live on the service that owns the ARCANA URL path
  and auth scheme (`client.arcana.version()` / `client.arcana.heartbeat()`).
  `SAIAClient.arcana_version()` / `arcana_heartbeat()` are kept as thin
  delegators, so existing calls are unchanged.

### Changed

- Internal de-duplication (no behavior change): the chat-completion POST
  (shared by `ChatService.completions` and `ArcanaService.chat`), the directory
  upload/delete batch loop, the optional-`tqdm` progress wrapper, the
  background-thread `Session` helper, and API-key / base-URL resolution
  (`resolve_credentials`, shared by `SAIAClient` and `create_openai_client`)
  each now have a single implementation. ARCANA's URL path and auth scheme are
  no longer duplicated in `SAIAClient`.
- **Moved** base-URL / credential resolution into the configuration module:
  `resolve_base_url`, `resolve_credentials`, and `DEFAULT_BASE_URL` now live in
  `saia_python.auth` (beside `load_api_key` / `load_config`) rather than
  `saia_python.client`. The package-level `saia_python.resolve_base_url` import
  path is unchanged; only the `saia_python.client.resolve_base_url` submodule
  path is affected (breaking for code that imported from `saia_python.client`).

## [0.3.0] — 2026-05-30

### Added

- `ModelsService.list_raw()` — returns the raw ``GET /models`` response
  envelope (the OpenAI ``{"object": "list", "data": [...]}`` dict) without
  unwrapping, for callers that re-serve the full OpenAI-compatible payload
  (e.g. an adapter proxying ``GET /v1/models``). `list()` now delegates to it.
  New `tests/test_models.py`.
- Test coverage for previously-untested 0.2.0 behavior: `get_rate_limits()`
  raising `AuthenticationError` on 401/403 (`tests/test_client.py`), and chat
  streaming/non-streaming rate-limit parity (`tests/test_chat.py`).
- `saia_python.arcana_references` — a pure, dependency-free module that parses
  GWDG ARCANA's appended `References:` block into structured data:
  `parse_arcana_references()`, `parse_reference_entries()`, `is_arcana_event()`,
  and the `ArcanaReference` / `ParsedReferences` dataclasses. No HTTP/I-O, so
  it imports cleanly into async servers. Lets external SAIA consumers (e.g. an
  OpenAI-compatible adapter) drop their own copy of the GWDG reference regex.
  See ADR-0005. New `tests/test_arcana_references.py`.

## [0.2.0] — 2026-05-29

### Added

- `VoiceService.transcribe()` / `translate()` with `wait=False` now return a
  `concurrent.futures.Future[str]` (run on a dedicated background `Session`)
  instead of discarding the result. Resolve with `.result()` (re-raises on
  error), poll with `.done()`, or attach `.add_done_callback()`. New
  `tests/test_voice.py`.
- `RateLimitInfo.to_dict()` — a plain, JSON-serializable view of the parsed
  rate-limit headers.
- Optional `openai` extra (`pip install saia-python[openai]`). The `openai`
  package is now imported lazily inside `create_openai_client()`, so the core
  package installs and imports without it; using the OpenAI-compat layer
  without the extra raises a clear `ImportError` with install instructions.
- `SSEStream` — streaming chat / ARCANA calls now return an iterable wrapper
  whose `.rate_limits` attribute exposes the rate-limit headers as a
  JSON-serializable dict (parity with the non-streaming `_rate_limits` key).
  Exported from the package; iterating it yields the same chunks as before.
- Architecture Decision Records under `docs/adr/` (MADR format), linked from the
  documentation: recording the ADR process itself, the optional `openai` extra,
  rate-limit metadata exposure, `pyproject.toml` as the single source of
  dependency truth, and non-blocking operations via Futures + dedicated Sessions.

### Changed

- `ModelsService.list()` now uses `GET /models` (was `POST`), matching the
  OpenAI-compatible endpoint and the OpenAI SDK.
- Non-streaming Chat and ARCANA responses attach `_rate_limits` as a plain,
  JSON-serializable dict (was a `RateLimitInfo` instance) so the whole response
  can be `json.dumps`-ed.
- `ArcanaService.generate_index(wait=False)` fires the background trigger on its
  own `requests.Session` (a `Session` is not safe to share across threads with
  the caller's polling calls).
- `SAIAClient.get_rate_limits()` now raises `AuthenticationError` on 401/403
  instead of silently returning an empty `RateLimitInfo`.
- `openai` moved from core dependencies to the optional `[openai]` extra; the
  `test` extra pulls it in so CI is unaffected.
- CI: bump `actions/checkout@v4 → @v5` and
  `actions/setup-python@v5 → @v6` across both the docs and tests
  workflows. Addresses the Node.js 20 deprecation warning (Node 20
  removed from GitHub runners September 2026).

### Removed

- `requirements.txt` — `pyproject.toml` is the single source of truth for
  dependencies. The file was incomplete (missing `openai`/`tomlkit`) and
  referenced only by the README; CI installs via `pip install -e ".[test|docs]"`.

### Fixed

- `iter_sse()` now closes the streaming response in a `finally` block (it
  previously leaked the connection until garbage collection).
- `load_api_key(path=...)` no longer mis-classifies a raw key containing `=`
  (e.g. base64 padding) as dotenv, and no longer `IndexError`s on an empty
  file: the dotenv form is tried first, then the first non-empty, non-comment
  line.
- Docs: corrected the clone URL to `github.com/fschwar4/saia_python`; removed an
  inaccurate `tomllib`/`tomli` note from `configuration.rst` (the package parses
  config with `tomlkit`); fixed the README repo-structure listing (dropped the
  non-existent `backlog.md`, added `.env.example` and `CHANGELOG.md`).
- Removed a dead `if not resp.ok` branch in `raise_for_status()` and a redundant
  `.env` re-read in `_resolve_owner_prefix()`.
- `ArcanaService.setup_from_directory()` docstring no longer breaks
  the docs build under `sphinx-build -W`. The multi-line ``…`` inline
  literal in the original Returns: block is not valid RST and produced
  `"Inline literal start-string without end-string"`. Rewrote the
  Returns: block to describe the three-key dict semantically (using
  ``:meth:`` cross-references to :meth:`create`,
  :meth:`upload_directory`, and :meth:`generate_index`) — same
  information, valid RST.

## [0.1.2] — 2026-05-22

### Added

- `SAIAClient.health_check(verbose=False)` — verify connectivity *and*
  authentication in one call. Combines the existing
  `arcana_heartbeat()` (cheap 204 GET) with an authenticated
  `models.list_ids()` so callers can distinguish "service down" from
  "auth failed". Returns a bool by default; `verbose=True` returns a
  diagnostic dict (`ok`, `base_url`, `models_ok`, `model_count`,
  `arcana_ok`, `error`) suitable for surfacing in onboarding scripts.
- `saia_python.text_of(response)` — module-level helper that extracts
  the first choice's assistant content from an OpenAI-style response
  dict (the shape returned by both `ChatService.completions` and
  `ArcanaService.chat`). Empty `choices` lists and missing/`None`
  `content` fields return `""` with a logged warning so silent
  regressions surface in logs.
- `ArcanaService.setup_from_directory(name, source_dir, ...)` —
  end-to-end convenience that composes `create()`,
  `upload_directory()`, and `generate_index()` into a single call.
  Returns `{"arcana": <create-result>, "uploads": <list>,
  "index": <index-result>}` so callers can inspect any step. Uses the
  UUID-suffixed name from `create()` for the upload + index calls so
  the composition stays correct without the caller having to remember
  the renaming.
- Test coverage for all three additions:
  `tests/test_health_check.py` (6 tests), `tests/test_responses.py`
  (6 tests), `tests/test_setup_from_directory.py` (3 tests). Suite is
  network-free; HTTP / SDK calls are mocked.

## [0.1.1] — 2026-05-18

### Fixed

- `ArcanaService.generate_index(wait=True)` no longer re-raises
  `requests.exceptions.ConnectionError` when the ARCANA server drops
  the trigger connection mid-flight. The previous substring filter
  only matched `"504"` / `"timeout"` strings and missed the common
  `RemoteDisconnected` case — the server accepts the indexing job,
  holds the connection while building the embedding queue, then
  closes it without a response. Transport-level failures
  (`requests.exceptions.Timeout`, `requests.exceptions.ConnectionError`)
  and `APIError(504)` from the nginx gateway now fall through to the
  poll loop, with a sanity `GET` so a genuinely-down server still
  fails fast instead of waiting out the full poll timeout.
- `generate_index()` no longer raises `UnboundLocalError` when a very
  short `timeout` causes the poll deadline to elapse before any
  iteration runs. The resulting `TimeoutError` message now formats
  cleanly.

### Changed

- `saia_python.arcana` imports `requests` at runtime (was
  `TYPE_CHECKING`-only) so the `requests.exceptions.*` types are
  available for explicit handling.

### Added

- Test suite for `ArcanaService.generate_index()` covering the
  transport-error paths (`ConnectionError`, `ReadTimeout`,
  `APIError(504)`), the genuinely-down-server case, propagation of
  non-504 API errors, the happy path, and the `TimeoutError` path.

## [0.1.0] — 2026-04-02

### Added

- Initial release of `saia-python`, a wrapper for the
  [GWDG SAIA platform](https://docs.hpc.gwdg.de/services/ai-services/saia/index.html)
  REST API.
- Object-oriented `SAIAClient` composing Chat AI, Voice AI (Whisper
  transcription and translation), ARCANA (RAG / knowledge bases),
  Docling document conversion, model listing, and rate-limit
  inspection.
- Standalone functional API mirroring the OOP surface
  (`list_model_ids`, `chat_completion`, `transcribe`, `translate`,
  `list_arcanas`, `upload_to_arcana`, `arcana_chat`,
  `convert_document`, `get_rate_limits`).
- OpenAI SDK compatibility layer via `client.openai` and
  `client.openai_async`.
- Credential and configuration discovery from environment variables,
  `.saia_api`, `.env`, and `config.toml`, including ARCANA ID
  resolution with owner-prefix handling.
- Sphinx documentation (PyData theme) and a unit test suite.

[Unreleased]: https://github.com/fschwar4/saia_python/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/fschwar4/saia_python/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/fschwar4/saia_python/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/fschwar4/saia_python/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/fschwar4/saia_python/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/fschwar4/saia_python/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/fschwar4/saia_python/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/fschwar4/saia_python/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/fschwar4/saia_python/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/fschwar4/saia_python/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/fschwar4/saia_python/releases/tag/v0.1.0
