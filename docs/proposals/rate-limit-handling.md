# Proposal: Transport-policy layer for rate-limit handling (default-on, opt-out)

**Status:** Phase 1 implemented (2026-06-02) · **Scope:** `saia_python` client / session dispatch layer · **Type:** default-on feature + a small architectural seam
**Supersedes:** the earlier `rate-limit-handling` draft (absorbed below — reference impl preserved in §12).
**Relates to:** [ADR-0002](../adr/0002-rate-limit-metadata-on-responses.md) (rate-limit metadata on responses),
[ADR-0004](../adr/0004-non-blocking-operations-via-futures.md) (non-blocking via Futures + dedicated Sessions),
and the v0.5.0 control-plane timeout work (`arcana._request` / `DEFAULT_TIMEOUT`).
**Reference implementation:** a proven minimal core shipped in **avor-backend v0.8.11** (2026-06-02) — the lift-and-generalise seed (§12).

---

## 0. Thesis — one seam, on by default

Auto-retry on 429 is not a one-off feature. It is one instance of a pattern the codebase is **already converging on**: a *policy interposed on every outbound request at a single chokepoint*. Two such policies exist today, in ad-hoc form:

1. **Timeout injection** — `arcana._request` (v0.5.0) sets a default `(connect, read)` on control-plane calls.
2. **Error mapping + rate-limit metadata** — `exceptions.raise_for_status` (the universal chokepoint every service funnels through) maps 429 → `RateLimitError` and attaches the parsed `RateLimitInfo`.

Give retry — and them — **one home: a thin transport-policy seam around `session.request`.** Retry is **ON by default**, scoped to **idempotent** calls, and **opt-out** (globally or per call). This **amends** [ADR-0002](../adr/0002-rate-limit-metadata-on-responses.md)'s default — the library now *acts* on a transient 429 instead of only surfacing it — while **retaining** ADR-0002's passive metadata on every response and an explicit escape hatch (§14).

**The default change is consciously accepted now.** The install base is currently tiny (a few known users, pre-1.0), so this is the cheapest moment to flip a default — before adoption hardens expectations. The behavior change is real but acceptable in this window.

The keystone that keeps this safe: the seam sits **before** `raise_for_status` and **returns the raw response**, so when it is disabled, exhausts its budget, or hits a window it must not wait on, the existing `RateLimitError` flow fires unchanged. No new exception type, no contract change, no special-casing of streaming.

## 1. Motivation

SAIA enforces layered rate limits (observed live, 2026-06-02):

| Window | Limit |
|--------|-------|
| minute |   30  |
| hour   |  200  |
| day    | 1000  |
| month  | 3000  |

Today a 429 surfaces as `RateLimitError` and **aborts the call**. Every batch or unattended workload must hand-roll its own retry/backoff — duplicated across consumers, and usually wrong. The driving case is the **AvorMedical guideline-ingestion pipeline** (~26 chapter PDFs via the Docling endpoint + enrichment / parser-comparison runs): against a 30/min ceiling it *reliably* trips the per-minute limit. Conversions and inference reads are idempotent, so bounded auto-retry carries no correctness risk for the common batch path — which is why **on-by-default** is the right ergonomics for this library.

## 2. Where this sits — existing architecture (ground truth, with file refs)

- **The chokepoint already exists.** `raise_for_status` (`saia_python/exceptions.py:54`) is called by *every* service. On 429 it raises `RateLimitError(detail, rate_limits=parse_rate_limits(resp.headers))` — so **`reset_seconds` already rides the error** (`exceptions.py:65`). The retry feature *consumes* this; it does not invent a new signal.
- **The data we have — and don't.** `RateLimitInfo` (`saia_python/rate_limits.py`) carries per-window `limit_*` / `remaining_*` for minute/hour/day/month, but a **single** `reset_seconds` (from the `ratelimit-reset` header). We can tell *which* window is exhausted (`remaining_* == 0`) but can only *time* the reset of whichever window `reset_seconds` reflects (empirically the minute). §5 makes the retry honest about this.
- **ADR-0002 — was passive.** Responses expose limits (`_rate_limits` dict; `SSEStream.rate_limits`); the library did not act on them. This proposal **amends the default** (act on idempotent 429s) but **keeps the metadata** and the opt-out.
- **ADR-0004 — Futures + dedicated Sessions.** `wait=False` runs on a worker thread with its *own* `Session`. Consequences: (a) any shared policy state (a pacing throttle) **must be thread-safe**; (b) the seam must run **inside the worker**, so a `wait=False` call retries too; (c) jitter is required to avoid a thundering herd across parallel workers.
- **The timeout seam is the same shape.** `arcana._request` (`saia_python/arcana.py:90`) injects a default timeout on control-plane calls; data-plane calls (chat, voice, documents) are deliberately uncapped. That is *literally another dispatch-boundary policy* — §10 folds it into the same seam over time.

