Implementation Details
======================

This page documents specific implementation decisions and their rationale.


ARCANA Default ID — Priority Chain
-----------------------------------

When ARCANA IDs are configured across multiple sources, the library
determines the ``"default"`` entry in the dict returned by
:func:`~saia_python.load_arcana_ids` using the following priority chain:

.. list-table::
   :header-rows: 1
   :widths: 10 30 60

   * - Priority
     - Source
     - Rationale
   * - 1
     - ``SAIA_ARCANA_ID`` in env / ``.env``
     - Environment-specific override. The ``.env`` file is per-deployment
       (development, staging, production) and takes precedence over
       static configuration.
   * - 2
     - ``[saia.arcana] default`` in ``config.toml``
     - Explicit default in the structured configuration file.
   * - 3
     - First element of ``[saia.arcana] ids`` in ``config.toml``
     - Implicit default: when no explicit default is declared, the first
       entry in the array is treated as primary.
   * - 4
     - First ``SAIA_ARCANA_ID_XX`` env var (insertion order)
     - Lowest priority. Numbered env vars are a fallback for environments
       where ``config.toml`` is unavailable.

All sources are merged into a single dict. The priority chain only
determines which value receives the ``"default"`` key:

.. code-block:: python

   from saia_python import load_arcana_ids

   ids = load_arcana_ids()
   # {
   #     'default': 'user/Primary-Arcana',      # from priority chain
   #     '0': 'user/First-Arcana',               # from config.toml ids array
   #     '1': 'user/Second-Arcana',              # from config.toml ids array
   #     'project_a': 'user/ProjectA-Arcana',    # from config.toml labels
   #     '01': 'user/Numbered-Arcana',           # from SAIA_ARCANA_ID_01
   # }


ARCANA Name vs Full ID
-----------------------

The SAIA platform distinguishes two identifier formats:

- **Name** (e.g. ``My-Arcana-abc123``) — used by the management REST API
  (``get``, ``upload``, ``delete_file``, ``generate_index``).
- **Full ID** (e.g. ``saiauser123/My-Arcana-abc123``, ``owner/name`` format) —
  used by the chat endpoint for RAG context injection.

The library handles this distinction transparently. Management methods
(:meth:`~saia_python.arcana.ArcanaService.get`,
:meth:`~saia_python.arcana.ArcanaService.upload`, etc.) accept either format
and extract the name portion via
:func:`~saia_python.arcana.extract_arcana_name`. The chat method passes the
full ID as-is.

Values from ``load_arcana_ids()`` can be passed directly to any method
without format conversion.


Owner Prefix Resolution
~~~~~~~~~~~~~~~~~~~~~~~

When ``load_arcana_ids()`` encounters an ARCANA ID without a ``/``
(i.e. a plain name like ``MyArcana`` instead of ``saiauser123/MyArcana``),
it automatically prepends the configured username:

.. code-block:: python

   # config.toml:
   # [saia]
   # username = "saiauser123"
   # [saia.arcana]
   # default = "MyArcana"

   ids = load_arcana_ids()
   # ids["default"] == "saiauser123/MyArcana"

The username is resolved from (in order): ``SAIA_USERNAME`` env var,
``SAIA_USERNAME`` in ``.env``, or ``[saia] username`` in ``config.toml``.

If an ID has no ``/`` and no username is configured, ``load_arcana_ids()``
raises a ``ValueError`` with a message indicating which IDs are missing
the owner prefix and how to set the username.


ARCANA Creation — UUID Suffix
-----------------------------

The SAIA API creates arcanas with the exact name provided. The web UI
appends a UUID4 suffix (e.g. ``MyArcana-a1b2c3d4-e5f6-...``) to avoid
name collisions. Since the API does not do this automatically, the library
provides client-side UUID generation via the ``append_uuid`` parameter:

