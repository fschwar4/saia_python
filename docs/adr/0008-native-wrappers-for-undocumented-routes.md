# Native wrappers for routes GWDG does not document

- Status: Accepted
- Date: 2026-11-22
- Deciders: saia-python maintainers

## Context and Problem Statement

Before v0.11.0, the only route saia-python wrapped natively for text
generation was `/chat/completions` (chat and ARCANA RAG). SAIA answers on three
more routes that generate text (checked live on 2026-11-19):

| Route | Format | In GWDG's documentation (seen 2026-11-22) |
|---|---|---|
| `/completions` | OpenAI's text completion | listed, without an example |
| `/responses` | OpenAI's Responses API | not listed |
| `/messages` | Anthropic's Messages API | not listed |

The first two were reachable only through the OpenAI SDK (`client.openai`),
which bypasses the library's 429 retry policy
([ADR-0006](0006-transport-policy-rate-limit-handling.md)), its rate-limit data
([ADR-0002](0002-rate-limit-metadata-on-responses.md)) and its typed errors.
`/messages` was not reachable at all: the OpenAI SDK cannot send that format.

A route the provider does not document can change or disappear without notice.
Should the library wrap such routes, and if so, how, so that a change on GWDG's
side shows up quickly and the wrappers stay cheap to maintain?

## Decision Drivers

- Every route the library offers should carry the library's behaviour: the 429
  retry, `_rate_limits`, typed errors, streaming, and an async twin
  ([ADR-0007](0007-native-async-transport.md)).
- An undocumented route can change at any time. The library must notice, and it
  must not claim more than was checked.
- The vendor formats are large, and each vLLM release adds fields. Code that
  mirrors them field by field needs constant upkeep.
- No new dependency. `openai` stays optional
  ([ADR-0001](0001-openai-as-an-optional-extra.md)), and pydantic stays out of
  the core.
- A result should read the same way whether it came from the native service or
  from a vendor SDK.

## Considered Options

- **(a) Leave the routes to the SDKs.** `client.openai.completions` and
  `client.openai.responses` already exist; `/messages` would need the Anthropic
  SDK and a factory for it. Rejected: the SDK path drops the retry policy, the
  rate-limit data and the typed errors, and a second SDK would be needed for
  one route.
- **(b) Native services with typed response models**, our own classes that
  mirror OpenAI's and Anthropic's types. Rejected: the copies would have to
  track two large, moving type definitions, for routes of which two have no
  documentation to track, and they would pull pydantic into the core.
- **(c) Native services that return plain dicts**, on the shared transport, with
  readers for every format and live tests that watch the routes.

## Decision Outcome

Chosen: **(c)**.

- **Three services, named as in the vendor SDKs.** `client.completions.create()`,
  `client.responses.create()` and `client.messages.create()`, each with an async
  twin on `AsyncSAIAClient`. Switching between the native call and the SDK call
  is a one-word change. Chat adopts the same name,
  `client.chat.completions.create()`, and keeps its old call form as an alias.
- **One transport.** `post_generation` and `apost_generation` (formerly
  `post_chat_completion` and `apost_chat_completion`, kept as aliases) serve all
  four routes, and `_payloads.py` builds the request bodies. A 429 means nothing
  was generated, so every call may be retried; a stream is retried before it is
  handed out, never in the middle (ADR-0006).
- **Dicts, not models.** A response is the JSON as a dict, plus `_rate_limits`;
  a stream yields dict chunks. Chat and ARCANA already work this way. Typed
  objects come from the SDK path: `client.openai.responses.create()`, for
  example, returns an `openai.types.responses.Response`.
- **Stateless only.** As of 2026-11-19, `/responses` keeps no state: `store` is
  accepted, but nothing can be retrieved, and `previous_response_id` and
  `GET /responses/{id}` get a 404. The library offers `create` and nothing that
  needs a stored response (retrieve, delete, cancel, background mode). The
  stateful fields still pass through `**kwargs` unchanged.
- **No ARCANA on the new routes.** On 2026-11-19, `/responses` and `/messages`
  accepted the ARCANA fields and ignored them. The new services take no
  `arcana_id`; RAG stays on `client.arcana.chat()`.
- **Named parameters for the common case; the rest passes through.** Each
  `create()` names the parameters most calls need. Everything else (`tools`,
  `tool_choice`, `text`, …) passes through `**kwargs`, so a field GWDG adds
  needs no new release.
- **One set of readers.** `text_of()`, `iter_text()` / `aiter_text()` and
  `usage_of()` read all four formats (chat, text completion, Responses,
  Messages), from native dicts and SDK objects alike. They skip reasoning and
  thinking, and they raise `APIError` when a stream reports an error.
- **Dated statements, guarded by live tests.** Docstrings and docs give the
  documentation status and every observed behaviour with the date of the check,
  for example "As of 2026-11-22, GWDG's documentation does not list
  `/messages`". One opt-in live test per route calls the native service against
  the real one and checks the response shape, the end of the stream and
  `text_of()`. The tests are skipped unless their environment variable is set,
  so CI needs neither a key nor the network.

### Consequences

- Good — all generation routes carry the library's retry, rate-limit data,
  typed errors and async twins, and `/messages` works without the Anthropic SDK.
- Good — no new dependency and no copied type definitions to maintain; fields
  GWDG adds pass through untouched.
- Good — one way to read a result, native or SDK.
- Trade-off — a dict offers no attribute access and no IDE completion. Callers
  who want those use the SDK path.
- Trade-off — the library now relies on routes without a documented contract. A
  change at GWDG can break them between two releases; the live tests detect
  such a change, they cannot prevent it.
- Trade-off — three more sync/async pairs to keep in step, the duplication tax
  of ADR-0007. The shared transport, body builders and readers keep the twins
  thin.

### Confirmation

Unit tests replay responses and streams recorded from SAIA
(`tests/_generation_fixtures.py`: `/completions` and `/responses` recorded on
2026-11-20, `/messages` on 2026-11-22). They live in `tests/test_completions.py`,
`tests/test_responses_api.py`, `tests/test_messages.py` and their async twins,
with `tests/test_payloads.py` for the bodies and `tests/test_responses.py` for
the readers. The live tests are opt-in:

```bash
SAIA_COMPLETIONS_LIVE=1 pytest tests/test_live_completions_route.py
SAIA_RESPONSES_LIVE=1 pytest tests/test_live_responses_route.py
SAIA_MESSAGES_LIVE=1 pytest tests/test_live_messages_route.py
```

Run them before a release, and whenever a route behaves unexpectedly.

## More Information

The plan, with every live result behind this decision, is
`docs/proposals/native-generation-routes.md`. This decision does not cover
helpers for structured output or tool calls on the new routes, a factory for
the Anthropic SDK, functional wrappers, or image generation.
