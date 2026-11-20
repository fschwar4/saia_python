# Proposal: Native services for `/completions`, `/responses` and `/messages`

**Status:** draft, decisions taken 2026-11-19 (§11) · **Scope:** three new services (sync and async), the shared transport, and `responses.py` helpers · **Type:** feature (minor release, v0.11.0)
**Relates to:** [ADR-0001](../adr/0001-openai-as-an-optional-extra.md) (`openai` stays optional),
[ADR-0002](../adr/0002-rate-limit-metadata-on-responses.md) (`_rate_limits` on every response),
[ADR-0006](../adr/0006-transport-policy-rate-limit-handling.md) (retry seam),
[ADR-0007](../adr/0007-native-async-transport.md) (async twins).

---

## 1. Motivation

GWDG's sandbox (`https://saia.gwdg.de/sandbox`) now shows example calls for six
routes. saia-python wraps two of them itself: `/chat/completions` and `/models`.
Of the other four:

| Route | Today in saia-python |
|---|---|
| `POST /completions` | Only through `client.openai.completions.create()` |
| `POST /responses` | Only through `client.openai.responses.create()`, plus an opt-in live test |
| `POST /messages` | Not reachable. It speaks Anthropic's Messages format, which the OpenAI SDK cannot send. |
| `POST /images/generations` | Postponed; not part of this proposal |

The goal is that each route works in two ways: natively, with our transport (retry, `_rate_limits`, `SAIAError`, async twin), and through the vendor SDK. Shared helpers read the result either way.

## 2. Facts verified live (2026-11-19)

All checks used `qwen3-30b-a3b-instruct-2507`. The reasoning checks used `deepseek-v4.1-flash-1017`. These facts constrain the design:

| | `/completions` | `/responses` | `/messages` |
|---|---|---|---|
| In GWDG's docs | listed (no example) | **no** | **no** |
| Response | `object: "text_completion"`, `choices[].text` | `object: "response"`, `output[]` items | `type: "message"`, `content[]` blocks, `stop_reason` |
| Text lives in | `choices[0].text` | `output[type=message].content[type=output_text].text` | `content[type=text].text` |
| Reasoning | n/a | separate `output[type=reasoning]` item (`reasoning_text`) | separate `thinking` block (with `signature`) |
| Usage keys | `prompt_tokens` / `completion_tokens` | `input_tokens` / `output_tokens` | `input_tokens` / `output_tokens` |
| Stream | `data:` lines only, final usage chunk with empty `choices`, then `[DONE]` | `event:` + `data:` lines; each JSON carries `type` (`response.created` … `response.completed`); **no `[DONE]`** | `event:` + `data:` lines; each JSON carries `type` (`message_start` … `message_stop`); **no `[DONE]`** |
| Rate-limit headers | all 9 `x-ratelimit-*` | all 9 | all 9 |
| Required fields | `model`, `prompt` | `model`, `input` | `model`, `messages`, **`max_tokens`** (400 without it) |
| Auth | Bearer | Bearer | Bearer **or** `x-api-key`; no `anthropic-version` needed |

**`/responses` keeps no state (as of 2026-11-19).** OpenAI's Responses API can store a response on the server and build on it later. On SAIA none of that works:

| Feature | What it does at OpenAI | SAIA, as of 2026-11-19 |
|---|---|---|
| `store: true` | keep the response on the server | accepted, but nothing is retrievable afterwards |
| `previous_response_id` | continue a conversation without resending it | `404 "Response with id … not found"` |
| `GET /responses/{id}` | fetch a stored response | `404 {"detail": "Not Found"}` |
| delete, cancel, `background: true` + polling, input-item listing | manage stored or running responses | not offered: they need a stored response or a GET route |

The likely cause is that the gateway routes on the `model` in the request body, which a GET has no room for, and that the vLLM instances share no response store. Only stateless `create` works, so a conversation must be sent in full as an `input` list, as chat sends `messages`. Re-check this before relying on it in either direction; GWDG may change it.

**The existing SSE parser already fits all three streams.**
- `iter_sse` skips `event:` lines, parses every `data:` line, and stops at `[DONE]` or when the connection closes.
- Every `data:` JSON on `/responses` and `/messages` carries its own `type`, so no event name is lost.

## 2a. Live checks (done as of 2026-11-19)

