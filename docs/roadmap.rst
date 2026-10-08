Roadmap
=======

This roadmap outlines planned features for positioning ``saia-python`` as
the foundational Python building block for the GWDG/KISSKI AI ecosystem.


Research Tooling (v0.5)
------------------------

**Batch processing**:
  ``client.chat.batch(prompts, model)`` — rate-limit-aware parallel
  inference with tqdm progress, automatic throttling, and checkpoint-based
  resume on failure.

**Experiment logging**:
  ``client.chat.completions(..., log_to="experiment")`` — log prompts,
  responses, latency, and token counts to JSON Lines, CSV, or SQLite.
  Essential for reproducible research workflows.

**Model comparison**:
  ``client.compare(models=["llama-3.3-70b", "qwen3-235b"], messages=[...])``
  — same prompt to multiple models with side-by-side output, latency,
  and token count. Useful for systematic evaluation.

**Usage tracking**:
  Cumulative quota tracking across a session or experiment.
  ``client.usage.summary()`` with alerts before quota exhaustion.

**Response caching**:
  ``client.chat.completions(..., cache=True)`` — local cache keyed by
  (model, messages, parameters) to avoid redundant API calls during
  iterative prompt engineering.


Ecosystem Integration (v0.6)
-----------------------------

**LangChain integration** (``saia_python.langchain``):
  ``SaiaChatModel`` and ``SaiaEmbeddings`` classes compatible with LangChain
  chains, agents, and LCEL. Optional dependency via
  ``pip install saia-python[langchain]``.

**LangChain ARCANA example** (``examples/langchain_arcana.ipynb``):
  Example-only notebook (no package dependency) covering the LangChain
  integration that SAIA's OpenAI-compatibility does *not* already provide for
  free: wrapping ARCANA RAG (``client.arcana.chat`` routed by ``arcana_id``) as
  a LangChain ``Runnable`` / retriever, then collapsing GWDG's verbose
  ``References:`` block into compact, numbered citations inside the chain via
  ``arcana_references.parse_arcana_references()``. Plain chat and tool calling
  are intentionally out of scope — those already work by pointing LangChain's
  ``ChatOpenAI`` at the SAIA ``base_url``. Serves as the low-commitment
  precursor to the native ``saia_python.langchain`` classes above, mirroring the
  example-only pattern of ``examples/openai_compatible_proxy.ipynb``.

**Native embeddings service** (``saia_python/embeddings.py``):
  Direct wrapper around ``POST /embeddings`` with typed return values,
  complementing the OpenAI-compatible access that already works via
  ``client.openai.embeddings.create()``.

**Image generation service** (``saia_python/images.py``):
  Wrapper for ``POST /images/generations`` and ``POST /images/edits/``.
  Currently undocumented in the library.


instructor (to evaluate)
------------------------

`instructor <https://python.useinstructor.com/>`_ (MIT) wraps an OpenAI-style
client: you pass ``response_model=SomeModel``, it checks the answer with
Pydantic and, when the check fails, asks the model again with the error
attached, up to ``max_retries``. The native
:meth:`~saia_python.chat.ChatService.completions_structured` already covers the
common case without it, because SAIA enforces the schema while generating. This
item is about checking instructor out and deciding whether it earns a place —
it is not a plan to build on it. Anything that comes of it would be an
additional, opt-in option, just as structured output is: the plain
``completions()`` workflow stays as it is, and instructor would sit next to
``completions_structured()`` rather than replace it.

**Status — to evaluate (no implementation planned)**:
  Try it against SAIA through ``client.openai`` before deciding anything.

**Questions to answer**:
  - Which entry point and mode work with SAIA's base URL? instructor now
    recommends ``from_provider`` (the quickstart still shows ``from_openai``),
    and its default OpenAI mode, ``Mode.TOOLS``, needs a model with tool-calling
    support. Is the answer schema-enforced in each mode?
  - What does it add beyond the native path? Candidates: asking again when a
    custom Pydantic validator fails (rules a JSON Schema cannot express, such as
    "end date after start date"), streaming partial objects
    (``create_partial``), and the parsed object together with the raw completion
    (``create_with_completion``).
  - What does asking again cost? Each retry is a full request against the
    per-minute limit, and its ``usage`` adds up.
  - How much can a dependency rest on it? instructor is widely used and actively
    released (1.17.0 on 2026-09-09), but its development rests largely on one
    person, its creator Jason Liu: 71 of the last 100 commits in its
    `repository <https://github.com/567-labs/instructor>`_ (as of 2026-10).

