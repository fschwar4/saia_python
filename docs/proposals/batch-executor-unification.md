# Refactor Proposal: Unify the per-file batch executor

**Status:** implemented (2026-06-02, `arcana.py`) · **Scope:** `saia_python/arcana.py` (internal only) · **Type:** refactor
**Public API:** unchanged — no signature or return-shape change on any public method.
**Gate:** this refactor is recommended *only because* it improves separation of concerns
(see §3). If it merely cut line count it would not be worth doing.

---

## 1. Motivation (why)

`ArcanaService` runs a "do something to each of N files, record a per-file outcome,
continue on error" loop in **two** places that drifted apart:

- `_run_file_batch` (`arcana.py:143`) — the executor behind `upload_directory`,
  `upload_files`, `delete_directory`. Returns a flat `list[{"file","status",["error"]}]`.
- `sync_directory`'s **Pass 2** (`arcana.py:850`) — re-implements the *same* try /
  build-entry / record-error / verbose-print / `on_result` skeleton inline, only to bucket
  results into a categorized `report` dict instead of a flat list.

The earlier review flagged this as the one genuine logic duplication in the package. The
question it raised — *is the `dict`-vs-`list` difference fundamental?* — is **no**: the
`report` dict is a `groupby(status)` projection of the same per-file entries. So the loop
can be single-sourced; the difference lives entirely in a cheap post-step.

## 2. Goals / Non-goals

**Goals**
- One executor for *all* multi-file operations, including `sync_directory`'s apply pass.
- Keep the per-file entry shape (`{"file","status",["error"]}`) and `on_result` payload
  identical, so observable behavior and the public return shapes are preserved.
- Localize the change: callers should barely move.

**Non-goals**
- No public API change (signatures, return shapes, exceptions all stay).
- No attempt to also fold in `prune` or `generate_index` (see §3 — those are *different*
  concerns and must stay separate).
- No new dependency, no new module.

## 3. Best-practice assessment (the gate)

This is the part that decides whether to proceed. Verdict: **proceed — it improves
modularity and SoC, not just DRY.**

**Why it improves separation of concerns.** The work decomposes into four distinct
responsibilities. Today the *executor* one is implemented twice and tangled into
`sync_directory`; after, each lives in exactly one place:

| Concern | Owner (after) | Notes |
|---|---|---|
| **Policy** — which op per file | `select` callback (caller) | already separated |
| **Execution** — run op, capture outcome, progress, `on_result`, continue-on-error | `_run_file_batch` | *was duplicated*; now single-sourced |
| **Aggregation** — entries → categorized report | inline projection in `sync_directory` | sync's own output contract (see below) |
| **Orchestration** — plan → execute → aggregate → prune → index | `sync_directory` | composes the others |

- **Single Responsibility.** The executor's job becomes precisely *"apply an action over a
  set of files and report each outcome."* It learns nothing about reports, policies,
  pruning, or indexing — those stay with `sync_directory`. Cohesion goes up, not down.
- **Open/closed-shaped extension.** The executor is generalized by letting the *action*
  name its own outcome (return a status label) instead of hard-coding a single success
  `verb`. New outcome kinds (`"replaced"`, `"skipped"`) are added by the caller's action,
  without modifying the executor per caller. This is the clean seam, and it makes the
  executor *more* honest (it no longer assumes every batch has one success word).
- **DRY without coupling.** The duplicated ~20-line loop collapses to one definition; the
  `report` becomes a 5-line projection.

**Where I deliberately did *not* abstract (avoiding the opposite mistake).** Best practice
is also *not over-engineering*, so two things stay separate on purpose:

1. **`prune` keeps its own short loop.** It iterates a *different collection* (remote
   orphan names, not local `Path`s) and is intentionally outside `on_result`. Forcing it
   through the file executor would couple two unrelated data sources — that would *reduce*
   clarity. Keeping it separate is the SoC-correct call.
2. **The entries→report projection is inlined, not extracted into a helper.** It has a
   single caller and is 5 readable lines. Extracting a one-call `_classify()` would add
   indirection without reuse — premature abstraction. (If a second caller ever needs the
   same shaping, extract then.)

**Honest costs** (all minor, all acceptable — see §6):
- The executor signature grows by two opt-out flags (`show_progress`, `print_summary`).
- The executor is marginally more abstract (action-returns-label + an `isinstance` guard).
- Two cosmetic `verbose` output changes (§6) — both arguably improvements.

Net: cohesion up, duplication gone, blast radius tiny, no public change. Worth doing.

## 4. Current state

