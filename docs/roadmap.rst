Roadmap
=======

This roadmap outlines planned features for positioning ``saia-python`` as
the foundational Python building block for the GWDG/KISSKI AI ecosystem.


Research Tooling (v0.4)
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


Ecosystem Integration (v0.5)
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
