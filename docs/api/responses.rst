Responses
=========

Helpers for reading generation responses and streams: chat and ARCANA RAG
(:meth:`~saia_python.chat.ChatCompletions.create`,
:meth:`~saia_python.arcana.ArcanaService.chat`), raw-text completions
(:meth:`~saia_python.completions.CompletionsService.create`), the Responses
API (:meth:`~saia_python.responses_api.ResponsesService.create`) and the
Messages API (:meth:`~saia_python.messages.MessagesService.create`). They read
the native dicts and SDK objects alike.

.. autofunction:: saia_python.text_of
.. autofunction:: saia_python.iter_text
.. autofunction:: saia_python.aiter_text
.. autofunction:: saia_python.usage_of

.. autoclass:: saia_python.TextIterator
   :members: usage, last, references, close

.. autoclass:: saia_python.AsyncTextIterator
   :members: usage, last, references, aclose
