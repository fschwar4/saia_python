Tokenizers
==========

Tokenizer support for the GWDG open-weight models. Requires the optional
``[tokenizer]`` extra::

    pip install saia-python[tokenizer]

Why a built-in catalogue
-------------------------

The ``GET /models`` listing does **not** carry a repository link — its per-model
payload is ``id`` / ``name`` / ``input`` / ``output`` / ``owned_by`` /
``created`` / ``demand`` / ``status`` only. The mapping from a GWDG model id to
its upstream Hugging Face tokenizer is published only in the human-readable
`model catalogue <https://docs.hpc.gwdg.de/services/ai-services/chat-ai/models/index.html>`_,
so it is captured here in :data:`~saia_python.tokenizer.GWDG_MODEL_REPOS`.
:meth:`~saia_python.tokenizer.TokenizerService.available_repos` annotates the
*live* model list from that catalogue (proprietary external models, which have no
downloadable tokenizer, map to ``None``).

Tokenizers download — files only, never weights — into
``~/saia_python/tokenizers/`` by default (override per call or via the
``SAIA_TOKENIZER_DIR`` environment variable).

Authenticated downloads (``HF_TOKEN``)
--------------------------------------

Public tokenizers download anonymously, but a Hugging Face token lifts the Hub's
anonymous rate limit (the *"sending unauthenticated requests to the HF Hub"*
warning) and is required for gated repos. A token is resolved by
:func:`~saia_python.tokenizer.load_hf_token` from, in order: the ``HF_TOKEN`` /
``HUGGING_FACE_HUB_TOKEN`` / ``HUGGINGFACE_TOKEN`` environment variable, then a
``.env`` then ``.saia_env`` file in the working directory, then the home
directory — and is applied automatically by every download function.

First-time setup:

#. Create a *read* token at https://huggingface.co/settings/tokens .
#. Add it next to your SAIA key, in ``.env`` or ``.saia_env``::

       HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxx

It is then picked up automatically by every download.

A few catalogue repos are **gated** (e.g. ``google/medgemma-27b-it``, under
Google's Health AI terms). For those a valid token is not enough — you must also
accept the licence once on the model's Hugging Face page, signed in as the token
account; otherwise the download raises
:class:`~saia_python.tokenizer.GatedRepoAccessError` (HTTP 403) — an expressive
error carrying the licence URL and the exact setup steps. In a
:func:`~saia_python.tokenizer.download_all_tokenizers` run a gated model is
instead recorded as ``None`` and the batch continues; pass ``verbose=True`` to
see the licence hint.

Sizing a RAG corpus
-------------------

:func:`~saia_python.tokenizer.token_distribution` walks a directory recursively,
tokenizes every text file (and estimates a token cost for each image), and
returns per-file counts plus aggregate statistics — for sizing a RAG corpus
against a model's tokenizer (e.g. the embedding model ``qwen3-embedding-4b``,
which ARCANA's RAG pipeline uses internally).

API
---

.. automodule:: saia_python.tokenizer
   :members:
   :member-order: bysource
