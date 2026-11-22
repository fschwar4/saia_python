Testing
=======

Running Tests
-------------

.. code-block:: bash

   pip install -e ".[test]"
   pytest -v

Tests run automatically via GitHub Actions on every push and pull request
to ``main`` (Python 3.10–3.13). See ``.github/workflows/tests.yml``.


Test Strategy
-------------

The test suite focuses on logic that can break in non-obvious ways:
resolution order, parsing, formatting, and protocol handling. Service
classes (chat, voice, arcana) are thin HTTP wrappers — their correctness
is best verified by integration tests against the real API, not by mocking
``requests``.

Tests are deliberately kept minimal. Each test either:

- protects a priority ordering that could silently regress,
- validates parsing of a real-world format variant, or
- has already caught a bug during development.


Test Inventory
--------------

``test_auth.py`` — API Key Discovery
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_explicit_path_raw``
     - ``.saia_api`` file loads correctly
   * - ``test_explicit_path_dotenv``
     - ``.env`` file loads correctly (with quotes)
   * - ``test_env_var``
     - ``SAIA_API_KEY`` env var resolves
   * - ``test_env_var_stripped``
     - Whitespace around env var value is stripped
   * - ``test_env_var_empty_skipped``
     - Empty ``SAIA_API_KEY=""`` falls through to file
   * - ``test_saia_api_file_in_cwd``
     - ``.saia_api`` in cwd is found
   * - ``test_saia_api_file_skips_comments``
     - Lines starting with ``#`` are ignored
   * - ``test_dotenv_file_in_cwd``
     - ``.env`` in cwd is parsed, other keys ignored
   * - ``test_dotenv_strips_quotes``
     - Single and double quotes stripped from values
   * - ``test_nothing_found_raises``
     - ``ValueError`` with helpful message when no key found
   * - ``test_env_var_beats_file``
     - Env var takes priority over ``.saia_api`` file
   * - ``test_saia_api_beats_dotenv``
     - ``.saia_api`` takes priority over ``.env``

``test_auth.py`` — ARCANA ID Priority Chain
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_priority_1_env_saia_arcana_id``
     - ``SAIA_ARCANA_ID`` env var beats config.toml
   * - ``test_priority_2_toml_default``
     - ``[saia.arcana] default`` beats ``ids`` array
   * - ``test_priority_3_toml_ids_first``
     - First ``ids`` element becomes default when no explicit default
   * - ``test_priority_4_numbered_env_first``
     - First ``SAIA_ARCANA_ID_XX`` becomes default as last resort
   * - ``test_env_default_beats_toml_default``
     - ``.env`` ``SAIA_ARCANA_ID`` beats config.toml default

``test_auth.py`` — ARCANA ID Source Merging
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_toml_ids_array``
     - ``[saia.arcana] ids`` parsed as indexed dict entries
   * - ``test_toml_labels``
     - ``[saia.arcana.labels]`` parsed as named entries
   * - ``test_numbered_env_vars``
     - ``SAIA_ARCANA_ID_XX`` env vars collected by suffix
   * - ``test_empty_returns_empty_dict``
     - No configuration returns ``{}``
   * - ``test_all_sources_merge``
     - All sources (env, toml ids, toml labels, numbered) merge into one dict

``test_auth.py`` — Legacy Removal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_legacy_arcana_id_ignored``
     - ``ARCANA_ID`` (without ``SAIA_`` prefix) is no longer accepted

``test_auth.py`` — Owner Prefix Resolution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_username_set_id_without_prefix``
     - Username configured, ID has no ``/`` → username auto-prepended
   * - ``test_no_username_id_with_prefix``
     - No username, ID already has ``/`` → works as-is
   * - ``test_both_username_and_prefix``
     - Username set and ID has ``/`` → ID left unchanged
   * - ``test_no_username_no_prefix_raises``
     - No username and no ``/`` in ID → ``ValueError`` raised

``test_auth.py`` — extract_arcana_name
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_full_id_strips_owner``
     - ``owner/name`` → ``name`` (the bug that caused a 404)
   * - ``test_owner_with_multiple_slashes``
     - Only the first ``/`` is treated as the separator
   * - ``test_name_with_spaces``
     - Spaces in arcana names are preserved

