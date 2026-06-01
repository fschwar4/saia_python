ARCANA incremental sync
=======================================================================

Re-uploading and re-indexing an entire knowledge base on every run is slow.
This guide shows how to push **only the files that changed** and re-embed only
those — the pattern a production ingestion pipeline uses against ARCANA.


The idea
-----------------------------------------------------------------------

ARCANA's index trigger (``generate_index``) is **whole-arcana** — there is no
per-file index call. But the server **skips files already at**
``index_status == "INDEXED"``, and uploading a file resets it to
``NOT_INDEXED``. So the efficient pattern is:

#. Work out which local files are new or changed (your code — ARCANA exposes
   no content hash).
#. Upload only those: new files ``POST``, existing files ``PUT``. They flip to
   ``NOT_INDEXED``; everything else stays ``INDEXED``.
#. Trigger **one** ``generate_index`` — the server re-embeds only the
   ``NOT_INDEXED`` files, i.e. exactly what you just uploaded.

A no-op re-run uploads nothing and indexes nothing.

.. note::

   This relies on the server's skip-``INDEXED`` behavior (documented on
   ``generate_index`` in the :doc:`api/index`). If that ever changes, the calls
   stay correct but a single ``generate_index`` would re-embed the whole
   arcana.


Recipe 1: ``sync_directory`` with a SHA-256 policy
-----------------------------------------------------------------------

``sync_directory`` does the plumbing — glob the directory, list the remote
files, apply your decisions, and trigger one index — while you supply a
``select`` callback that decides, per file, whether to ``"upload"`` (new),
``"replace"`` (changed), or ``"skip"``. Change-detection (here SHA-256 against
a local manifest you persist between runs) lives entirely in that callback.

.. code-block:: python

   import hashlib
   import json
   from pathlib import Path

   from saia_python import SAIAClient

   client = SAIAClient()
   ARCANA = "my-kb"
   MANIFEST = Path("arcana_manifest.json")


   def sha256(path: Path) -> str:
       return hashlib.sha256(path.read_bytes()).hexdigest()


   manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
   digests: dict[str, str] = {}  # filled by select(), reused by on_result()


   def select(path: Path, remote: dict | None) -> str:
       digests[path.name] = sha256(path)
       if remote is None:
           return "upload"                          # not on the arcana yet (POST)
       if digests[path.name] != manifest.get(path.name):
           return "replace"                         # contents changed (PUT)
       return "skip"                                # unchanged


   def on_result(path: Path, entry: dict) -> None:
       # entry == {"file", "status", ["error"]}; status is uploaded/replaced/
       # skipped/failed. Persist the digest only for files we actually pushed.
       if entry["status"] in ("uploaded", "replaced"):
           manifest[path.name] = digests[path.name]


   report = client.arcana.sync_directory(
       ARCANA,
       "docs/",
       select=select,
       pattern="*.md",
       prune=True,            # delete remote files with no local counterpart
       on_result=on_result,
   )
   MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True))

   print(report["uploaded"], report["replaced"], report["skipped"])

``sync_directory`` triggers ``generate_index`` once, and only when something
actually changed (an upload, replace, or prune). Because ``select`` returns
``"upload"`` vs ``"replace"``, the call chooses ``POST`` (new) vs ``PUT``
(existing) per file, so the sync is idempotent regardless of what is already on
the arcana.


Recipe 2: explicit list + one index (provenance-heavy pipelines)
-----------------------------------------------------------------------

When the *unit of change* is coarser than a file (e.g. a source document that
re-splits into many files), or you need a transaction-log entry per upload,
decide the file set upstream and push it with ``upload_files``, then trigger one
index yourself. ``on_result`` streams each file's outcome so you can record
provenance (e.g. a git SHA) as the upload happens.

.. code-block:: python

   TERMINAL = {"INDEXED", "ERROR", "NOT_INDEXED"}
   transaction_log: list[dict] = []


   def push_changed(client, arcana: str, candidates: list[Path], manifest: dict):
       # 1. Your change-detection decides the set.
       changed = [p for p in candidates if sha256(p) != manifest.get(p.name)]
       if not changed:
           print("nothing changed — skipping upload + index")
           return None

       # 2. Don't trigger a reindex while one is already running — the server
       #    rejects a concurrent whole-arcana reindex. Defer if busy.
       info = client.arcana.get(arcana).get("index_info") or {}
       status = info.get("index_status")
       if status and status not in TERMINAL:
           print(f"arcana busy (status={status}); re-run when idle")
           return None

       # 3. Upload only the changed files; record provenance per file.
       def record(path: Path, entry: dict) -> None:
           transaction_log.append(
               {
                   "file": entry["file"],
                   "status": entry["status"],
                   "sha256": sha256(path),
                   "error": entry.get("error"),
               }
           )

       client.arcana.upload_files(arcana, changed, overwrite=True, on_result=record)

       # 4. One whole-arcana index — re-embeds only the files just uploaded.
       return client.arcana.generate_index(arcana, wait=True, timeout=1800)

.. note::

   ``upload_files`` uses a single ``overwrite`` mode for the whole batch
   (``True`` → ``PUT``, ``False`` → ``POST``), and a ``PUT`` against a file that
   isn't on the arcana yet fails. So ``overwrite=True`` is correct only when
   every file in the set already exists. For a mixed set, either call
   ``list_files()`` once and split into a ``POST`` batch (new) and a ``PUT``
   batch (existing), or use Recipe 1 — its ``select`` picks ``POST``/``PUT`` per
   file automatically.


Reliability
-----------------------------------------------------------------------

- **Transport-drop tolerance.** ``generate_index`` treats a dropped trigger
  connection (``RemoteDisconnected`` / 504 / read timeout) as "the server
  accepted the work" and falls through to polling the index state, which is
  authoritative. With ``wait=True`` it polls until the status is terminal,
  tolerating a transient failure on an individual poll; only the overall
  ``timeout`` ends the wait, and the raised ``TimeoutError`` names the last
  status and/or transport error so a stuck reindex is diagnosable.
- **Fail-fast everywhere else.** Every other ARCANA call carries a default
  ``(connect, read)`` timeout, so a stalled ``list_files`` / ``upload`` /
  ``get`` raises ``requests.Timeout`` instead of hanging. In a batch,
  ``on_result`` still records the per-file failure and the loop continues.
- **One reindex at a time.** Triggering a whole-arcana reindex while one is
  already running is rejected by the server, so guard with the ``index_status``
  check shown in Recipe 2 before triggering, and defer if it is non-terminal.


When to use which
-----------------------------------------------------------------------

- **Recipe 1 (``sync_directory``)** — local files map roughly 1:1 to KB files
  and you keep a per-file manifest. It handles ``POST``/``PUT``/skip, pruning,
  and the single index for you.
- **Recipe 2 (``upload_files`` + ``generate_index``)** — selection happens
  upstream (coarser than per-file), or you need per-file provenance /
  transaction logging and explicit control over when the index fires.

Both keep change-detection in *your* code, because ARCANA exposes no content
hash. Server-side scoped indexing and a ``content_sha256`` field that would
move that detection onto the server are on the :doc:`roadmap`.
