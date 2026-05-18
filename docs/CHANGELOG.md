# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/fschwar4/saia_python/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/fschwar4/saia_python/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/fschwar4/saia_python/releases/tag/v0.1.0
