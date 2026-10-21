# PoC D — Async Platform Lifecycle / UNKNOWN Reconciliation

## Hypothesis

ViMi Social can model asynchronous publishing as a monotonic lifecycle in which an ambiguous external mutation outcome never causes an automatic second publish. Reconciliation must use the same logical operation identity and may authorize a retry only when the adapter can positively establish that no external publication exists.

## Architecture question

Can one platform-neutral orchestration contract safely cover providers that:

- confirm publication synchronously;
- accept work asynchronously and expose pending state;
- time out after an external mutation may already have happened;
- expose eventual-consistency lookups;
- send duplicate or out-of-order callbacks;
- distinguish known-safe pre-mutation failures from permanent failures?

This PoC is a deterministic platform mock. PoC A already validates Temporal durability/versioning; PoC D isolates lifecycle semantics so Architecture 1.0 can compose the two results without repeating the Temporal experiment.

## State contract

The PoC uses the Architecture 0.10 publication states:

```text
CREATED
  -> STARTED
       -> PROVIDER_ACCEPTED -> PENDING -> CONFIRMED
       -> CONFIRMED
       -> UNKNOWN
       -> FAILED_SAFE
       -> FAILED_PERMANENT

UNKNOWN
  -> reconcile found confirmed  -> CONFIRMED
  -> reconcile found pending    -> PENDING
  -> reconcile proved absent    -> FAILED_SAFE
  -> reconcile inconclusive     -> UNKNOWN

FAILED_SAFE
  -> explicit bounded safe retry -> STARTED
```

`CONFIRMED` and `FAILED_PERMANENT` are terminal in this PoC. A late or duplicate callback must not regress a terminal result.

## Operation identity

`operation_key` is the logical external publication identity. A repeated start for the same operation key must join the existing lifecycle rather than create another mutation. Reusing an operation key for a different target is a conflict.

A safe retry reuses the same operation key. The PoC does not assume that every real provider offers native idempotency; when it does not, `PROVED_ABSENT` is the required gate before an external mutation can be attempted again after an ambiguous result.

## PASS criteria

Automated tests must prove all of the following:

1. synchronous confirmation performs one external mutation and becomes `CONFIRMED`;
2. asynchronous acceptance can move through `PROVIDER_ACCEPTED` / `PENDING` to `CONFIRMED` without a second mutation;
3. an ambiguous publish result becomes `UNKNOWN` and repeated `start()` calls do not publish again;
4. an inconclusive lookup preserves `UNKNOWN` (or the current pending state) and does not authorize retry;
5. only an explicit `PROVED_ABSENT` reconciliation result can turn an ambiguous outcome into `FAILED_SAFE`;
6. `FAILED_SAFE` does not auto-retry; retry is explicit and bounded;
7. a known-safe pre-mutation failure may enter `FAILED_SAFE` directly;
8. a permanent provider failure becomes `FAILED_PERMANENT` and cannot be retried;
9. operation-key/target mismatch is rejected;
10. concurrent starts for the same operation key cause at most one publish call;
11. duplicate callbacks are idempotent;
12. late pending callbacks cannot regress `CONFIRMED`;
13. callback and reconciliation transitions remain monotonic under serialized operation ownership;
14. tests and `REPORT.md` do not claim provider guarantees that the mock does not prove.

## Non-goals

- no real social-network API calls or credentials;
- no proof of provider-specific webhook authenticity or account-to-tenant resolution (PoC B covers trusted tenant resolution architecture);
- no repeat of Temporal worker-kill/versioning tests (PoC A covers durable execution);
- no rate-limit policy optimization;
- no production database schema;
- no claim that a generic HTTP 404 alone means `PROVED_ABSENT` — that semantic must be adapter-specific and strong enough to rule out eventual-consistency ambiguity.

## Architecture 1.0 implication if PASS

Platform adapters should expose typed mutation and reconciliation outcomes rather than raw HTTP exceptions. Durable orchestration should persist `UNKNOWN`, reconcile by stable operation identity, keep external mutations non-retrying after ambiguous outcomes, and allow a bounded re-dispatch only after adapter-specific proof of absence or a known-safe pre-mutation failure.
