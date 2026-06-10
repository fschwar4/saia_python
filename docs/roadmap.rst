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

**Structured output**:
  Integration with ``instructor`` for Pydantic-validated model responses.
  Convenience method ``client.chat.completions_structured(model, messages, response_model=...)``
  to eliminate patching boilerplate.

**Native embeddings service** (``saia_python/embeddings.py``):
  Direct wrapper around ``POST /embeddings`` with typed return values,
  complementing the OpenAI-compatible access that already works via
  ``client.openai.embeddings.create()``.

**Image generation service** (``saia_python/images.py``):
  Wrapper for ``POST /images/generations`` and ``POST /images/edits/``.
  Currently undocumented in the library.


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
