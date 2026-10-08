Structured Output
=================

Turn a Pydantic v2 model into the ``response_format`` request field, and a chat
response back into a validated instance. SAIA enforces the schema on the server.
:meth:`ChatService.completions_structured
<saia_python.chat.ChatService.completions_structured>` combines both steps;
:class:`~saia_python.StructuredOutputError` reports an answer that is unusable.

.. autofunction:: saia_python.response_format_for

.. autofunction:: saia_python.parse_structured