```python
# _run_file_batch — the executor (one fixed success `verb`)
for fp in progress_iter(files, desc=desc, unit="file"):
    entry = {"file": fp.name}
    try:
        action(fp); entry["status"] = verb
    except Exception as e:
        entry["status"] = "failed"; entry["error"] = str(e)
    if verbose: ...
    if on_result is not None: on_result(fp, entry)
    results.append(entry)
# ... + N/M summary

# sync_directory Pass 2 — the SAME skeleton, re-implemented for 3 outcomes + buckets
for path, action in plan:
    if action == "skip":
        report["skipped"].append(path.name)
        if on_result is not None: on_result(path, {"file": path.name, "status": "skipped"})
        continue
    overwrite = action == "replace"; bucket = "replaced" if overwrite else "uploaded"
    entry = {"file": path.name}
    try:
        self.upload(name, path, overwrite=overwrite)
        report[bucket].append(path.name); entry["status"] = bucket
        ...
    except Exception as e:
        entry["status"] = "failed"; entry["error"] = str(e)
        report["failed"].append({"file": path.name, "error": str(e)}); ...
    if on_result is not None: on_result(path, entry)
```

## 5. Design

**Generalize the executor** so the action reports its own outcome; everything else (error
capture, progress, `on_result`, verbose, tally) stays its job. Two opt-out flags let an
orchestrator drive its own progress/summary.

**`sync_directory` becomes** *plan → execute(via executor) → project → prune → index*: the
policy pass builds a `{path: decision}` plan, a tiny `_apply` closure maps each decision to
the upload + the status label (`"skip"` does no I/O), the executor runs them, and a 5-line
projection turns the flat entries into the categorized report.

## 6. Implementation

### 6.1 `_run_file_batch` (generalized executor)

```python
def _run_file_batch(
    self,
    files: list[Path],
    action: Callable[[Path], object],
    *,
    default_status: str,
    desc: str,
    verbose: bool,
    show_progress: bool = True,
    print_summary: bool = True,
    on_result: Callable[[Path, dict], None] | None = None,
) -> list[dict]:
    """Apply ``action`` to each file, collecting one outcome entry per file.

    The single executor behind every multi-file operation —
    :meth:`upload_directory`, :meth:`upload_files`, :meth:`delete_directory`,
    and the apply pass of :meth:`sync_directory`. It owns exactly the concerns
    those share: iteration, an optional progress bar, per-file error capture,
    the ``on_result`` callback, and the verbose tally. No caller reimplements
    this loop.

    ``action(path)`` performs the work for one file. If it returns a ``str``
    that value is recorded as the file's ``status`` (e.g. ``"replaced"`` vs
    ``"uploaded"``); any other return value (an API response dict, ``None``)
    records ``default_status``. Any exception is caught, recorded as
    ``"failed"`` with the stringified error, and iteration continues.

    Args:
        default_status: Status recorded when ``action`` does not return a
            ``str`` (the common upload/delete case).
        show_progress: Wrap the loop in a tqdm bar (default). ``False`` for
            callers that drive their own reporting (e.g. ``sync_directory``).
        print_summary: Print the ``N/M files <status>`` tally when ``verbose``
            (default). ``False`` for callers that print a richer summary.
        on_result: Called as ``on_result(path, entry)`` after each file.
    """
    iterator = (
        progress_iter(files, desc=desc, unit="file") if show_progress else files
    )
    results: list[dict] = []
    for fp in iterator:
        entry: dict = {"file": fp.name}
        try:
            label = action(fp)
            entry["status"] = label if isinstance(label, str) else default_status
        except Exception as e:
            entry["status"] = "failed"
            entry["error"] = str(e)
        if verbose:
            line = f"  {fp.name}  {entry['status']}"
            if entry["status"] == "failed":
                line += f" ({entry['error']})"
            print(line)
        if on_result is not None:
            on_result(fp, entry)
        results.append(entry)

    if verbose and print_summary:
        succeeded = sum(1 for r in results if r["status"] != "failed")
        failed = len(results) - succeeded
        summary = f"{succeeded}/{len(results)} files {default_status}"
        if failed:
            summary += f" ({failed} failed)"
        print(summary)
    return results
```

### 6.2 The three simple callers — one keyword each

`upload_directory`, `upload_files`, `delete_directory` change *only* `verb=` →
`default_status=`. Their action lambdas are unchanged: `self.upload(...)` returns
`dict | None`, which is not a `str`, so the `isinstance` guard falls through to
`default_status` exactly as before.

```python
# upload_directory / upload_files
return self._run_file_batch(
    files,
    lambda fp: self.upload(name, fp, overwrite=overwrite),
    default_status="uploaded",          # was: verb="uploaded"
    desc="Uploading", verbose=verbose, on_result=on_result,
)

# delete_directory
return self._run_file_batch(
    files,
    lambda fp: self.delete_file(name, fp.name),
    default_status="deleted",           # was: verb="deleted"
    desc="Deleting", verbose=verbose, on_result=on_result,
)
```

### 6.3 `sync_directory` — plan → execute → project → prune → index

