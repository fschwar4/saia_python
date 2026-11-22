# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Native `/completions` service.** `client.completions.create(model, prompt, ...)`
  and its async twin `await aclient.completions.create(...)` send a raw-text
  completion through the same transport as chat: the 429 retry policy,
  `_rate_limits` on the dict (`stream.rate_limits` on a stream), the typed
  errors and `stream=True`. The model continues `prompt` verbatim, without a
  chat template. Set `max_tokens`: without it SAIA stops after 16 tokens
  (seen 2026-11-20). `build_completion_body()` builds the request body for
  callers that send it themselves. The unit tests replay a response and a
  stream recorded from SAIA on 2026-11-20.
- **Native `/responses` service (OpenAI's Responses API format).**
  `client.responses.create(model, input, instructions=..., max_output_tokens=...)`
  and its async twin use the same transport. As of 2026-11-20, GWDG's
  documentation does not list the route, but it works (checked live that
  day). Seen on 2026-11-19: it keeps no state (`previous_response_id` gets a
  404, so send the whole conversation as `input`), supports tool calling and
  an enforced `text.format` JSON schema, and ignores the ARCANA fields. When
  `max_output_tokens` runs out, the response comes back `incomplete` with
  the text so far. `build_response_body()` builds the request body. The unit
  tests replay responses and streams recorded on 2026-11-20, a reasoning
  model's among them.
- **Native `/messages` service (Anthropic's Messages format).**
  `client.messages.create(model, messages, max_tokens, system=...)` and its
  async twin use the same transport, without the Anthropic SDK; the OpenAI
  SDK cannot send this format at all. As of 2026-11-22, GWDG's
  documentation does not list the route, but it works (checked live that
  day). `max_tokens` is a required argument, since SAIA answers 400 without
  it. Seen on 2026-11-19: tool calling works (`tools` with an
  `input_schema`; for structured output, force a tool with `tool_choice`),
  `response_format` and the ARCANA fields are ignored, and reasoning models
  send a `thinking` block before the answer. When `max_tokens` runs out,
  `stop_reason` is `max_tokens` and the text so far comes back.
  `build_message_body()` builds the request body. The unit tests replay
  responses and streams recorded on 2026-11-22: a plain answer, a reasoning
  model's, a tool call and an answer cut off by `max_tokens`.
- **`client.chat.completions.create(...)`, as in the OpenAI SDK.** Chat gets
  `create()` like the new services, and the async twin is
  `await aclient.chat.completions.create(...)`. The native call and
  `client.openai.chat.completions.create(...)` now differ by one word. The
  form without `.create`, `client.chat.completions(...)`, does the same and
  keeps working, without a deprecation warning. The docs, docstrings and
  example notebooks use `.create()`. Unit tests cover both call forms, sync
  and async, and the ways to patch them listed under Changed.
- **One set of helpers for native results and SDK objects.**
  `text_of()` now also reads `text_completion` responses, Responses API
  objects (every `output_text` part of the message items, reasoning skipped,
  like the OpenAI SDK's `Response.output_text`) and Messages API objects
  (every `text` block, `thinking` skipped), and takes an SDK object directly,
  without `.model_dump()`. The new `iter_text()` and `aiter_text()` yield the
  text of a chat, completion, Responses or Messages stream, ours or an SDK's.
  They keep to the first choice, skip reasoning and thinking, tool-call
  arguments, usage chunks and lifecycle events, close the stream when done,
  and raise `APIError` when a chunk reports an error (including the
  Responses API's `error` and `response.failed` events and the Messages
  API's `error` event) instead of ending as if the answer were complete. The
  new `usage_of()` returns `input_tokens`, `output_tokens` and
  `total_tokens`, whichever spelling the response uses; it also reads a
  stream event that carries counts, such as a Responses stream's final
  `response.completed`. The iterator that `iter_text()` and `aiter_text()`
  return keeps the token counts the stream reports in `.usage`, so the text
  can stream live and the counts are there once it is through. A chat,
  completion or Responses stream reports them once, in its last chunk (seen
  2026-11-20); a Messages stream reports the input tokens in
  `message_start` and the final counts in `message_delta` (seen
  2026-11-22). Each report gives the counts so far, so a later one replaces
  an earlier one instead of being added. The iterator also keeps the last
  chunk it read in `.last`.
- **Streaming ARCANA answers, with anchors that resolve.**
  `iter_text(stream, references=True)` (and `aiter_text`) streams an ARCANA
  answer without GWDG's verbose `References:` block, and without the
  horizontal rule GWDG puts right under the answer's last line, which
  Markdown would render as a heading underline (`strip_separator=False`
  keeps the rule). Once the stream is through, `text.references` holds the
  parsed block: the same `ParsedReferences` that `parse_arcana_references()`
  gives for the complete answer. Underneath, the new `ReferencesSplitter`
  works on plain text deltas (`feed()`, `flush()`, `result`), so a proxy
  that rewrites raw SSE lines can use it as well. It holds text back only
  while it could still become the marker, the rule or an anchor, so the
  answer streams without a fixed delay, and it never splits an anchor such
  as `[RREF2]` or `[RREF2, RREF5]` between two pieces. `ParsedReferences`
  keeps its fields and gains read-only properties: `answer` and `separator`
  split the prose, so `answer + separator + references_block` is the whole
  content; `anchors` lists the numbers the prose cites; `by_number` maps
  every number in the block to its own entry, with its own distance and
  page; `dangling` lists cited numbers the block does not have, a hint at a
  made-up citation. `split_compound_anchors()` rewrites `[RREF2, RREF5]` as
  `[RREF2] [RREF5]`, and `REFERENCES_ANCHOR_RE` matches both forms.
- **Tokenizer catalogue: four more GWDG models** — `eurollm-22b-instruct-2512`,
  `deepseek-v4.1-flash-1017`, `glm-5.3` and `mistral-large-4-1t-a52b` now
  resolve to their Hugging Face repositories. All four are in GWDG's live
  `/models` listing as of 2026-11-19. EuroLLM's repository comes from GWDG's
  model catalogue. The other three are not in the catalogue yet, so they map to
  the vendors' official repositories whose names match the live `/models` name.
  For all four, the raw-text token count matches the `prompt_tokens` that
  SAIA's `/completions` reports, except that SAIA adds a start token for Mistral.
- **Repository hygiene test** (`tests/test_public_repo_hygiene.py`). Tracked
  files must not contain absolute home-directory paths or rule numbers copied
  from other repositories' agent instructions. Notebooks must use the generic
  `Python 3` kernel name.
- **Rate-limit fields for SAIA's current header scheme.** `RateLimitInfo`, and
  with it `_rate_limits` and `stream.rate_limits`, gains `limit_10s`,
  `remaining_10s`, a reset per window (`reset_10s`, `reset_minute`,
  `reset_hour`, `reset_day`, `reset_month`), `retry_after` and
  `exhausted_windows()`. The earlier fields stay, so existing keys keep
  working. `print(client.get_rate_limits())` shows each window's reset and the
  `Retry-After`. `get_rate_limits()` takes an optional `model=`.
- **Live rate-limit check**, opt-in:
  `SAIA_RATE_LIMITS_LIVE=1 pytest tests/test_live_rate_limits.py` fails when
  SAIA's rate-limit headers no longer parse. The unit tests of the normal path
  (chat, streaming, the async transport) now use headers recorded from SAIA on
  2026-11-19, so a renamed header fails a test there too.
- **Live checks for the native routes**, opt-in:
  `SAIA_COMPLETIONS_LIVE=1 pytest tests/test_live_completions_route.py` and
  `SAIA_MESSAGES_LIVE=1 pytest tests/test_live_messages_route.py` call the
  native services against SAIA, plain and streamed, and check the response
  shape, how the stream ends and what `text_of()` reads. The `/responses`
  check (`SAIA_RESPONSES_LIVE`) now does the same through
  `client.responses.create()`, next to its raw request. None of them runs in
  CI.

### Changed

- Docs, docstrings, tests and examples describe downstream consumers
  generically. Notebook kernel metadata uses `Python 3`.
- **The shared transport has a route-neutral name.** `post_chat_completion`
  and `apost_chat_completion` are now `post_generation` and
  `apost_generation`, since `/completions` and `/responses` use them too.
  The old names stay
  as aliases, without a deprecation warning, and `saia_python.aio` exports
  both.
- **`client.chat.completions` is an object, built once per service.**
  `ChatService.completions` is no longer a method but a
  `functools.cached_property` that returns a `ChatCompletions` object (on
  the async client an `AsyncChatCompletions`). Calls work as before. To mock
  chat calls in a test, patch `create`: on one client with
  `patch.object(client.chat.completions, "create", …)`, on every client with
  `patch.object(ChatCompletions, "create", …)`. Either catches both call
  forms and `completions_structured()`. Replacing the whole object on the
  instance, `patch.object(client.chat, "completions", …)`, works too. A patch
  of `ChatService.completions` on the class misses a service that has
  already built its object, and fails with `autospec=True`.
  `inspect.iscoroutinefunction(aclient.chat.completions)` is now `False`;
  where code checks that, pass `aclient.chat.completions.create`.
- **`text_of()` logs a tool call at DEBUG, not as a warning.** In a tool loop
  a response that calls a tool instead of answering is the expected answer,
  yet each one logged a warning (`first choice has empty content;
  finish_reason='tool_calls'`), which Python prints to stderr even without a
  logging setup. Now it logs `text_of: no text, the response calls
  get_weather` at DEBUG, for chat, Responses API and Messages API objects
  alike. A truncated tool call (`finish_reason: "length"`,
  `status: "incomplete"`, `stop_reason: "max_tokens"`) and every other empty
  answer keep the warning.

### Fixed

- **ARCANA references from PDF sources are parsed.** GWDG lists a PDF chunk
  as `[RREF1] <name>.pdf p.21,y:413 (0.688)`, with the page and the position
  on it (seen 2026-11-21). `REFERENCES_ENTRY_RE` accepted only
  `<name>.md (<distance>)`, so `parse_arcana_references()` found no
  references at all in such an answer. It now takes any file type, file
  names with spaces and the optional position, which `ArcanaReference` keeps
  in the new fields `page` and `y` (`None` for markdown sources). Markdown
  entries parse as before.
- **Rate-limit data is back, and the 429 retry waits as long as SAIA asks.**
  SAIA's gateway now sends `x-ratelimit-{limit,remaining,reset}-requests-{10s,hour,day}`
  and, on a 429, `Retry-After` (seen 2026-11-19). saia-python knew only the
  earlier names (`x-ratelimit-{limit,remaining}-{minute,hour,day,month}` and
  `ratelimit-reset`). So `_rate_limits`, `stream.rate_limits` and
  `get_rate_limits()` came back empty, and every 429 got the blind fallback of
  up to two 31-second waits. Both schemes are now parsed. The retry waits for
  `Retry-After` first, then for the reset of the exhausted window, and still
  fails fast when the wait would exceed `max_waiting_time`. Checked live: the
  eleventh request of a burst now waits about 10 seconds and then goes through.
- **`get_rate_limits()` works again.** Its probe, a bodiless
  `GET /chat/completions`, now gets `405` and no rate-limit headers: SAIA sends
  them only for requests that name a served model. The probe is now a
  `POST /chat/completions` whose body holds only `model`, which SAIA rejects
  with 400 before generating anything. It counts as one request. The model
  defaults to a served text model from `GET /models`, looked up once per
  client. A probe that comes back without headers now logs a warning instead
  of returning empty limits silently.
- **Error messages show the server's text instead of raw JSON.** SAIA's model
  gateway now answers errors with an OpenAI-style `{"error": {"message": …}}`
  body, and its API gateway answers auth errors with `{"message": …}`. The
  exceptions now take their message from these fields, as they already did
  from `{"detail": …}`. `response_body` still holds the raw body.
- **The `[tokenizer]` extra now installs `jinja2`.** transformers pulls it only
  through its own `[chat-template]` extra. Without it, `chat_template_tokens`
  could not apply the model's chat template and fell back to a plain
  `role: content` render, noting this in `ChatTokenCount.warnings`, so its
  counts left out the template's special tokens. Development installs never
  showed this because Sphinx and Jupyter bring `jinja2` along. With `jinja2`
  installed, the counts for five GWDG models (qwen3-30b-a3b-instruct-2507,
  EuroLLM, GLM 5.3 Flash, Mistral Large 4, DeepSeek V4.1) match the chat
  `prompt_tokens` SAIA reports exactly (checked 2026-11-19).

## [0.10.1] — 2026-10-09

### Added

- **Tokenizer catalogue: four newer GWDG models** — `deepseek-v4-flash-0731`,
  `glm-5.3-flash`, `qwen3.8-27b` and `qwen3-coder-next` now resolve to their
  Hugging Face repositories, taken from GWDG's model catalogue on 2026-10-09.
  DeepSeek V4 ships no Jinja chat template, so `chat_template_tokens` falls back
  to a plain `role: content` render with a warning for it; raw-text counts are
  unaffected. Loading the GLM 5.3 Flash tokenizer needs transformers 5. The 11
  catalogue models GWDG no longer serves, among them the three retired on
  2026-10-08, stay listed in a block of their own, so their ids still resolve.

### Fixed

- **Examples no longer name retired models.** GWDG retired `openai-gpt-oss-120b`,
  `devstral-2-123b-instruct-2512`, `mistral-medium-3.5-128b` and
  `apertus-70b-instruct-2509` on 2026-10-08, and requests naming them now fail;
  `llama-3.3-70b-instruct` had already gone. The README, the quickstart, the
  docstrings and the example notebooks now use `deepseek-v4-flash-0731` for chat,
  ARCANA and tool calling, and Gemma 4 / Qwen 3.6 for the tokenizer examples
  (DeepSeek V4 has no chat template, and the Qwen 3.5 / 3.6 templates reject a
  system prompt without a user turn). `examples/arcana_frontmatter_repro.py`
  defaults to `deepseek-v4-flash-0731`; its committed JSON captures and notebook
  outputs stay as recorded on 2026-06-10 with `openai-gpt-oss-120b`.

## [0.10.0] — 2026-10-09

### Added

- **Structured output** — `client.chat.completions_structured(model, messages,
  response_model)` (sync and async) sends a Pydantic v2 model's JSON Schema as a
  `json_schema` `response_format` and returns a validated instance. SAIA
  enforces the schema on the server, so there is no retry loop; this replaces
  the roadmap's planned `instructor` integration. An unusable answer raises the
  new `StructuredOutputError`, which keeps the response and its `usage` — most
  often a reasoning model that spent its `max_tokens` thinking (`content: None`,
  `finish_reason: "length"`). The building blocks `response_format_for()` and
  `parse_structured()` are exported for callers who also need the raw response.
  Pydantic stays optional: the package imports it only when `parse_structured()`
  runs, and the `[test]` extra now lists `pydantic>=2`. Opt-in live check:
  `SAIA_STRUCTURED_LIVE=1 pytest tests/test_live_structured.py`.
- **`AGENTS.md`** — a tool-neutral contributor/agent guide (package layout, CI
  gates, release process). Read natively by agent tools that support `AGENTS.md`,
  and by Claude Code via a thin **`CLAUDE.md`** that imports it (`@AGENTS.md`).
  Per-machine notes stay in a gitignored `CLAUDE.local.md`; `.gitignore` now
  allows a shared `.claude/settings.json` while keeping personal
  `.claude/settings.local.json` and `.claude/worktrees/` out of git.
- **Opt-in live check for SAIA's `/v1/responses` route**
  (`tests/test_live_responses_route.py`) — GWDG documents the Responses API as
  unsupported, yet the route currently answers; the test tracks that against the
  real service and is skipped unless `SAIA_RESPONSES_LIVE=1` is set.
- **Test coverage for the trailing stream usage chunk** — SAIA ends every chat
  stream with a chunk whose `choices` is empty but which carries the token
  `usage`; `tests/test_streaming.py` and `tests/test_async_streaming.py` now
  check that the sync and async streams pass it through unchanged.
- **uv `dev` dependency group** (`ipykernel`) — lets a uv-managed `.venv` run
  the example notebooks. pip installs are unaffected; `uv.lock` stays untracked.

## [0.9.0] — 2026-07-09

### Added

- **Native async transport** behind a new `[async]` extra
  (`pip install saia-python[async]`, pulls `httpx`). New `saia_python.aio`
  module: `AsyncSAIAClient` + `AsyncChatService` / `AsyncArcanaService` /
  `AsyncModelsService`, the `httpx.AsyncClient` twins of the sync data plane —
  chat completions and ARCANA RAG `chat` (streaming + non-streaming),
  `get_rate_limits`, and `health_check`. Use it as an async context manager;
  `from saia_python import AsyncSAIAClient` resolves lazily so importing the
  package never pulls `httpx` for sync-only users. See ADR-0007.
  - **The retry brains are shared, not copied.** `aexecute` /
    `apost_chat_completion` reuse `RetryPolicy` / `_plan` / `_jitter` /
    `resolve_retry` / `parse_rate_limits` verbatim, so the async path honours the
    same 429 policy (ADR-0006) as the sync path and the two cannot drift. The
    `retry` keyword works identically (`retry=False` fails fast; a `RetryPolicy`
    tunes it).
  - **`AsyncSSEStream`** owns the `httpx` `client.stream(...)` context, retrying
    an initial 429 *before* the body is exposed (never mid-stream). Two
    consumption modes: `async for chunk in stream` (decoded dicts; raises on an
    error status) or `async for line in stream.aiter_lines()` (raw lines, no
    raise — lets a gateway frame upstream errors itself).
- **Informative 429 errors** (`format_rate_limit_error`, exported). When retry is
  off or the budget is spent, `RateLimitError` now carries a human-readable
  message — which window was hit, when it resets, and how to auto-retry — instead
  of only the bare server string. Shared by both transports (raised from
  `raise_for_status`).
- **Pure request builders** (`saia_python._payloads`, re-exported at top level):
  `build_chat_body`, `apply_arcana_fields`, `arcana_chat_headers`, and the
  `INFERENCE_SERVICE` constant. Transport-free, so the sync services, the async
  services, and external gateways (e.g. a proxy) share **one** definition of
  the three-part ARCANA injection invariant (`enable-tools` + `arcana.id` body
  fields + the `inference-service` header) — defined and unit-tested once.

### Changed

- **Every `SAIAError` now carries `status_code` + `response_body`** (previously
  only `APIError` did). Lets a caller reframe the exact upstream response.
  `RateLimitError` keeps its `rate_limits` attribute (unchanged signature).
- **`raise_for_status` is transport-agnostic** — it accepts a `requests.Response`
  (honouring `.ok`) or an `httpx.Response` (deciding success from `status_code`),
  so one implementation serves both paths. No behaviour change for sync callers.
- The `test` extra now installs `[async]` too, so CI exercises the async suite.

### Notes

- Async covers the data plane + read-only control-plane calls. File
  upload/index/sync, voice, and document conversion stay **sync-only** on
  `SAIAClient` (batch/admin work, blocking file I/O, no concurrency benefit). See
  ADR-0007 for the scope rationale.
- Tests: +42 async tests (`test_async_transport` / `_streaming` / `_arcana` /
  `_chat` / `_client`, `test_payloads`, `test_rate_limit_message`); the suite
  grows 198 → 240 and stays `mypy`- and `ruff`-clean.

## [0.8.0] — 2026-06-28

### Added

- `ArcanaService.delete_files(name, file_names, *, verbose=False, on_result=None)`
  — batch-delete an explicit list of files from an arcana by name, the
  counterpart to `delete_file`. Reuses the shared `_run_file_batch` executor
  (per-file error capture, progress bar, `on_result`, uniform
  `{"file", "status", ["error"]}` entries), so one failed/timed-out file no
  longer aborts the rest. File names are validated as flat (no `/`) up front and
  the whole batch is refused **atomically** if any contains a path separator —
  guarding against a silent wrong-file delete through the `Path`-based executor.
- `ArcanaService.recreate(name, *, update_toml=False)` — wipe an entire arcana
  in two API calls (`delete` + `create(append_uuid=False)`), recreating it empty
  with the **same `owner/name-uuid` ID** so a downstream pin (e.g. a manifest)
  stays valid. Raises `APIError` if creation fails after the delete already
  landed (the arcana is then gone — the message says so explicitly). The
  minimal-call alternative to deleting thousands of files one `delete_file` at a
  time.

## [0.7.0] — 2026-06-22

### Added

- Tokenizer support for the GWDG open-weight models, behind a new optional
  `[tokenizer]` extra (`pip install saia-python[tokenizer]`:
  `transformers` + `huggingface-hub` + `tiktoken` + `sentencepiece`). New
  `saia_python.tokenizer` module and `client.tokenizers` service:
  - `GWDG_MODEL_REPOS` / `resolve_repo()` / `repo_url()` map a GWDG model id (or
    display name, or a full `org/name` repo) to its Hugging Face tokenizer
    repository. The catalogue is required because `GET /models` does **not**
    expose a repository link — its per-model payload is
    `id`/`name`/`input`/`output`/`status`/`demand` only — so
    `client.tokenizers.available_repos()` annotates the live model list from the
    catalogue (proprietary external models map to `None`).
    The registry includes the embedding model `qwen3-embedding-4b` (the model
    ARCANA's RAG pipeline uses internally).
  - `download_tokenizer()` / `download_all_tokenizers()` fetch only the
    tokenizer files (never the weights) into `~/saia_python/tokenizers/` by
    default — overridable per call or via the `SAIA_TOKENIZER_DIR` env var —
    and tolerate per-model failures. `load_tokenizer()` loads via
    `transformers.AutoTokenizer` (process-cached). `load_hf_token()` resolves a
    Hugging Face token from `HF_TOKEN` (and aliases) or a `.env` / `.saia_env`
    file, applied automatically to downloads for higher rate limits and gated
    repos. A gated repo (e.g. `google/medgemma-27b-it`) raises an expressive
    `GatedRepoAccessError` from `download_tokenizer()` / `load_tokenizer()` —
    carrying the licence URL and setup steps — and is recorded as `None` (with a
    `verbose=True` hint) in a `download_all_tokenizers()` batch.
  - `chat_template_tokens()` applies a model's chat template to a
    `role`/`content` conversation (the system prompt, and optionally the user
    turn, may be read from a `.txt`/`.md` file) and returns a `ChatTokenCount`
    with the templated length, the raw-text length, the special/structural-token
    **overhead** (absolute, plus relative to the text and as a share of the full
    prompt), and the **subword fertility**. It is tolerant: a missing user turn
    (or any shape a strict template rejects) degrades to a best-effort count with
    a recorded warning rather than raising. `chat_template_length()`,
    `special_token_overhead()` and `subword_fertility(include_special=…)` are
    thin wrappers; the flag selects whether fertility counts the template's
    special/structural tokens.
  - `token_distribution()` walks a directory recursively, tokenizes every text
    file as raw content and estimates a token cost for each image, and returns a
    `TokenDistribution` (per-file `FileTokenCount` rows plus aggregate stats /
    histogram) — for sizing a RAG corpus against a model's tokenizer.
  - `count_tiktoken_tokens()` covers the externally hosted OpenAI models
    (GPT-5.x, o3, …), which have no downloadable tokenizer, via `tiktoken`.
  - The heavy libraries are imported lazily, so importing `saia_python` never
    requires the extra; the offline test suite exercises the counting logic
    against an injected fake tokenizer.
  - Worked example: `examples/tokenizer_features.ipynb` — a notebook that
    exercises every public entry point of the feature, with an idempotent
    install cell for the `[tokenizer]` extra.
- `examples/arcana_frontmatter_repro.py` — self-contained, library-independent
  reproduction (for the GWDG ARCANA team) showing that the YAML front matter of
  an uploaded markdown file does not survive retrieval: the `References:` block
  returns the chunk body verbatim but strips the metadata header, and no
  response field carries it. The test header mirrors the documented Docling
  "Markdown Plus" metadata-header example field for field. Verified 2026-06-10
  against ARCANA API 0.4.18 via both the OpenAI SDK and a plain HTTP POST; the
  stored file itself — see the `/download` endpoint — still contains the front
  matter. The raw responses are saved as
  `examples/arcana_frontmatter_response_*.json` (committed as frozen evidence),
  and the companion notebook `examples/arcana_frontmatter_repro.ipynb` walks
  the same steps interactively with the full response JSON shown per step.

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

[Unreleased]: https://github.com/fschwar4/saia_python/compare/v0.10.1...HEAD
[0.10.1]: https://github.com/fschwar4/saia_python/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/fschwar4/saia_python/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/fschwar4/saia_python/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/fschwar4/saia_python/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/fschwar4/saia_python/compare/v0.6.0...v0.7.0
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
