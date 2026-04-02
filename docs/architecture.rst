Architectural Overview
======================

This page describes the internal structure of the package and the design
rationale behind the dual API (object-oriented and functional).


Repository Layout
-----------------

.. code-block:: text

   saia-python/
   ├── saia_python/                  # Main package
   │   ├── __init__.py               # Public API, version, functional wrappers
   │   ├── client.py                 # SAIAClient — composes all services
   │   ├── chat.py                   # ChatService — completions + streaming
   │   ├── voice.py                  # VoiceService — transcribe + translate
   │   ├── arcana.py                 # ArcanaService — RAG / knowledge bases
   │   ├── models.py                 # ModelsService — list available models
   │   ├── documents.py              # DocumentService — Docling conversion
   │   ├── openai_compat.py          # OpenAI SDK compatibility layer
   │   ├── auth.py                   # Credential and config discovery
   │   ├── rate_limits.py            # RateLimitInfo dataclass + parser
   │   ├── exceptions.py             # SAIAError hierarchy + raise_for_status
   │   └── _streaming.py             # Shared SSE iterator
   ├── tests/                        # Unit tests
   ├── docs/                         # Sphinx documentation (PyData theme)
   ├── examples/
   │   ├── saia_python_demo.ipynb    # Interactive demo
   │   └── config.toml.example       # Template for structured config
   ├── .github/workflows/            # CI/CD (tests + docs deployment)
   ├── pyproject.toml                # Package metadata + dependencies
   └── README.md


Module Layers
~~~~~~~~~~~~~

The package follows a four-layer architecture:

**Infrastructure** — shared utilities with no service-specific logic:

- ``auth.py`` — credential and configuration discovery across environment
  variables, ``.env``, ``.saia_api``, and ``config.toml``.
- ``exceptions.py`` — exception hierarchy and the single
  ``raise_for_status()`` implementation used by all service modules.
- ``_streaming.py`` — SSE (Server-Sent Events) line parser, shared by
  ``ChatService`` and ``ArcanaService``.
- ``rate_limits.py`` — parses ``x-ratelimit-*`` response headers into a
  ``RateLimitInfo`` dataclass.

**Service classes** — each module encapsulates one SAIA API surface:

- ``chat.py`` — ``ChatService``: chat completions with streaming support.
- ``voice.py`` — ``VoiceService``: audio transcription and translation.
- ``arcana.py`` — ``ArcanaService``: RAG knowledge base management and chat.
- ``models.py`` — ``ModelsService``: model listing.
- ``documents.py`` — ``DocumentService``: document conversion via Docling.

Each service receives a shared ``requests.Session`` and base URL from the
client. Services do not manage authentication or HTTP sessions.

**Composition** — wires infrastructure and services together:

- ``client.py`` — ``SAIAClient`` creates the authenticated session and
  lazily instantiates service classes as properties (``.chat``, ``.voice``,
  ``.models``, ``.arcana``, ``.documents``).

**Public surface** — the user-facing API:

- ``__init__.py`` — re-exports ``SAIAClient``, exception types, and
  configuration utilities. Defines the functional API as thin wrappers.


Dual API: OOP and Functional
-----------------------------

The library exposes two equivalent calling styles:

.. code-block:: python

   # Object-oriented
   client = SAIAClient()
   client.models.list_ids()
   client.chat.completions(model="...", messages=[...])

   # Functional
   from saia_python import list_model_ids, chat_completion
   list_model_ids()
   chat_completion(model="...", messages=[...])


Avoiding Code Duplication
~~~~~~~~~~~~~~~~~~~~~~~~~

All logic resides exclusively in the service classes. The functional API
consists of one-line wrappers that instantiate a temporary ``SAIAClient``
and delegate:

.. code-block:: python

   # __init__.py (simplified)
   def _make_client(api_key=None, base_url=None):
       return SAIAClient(api_key=api_key, base_url=base_url or DEFAULT_BASE_URL)

   def list_model_ids(*, api_key=None, base_url=None):
       return _make_client(api_key, base_url).models.list_ids()

The resulting call chain:

.. code-block:: text

   Functional wrapper (__init__.py)
       → SAIAClient (client.py)
           → ServiceClass (e.g. ChatService)
               → HTTP request via shared Session
                   → raise_for_status() (exceptions.py)
                   → iter_sse() for streaming (_streaming.py)

No HTTP logic, request construction, or error handling is duplicated.


Performance Tradeoff
~~~~~~~~~~~~~~~~~~~~

Each functional call creates a new ``SAIAClient`` and ``requests.Session``,
incurring a TCP handshake and TLS negotiation per call. The OOP style
reuses a single session with HTTP keep-alive:

.. code-block:: python

   # New session per call — acceptable for exploratory use
   for prompt in prompts:
       chat_completion(model="...", messages=[{"role": "user", "content": prompt}])

   # Shared session — recommended for batch processing
   client = SAIAClient()
   for prompt in prompts:
       client.chat.completions(model="...", messages=[{"role": "user", "content": prompt}])

This follows the same pattern as the ``requests`` library, where
``requests.get()`` creates an internal session while
``requests.Session().get()`` reuses one.

Use the functional API for interactive exploration and single calls.
Use ``SAIAClient`` when issuing multiple requests in sequence.
