SAIA Python Wrapper
===================

A Python wrapper for the `GWDG SAIA platform <https://docs.hpc.gwdg.de/services/ai-services/saia/index.html>`_ REST API,
providing object-oriented and functional interfaces to Chat AI, Voice AI,
ARCANA (RAG), and document conversion services.

.. grid:: 2
   :gutter: 3

   .. grid-item-card:: Getting Started
      :link: quickstart
      :link-type: doc

      Installation, authentication, and initial API calls.

   .. grid-item-card:: Explanations
      :link: explanations
      :link-type: doc

      Architecture, implementation rationale, and configuration reference.

   .. grid-item-card:: API Reference
      :link: api/index
      :link-type: doc

      Complete reference for all classes and functions.

   .. grid-item-card:: Development
      :link: development
      :link-type: doc

      Local setup, testing, documentation builds, and release workflow.


Wrapped Services
----------------

- `Chat AI <https://docs.hpc.gwdg.de/services/ai-services/chat-ai/index.html>`_ — chat completions with streaming and tool calling
- `Voice AI <https://docs.hpc.gwdg.de/services/ai-services/voice-ai/index.html>`_ — audio transcription and translation (Whisper)
- `ARCANA <https://docs.hpc.gwdg.de/services/ai-services/arcana/index.html>`_ — RAG: knowledge base management and retrieval-augmented chat
- `Documents (Docling) <https://docs.hpc.gwdg.de/services/ai-services/saia/index.html>`_ — PDF and document conversion to Markdown, HTML, JSON
- `Models <https://docs.hpc.gwdg.de/services/ai-services/saia/index.html>`_ — list available models and probe tool-calling support
- `Rate Limits <https://docs.hpc.gwdg.de/services/ai-services/saia/index.html>`_ — inspect current quota and usage


Minimal example
---------------

.. code-block:: python

   from saia_python import SAIAClient

   client = SAIAClient()  # API key resolved from env var, .saia_api, or .env

   print(client.models.list_ids())

   response = client.chat.completions(
       model="meta-llama-3.1-8b-instruct",
       messages=[{"role": "user", "content": "Hello!"}],
   )
   print(response["choices"][0]["message"]["content"])
   print(client.get_rate_limits())

Institutions & Funding
----------------------
|

.. image:: _static/cidbn_logo.svg
   :alt: CIDBN Logo
   :height: 80px
   :target: https://uni-goettingen.de/de/608362.html

The developer team is part of the `Göttingen Campus Institute for Dynamics
of Biological Networks (CIDBN) <https://uni-goettingen.de/de/608362.html>`_.


.. toctree::
   :maxdepth: 2
   :hidden:

   quickstart
   explanations
   api/index
   development
   CHANGELOG