Their results go into §2 and decide the related non-goals in §3. Each check that passes becomes an opt-in live test (§8), so a later change at GWDG shows up.

**Results as of 2026-11-19**, with `qwen3-30b-a3b-instruct-2507` and `deepseek-v4-flash-0731`:

| Check | `/responses` | `/messages` | `/completions` |
|---|---|---|---|
| Tool call (auto) | ✅ both models: `function_call` item | ✅ both models: `tool_use` block, `stop_reason: "tool_use"` | n/a |
| Round trip (result sent back, used in the answer) | ✅ both | ✅ both | n/a |
| Forced tool (`tool_choice`) | ✅ both | ✅ both | n/a |
| Streamed tool call | ✅ both: `response.function_call_arguments.delta` / `.done` | ✅ both: `content_block_start` (`tool_use`) + `input_json_delta` | n/a |
| Schema enforced | ✅ both, via `text.format` | ❌ `response_format` is ignored (prose comes back); ✅ both via a forced `tool_use` | ⚠️ qwen ✅, deepseek-v4-flash ❌: `response_format` is honoured per model, not reliably |

The structured-output prompts asked for prose on purpose, so only an enforced schema could produce schema-shaped JSON.

**ARCANA, as of 2026-11-19:** retrieval fires only on `/chat/completions`.

The test used a test arcana holding one scientific preprint. The same question ("which documents does this knowledge base hold?") went to all three routes, each with the three ARCANA fields (header `inference-service: saia-openai-gateway`, body `enable-tools: true` and `arcana.id`).

| Route | Result |
|---|---|
| `/chat/completions` (`client.arcana.chat`) | ✅ names the preprint and its topic, and ends with a `References:` block |
| `/responses` | ❌ HTTP 200, but the fields are ignored: a generic invented answer, no references, no better than the control without ARCANA |
| `/messages` | ❌ same as `/responses` |

ARCANA therefore stays on `/chat/completions`, and the new services do not offer an `arcana_id` parameter.

The check designs follow.