``test_auth.py`` — Username and Summary
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_from_toml``
     - Username loaded from ``[saia] username`` in config.toml
   * - ``test_env_beats_toml``
     - Env var ``SAIA_USERNAME`` overrides config.toml
   * - ``test_none_when_missing``
     - Returns ``None`` when no username configured
   * - ``test_summary_output``
     - ``arcana.summary()`` includes configured IDs, labels, and server data

``test_rate_limits.py`` — Header Parsing and Formatting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

SAIA has sent two header schemes. The tests of the current one use headers
recorded from the live gateway (``tests/_rate_limit_headers.py``), and so do the
normal-path tests of chat, streaming and the async transport, so a renamed
header shows up as a failing test rather than as silently empty limits.

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_full_headers``
     - The earlier scheme's 9 headers map to the right dataclass fields
   * - ``test_current_scheme``
     - The current scheme's limit, remaining count and reset per window
   * - ``test_current_429_has_retry_after_and_names_the_exhausted_window``
     - A recorded 429 yields ``retry_after`` and the exhausted window
   * - ``TestRetryAfter``
     - ``Retry-After`` as seconds or as an HTTP-date; garbage is ignored
   * - ``test_non_integer_values_ignored``
     - Non-numeric header values are silently skipped
   * - ``TestRateLimitInfoStr``
     - The summary renders every window, its reset and ``Retry after``,
       and tolerates ``None`` fields

``tests/test_transport_policy.py`` covers the 429 retry planner for both
schemes: ``Retry-After`` first, then the exhausted window's reset, then the
earlier scheme's single reset.

``test_streaming.py`` — SSE Line Parsing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_normal_chunks``
     - Standard ``data: {...}`` lines yield parsed JSON
   * - ``test_done_terminates``
     - Generator stops at ``data: [DONE]`` and does not yield after
   * - ``test_malformed_json_skipped``
     - Invalid JSON lines are silently skipped
   * - ``test_no_space_after_data_colon``
     - ``data:{...}`` (no space) is handled correctly
   * - ``test_error_response_raises``
     - HTTP errors raise before iteration begins

``test_exceptions.py`` — Error Handling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_429_includes_parsed_rate_limits``
     - ``RateLimitError`` includes parsed ``rate_limits`` attribute from headers
   * - ``test_current_429_carries_retry_after_and_the_gateway_message``
     - A recorded 429 keeps ``Retry-After`` and the gateway's own message
   * - ``TestExtractDetail``
     - The error message comes from ``detail``, ``error.message`` or
       ``message``, else from the raw body

Live Checks
-----------

A few checks run against the real service and are skipped unless their
environment variable is set. These need an API key and count against your rate
limits:

.. code-block:: bash

   SAIA_COMPLETIONS_LIVE=1 pytest tests/test_live_completions_route.py
   SAIA_MESSAGES_LIVE=1 pytest tests/test_live_messages_route.py
   SAIA_RATE_LIMITS_LIVE=1 pytest tests/test_live_rate_limits.py
   SAIA_RESPONSES_LIVE=1 pytest tests/test_live_responses_route.py
   SAIA_STRUCTURED_LIVE=1 pytest tests/test_live_structured.py

The checks read the key the way the client does (``SAIA_API_KEY``,
``.saia_api``, ``.env``), send it only to the configured base URL and never
print it. Their prompts are fixed and generic, such as "What is the capital of
France?". CI sets none of the variables, so there they are always skipped.

The three route checks call the native service, plain and streamed, and check
the response shape, how the stream ends and what ``text_of`` reads. As of
2026-11-22, GWDG's documentation lists neither ``/responses`` nor
``/messages``, so these checks are what notices a change there
(:doc:`ADR-0008 <adr/0008-native-wrappers-for-undocumented-routes>`). Run them
before a release when a key is available locally; together they send seven
requests:

.. code-block:: bash

   SAIA_COMPLETIONS_LIVE=1 SAIA_RESPONSES_LIVE=1 SAIA_MESSAGES_LIVE=1 \
       pytest tests/test_live_completions_route.py \
       tests/test_live_responses_route.py tests/test_live_messages_route.py

The tokenizer smoke test downloads a tokenizer from Hugging Face instead and
needs the ``[tokenizer]`` extra:

.. code-block:: bash

   SAIA_TOKENIZER_LIVE=1 pytest tests/test_tokenizer.py
