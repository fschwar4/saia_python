Responses
=========

Helpers for reading generation responses and streams: chat and ARCANA RAG
(:meth:`~saia_python.chat.ChatService.completions`,
:meth:`~saia_python.arcana.ArcanaService.chat`) and raw-text completions
(:meth:`~saia_python.completions.CompletionsService.create`). They read the
native dicts and the OpenAI SDK's objects alike.

.. autofunction:: saia_python.text_of
.. autofunction:: saia_python.iter_text
.. autofunction:: saia_python.aiter_text
.. autofunction:: saia_python.usage_of