**ARCANA over `/responses` and `/messages`**
- *Needs* an arcana that holds a document with a fact the model cannot know otherwise.
- *Send* the same question three ways, each with header `inference-service: saia-openai-gateway`, body `arcana: {"id": …}` and `enable-tools: true`, model `qwen3-30b-a3b-instruct-2507` (the model GWDG's docs use):
  1. `/chat/completions`, the baseline that works today;
  2. `/responses`;
  3. `/messages`.
- *Supported* if the answer contains the fact and a `References:` block, as the baseline does.
- *Ignored* if the call succeeds but answers without the document.
- *Unsupported* if the call errors.

**Tool calling**
- *Models:* run each check with two models, `qwen3-30b-a3b-instruct-2507` and `deepseek-v4-flash-0731`. Tool support depends on the model's tool-call parser in vLLM.
- *Tool:* one function, `get_weather(city: str)`.
- *Round trip:* the model asks for the tool, we send a canned result back, and the model must use it in its final answer.
- *Also check* forcing the tool, and the streamed form of the call.
- `/completions` has no tool concept and is skipped.

| Step | `/responses` | `/messages` |
|---|---|---|
| Declare | `tools=[{"type": "function", "name", "description", "parameters": <JSON Schema>}]` | `tools=[{"name", "description", "input_schema": <JSON Schema>}]` |
| Expect | an `output` item of `type: "function_call"` with `name`, `arguments` (a JSON string) and `call_id` | a `content` block of `type: "tool_use"` with `id`, `name` and `input` (a dict), plus `stop_reason: "tool_use"` |
| Send back | `input` = the user turn + that `function_call` item + `{"type": "function_call_output", "call_id", "output"}` | `messages` + the assistant turn holding the `tool_use` block + a user turn with `{"type": "tool_result", "tool_use_id", "content"}` |
| Force | `tool_choice={"type": "function", "name": "get_weather"}` | `tool_choice={"type": "tool", "name": "get_weather"}` |
| Stream | `response.function_call_arguments.delta` / `.done` events | `content_block_start` (`tool_use`) + `input_json_delta` |

**Structured output**
- Use a small Pydantic model, say `{city: str, temperature_c: float}`, as the JSON Schema.
- *Supported* if the answer parses and validates against it.

| Route | How to request a schema |
|---|---|
| `/responses` | `text={"format": {"type": "json_schema", "name": "Weather", "schema": …, "strict": true}}` |
| `/messages` | Anthropic's format has no `response_format`. Check (a) a forced `tool_use`, the classic way to get structured output from the Messages API; (b) whether vLLM honours a `response_format` field passed through. |
| `/completions` | `response_format={"type": "json_schema", "json_schema": {…}}`, which vLLM also accepts on `/completions` |

## 3. Goals / Non-goals

**Goals**
- Three native services, `client.completions`, `client.responses` and `client.messages`, each with an async twin on `AsyncSAIAClient`.
- The same transport as chat: the 429 retry policy, `_rate_limits` on dicts and `rate_limits` on streams, `SAIAError` mapping, `SSEStream` / `AsyncSSEStream`.
- The SDK path keeps working unchanged. The shared helpers (§6) accept our dicts and SDK objects alike.
- No new dependency.

**Non-goals**
- **Typed response models.** We return plain dicts, as chat and ARCANA do. Reasons:
  - Both formats are large, and each vLLM upgrade adds fields (e.g. `kv_transfer_params`, `input_messages`). GWDG does not document two of the three routes, so typed models would break or need upkeep.
  - Callers who want typed objects already get them from the vendor SDKs, and the SDK path keeps working (§6). `client.openai.responses.create()` returns `openai.types.responses.Response`, with `.output_text`, `.output` and `.usage` as attributes. `client.openai.completions.create()` returns `openai.types.Completion`. The `anthropic` SDK returns a typed `Message` (TODO, §3). Building our own classes would mean re-implementing OpenAI's and Anthropic's type definitions and then tracking them.
  - The core stays free of pydantic, which is imported only lazily for structured output.
- **Stateful Responses features:** `store`, `previous_response_id`, retrieve, delete, cancel, `background` and input-item listing. SAIA does not support them (§2). The fields still pass through `**kwargs`, so nothing blocks them if GWDG enables them later.
- **ARCANA over the new routes.** GWDG documents RAG only for `/chat/completions`, and the live check in §2a confirms that `/responses` and `/messages` accept the ARCANA fields but ignore them. RAG stays on `client.arcana.chat()`.
- **Structured-output and tool-calling helpers for the new routes.** SAIA supports tool calling on `/responses` and `/messages`, and enforces a schema via `/responses` `text.format` (§2a). The raw fields (`tools`, `tool_choice`, `text.format`, …) pass through `**kwargs`. Helpers such as a `create_structured()` would be a later, separate step. On `/completions` a schema is not enforced reliably (model-dependent), and on `/messages` only through a forced tool.
- **An Anthropic SDK factory** (`create_anthropic_client()`, an `[anthropic]` extra). This is a separate TODO and needs its own live check (base URL without `/v1`, auth). Native `messages.create` does not need the SDK, and §6's helpers already accept Anthropic SDK objects.
- **Functional wrappers** (`text_completion()`, `create_response()`, `create_message()`). On the TODO list and not urgent; only when someone asks.
- **Image generation** (postponed).

## 4. Public API

```python
client.completions.create(
    model, prompt, *, max_tokens=None, temperature=None, top_p=None,
    stream=False, retry=None, **kwargs,
) -> dict | SSEStream

client.responses.create(
    model, input, *, instructions=None, max_output_tokens=None,
    temperature=None, top_p=None, stream=False, retry=None, **kwargs,
) -> dict | SSEStream

client.messages.create(
    model, messages, max_tokens, *, system=None, temperature=None,
    top_p=None, stream=False, retry=None, **kwargs,
) -> dict | SSEStream
```

- **Naming (decided).** `.create()` mirrors the vendor SDKs: `openai` has `completions.create` and `responses.create`, and `anthropic` has `messages.create`. Moving between the native call and the SDK call is then a one-word change. Chat adopts the same form (§4a).
- **`max_tokens` is required for `messages.create`.** SAIA rejects a call without it, so the signature enforces it rather than letting the call fail at runtime.
- **Return values.** As in chat, a dict carries an extra `_rate_limits` key, and a stream exposes `.rate_limits`.
- **Modules.** `saia_python/completions.py` (`CompletionsService`), `saia_python/messages.py` (`MessagesService`) and `saia_python/responses_api.py` (`ResponsesService`). The last name is needed because `saia_python/responses.py` already holds `text_of` and is a public import path. Async twins go in `aio.py`, next to `AsyncChatService`.
- **Docstrings** for `/responses` and `/messages` state that GWDG does not document these routes and that both may change without notice.

## 4a. Aligning the existing chat service with `.create()`

Decided: existing services adopt `.create()` too, where a vendor-SDK twin exists. In practice that means chat:

```python
client.chat.completions.create(model, messages, ...)   # new, identical to the OpenAI SDK
client.chat.completions(model, messages, ...)          # existing form keeps working
await aclient.chat.completions.create(...)             # async twin, same shape
```

- **Mechanics.** `ChatService.completions` changes from a method to a property. The property returns a small `ChatCompletions` object, holding the service, with:
  - `create(...)`: the current implementation, moved over;
  - `__call__(...)`: delegates to `create`, so every existing call keeps working.

  The same applies to `AsyncChatService`.
- **No deprecation warning yet.** Docs and examples switch to `.create()`, and the old call form is documented as an alias. Whether to deprecate it is decided at 1.0.
- **`completions_structured` stays as it is.** The OpenAI SDK's nearest twin, `chat.completions.parse()`, returns a `ParsedChatCompletion`, not the model instance. Reusing the name `parse` with a different return type would mislead.
- **Other services** keep their names:
  - `models.list()` already matches the SDK.
  - Voice's SDK twin would be a new `audio.transcriptions.create()` service. That is out of scope here.
  - Documents and ARCANA have no SDK twin.
- **Compatibility risk.** Low. Callers and `MagicMock`-based patches of `client.chat.completions` still work. Only code that patches the class attribute `ChatService.completions` directly sees a property instead of a function. Mention this in the CHANGELOG.

## 5. Transport

- **Generalise `post_chat_completion` / `apost_chat_completion`.**
  - Turn them into `post_generation` / `apost_generation`.
  - The body is already generic: url, body, stream, headers, policy. Only the name and the docstring are chat-specific.
  - Keep the old names as thin aliases, so chat and ARCANA stay untouched.
- **All three calls count as idempotent for 429 retry,** with the same reasoning as chat: a 429 means nothing was generated. For streams, the retry happens before the stream is handed out, never mid-stream (ADR-0006).
- **Body builders go in `_payloads.py`,** next to `build_chat_body`: `build_completion_body`, `build_response_body` and `build_message_body`. Sync and async share them. Parameters left at `None` are omitted, and `**kwargs` pass through.
- **No extra headers.** The session's Bearer auth is enough for `/messages`, as verified live.

## 6. Shared helpers: one reader for both paths

**`text_of(response)`** is extended. Its signature does not change, and the chat path works as before.
- **Input.** It accepts a dict or an SDK object. Anything with `model_dump()` is dumped first. That covers both openai and anthropic objects, which are pydantic models.
- **Shape detection:**
  - `chat.completion`: as today.
  - `text_completion`: `choices[0].text`.
  - `response`: join every `output_text` part of every `message` item.
  - `message` (Anthropic): join every `text` block.
- **Reasoning** items and blocks (`reasoning`, `thinking`) are skipped.
- **Empty results** log a warning and return `""`, exactly like chat today.

**`iter_text(stream)` / `aiter_text(stream)`** are new. They yield the text deltas of any stream, whether ours (dict chunks) or an SDK stream (event objects, dumped first):
- chat chunk: `choices[0].delta.content`;
- completion chunk: `choices[0].text`;
- Responses: `type == "response.output_text.delta"` gives `delta`;
- Messages: `type == "content_block_delta"` with `delta.type == "text_delta"` gives `delta.text`.

Everything else is skipped: usage chunks, `reasoning_text` / `thinking_delta`, `signature_delta`, and lifecycle events.

Both paths, same helper:

```python
r1 = client.responses.create(model=M, input="…")          # native → dict
r2 = client.openai.responses.create(model=M, input="…")   # OpenAI SDK → Response
assert text_of(r1) == text_of(r2)                         # same answer, either way

for piece in iter_text(client.messages.create(M, msgs, 512, stream=True)):
    print(piece, end="")
```

**`usage_of(response)`** (decided) returns `{"input_tokens", "output_tokens", "total_tokens"}` for all four shapes. It is groundwork for the roadmap's usage tracking.

## 7. Edge cases

- **Responses with `status: "incomplete"`** (the `max_output_tokens` budget ran out): `text_of` returns the partial text. This matches chat, where `finish_reason: "length"` is not an error either.
- **Reasoning models** spend budget on reasoning items and blocks. Docstrings repeat the existing `max_tokens` headroom advice from `completions_structured`.
- **Errors inside a stream (decided).** A Responses stream may send `response.failed` or an `error` event, and a Messages stream an `error` event. The raw stream yields them as dicts. `iter_text` raises `APIError` on them instead of silently stopping.
- **HTTP errors** (`{"detail": …}` or `{"error": {"message": …}}`) already go through `raise_for_status`. Add a test for the `/messages` 400 shape.

## 8. Tests

**Unit tests** need no network or key, per AGENTS.md:
- Body building: `None` values omitted, `kwargs` passed through, `max_tokens` required.
- The URL each service calls.
- 429 retry and `_rate_limits`, reusing the `test_transport_policy` patterns.
- Async twins via `tests/_async_fakes.py`.
- Stream parsing from recorded SSE fixtures for all three protocols: `event:` and `data:` lines, no `[DONE]`.
- `text_of` and `iter_text` on dicts, on openai SDK objects (`openai` is in the `test` extra; build them with `model_validate`), and on a stub with `model_dump()` standing in for anthropic objects. Reasoning items must be skipped.

**Live tests** are opt-in and never run in CI:
- Extend `tests/test_live_responses_route.py` (`SAIA_RESPONSES_LIVE`) to call the native service.
- Add `SAIA_MESSAGES_LIVE` and `SAIA_COMPLETIONS_LIVE` in the same pattern.
- Each checks the shape, the streaming end, and `text_of`.

## 9. Docs

- **`docs/implementation.rst`, OpenAI-compat table:**
  - add `responses.create()` and `completions.create()` (both "Works");
  - correct `images.generate()`, which works with `model="flux"` and returns base64 only, not "N/A".
- **`docs/implementation.rst`, new section:** the three native services, and the note that GWDG does not document `/responses` or `/messages`. It must also carry:
  - **The stateless Responses caveat, with its date.** Include the table from §2, headed "as of 2026-11-19". It applies to `client.openai.responses.create()` too.
  - **"Dicts, not objects."** The native services return plain dicts. For typed objects use the SDK path (`client.openai.responses.create()` → `Response`). Give the short reason from §3.
  - **The results of §2a,** dated in the same way.
- **`docs/api/`:** new autodoc pages `completions.rst`, `responses_api.rst` and `messages.rst`. Add `iter_text` to `responses.rst`.
- **README:** a row in "Supported Services" and a short Quick Start snippet.
- **AGENTS.md:** replace the `/v1/responses` "unsupported but seems to work" note with a pointer to the new module and its undocumented status.
- **CHANGELOG:** `[Unreleased]` entries under Added.
- **ADR-0008:** "Native wrappers for routes GWDG does not document". It records the dicts-not-models choice, stateless only, shared shape-agnostic helpers, and the rule that live tests guard these routes.

## 10. Phases

1. **No v0.10.2.** The catalogue update (f55005f) and the `jinja2` fix (e929de2) stay under `[Unreleased]` and ship with v0.11.0.
2. **Transport and `/completions`:** generalise the transport, add `CompletionsService` and its async twin, and teach `text_of` / `iter_text` the `text_completion` shape. This is the smallest route, so it proves the pattern.
3. **`/responses`:** `ResponsesService`, its twin, and the Responses shape in the helpers.
4. **`/messages`:** `MessagesService`, its twin, and the Anthropic shape in the helpers.
5. **Chat alignment (§4a):** `client.chat.completions.create()` and its async twin; docs and examples switch to it.
6. **Docs, ADR-0008 and live tests,** then release v0.11.0.

Each phase is its own commit (or a few) and passes every CI gate on its own.

## 11. Decisions (2026-11-19)

1. **Naming:** `.create()` everywhere. Existing services adopt it where an SDK twin exists, which in practice means chat (§4a).
2. **`usage_of()`:** add it now, as part of §6. It is small, and it makes the four usage-key spellings visible in one place.
3. **Functional wrappers:** not now. They are on the TODO list and not urgent.
4. **Errors inside a stream:** `iter_text` raises `APIError`.
5. **Release:** no v0.10.2. Everything ships together as v0.11.0 (§10).