**Possible outcomes**:
  A tested quickstart example (docs only), an optional ``[instructor]`` extra,
  or nothing — whichever a real workload needs.


ARCANA incremental indexing (gated on backend)
-----------------------------------------------

Client passthroughs that become useful once the ARCANA server adds the matching
API support; documented here so the work is ready to wire up. Today the index
trigger is whole-arcana and ``FileOutSchema`` exposes no content hash, so the
library relies on the server skipping already-``INDEXED`` files — the
"upload only the changed files, then index once" pattern.

**Scoped and forced reindex**:
  ``generate_index(name, *, files=None, force=False)`` — once
  ``POST .../generate-index`` accepts ``{"files": [...]}`` / ``{"force": true}``,
  pass them through to (re)index only named files, or force a re-embed without
  re-uploading identical bytes. ``sync_directory`` would then hand its changed
  set (``uploaded`` + ``replaced``) to ``generate_index(files=...)`` for true
  per-file indexing instead of a whole-arcana trigger.

**Server-side change detection**:
  Once ``FileOutSchema`` carries a ``content_sha256``, offer a built-in
  hash-based ``select`` default for ``sync_directory`` (local SHA-256 vs. the
  remote hash), removing the caller's own manifest. Valuable only paired with
  scoped indexing.

**Priority (from a production consumer)**:
  Contract the skip-``INDEXED`` behavior and add ``force`` first; ship scoped
  ``files=`` and ``content_sha256`` together; de-prioritize per-file
  index-on-upload (it re-triggers once per file — the opposite of the
  batch-then-index pattern).


Unified transport-error exception (deferred)
--------------------------------------------

Now that control-plane calls carry a default timeout (a stalled call raises
``requests.exceptions.Timeout`` / ``ConnectionError`` instead of hanging),
callers catch *two* exception families: ``SAIAError`` for HTTP-status failures
and the raw ``requests.*`` transport errors. Wrapping the transport errors in a
``SAIAError`` subclass would collapse that to a single catch surface.

**Status — deferred (low value for the current consumer)**:
  The production ingestion consumer is ``requests``-native: it imports only
  ``SAIAClient`` (catches no ``saia_python`` exceptions), and its
  transport-drop detection is built directly on ``requests.exceptions.*`` plus
  stdlib socket errors, walking the ``__cause__`` / ``__context__`` chain with a
  regex fallback explicitly "for SDK-specific exception classes that don't
  subclass ``requests.exceptions.*``." It already defends against wrapped
  exceptions, so a unified type adds nothing for it — and a careless version
  could regress it. The proposal's real audience is *simple* consumers that
  would rather not touch ``requests`` at all.

**Requirements if revisited** (must be strictly backward-compatible):
  - **Dual-base the wrapper** — subclass *both* ``SAIAError`` and the underlying
    ``requests.exceptions.Timeout`` / ``ConnectionError``, so existing
    ``except requests.exceptions.*`` handlers keep matching.
  - **Preserve the cause chain** — raise via ``raise SAIA... from exc`` so
    consumers that walk ``__cause__`` / ``__context__`` still classify it.
  - **Leave ``generate_index``'s poll-deadline ``TimeoutError`` (stdlib)
    untouched** — consumers catch it directly; retyping it would silently break
    that branch.


Adaptive rate-limit pacing (deferred)
----------------------------------------

Reactive 429 retry shipped in v0.6.0 (see ADR-0006); *proactive* pacing — a
client-side throttle that spaces requests to stay under the limit so a 429 is
rarely hit at all — is deferred. Reactive retry remains the safety net, so most
workloads need nothing more.

**Status — deferred (no implementation planned)**:
  Only sustained, high-throughput batch jobs that constantly bounce off the
  per-minute limit would benefit; ordinary use is well served by the shipped
  reactive retry. Parked until a workload actually needs it.

**Constraint when revisited — the limit must be adaptable**:
  The account quota can change (a granted increase from, e.g., 30 to 60 per
  minute), so the pace target must **not** be hard-coded. It must be
  configurable *and* ideally derived from the server-reported
  ``x-ratelimit-limit-*`` headers — already parsed into ``RateLimitInfo`` on
  every response — so a quota increase is honored automatically, with no code or
  config change. Target a fraction (~90%) of the observed limit; an explicit
  ``target_rpm`` overrides it. Design detail lives in
  ``docs/proposals/rate-limit-handling.md`` (§8).
