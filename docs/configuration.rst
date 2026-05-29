Configuration
=============

Configuration is split across two files with distinct responsibilities:

- ``.env`` — **secrets and environment-specific overrides** (excluded from version control)
- ``config.toml`` — **structured application settings** (safe to commit)

Both files are searched first in the current working directory, then in the
home directory. Environment variables always take precedence over file-based
values.


``.env`` — Secrets
------------------

The ``.env`` file stores credentials and environment-specific values that
must not be committed to version control. It uses a flat ``KEY=VALUE``
format; all values are strings.

.. code-block:: text

   SAIA_API_KEY=your-api-key-here
   SAIA_ARCANA_ID=username/My-Arcana-xxxxxxxx

Supported keys:

.. list-table::
   :header-rows: 1
   :widths: 30 12 58

   * - Key
     - Required
     - Description
   * - ``SAIA_API_KEY``
     - Yes
     - API key (Bearer token) for SAIA authentication.
   * - ``SAIA_ARCANA_ID``
     - No
     - Single default ARCANA ID. Highest priority in the default chain
       (see :doc:`implementation`).
   * - ``SAIA_USERNAME``
     - No
     - Academic Cloud username.
   * - ``SAIA_ARCANA_ID_XX``
     - No
     - Numbered ARCANA IDs (e.g. ``SAIA_ARCANA_ID_01``). Prefer
       ``config.toml`` arrays when possible.

Inherent limitations of ``.env``:

- No data types (all values are strings)
- No nesting or sections
- No native list or array support
- No formal specification


``config.toml`` — Structured Settings
--------------------------------------

The ``config.toml`` file stores structured, non-secret configuration. TOML
provides native support for typed values, arrays, and nested tables.

.. code-block:: toml

   [saia]
   username = "saiauser123"
   # base_url = "https://chat-ai.academiccloud.de/v1"

   [saia.arcana]
   default = "saiauser123/My-Default-Arcana"

   ids = [
       "saiauser123/First-Arcana",
       "saiauser123/Second-Arcana",
   ]

   [saia.arcana.labels]
   project_a = "saiauser123/ProjectA-Arcana"
   project_b = "saiauser123/ProjectB-Arcana"

Key reference:

.. list-table::
   :header-rows: 1
   :widths: 35 12 53

   * - Key
     - Type
     - Description
   * - ``[saia] username``
     - string
     - Academic Cloud username (owner prefix in ARCANA IDs).
   * - ``[saia] base_url``
     - string
     - Override the default API base URL.
   * - ``[saia.arcana] default``
     - string
     - Default ARCANA ID (``owner/name`` format). Priority 2 in the
       default chain.
   * - ``[saia.arcana] ids``
     - array
     - List of ARCANA IDs. Indexed as ``"0"``, ``"1"``, etc. First
       element serves as priority 3 for the default.
   * - ``[saia.arcana.labels]``
     - table
     - Named ARCANA IDs for direct access by label.

Loading in code:

.. code-block:: python

   from saia_python import load_config

   config = load_config()
   # {'saia': {'username': 'saiauser123', 'arcana': {'default': '...', ...}}}


File Responsibilities
---------------------

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Setting
     - ``.env``
     - ``config.toml``
   * - API key
     - **Required** (secret)
     - Not supported
   * - Username
     - Supported
     - **Recommended** (not a secret)
   * - Single ARCANA ID
     - **Highest priority** default
     - Explicit default
   * - Multiple ARCANA IDs
     - Via numbered keys (``_01``, ``_02``)
     - **Recommended** (native arrays)
   * - Named ARCANA labels
     - Not supported
     - **Supported** (``[saia.arcana.labels]``)
   * - Base URL override
     - Not supported
     - **Supported** (``[saia] base_url``)
