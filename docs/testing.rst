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

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Test
     - Purpose
   * - ``test_full_headers``
     - All 9 rate-limit headers map to correct dataclass fields
   * - ``test_non_integer_values_ignored``
     - Non-numeric header values are silently skipped
   * - ``test_full_output_alignment``
     - ``/`` and ``(`` columns are aligned across all rows
   * - ``test_remaining_none_shows_question_mark``
     - ``None`` remaining displays ``?`` (caught a real ``TypeError``)

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