.. code-block:: python

   # With UUID suffix (default) — mirrors web UI behavior
   result = client.arcana.create("MyArcana")
   # result["name"] == "MyArcana-a1b2c3d4-e5f6-7890-abcd-ef1234567890"

   # Without UUID suffix
   result = client.arcana.create("MyArcana", append_uuid=False)
   # result["name"] == "MyArcana"

The ``append_uuid=True`` default is deliberate: arcana names are global
within a user's namespace, and collisions produce opaque API errors.

Both ``create()`` and ``delete()`` accept an ``update_toml=True`` parameter
to automatically add or remove the arcana ID in ``config.toml``:

.. code-block:: python

   # Create and register in config.toml under [saia.arcana] ids
   client.arcana.create("MyArcana", update_toml=True)

   # Create and register under [saia.arcana.labels]
   client.arcana.create("MyArcana", update_toml=True, toml_label="project_a")

   # Delete and remove from config.toml
   client.arcana.delete("saiauser123/MyArcana-...", update_toml=True)


OpenAI Compatibility Layer
--------------------------

The ``create_openai_client()`` factory and ``SAIAClient.openai`` property
return an ``openai.OpenAI`` instance pointed at the SAIA base URL. This
enables direct use of the OpenAI Python SDK and ecosystem tools (RAGAS,
LangChain, instructor) without manual credential extraction.

The factory reuses the same resolution functions as ``SAIAClient``:

- ``load_api_key()`` for the API key
- ``resolve_base_url()`` for the base URL

The ``openai`` package is an optional dependency
(``pip install saia-python[openai]``). Accessing ``.openai`` without it
raises an ``ImportError`` with install instructions.

Endpoint compatibility:

.. list-table::
   :header-rows: 1
   :widths: 35 15 50

   * - OpenAI SDK Endpoint
     - Status
     - Notes
   * - ``chat.completions.create()``
     - Works
     - Streaming, tool calling
   * - ``chat.completions.parse()``
     - Works
     - Structured output from a Pydantic model
   * - ``completions.create()``
     - Works
     - Raw-text completion; native twin ``client.completions.create()``
   * - ``responses.create()``
     - Works
     - Stateless only (see `Native Generation Routes`_); native twin
       ``client.responses.create()``
   * - ``models.list()``
     - Works
     - Returns SAIA model IDs
   * - ``embeddings.create()``
     - Works
     - ``e5-mistral-7b-instruct``, ``multilingual-e5-large-instruct``, ``qwen3-embedding-4b``
   * - ``audio.transcriptions``
     - N/A
     - Use ``SAIAClient.voice`` instead
   * - ``images.generate()``
     - Works
     - Only with ``model="flux"``, which ``/models`` does not list; the image
       comes back as base64 (``b64_json``), never as a URL (checked
       2026-11-22)


Native Generation Routes
------------------------

Besides chat, SAIA answers on three more routes that generate text, and
saia-python wraps each of them natively, on the same transport as chat: the
429 retry policy, ``_rate_limits`` on every response dict (``rate_limits`` on a
stream), the typed errors, streaming, and an async twin on ``AsyncSAIAClient``.
The calls are named as in the vendor SDKs, so moving between the native call
and the SDK call changes one word.

.. list-table::
   :header-rows: 1
   :widths: 18 44 38

   * - Route
     - Native call
     - Format and SDK twin
   * - ``/completions``
     - ``client.completions.create(model, prompt, max_tokens=...)``
     - OpenAI's text completion; ``client.openai.completions.create()``
   * - ``/responses``
     - ``client.responses.create(model, input, instructions=...)``
     - OpenAI's Responses API; ``client.openai.responses.create()``
   * - ``/messages``
     - ``client.messages.create(model, messages, max_tokens, system=...)``
     - Anthropic's Messages API, which the OpenAI SDK cannot send

As of 2026-11-22, GWDG's documentation lists ``/completions`` but neither
``/responses`` nor ``/messages``. Both work and answer in their vendor formats
(checked live that day). The opt-in live checks in :doc:`testing` re-check all
three routes, and :doc:`ADR-0008 <adr/0008-native-wrappers-for-undocumented-routes>`
records the design.


