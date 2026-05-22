Getting Started
===============

Installation
------------

.. code-block:: bash

   pip install saia-python

Or install from source:

.. code-block:: bash

   git clone https://github.com/AvorMedicalIntelligence/saia-python.git
   cd saia-python
   pip install -e .


Authentication
--------------

The library resolves the API key automatically from the following sources,
checked in order:

1. ``SAIA_API_KEY`` environment variable
2. ``.saia_api`` file (current directory, then home directory) containing the raw key
3. ``.env`` file (current directory, then home directory) with ``SAIA_API_KEY=...``

API keys are obtained through the `KISSKI LLM Service booking page <https://kisski.gwdg.de/leistungen/2-02-llm-service/>`_.


Username
--------

The username corresponds to your Academic Cloud account and serves as the
owner prefix in ARCANA IDs (e.g. ``saiauser123`` in ``saiauser123/My-Arcana``).
It can be set via the ``SAIA_USERNAME`` environment variable, ``.env``, or
``config.toml``:

.. code-block:: python

   from saia_python import load_username

   username = load_username()


ARCANA IDs
----------

ARCANA IDs are resolved from ``.env``, ``config.toml``, and environment
variables via :func:`~saia_python.load_arcana_ids`.

Use ``config.toml`` for multiple IDs:

.. code-block:: toml

   [saia.arcana]
   default = "username/My-Default-Arcana"
   ids = ["username/First-Arcana", "username/Second-Arcana"]

Or set a single default in ``.env``:

.. code-block:: text

   SAIA_ARCANA_ID=username/My-Arcana

.. code-block:: python

   from saia_python import load_arcana_ids

   arcana_ids = load_arcana_ids()
   # {'default': 'username/My-Arcana', '0': 'username/First', ...}

The full priority chain is documented in :doc:`implementation`.
The distinction between ``.env`` and ``config.toml`` is described in
:doc:`configuration`.

.. note::

   Management endpoints (``get``, ``upload``) accept both the full
   ``owner/name`` format and the plain name. The owner prefix is stripped
   automatically. The chat endpoint requires the full ``owner/name`` format.


OOP Interface
-------------

.. code-block:: python

   from saia_python import SAIAClient

   client = SAIAClient()

   # Connectivity + auth check (combines /models GET with the ARCANA
   # heartbeat). Returns bool by default; verbose=True returns a
   # diagnostic dict listing which leg succeeded/failed.
   client.health_check()
   client.health_check(verbose=True)

   # Models
   client.models.list_ids()

   # Chat completion
   client.chat.completions(
       model="meta-llama-3.1-8b-instruct",
       messages=[{"role": "user", "content": "Hello!"}],
   )

   # Streaming
   for chunk in client.chat.completions(
       model="meta-llama-3.1-8b-instruct",
       messages=[{"role": "user", "content": "Count to 5."}],
       stream=True,
   ):
       choices = chunk.get("choices", [])
       if choices:
           print(choices[0].get("delta", {}).get("content", ""), end="")

   # Voice AI
   client.voice.transcribe("audio.wav", language="de")
   client.voice.translate("audio.wav")

   # ARCANA (RAG)
   from saia_python import load_arcana_ids
   arcana_ids = load_arcana_ids()

   client.arcana.list()
   print(client.arcana.info(arcana_ids["default"]))

   client.arcana.upload(arcana_ids["default"], "document.pdf")
   client.arcana.upload_directory(arcana_ids["default"], "path/to/docs/")
   client.arcana.upload_directory(
       arcana_ids["default"], "path/to/docs/", pattern="*.pdf", recursive=True
   )
   client.arcana.list_files(arcana_ids["default"])
   client.arcana.delete_file(arcana_ids["default"], "document.pdf")

   client.arcana.generate_index(arcana_ids["default"])
   client.arcana.delete_index(arcana_ids["default"])

   # End-to-end: create a new arcana, upload a directory, build the
   # index — one call. The UUID-suffixed name from create() flows
   # through to upload + index automatically.
   result = client.arcana.setup_from_directory(
       "MyKB", "./markdown/",
       pattern="**/*.md",
       update_toml=True, toml_label="my_kb",
   )
   print(result["arcana"]["id"])      # owner/MyKB-<uuid>
   print(len(result["uploads"]))      # number of files uploaded
   print(result["index"])             # final index status

   response = client.arcana.chat(
       model="llama-3.3-70b-instruct",
       messages=[{"role": "user", "content": "Summarize the document."}],
       arcana_id=arcana_ids["default"],
   )

   # Pull the assistant text out of any chat / arcana response.
   # Safe against empty `choices` and missing `content` fields —
   # returns "" + logs a warning rather than raising.
   from saia_python import text_of
   print(text_of(response))

   # Rate limits
   print(client.get_rate_limits())


Tool Use (Function Calling)
---------------------------

The SAIA API follows the OpenAI tool-calling protocol. Tools are defined as
JSON schemas; the model decides when to invoke them:

.. code-block:: python

   import json

   tools = [{
       "type": "function",
       "function": {
           "name": "get_weather",
           "description": "Get the current weather for a city.",
           "parameters": {
               "type": "object",
               "properties": {"city": {"type": "string"}},
               "required": ["city"],
           },
       },
   }]

   response = client.chat.completions(
       model="llama-3.3-70b-instruct",
       messages=[{"role": "user", "content": "Weather in Berlin?"}],
       tools=tools,
   )

   msg = response["choices"][0]["message"]
   if msg.get("tool_calls"):
       tc = msg["tool_calls"][0]
       args = json.loads(tc["function"]["arguments"])
       result = {"temp_c": 18, "condition": "partly cloudy"}

       final = client.chat.completions(
           model="llama-3.3-70b-instruct",
           messages=[
               {"role": "user", "content": "Weather in Berlin?"},
               msg,
               {"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result)},
           ],
           tools=tools,
       )
       print(final["choices"][0]["message"]["content"])


OpenAI SDK Integration
----------------------

The library provides an OpenAI-compatible client for use with tools that
require the ``openai`` SDK (RAGAS, LangChain, instructor, etc.).
Requires ``pip install saia-python[openai]``.

.. code-block:: python

   from saia_python import create_openai_client

   # Credentials resolved automatically (same as SAIAClient)
   openai_client = create_openai_client()

   # Chat completions via OpenAI SDK
   response = openai_client.chat.completions.create(
       model="llama-3.3-70b-instruct",
       messages=[{"role": "user", "content": "Hello!"}],
   )

   # Embeddings
   embedding = openai_client.embeddings.create(
       model="e5-mistral-7b-instruct",
       input="Text to embed",
   )

Or via the ``SAIAClient`` property:

.. code-block:: python

   client = SAIAClient()
   client.openai.chat.completions.create(model="...", messages=[...])

Integration with ecosystem tools:

.. code-block:: python

   # instructor
   import instructor
   patched = instructor.from_openai(create_openai_client())

   # RAGAS
   from ragas.llms import LangchainLLMWrapper
   from langchain_openai import ChatOpenAI

   llm = ChatOpenAI(
       model="llama-3.3-70b-instruct",
       openai_api_key=client._api_key,
       openai_api_base=client._base_url,
   )


Functional Interface
--------------------

All services are accessible as standalone functions. The API key is resolved
automatically when omitted:

.. code-block:: python

   from saia_python import list_model_ids, chat_completion, get_rate_limits

   list_model_ids()

   chat_completion(
       model="meta-llama-3.1-8b-instruct",
       messages=[{"role": "user", "content": "Hello!"}],
   )

   print(get_rate_limits())