```python
local_files = self._glob_files(directory, pattern, recursive=recursive)
remote_files = cast(list, self.list_files(name))
remote_by_name = {f["name"]: f for f in remote_files}

# Pass 1 — policy. Ask the caller what to do with each local file, against the
# remote state as it is *before* any upload. Raises on a bad decision before any I/O.
valid = {"upload", "replace", "skip"}
plan: dict[Path, str] = {}
for path in local_files:
    decision = select(path, remote_by_name.get(path.name))
    if decision not in valid:
        raise ValueError(
            f"select() must return one of {sorted(valid)}; "
            f"got {decision!r} for {path.name}"
        )
    plan[path] = decision

# Pass 2 — execute via the shared executor. The action maps each planned
# decision to the work plus the status label to record; "skip" does no I/O.
# Error capture, on_result, and per-file verbose output are the executor's job.
def _apply(path: Path) -> str:
    decision = plan[path]
    if decision == "skip":
        return "skipped"
    self.upload(name, path, overwrite=(decision == "replace"))
    return "replaced" if decision == "replace" else "uploaded"

entries = self._run_file_batch(
    local_files,
    _apply,
    default_status="uploaded",
    desc="Syncing",
    verbose=verbose,
    show_progress=False,    # sync prints its own richer summary below
    print_summary=False,
    on_result=on_result,
)

# Aggregate the flat outcomes into the categorized report (a groupby view of
# the entries — sync's own output contract).
report: dict = {
    "uploaded": [], "replaced": [], "skipped": [],
    "deleted": [], "failed": [], "index": None,
}
for e in entries:
    if e["status"] == "failed":
        report["failed"].append({"file": e["file"], "error": e["error"]})
    else:
        report[e["status"]].append(e["file"])

# Prune — remote-only orphans. A distinct data source (remote names, not local
# paths) and intentionally outside on_result, so it stays its own short loop.
if prune:
    local_names = {p.name for p in local_files}
    for remote_name in remote_by_name:
        if remote_name in local_names:
            continue
        try:
            self.delete_file(name, remote_name)
            report["deleted"].append(remote_name)
            if verbose:
                print(f"  {remote_name}  deleted")
        except Exception as e:
            report["failed"].append({"file": remote_name, "error": str(e)})

if index and (report["uploaded"] or report["replaced"] or report["deleted"]):
    report["index"] = self.generate_index(name, wait=index_wait)

if verbose:
    print(
        f"sync: {len(report['uploaded'])} uploaded, "
        f"{len(report['replaced'])} replaced, "
        f"{len(report['skipped'])} skipped, "
        f"{len(report['deleted'])} deleted, "
        f"{len(report['failed'])} failed"
    )
return report
```

## 7. Behavior compatibility

**Identical:** public signatures; the `sync_directory` `report` shape and all bucket
contents; the `on_result` payloads (skip = `{"file","status":"skipped"}`; success =
`{"file","status":bucket}`; failure = `{"file","status":"failed","error":…}`); `prune`;
the conditional single `generate_index`; `select`-called-before-any-upload ordering; the
`ValueError` on a bad `select` return (still raised before any I/O).

**Two deliberate `verbose`-only cosmetic changes** (console text; no API impact):
1. `sync_directory` now prints a line for **skipped** files too (the executor prints every
   file). Today skips are silent. This is more complete; flag if you'd rather keep skips
   quiet (trivial to filter).
2. Failed lines now read `name  failed (error)` (lowercase, with the error) everywhere —
   the simple callers previously printed just `name  FAILED` without the error. This is an
   improvement and unifies the format across all callers.

## 8. Test plan

The existing `tests/test_arcana.py` suites should pass unchanged in behavior:
`TestUploadFiles`, `TestSyncDirectory` (`test_classifies_and_indexes_once`,
`test_no_changes_skips_index`, `test_index_false_suppresses_indexing`,
`test_prune_false_keeps_orphans`, `test_bad_select_return_raises`), and `TestOnResultHook`
(`test_upload_files_invokes_on_result_per_file_in_order`,
`test_on_result_reports_failure_with_error`,
`test_sync_directory_invokes_on_result_for_local_files`).

Add/confirm:
- A `sync_directory` case asserting a `select` returning `"skip"` yields an `on_result`
  entry with `status == "skipped"` and no `error` (locks the skip path through the executor).
- A case asserting `upload_directory(verbose=True)` failure output includes the error text
  (locks change §7.2), if output is asserted anywhere.

Gate after applying: `ruff check`, `ruff format --check`, `mypy`, `pytest -q`.

## 9. Risks

- **Low.** Internal-only; no public surface moves; blast radius is the executor + three
  one-keyword caller edits + the `sync_directory` body.
- The `isinstance(label, str)` guard is the one subtlety — covered by the existing
  upload/delete tests (their actions return `dict | None` → must record `default_status`).
- `verbose` text changes are cosmetic; called out in §7 so they aren't a surprise.

## 10. Verdict

**Recommended.** It removes the package's only real logic duplication *and* improves
separation of concerns (one cohesive executor; policy / aggregation / pruning / orchestration
each in one place), while staying internal, behavior-preserving, and small. The parts that
don't fit the executor (`prune`, `generate_index`, the report projection) are kept separate
on purpose — that restraint is part of why the result is clean rather than a god-helper.