Dicts, Not Objects
~~~~~~~~~~~~~~~~~~

The native services return the JSON as a plain dict, and a stream yields dict
chunks, as chat and ARCANA do. Typed objects come from the SDK path:
``client.openai.responses.create()`` returns an
``openai.types.responses.Response`` with ``.output_text`` and ``.usage``. Both
formats are large and grow with each vLLM release, and GWDG does not document
two of the three routes, so typed classes of our own would need constant
upkeep.

The same helpers read either kind of result: :func:`~saia_python.text_of` the
answer, :func:`~saia_python.iter_text` a stream's text, and
:func:`~saia_python.usage_of` the token counts.

.. code-block:: python

   from saia_python import iter_text, text_of

   native = client.responses.create(model="qwen3-30b-a3b-instruct-2507", input="Hello!")
   typed = client.openai.responses.create(model="qwen3-30b-a3b-instruct-2507", input="Hello!")
   print(text_of(native), text_of(typed))  # a dict and a Response, read alike

   text = iter_text(client.messages.create(
       "qwen3-30b-a3b-instruct-2507",
       [{"role": "user", "content": "Name three colours."}],
       max_tokens=64,
       stream=True,
   ))
   for piece in text:
       print(piece, end="")
   print(text.usage)  # the token counts the stream reported


``/responses`` Keeps No State
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenAI's Responses API can store a response on the server and build on it
later. On SAIA none of that works:

.. list-table::
   :header-rows: 1
   :widths: 28 36 36

   * - Feature
     - What it does at OpenAI
     - SAIA, as of 2026-11-19
   * - ``store: true``
     - keeps the response on the server
     - accepted, but nothing is retrievable afterwards
   * - ``previous_response_id``
     - continues a conversation without resending it
     - ``404 "Response with id … not found"``
   * - ``GET /responses/{id}``
     - fetches a stored response
     - ``404 {"detail": "Not Found"}``
   * - delete, cancel, ``background: true``, input-item listing
     - manage stored or running responses
     - not offered: they need a stored response or a ``GET`` route

This holds for ``client.openai.responses.create()`` as much as for the native
service. Send the whole conversation each time, as an ``input`` list, the way
chat sends ``messages``. The stateful fields still pass through ``**kwargs``
unchanged.


What Works on Each Route
~~~~~~~~~~~~~~~~~~~~~~~~

Checked live on 2026-11-19 with ``qwen3-30b-a3b-instruct-2507`` and
``deepseek-v4-flash-0731``; the reasoning row with
``deepseek-v4.1-flash-1017``:

.. list-table::
   :header-rows: 1
   :widths: 22 26 26 26

   * - Feature
     - ``/completions``
     - ``/responses``
     - ``/messages``
   * - Required fields
     - ``model``, ``prompt``
     - ``model``, ``input``
     - ``model``, ``messages``, ``max_tokens`` (400 without it)
   * - Tool calling: automatic, forced, streamed, round trip
     - n/a (no tools)
     - works
     - works
   * - Output that follows a JSON Schema
     - ``response_format`` depends on the model: enforced for qwen, not for
       deepseek
     - enforced, via ``text.format``
     - ``response_format`` is ignored; force a tool instead
   * - Reasoning
     - n/a
     - a separate ``reasoning`` output item
     - a separate ``thinking`` block
   * - ARCANA fields
     - not checked
     - ignored
     - ignored

ARCANA retrieval works only on ``/chat/completions``, so RAG stays on
:meth:`ArcanaService.chat <saia_python.arcana.ArcanaService.chat>`. Without
``max_tokens``, ``/completions`` stops after 16 tokens (seen 2026-11-20).


Dual API Design
---------------

Both calling styles (object-oriented and functional) are supported without
code duplication. The functional wrappers instantiate a temporary
``SAIAClient`` per call, which means each invocation creates a new
``requests.Session`` with its own TCP connection pool.

For detailed explanation and performance considerations, see
:doc:`architecture`.
