# Rate-limit metadata on responses

- Status: Accepted
- Date: 2026-05-29
- Deciders: saia-python maintainers

## Context and Problem Statement

The SAIA API returns rate-limit state in `x-ratelimit-*` response headers.
Callers frequently want that state right after a call, without paying for a
second round-trip to `get_rate_limits()`. How should a chat / ARCANA response
expose it?

The original implementation attached a `RateLimitInfo` **dataclass instance** to
the response dict under `_rate_limits`. That made the dict non-JSON-serializable
(`json.dumps` raised `TypeError`) and was present only on the non-streaming path.

## Decision Drivers

- The response object should stay JSON-serializable (cached, logged, forwarded).
- Convenience: avoid a mandatory extra API call just to read limits.
- Parity between the streaming and non-streaming paths.
- Minimize churn to the existing, already-used `_rate_limits` convenience.

## Considered Options

- **(a) Client attribute** — store `client.last_rate_limits`; keep the response
  pure.
- **(b) Tuple / wrapper return** — return `(response, rate_limits)`.
- **(c) Keep it on the response, but correct it** — store a plain
  JSON-serializable dict, expose it on streaming too, and document the key.
- **(d) Drop it** — rely on `get_rate_limits()` and the `rate_limits` already
  attached to `RateLimitError` (429).

## Decision Outcome

Chosen option: **(c)**. Non-streaming responses carry `_rate_limits` as a plain
dict (`RateLimitInfo.to_dict()`), so the whole response can be `json.dumps`-ed.
Streaming calls return an `SSEStream` — iterable over chunks, with a
`.rate_limits` attribute exposing the same dict (available immediately, since
headers arrive before the body). The key and attribute are documented.

### Consequences

- Good — responses are JSON-safe again, and both paths expose limits.
- Good — lowest-churn option; keeps the ergonomic one-object access callers
  already relied on.
- Trade-off — `_rate_limits` remains a field the API never sent, so strict
  schema validators will see an extra key. This is documented and intentional.
- Trade-off — streaming uses an attribute (`stream.rate_limits`) while
  non-streaming uses a dict key (`resp["_rate_limits"]`); the access patterns
  differ because one object is a dict and the other a stream.

### Confirmation

`RateLimitInfo.to_dict()` is unit-tested for JSON-serializability;
`tests/test_streaming.py::TestSSEStream` asserts `.rate_limits` is populated and
that the stream still yields chunks.

## More Information

The formatted, human-readable table (`str(RateLimitInfo)`) remains available via
`client.get_rate_limits()`. Relates to ADR-0004 — the `SSEStream` wrapper is
also where streaming-response cleanup lives.

The passive-by-default stance recorded here is **amended by
[ADR-0006](0006-transport-policy-rate-limit-handling.md)**, which makes the
library retry 429s by default (opt-out); the metadata decision itself stands.
