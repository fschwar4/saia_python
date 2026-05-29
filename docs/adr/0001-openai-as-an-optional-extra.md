# `openai` as an optional extra

- Status: Accepted
- Date: 2026-05-29
- Deciders: saia-python maintainers

## Context and Problem Statement

`saia-python` ships an OpenAI-compatibility layer (`create_openai_client()` and
the `SAIAClient.openai` / `.openai_async` properties) built on the `openai` SDK.
Everything else — chat, voice, ARCANA, documents, models, rate limits — speaks
the SAIA REST API directly through `requests`. Should `openai` be a mandatory
dependency of the whole package?

Originally it was: `openai` sat in the core dependencies and was imported at
package-import time (`__init__` → `openai_compat` → `import openai`). That
contradicted the documentation, which described `openai` as optional and
promised a friendly `ImportError` — impossible when a missing `openai` breaks
`import saia_python` itself.

## Decision Drivers

- The OpenAI layer is a single function; the native client never needs `openai`.
- `openai` is heavy (pulls `httpx`, `pydantic`, `anyio`, …).
- The documentation already promised an `[openai]` extra and a graceful failure.
- Consistency with the existing `tqdm` pattern (already imported lazily).

## Considered Options

- **Optional extra + lazy import** — move `openai` to
  `[project.optional-dependencies]` and import it inside
  `create_openai_client()`.
- **Keep it mandatory** — leave `openai` in core deps and delete the "optional"
  wording from the docs.

## Decision Outcome

Chosen option: **optional extra + lazy import**. `openai` moved to an `[openai]`
extra (`pip install saia-python[openai]`); the `import openai` now lives inside
`create_openai_client()`, guarded by a `try/except` that raises a clear
`ImportError` with install instructions. The core package installs and imports
with just `requests` + `tomlkit` (+ `tqdm`).

### Consequences

- Good — lean base install; the heavy SDK is opt-in.
- Good — the documented behavior is now true, and the property-level lazy import
  finally has an effect.
- Good — internally consistent with the `tqdm` optional-import pattern.
- Trade-off — a plain `pip install saia-python` no longer provides
  `client.openai`; users must add the extra. Mitigated by the explicit
  `ImportError`, and the `test` extra depends on `[openai]` so CI is unaffected.

### Confirmation

`import saia_python` no longer pulls `openai` into `sys.modules` (verified);
`tests/test_openai_compat.py` uses `pytest.importorskip("openai")` so the suite
is correct whether or not the extra is installed.

## More Information

If the OpenAI-compatibility layer ever becomes a headline, always-available
feature, the only change required is moving `openai>=1.0` back to core
dependencies — the lazy import remains harmless. Relates to ADR-0003.
