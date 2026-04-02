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
     - N/A
     - Not available


Dual API Design
---------------

Both calling styles (object-oriented and functional) are supported without
code duplication. The functional wrappers instantiate a temporary
``SAIAClient`` per call, which means each invocation creates a new
``requests.Session`` with its own TCP connection pool.

For detailed explanation and performance considerations, see
:doc:`architecture`.
