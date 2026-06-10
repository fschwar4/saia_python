# Transport-policy layer for rate-limit handling

- Status: Accepted
- Date: 2026-06-02
- Deciders: saia-python maintainers

## Context and Problem Statement

SAIA enforces layered rate limits (per minute / hour / day / month). A 429
currently aborts the call: [ADR-0002](0002-rate-limit-metadata-on-responses.md)
deliberately made the library **passive** — it surfaces `RateLimitInfo` and lets
the caller decide. So every batch or unattended consumer hand-rolls its own
retry/backoff, duplicated and usually wrong (fixed sleeps, no jitter, no
awareness of *which* window was hit, and prone to blocking for ~an hour on the
daily window). The driving case is the AvorMedical guideline-ingestion pipeline,
which reliably trips the 30/min limit.

Two dispatch-boundary policies already existed in ad-hoc form: the v0.5.0
control-plane timeout wrapper (`ArcanaService._request`), and the
`raise_for_status` mapping that turns a 429 into `RateLimitError` already
carrying `reset_seconds`. Should the library *act* on a 429; where should that
logic live; and what should the default be?

## Decision Drivers

- One owner for retry, not per-consumer boilerplate that drifts.
- The common batch path (chat / convert) is idempotent → safe to auto-retry.
- Never block for a long window inside a library call.
- Preserve the `RateLimitError` contract and the ADR-0002 metadata.
- Thread-safe under [ADR-0004](0004-non-blocking-operations-via-futures.md)
  workers; an injectable sleep so tests never block.
- Do not add a *third* parallel dispatch mechanism.

## Considered Options

- **(a) Stay passive** (ADR-0002 status quo) — the caller retries.
- **(b) Opt-in retry** (default off).
- **(c) Default-on retry at a single shared dispatch seam** — scoped to
  idempotent calls, opt-out.
- **(d) Per-consumer retry** — the avor-backend stop-gap.
- **(e) Session-mounted `HTTPAdapter`** — retry/timeout on the shared session.

## Decision Outcome

Chosen: **(c)**. A thin `execute()` seam in `saia_python/_http.py` applies a
`RetryPolicy` at the single point every service dispatches through. Retry is
**on by default** and **opt-out**, scoped to **idempotent** calls.

- The seam sits **before** `raise_for_status` and **returns the raw response**,
  so when retry is disabled, the budget is spent, or the window must not be
  waited on, the existing `RateLimitError` flow fires unchanged — no new
  exception type, and streaming and non-streaming behave identically.
- **Honest wait policy** for the single `reset_seconds` across four windows:
  honor a reset within `max_waiting_time` (default 60 s, settable); **fail fast**
  (raise, no sleep) on a longer or zeroed window; bounded blind fallback
  (31 s × 2) when no reset header is present. The library never blocks ~an hour.
- **Idempotency is declared at the call site**; mutations pass
  `idempotent=False` and are never auto-retried (overridable per call). Streaming
  retries only the *opening* 429, never mid-stream.
- The **control plane shares the same seam** (`_request` now delegates to
  `execute`): the timeout default is preserved, idempotent ARCANA reads inherit
  the policy, and `heartbeat` opts out so a liveness probe never blocks.
- **Default-on is accepted now** while the known user base is tiny (pre-1.0) —
  the cheapest moment to move a default before adoption hardens expectations.

### Consequences

- Good — batch jobs survive transient minute-window limits unattended with zero
  consumer code; a single dispatch seam now carries both timeout and retry; the
  ADR-0002 metadata is still surfaced on every response.
- Trade-off — a 429 on an idempotent call now *blocks* (bounded by
  `max_waiting_time` and the retry caps) instead of raising immediately. This is
  a real behavior change, accepted for the small user base; opt out with
  `SAIAClient(retry=False)` or per call.
- Trade-off — only the minute window's reset is timable from a single
  `reset_seconds`; longer windows fail fast rather than waiting precisely.

### Confirmation

`tests/test_transport_policy.py` covers the planner, `execute`, the
streaming/non-streaming integration, and `resolve_retry`;
`tests/test_arcana.py::TestControlPlaneRetry` covers the mutation / heartbeat /
idempotent wiring. All waits route through an injected `sleep`, so the suite
never blocks. The unchanged `TestDefaultTimeout` confirms the control-plane
timeout behavior is preserved by the convergence.

## More Information

Amends [ADR-0002](0002-rate-limit-metadata-on-responses.md) — the passive default
becomes active (opt-out); the metadata decision itself stands. Extends
[ADR-0004](0004-non-blocking-operations-via-futures.md) — retry runs inside the
`wait=False` worker and shared state is thread-safe. Folds in the v0.5.0
control-plane timeout wrapper as the control-plane instance of the same seam. The
full design and phased rollout live in `docs/proposals/rate-limit-handling.md`.
