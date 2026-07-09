# Native async transport (`saia_python.aio`)

- Status: Accepted
- Date: 2026-07-09
- Deciders: saia-python maintainers

## Context and Problem Statement

The library is 100% synchronous (`requests`). The only async surface is
[ADR-0001](0001-openai-as-an-optional-extra.md)'s `create_openai_client(async_client=True)`,
which hands back an `openai.AsyncOpenAI` — the OpenAI SDK's own transport, which
**bypasses our `RetryPolicy`/rate-limit handling entirely** and cannot inject
ARCANA retrieval. So there is no async path that carries the library's own
behaviour.

The forcing case is the AVOR adapter: a FastAPI (ASGI) reverse proxy in front of
GWDG serving ~20 clinicians concurrently on one event loop. A blocking
`requests` call there stalls *every* concurrent user for the duration of one
(minutes-long) RAG answer, so the adapter hand-rolled its own `httpx.AsyncClient`
GWDG transport — duplicating the chat-completion shape, the ARCANA injection
(the three-part `enable-tools` + `arcana.id` + `inference-service` invariant),
and SSE decoding, with **no** rate-limit retry. Two implementations of "talk to
GWDG" now risk drifting.

Should the library ship a native async transport; how much surface; and how do we
keep the sync and async paths from diverging on retry semantics?

## Decision Drivers

- One definition of the GWDG chat/RAG request (esp. the ARCANA injection
  invariant) and one retry policy — not a second copy in every ASGI consumer.
- Async must be **first-class**, not the `openai_async` shim: it must carry
  `RetryPolicy`, rate-limit surfacing, and ARCANA injection.
- No divergence: the retry *decision* (which window, how long to wait, jitter,
  give-up) must be the **same code** for sync and async.
- Keep `requests` the zero-cost default; async pulls `httpx` only when asked.
- Python has no way to share an I/O call stack between sync and async — minimise
  the duplicated surface.
- Scope to where async actually pays off (concurrent request/stream fan-in),
  not batch/admin work.

## Considered Options

- **(a) Do nothing** — consumers keep using `openai_async` or rolling their own.
- **(b) Full async parity** — async twins of *every* service (upload, index,
  sync, voice, documents), with async file I/O (`aiofiles`/`to_thread`).
- **(c) Native async **data plane** + a sans-I/O shared core** — async twins of
  chat, ARCANA RAG chat, streaming, and the light read-only control-plane calls;
  the pure retry/rate-limit/payload logic is *imported*, not copied; heavy
  control-plane stays sync-only.
- **(d) `unasync` codegen** — generate the sync code from an async source.

## Decision Outcome

Chosen: **(c)**. A new `saia_python/aio.py` (`AsyncSAIAClient` +
`AsyncChatService` / `AsyncArcanaService` / `AsyncModelsService`) over
`httpx.AsyncClient`, behind a new `[async]` extra.

- **The retry brains are shared, not duplicated.** `RetryPolicy`, `_plan`,
  `_jitter`, `resolve_retry` ([ADR-0006](0006-transport-policy-rate-limit-handling.md))
  and `parse_rate_limits` ([ADR-0002](0002-rate-limit-metadata-on-responses.md))
  are imported verbatim; only the socket-touching loop (`aexecute`,
  `apost_chat_completion`, `AsyncSSEStream`) is re-implemented with
  `await client.request(...)` / `await resp.aclose()` / `await asyncio.sleep`.
  The sync and async paths **cannot drift** on rate-limit behaviour.
- **The ARCANA injection invariant lives in one pure place.** New transport-free
  `_payloads.py` (`build_chat_body`, `apply_arcana_fields`, `arcana_chat_headers`)
  is reused by the sync services, the async services, **and** external gateways
  that assemble their own body (the adapter) — so the three-part retrieval
  invariant is defined once and unit-tested once.
- **`aexecute` preserves the ADR-0006 contract**: it returns the raw response on
  give-up (never raises), so `raise_for_status` still fires downstream. On a 429
  with retry off, that now carries an **informative message**
  (`format_rate_limit_error`: which window, when it resets, how to auto-retry),
  shared by both transports — this is the "retry as a keyword, informative error
  when off" behaviour.
- **`AsyncSSEStream` owns the `client.stream(...)` context** (httpx exposes a
  streamed body only inside it), retrying an initial 429 *before* the body is
  exposed — never mid-stream, exactly like the sync path. It offers **two**
  consumption modes: decoded `dict` chunks (high-level, raises on error status)
  and raw lines via `aiter_lines()` (low-level, no raise) so a gateway can frame
  upstream errors itself — the AVOR adapter uses the latter to keep its verbatim
  `[DONE]` / non-`data:` passthrough and its own error-chunk framing.
- **`httpx` is optional.** A `[async]` extra; `saia_python.aio` imports it only
  when an `AsyncSAIAClient` is constructed (a pointed ImportError otherwise), and
  `from saia_python import AsyncSAIAClient` resolves lazily so sync-only installs
  never pull `httpx`.

### Scope boundary (the sync/async duplication tax)

Async covers the **data plane** (chat, ARCANA RAG chat, streaming) plus the
cheap read-only control-plane calls (`models`, arcana `version`/`heartbeat`/
`list`/`get`, `health_check`). Upload / index / sync, voice, and document
conversion stay **sync-only** on `SAIAClient`: they are batch/admin work with
blocking file I/O and no concurrency benefit (and, being quota-bound, more
concurrency there would only hit the rate limits harder). Option (b) was rejected
as a large surface with negative value for the file paths; (d) as build
complexity we don't yet need given how small the truly-duplicated surface is
(three transport functions). Extending to the control plane later is purely
additive.

### Consequences

- Good — one retry policy and one ARCANA invariant across sync + async + the
  adapter; ASGI consumers get a first-class async client that carries the
  library's behaviour instead of the `openai_async` shim that drops it.
- Good — the adapter can delete its bespoke retry-less GWDG transport and consume
  `aexecute` / `AsyncSSEStream`, keeping only its presentation layer (the
  references rewriter).
- Trade-off — the sync/async duplication tax is real: `execute`,
  `post_chat_completion`, and `SSEStream` each have an async twin that must be
  kept in step. Mitigated by sharing every pure piece (the twins are thin) and by
  mirrored tests; if it grows, `unasync` (option d) remains open.
- Trade-off — a second HTTP dependency enters the tree (behind an extra), and
  async tests need an event loop (driven by `asyncio.run`, so no
  `pytest-asyncio` dependency was added).

### Confirmation

`tests/test_async_transport.py` mirrors `test_transport_policy.py` (retry,
retry-disabled, mutation gating, informative 429, error framing);
`tests/test_async_streaming.py` covers both consumption modes + retry-before-open;
`tests/test_async_arcana.py` pins the three-part ARCANA injection;
`tests/test_async_chat.py` / `test_async_client.py` cover the services + client;
`tests/test_payloads.py` and `tests/test_rate_limit_message.py` cover the shared
pure core. All waits route through an injected async `sleep`, so the suite never
blocks. `mypy` type-checks the new modules; `ruff` lints source + tests.

## More Information

Extends [ADR-0006](0006-transport-policy-rate-limit-handling.md) — the same
`RetryPolicy` now drives an async transport. Complements
[ADR-0001](0001-openai-as-an-optional-extra.md) — `openai_async` remains for
OpenAI-SDK compatibility, but the native async client is the path that carries
retry + rate limits + ARCANA. The consuming-side decision (the AVOR adapter
dropping its bespoke transport) is recorded in the frontend repo's ADR series.
