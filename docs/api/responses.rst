Responses
=========

Helpers for reading generation responses and streams: chat and ARCANA RAG
(:meth:`~saia_python.chat.ChatService.completions`,
:meth:`~saia_python.arcana.ArcanaService.chat`), raw-text completions
(:meth:`~saia_python.completions.CompletionsService.create`) and the Responses
API (:meth:`~saia_python.responses_api.ResponsesService.create`). They read
the native dicts and the OpenAI SDK's objects alike.

.. autofunction:: saia_python.text_of
.. autofunction:: saia_python.iter_text
.. autofunction:: saia_python.aiter_text
.. autofunction:: saia_python.usage_of

.. autoclass:: saia_python.TextIterator
   :members: last, references, close

.. autoclass:: saia_python.AsyncTextIterator
   :members: last, references, aclose
