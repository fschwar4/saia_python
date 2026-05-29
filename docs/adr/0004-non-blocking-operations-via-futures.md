# Non-blocking operations via Futures and dedicated Sessions

- Status: Accepted
- Date: 2026-05-29
- Deciders: saia-python maintainers

## Context and Problem Statement

Some SAIA operations are slow: audio transcription/translation, and ARCANA index
generation. Callers want to start them without blocking, and the client shares a
single `requests.Session` across all calls. Two questions follow:

1. How does a non-blocking call return its result?
2. How do background requests interact with the shared `Session`?

The original `wait=False` paths spawned a `daemon` thread that ran the request on
the **shared** `Session` and **discarded the return value**. For voice that meant
the transcription — the entire point of the call — was lost; for both paths it
raced the shared `Session` (not documented thread-safe) against the caller's
other requests.

## Decision Drivers

- A non-blocking call must still be able to deliver its result.
- `requests.Session` is not safe to use from multiple threads concurrently.
- `daemon` threads can be killed at interpreter exit before completing.
- Keep the simple, blocking default (`wait=True`) unchanged.

## Considered Options

- **Future + dedicated Session** — `wait=False` returns a
  `concurrent.futures.Future`; the worker runs on its own `Session`.
- **Lock around the shared Session** — serialize all requests through a mutex.
- **No background thread** — fire a short-timeout request and return.
- **Bare daemon thread** (the original) — fire-and-forget, result discarded.

## Decision Outcome

Chosen option: **Future + dedicated Session** for `VoiceService.transcribe()` /
`translate()`: `wait=False` returns a `Future[str]` resolved on a worker thread
that uses its own `Session`. For `ArcanaService.generate_index(wait=False)` —
genuinely fire-and-forget, since the result is polled later via `info()` — the
background trigger now also runs on its **own** `Session`; the no-thread,
short-timeout option remains a reasonable alternative there.

### Consequences

- Good — voice results are retrievable (`fut.result()`, `.done()`, callbacks),
  and errors surface on `.result()` instead of vanishing.
- Good — background requests never share the client `Session`, eliminating the
  data race with the caller's concurrent calls.
- Trade-off — a dedicated `Session` per background call forgoes connection
  keep-alive (one extra TLS handshake); negligible for these infrequent ops.
- Known limitation — workers are still `daemon` threads, so a process that exits
  before `fut.result()` may abandon the request. Callers needing a guarantee
  should await the `Future`.

### Confirmation

`tests/test_voice.py` asserts `wait=False` returns a resolvable `Future`, that
errors propagate through it, and that the shared `Session` is not used;
`tests/test_arcana.py` asserts `generate_index(wait=False)` posts on a fresh,
closed `Session`.

## More Information

The `SSEStream` wrapper (ADR-0002) is where streaming-response cleanup
(`close()` / connection release) lives. `requests`' own guidance is to use one
`Session` per thread.
