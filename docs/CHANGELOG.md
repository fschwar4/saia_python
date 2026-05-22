# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `ArcanaService.setup_from_directory()` docstring no longer breaks
  the docs build under `sphinx-build -W`. The multi-line ``…`` inline
  literal in the original Returns: block is not valid RST and produced
  `"Inline literal start-string without end-string"`. Rewrote the
  Returns: block to describe the three-key dict semantically (using
  ``:meth:`` cross-references to :meth:`create`,
  :meth:`upload_directory`, and :meth:`generate_index`) — same
  information, valid RST.

### Changed

- CI: bump `actions/checkout@v4 → @v5` and
  `actions/setup-python@v5 → @v6` across both the docs and tests
  workflows. Addresses the Node.js 20 deprecation warning (Node 20
  removed from GitHub runners September 2026).

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

[Unreleased]: https://github.com/fschwar4/saia_python/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/fschwar4/saia_python/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/fschwar4/saia_python/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/fschwar4/saia_python/releases/tag/v0.1.0
