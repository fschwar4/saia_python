Tokenizers
==========

Download the open-weight models' tokenizers and measure prompts **offline**:
token counts, the special/structural-token overhead a chat template adds, the
subword fertility of your text, and the token distribution across a whole RAG
corpus. This is a local capability built on Hugging Face ``transformers``; it
talks to the Hugging Face Hub, not the SAIA API, so it needs no SAIA key.

Availability
------------

The feature lives in :mod:`saia_python.tokenizer` and is an **opt-in extra** so
the heavy libraries never burden a plain install::

    pip install saia-python[tokenizer]

That pulls ``transformers`` (chat-template engine), ``huggingface-hub``
(downloads), ``tiktoken`` (the OpenAI encodings), and ``sentencepiece``. The
imports are lazy: importing ``saia_python`` without the extra still works — only
the tokenizer calls require it, and they raise a clear ``ImportError`` pointing
at the extra if it is missing.

Why a built-in catalogue is needed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The SAIA ``GET /models`` listing says *which* models exist but **not where each
tokenizer lives**. Its per-model payload is ``id`` / ``name`` / ``input`` /
``output`` / ``status`` / ``demand``, with no repository link. The GWDG model
catalogue publishes the Hugging Face repositories only in human-readable form.
:data:`~saia_python.tokenizer.GWDG_MODEL_REPOS` captures that mapping, and
:meth:`TokenizerService.available_repos
<saia_python.tokenizer.TokenizerService.available_repos>` annotates the *live*
model list with it (proprietary external models, e.g. GPT-5.x, o3, … map to
``None``; for those, use ``tiktoken`` instead).

Tokenizer files are cached under ``~/saia_python/tokenizers/`` by default,
overridable per call (``cache_dir=``) or globally via the ``SAIA_TOKENIZER_DIR``
environment variable. Only the *tokenizer* files are fetched — never the model
weights — so a download is a few megabytes, not gigabytes.

Authenticated and gated downloads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Set an ``HF_TOKEN`` (in the environment or a ``.env`` / ``.saia_env`` file beside
your SAIA key) for higher Hub rate limits;
:func:`~saia_python.tokenizer.load_hf_token` resolves it automatically. A few
catalogue repos are **gated** (e.g. ``google/medgemma-27b-it``, under Google's
Health AI terms): a token alone is not enough, but one must also accept the licence
once on the model's Hugging Face page, signed in as the token account. Otherwise
the download raises an expressive
:class:`~saia_python.tokenizer.GatedRepoAccessError` carrying the licence URL and
the exact setup steps; in a batch download the model is recorded as ``None`` and
the run continues.

Capabilities
------------

Counting chat-template tokens
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:func:`~saia_python.tokenizer.chat_template_tokens` applies a model's own chat
template to a ``role``/``content`` conversation and returns a
:class:`~saia_python.tokenizer.ChatTokenCount`. The system prompt (and,
optionally, the user turn) may be given inline **or read from a ``.txt`` /
``.md`` file**. It is deliberately tolerant: a missing user turn, an empty
conversation, or any shape a strict template rejects degrades to a best-effort
count with a recorded warning rather than raising.

The result separates the raw text from the template's scaffolding:

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Field
     - Meaning
   * - ``num_tokens``
     - Full chat-templated length, **including** special/structural tokens
       (BOS/EOS, role markers such as ``<|im_start|>``, the generation prompt).
   * - ``num_text_tokens``
     - Tokens from the raw message *content* alone (no special tokens).
   * - ``overhead_tokens``
     - ``num_tokens - num_text_tokens`` — what the template's scaffolding adds.
   * - ``overhead_ratio_text``
     - Overhead **relative to the text tokens** (``overhead / num_text_tokens``).
   * - ``overhead_ratio_total``
     - Overhead as a **share of the templated total**
       (``overhead / num_tokens``).
   * - ``fertility`` / ``fertility_with_special``
     - Subword fertility (tokens per word) of the raw text, and of the full
       templated prompt.

.. code-block:: python

   from saia_python import chat_template_tokens

   r = chat_template_tokens(
       "openai-gpt-oss-120b",
       system="You are a careful assistant. Cite sources.",
       user="Summarise the attached report.",
   )
   print(r.num_tokens, "tokens;", r.overhead_tokens, "from special tokens")
   print(f"overhead is {r.overhead_ratio_total:.0%} of the templated total, "
         f"{r.overhead_ratio_text:.0%} on top of the text")
   print("subword fertility:", round(r.fertility, 3))

   # The system prompt may instead be read from a file:
   r = chat_template_tokens("openai-gpt-oss-120b", system_file="system_prompt.md")

:func:`~saia_python.tokenizer.chat_template_length`,
:func:`~saia_python.tokenizer.special_token_overhead`, and
:func:`~saia_python.tokenizer.subword_fertility` (with an ``include_special``
flag) are thin wrappers when you only need one number.

Sizing a RAG corpus
~~~~~~~~~~~~~~~~~~~~~

:func:`~saia_python.tokenizer.token_distribution` walks a directory recursively,
tokenizes every text file (and estimates a token cost for each image), and
returns a :class:`~saia_python.tokenizer.TokenDistribution`: per-file counts plus
aggregate statistics (total, mean, median, percentiles, and a breakdown
``by_kind()``). Useful for sizing a knowledge base against a model's tokenizer;
for example the embedding model ``qwen3-embedding-4b``, which ARCANA's RAG
pipeline uses internally.

.. code-block:: python

   from saia_python import token_distribution

   dist = token_distribution("path/to/markdown", "qwen3-embedding-4b")
   print(dist.summary())
   print(dist.by_kind())     # tokens grouped by text vs. image

External OpenAI models
~~~~~~~~~~~~~~~~~~~~~~~~

The externally hosted, proprietary models (GPT-5.x, o3, …) have no downloadable
tokenizer. :func:`~saia_python.tokenizer.count_tiktoken_tokens` counts their
tokens through ``tiktoken`` instead, using
:data:`~saia_python.tokenizer.OPENAI_TIKTOKEN_ENCODINGS`.

From a client
~~~~~~~~~~~~~

Everything above is also reachable from a :class:`~saia_python.SAIAClient` via
``client.tokenizers`` (a :class:`~saia_python.tokenizer.TokenizerService`), which
additionally knows the live model list — e.g.
``client.tokenizers.download_all()`` downloads every open-weight model's
tokenizer, and ``client.tokenizers.available_repos()`` shows the id → repository
mapping.

See also
--------

- :doc:`api/tokenizer`: the complete API reference for every function and class.
- ``examples/tokenizer_features.ipynb``: a runnable notebook exercising every
  entry point end to end.