> **Insight:** timeout, error-mapping/metadata, and rate-limit retry are all **dispatch-boundary concerns**. One seam, composed policies.

## 3. Design principles (the lens)

1. **Active-by-default, bounded, opt-out.** On by default for *idempotent* calls (chat / convert / voice): a 429 transparently waits-and-retries within bounds. Opt out globally (`retry_on_rate_limit=False`) or per call (`retry=False`). **Mutations still raise by default** (idempotency, §7). Passive metadata (ADR-0002) is unchanged — this changes only whether the library *acts*. (Amends ADR-0002's default, §14; accepted now while the user base is small.)
2. **One chokepoint.** Retry lives at the session dispatch seam, not scattered per service.
3. **Honest, bounded wait.** Wait only when we can *time* the reset — i.e. the reset is within `max_waiting_time` (default 60 s, the minute window); **fail fast** (raise, no sleep) on anything longer. The blind fallback (no header) is a *separate, smaller* budget.
4. **Mutation safety.** The call site *declares* idempotency; mutations are not auto-retried even when retry is on.
5. **Testability seam.** Inject `sleep` (and clock) so tests never block — a hard constraint, already proven in the reference impl.
6. **Observability.** `logging` (module logger) on every wait/retry — unattended runs must not be mysteriously slow-and-silent.
7. **Thread-safety & composition.** Safe under ADR-0004 workers; the inter-attempt *wait* is a sleep, independent of any per-request `timeout`, so the two policies compose without conflict.

## 4. The seam

A thin executor in `saia_python/_http.py`, wrapping the lowest dispatch level shared by **both** the sync path and the ADR-0004 worker path, sitting **before** `raise_for_status`:

```python
def execute(session, method, url, *, policy, idempotent, sleep=time.sleep, **kwargs):
    """Issue session.request(...) under a transport policy; return the Response.

    Returns the raw response unchanged on success OR on give-up, so the existing
    raise_for_status chokepoint still raises RateLimitError when retry is off,
    the budget is spent, or the window must not be waited on. Inspects only
    status + headers (never the body), so streaming and non-streaming behave
    identically and the stream is not consumed.
    """
    attempt = 0
    while True:
        policy.pace(sleep)                       # phase 2 no-op until enabled
        resp = session.request(method, url, **kwargs)
        if resp.status_code != 429 or not policy.applies(idempotent):
            return resp                          # success, or retry not allowed → raise downstream
        wait = _plan(parse_rate_limits(resp.headers), policy, attempt)
        if wait is None:
            return resp                          # window we won't wait on / budget spent → raise
        resp.close()                             # release the (esp. streamed) connection before retry
        attempt += 1
        log.info("SAIA 429 (attempt %d) — waiting %.0fs", attempt, wait)
        sleep(wait + _jitter(policy))
```

`policy.applies(idempotent)` is `policy.on_rate_limit and (idempotent or policy.retry_mutations)`. Every service call routes through `execute(...)` instead of calling `self._session.<verb>` directly.

### 4.1 On which level is this implemented?

**Client-level configuration, transport-level enforcement, call-level override** — the same shape as the v0.5.0 `timeout`, so the mental model stays singular:

- **Configured on `SAIAClient`** (`retry=RetryPolicy(...)` or the `retry_on_rate_limit=` shorthand), stored as `self._retry`, and **forwarded to each service** exactly as `timeout` is today — `client.chat` / `.arcana` / `.voice` / `.documents` receive `retry=self._retry` when constructed.
- **Enforced at the shared dispatch seam** in `saia_python/_http.py` (`execute()`), the lowest level common to the synchronous path **and** the ADR-0004 worker threads — so a blocking call and a `wait=False` `Future` inherit the same policy from the same code.
- **Overridable per call**: a method-level `retry=` kwarg (`RetryPolicy` | `True` | `False`) wins over the client default for that one call.

It is **not** implemented per service and **not** in the consumer — that is the whole point (§11 retires the backend's per-consumer wrapper).

## 5. Reactive retry — the wait policy

Given a single `reset_seconds` but four windows, gated by the settable `max_waiting_time` (default 60 s):

```python
def _plan(info, policy, attempt):
    """Seconds to wait before the next attempt, or None to give up (→ raise)."""
    # A longer window is exhausted → we cannot time its reset; never block ~an hour.
    if any(getattr(info, f"remaining_{w}") == 0 for w in ("hour", "day", "month")):
        return None
    reset = info.reset_seconds
    if isinstance(reset, (int, float)) and reset > 0:
        if reset > policy.max_waiting_time:                 # reset beyond the cap → fail fast
            return None
        return None if attempt >= policy.max_retries else reset + 1.0   # +1s: wake AFTER rollover
    # reset_seconds absent (any reason) → conservative blind fallback.
    return None if attempt >= policy.fallback_max_retries else policy.fallback_wait
```

- **Reset known and ≤ `max_waiting_time`** (default 60 s): **wait until the next reset** (`reset_seconds + 1`, + jitter) and retry, up to `max_retries` (5). This is the common minute-window case — the one window we can time, so we wait it out rather than failing. `max_waiting_time` is **set per client (and overridable per call)** — raise it if you knowingly want to wait out longer resets, lower it for stricter interactive bounds.
- **Reset known but > `max_waiting_time`, or any longer window at 0** (`remaining_hour/day/month == 0`): **raise immediately, no sleep** — we can't time a long window's reset and won't block past the cap. `RateLimitError` surfaces *with its `rate_limits`* so the caller decides.
- **Reset unknown** (header missing, parse error, whatever): **blind fallback — wait 31 s, retry, at most twice**, then raise. Deliberately smaller than the reset-driven budget because we are guessing; two 31 s waits straddle a 60 s window.

> Worst-case added latency for a call that ultimately fails: reset path ≈ `max_retries × (max_waiting_time + 1)` (≈ 5 min at the 60 s default, on a pathological, persistently-empty minute window — in practice one ~minute wait clears it, since each reset refills the minute bucket); fallback path = `2 × 31 s`. Lower `max_retries` or `max_waiting_time` to tighten the interactive bound.

## 6. Streaming policies (detail)

Streaming needs its own rules because the 429 and the token stream live at different moments:

1. **Where a streamed 429 surfaces.** A 429 response is ordinary JSON, **not** SSE. With `stream=True` the body is requested lazily; today the error only surfaces when iteration begins (`iter_sse` → `raise_for_status`). The seam wraps the **POST** and inspects `resp.status_code` + headers **before** an `SSEStream` is constructed, so it sees the 429 up front.
2. **Retry covers connection establishment only — never mid-stream.** Retry applies *only* to the initial 429, before any tokens have been yielded. Once the server returns **200 and tokens begin flowing**, a drop mid-stream is **not** retried: partial chunks were already handed to the caller, and replaying the POST would produce a second, divergent completion. "Resume a broken stream" is explicitly out of scope; the boundary is hard.
3. **Connection hygiene.** A streamed 429 holds an open connection; the seam calls `resp.close()` **before** sleeping/retrying to release it back to the pool (consistent with the `SSEStream.close()` discipline from ADR-0002/0004). Without this, retries leak sockets.
4. **Status/headers only — the stream is never consumed to decide.** The seam reads `resp.status_code` and `resp.headers` (where `ratelimit-reset` lives); it never calls `iter_lines()`/`iter_content()`. So a successful (200) streamed response is handed to `SSEStream` untouched, with its body fully intact.
5. **Idempotency.** Streaming chat / arcana.chat is inference → `idempotent=True` → eligible for the initial-429 retry under the default-on policy. (A streamed *mutation* would not be — but there are none.)
6. **Pacing (phase 2) applies before the POST**, identical to non-streaming.
7. **Metadata parity preserved.** `SSEStream.rate_limits` is still populated from the final (successful) response headers, exactly as ADR-0002 specifies — the retry is invisible to that surface.
8. **Give-up is the status quo.** If the initial-429 retries are exhausted (or it is a long-window 429), the seam returns the 429 response; `SSEStream(resp)` wraps it and iteration raises `RateLimitError` — the same behavior streaming has today, just preceded by bounded waiting.

Net: **streaming gets transparent retry on the opening 429 and nothing else.** This is the only safe scope, and it covers the real failure mode (a batch worker opening a stream right as the minute window is exhausted).

## 7. Mutation / idempotency safety

The library cannot *infer* whether an arbitrary POST is safe to replay; the **call site declares it**, and mutations are excluded even though retry is on by default:

| Call | `idempotent` | Retried by default? |
|------|:---:|:---:|
| chat / arcana.chat / documents.convert / voice | `True` | **yes** |
| ARCANA `create` / `delete` / `delete_index` | `False` | no (raises) |
| ARCANA `upload` (PUT overwrite) | `False` default | no — *may* opt in (backend ADR-0007: PUT is idempotent) |

Separation of concerns: the **call site owns semantics** (`idempotent=`), the **policy owns aggressiveness** (`retry_mutations`, or a per-call `retry=`).

## 8. Proactive pacing (phase 2, optional)

An optional client-side throttle (min-interval or token bucket targeting `< limit/min`) so batch jobs self-pace and rarely hit 429 at all; reactive retry remains the safety net. Thread-safe (lock), jitter applied.

## 9. Public API (default ON)

```python
from saia_python import SAIAClient, RetryPolicy

client = SAIAClient(retry=RetryPolicy(
    on_rate_limit=True,      # DEFAULT ON — a 429 on an idempotent call is waited-out for you
    max_retries=5,           # reset-driven retries (minute window)
    max_waiting_time=60,     # max a single wait may block (seconds); default 60, settable;
                             #   a reset beyond it → fail fast (raise, no sleep)
    fallback_wait=31,        # blind fallback when no reset header
    fallback_max_retries=2,  # ...tried at most twice
    jitter=(0.0, 2.0),
    retry_mutations=False,   # ARCANA writes still raise
    pace=None,               # phase 2
))
# opt OUT globally: SAIAClient(retry_on_rate_limit=False)
# opt OUT one call:  client.chat.completions(..., retry=False)
# longer wait for one batch: client.chat.completions(..., retry=RetryPolicy(max_waiting_time=180))
```

A structured `RetryPolicy` is preferred over a growing kwargs list: composable, per-call overridable, unit-testable in isolation. The bool shorthand keeps the simple cases one flag. `max_waiting_time` is the single knob that bounds how long any one wait may block.

## 10. Convergence with the timeout layer (no churn now)

`arcana._request` is the **control-plane instance of this very seam** (inject `timeout`). Do **not** refactor it as part of phase 1 — it is freshly shipped and tested. When next touched, fold it into `execute(...)` with a *control-plane policy*. End state: **one dispatch seam, per-plane policy** — data-plane (uncapped timeout, retry-on), control-plane (timeout default, retry-maybe). The holistic target, reached incrementally.

## 11. Phased rollout & migration

- **Phase 1 (MVP):** `execute()` + `RetryPolicy` in `_http.py`; route the data-plane chat path (`post_chat_completion`), `documents.convert`, and `voice` through it; default ON; injected `sleep`; tests. Delivers the backend's need with zero consumer code.
- **Phase 2:** proactive pacing.
- **Phase 3:** converge the control-plane timeout wrapper (§10) and add per-call `retry=` override.
- **Backend migration:** **delete** avor-backend's `chat_completions` retry wrapper and `tests/test_saia_retry.py` — with default-on it is dead weight; handling now has a single owner in the library.

## 12. Reference implementation (avor-backend v0.8.11 — proven, 2026-06-02)

The stop-gap added in the consumer (`arcana/client.py`) when ingestion tripped 30/min. Deliberately minimal; the validated core is the seed, what it *omits* is exactly the library-level work above.

```python
DEFAULT_RATELIMIT_MAX_RETRIES = 5
DEFAULT_RATELIMIT_WAIT_SECONDS = 31.0          # fallback only (60s window; a 2nd retry covers it)

def _ratelimit_wait_seconds(exc, fallback: float) -> float:
    """Honour the server's reset_seconds (+1s buffer to wake AFTER rollover); else fallback."""
    info  = getattr(exc, "rate_limits", None)                       # RateLimitInfo | None
    reset = getattr(info, "reset_seconds", None) if info is not None else None
    if isinstance(reset, (int, float)) and reset > 0:
        return float(reset) + 1.0
    return float(fallback)

def chat_completions(*, max_retries=DEFAULT_RATELIMIT_MAX_RETRIES,
                     fallback_wait_seconds=DEFAULT_RATELIMIT_WAIT_SECONDS,
                     _client=None, _sleep=time.sleep, **kwargs):
    """SAIAClient.chat.completions(**kwargs) with bounded 429 retry."""
    from saia_python import RateLimitError
    client = _client if _client is not None else get_saia_client()
    attempt = 0
    while True:
        try:
            return client.chat.completions(**kwargs)
        except RateLimitError as exc:                       # ONLY 429s retried; others propagate
            attempt += 1
            if attempt > max_retries:
                raise
            wait = _ratelimit_wait_seconds(exc, fallback_wait_seconds)
            log.warning("SAIA rate limit (attempt %d/%d) — waiting %.0fs. %s",
                        attempt, max_retries, wait, exc.rate_limits or "(no headers)")
            _sleep(wait)
```

**Carries over:** drive the wait from `exc.rate_limits.reset_seconds` (+1 s buffer), `31 s` fallback when absent, retry **only** `RateLimitError`, injected `_sleep`/`_client` as the test seam, one shared chokepoint (confirms §2/§4). Validated by 6 offline tests (`tests/test_saia_retry.py`).
**Deliberately omitted → why it belongs in the library:** no `max_waiting_time` / long-window fail-fast (it sleeps `reset_seconds` unconditionally — §5); no jitter / thread-safety (needed under ADR-0004 — §6/§8); no pacing (§8); wraps `chat.completions` only, not the shared dispatch (§4/§11).

## 13. Acceptance criteria · test plan · risks

**Acceptance:** default ON ⇒ a 429 on an idempotent call is retried per §5; opt-out (`retry_on_rate_limit=False` or per-call `retry=False`) ⇒ single attempt = today's behavior. Honors the server reset within `max_waiting_time`; **raises immediately, no sleep**, when the reset is > `max_waiting_time` or a longer window is at 0; blind fallback = 31 s × ≤ 2 then raise; `max_waiting_time` settable per client and per call; mutations not auto-retried; streaming retries the opening 429 only, never mid-stream; `wait=False` retries inside the worker; pacing state thread-safe; every wait logged.

**Test plan** (repo convention: `MagicMock` session, injected `_sleep`, no real HTTP — new `tests/test_transport_policy.py`): 429-then-200 → retried, slept ≈ reset+1; reset > `max_waiting_time` → raises with **zero** sleeps; long-window (`remaining_hour==0`) → raises, no sleep; missing header → two 31 s waits then raise; exceeds `max_retries` → raises; custom `max_waiting_time` honored (per client and per call); non-idempotent op not retried (default); `retry=False` ⇒ single attempt; streaming opening-429 retried before `SSEStream`, mid-stream drop **not** retried; `resp.close()` called before each retry; jitter within bounds. Keep `ruff` + `mypy` clean.

**Risks (condensed):** interactive waits by default — **accepted**: the known user base is tiny (pre-1.0), making this the cheapest moment to change the default; it is bounded by `max_waiting_time` + the retry caps, logged, long windows fail fast, and opt-out exists. Thundering herd → jitter + pacing. Masking chronic over-use → pacing + surfaced quota. *Empirical check:* confirm SAIA emits `ratelimit-reset` on the 429 itself (correct either way via fallback). *Quota accounting:* confirm whether rejected 429s count against quota (a live test hinted they may not).

## 14. Decision record

On acceptance, record as **ADR-0006 — "Transport-policy layer for rate-limit handling."** It **amends ADR-0002's default**: for *idempotent* 429s the library now *acts* (bounded, reset-aware retry capped by `max_waiting_time`) rather than only surfacing metadata — while **retaining** ADR-0002's passive metadata on every response and an explicit opt-out. The default change is **accepted now** while the user base is small (pre-1.0) — the cheapest time to move a default. It **extends ADR-0004** (in-worker retry + thread-safety) and sets the convergence target for the control-plane timeout seam (§10).

## 15. Implementer notes

- Touch points: new seam + `RetryPolicy` (with `max_waiting_time`, default 60, settable per client and per call) in `saia_python/_http.py`; store `self._retry` on `SAIAClient` and forward it to services (mirror the v0.5.0 `timeout` threading); route `post_chat_completion`, `documents`, `voice` through `execute()`; declare `idempotent=` at each call site. `RateLimitError` already carries `reset_seconds` — no change there.
- Python ≥ 3.10, `from __future__ import annotations`, Google-style docstrings.
- Gate (any Python ≥3.10 with dev deps; e.g. `/Users/friedrichschwarz/mambaforge/bin/python`): `pytest -q`, `ruff check`, `ruff format --check`, `mypy`.
