# ViMi Social — validated post-PoC architecture decisions

**Status:** Architecture 0.10 amendments validated by PoCs A–E  
**Date:** 2026-10-16  
**Purpose:** Preserve executable findings that must be incorporated into Architecture 1.0.

This document does not replace Architecture Baseline 0.10. It records stricter or clarified contracts discovered through implementation, CI failure injection, and independent review.

---

## PoC A — Temporal durability, identity and workflow evolution — PASS

Validated decisions:

1. **Workflow/publication identity is derived from the stable external `operation_key`, not a caller `target_id`.** The same operation key cannot create a second workflow merely because a different target identifier is supplied.
2. Irreversible publish activities have **no automatic Temporal retry after ambiguous execution**; the default is effectively one mutation attempt before reconciliation.
3. Provider accepted + lost response, actual activity timeout after mutation may have happened, and equivalent ambiguous outcomes become **`UNKNOWN`**.
4. `UNKNOWN` is not retry authorization. It enters reconciliation.
5. A missing provider lookup result is not automatically proof of absence; eventually consistent lookups can remain `UNKNOWN`.
6. A retry is allowed only after **conclusive provider evidence of absence** or a failure positively classified as safe/pre-mutation.
7. Known-safe pre-mutation failures may use a deliberately bounded retry path separate from UNKNOWN handling.
8. Durable recovery evidence requires a real worker-process failure after a persisted checkpoint, not only graceful shutdown.
9. Workflow evolution must be proven with a compatible newer worker/workflow implementation replaying prior history.

Architecture 1.0 must combine deterministic workflow identity, non-retrying irreversible mutation activities, and explicit reconciliation.

---

## PoC B — PostgreSQL tenant isolation / RLS — PASS

Validated decisions:

1. Application-facing database roles are **non-owner, non-superuser, `NOBYPASSRLS`**.
2. The migration owner is separate from application logins.
3. Any controlled cross-tenant executor with `BYPASSRLS` is **`NOLOGIN`** and sits behind narrow `SECURITY DEFINER` functions.
4. Tenant-scoped helpers must own the **top-level transaction** or fail closed; nesting inside an existing transaction can make `SET LOCAL` semantics unsafe across savepoints.
5. Tenant context must be transaction-local and must not survive pooled physical connection reuse.
6. Temporal/background jobs must authenticate or derive an immutable execution envelope before reconstructing trusted `ExecutionContext`; raw caller-controlled tenant IDs are insufficient.
7. Webhook payload tenant claims are ignored. Tenant ownership is resolved from server-side platform-account mapping through a narrow resolver interface.
8. Privileged support reads require an explicit target and meaningful reason.
9. A transactional audit row alone is insufficient because a caller can roll it back after reading data. Production therefore requires **external append-only or otherwise caller-non-rollbackable audit evidence before privileged results leave the trusted support boundary**.
10. RLS must be tested in CI with production-like restricted roles, not merely with the migration owner/superuser.

---

## PoC C — secure media ingest — PASS

Validated decisions:

1. Remote media is untrusted input.
2. URL parsing permits only the explicitly supported HTTP/HTTPS forms, default ports, and no URL credentials.
3. Hostnames are resolved before connection; **all** returned addresses must satisfy the public-unicast destination policy. Mixed safe/unsafe answers fail closed.
4. Multicast must be rejected explicitly in addition to generic global/public address checks.
5. The exact validated address set is pinned into the HTTP connector; validation and transport cannot perform independent DNS decisions.
6. Every redirect is reparsed, re-resolved, and revalidated; automatic redirect following remains disabled.
7. DNS and HTTP timeout configuration must be finite and strictly positive.
8. Response limits are enforced both from declared length and while streaming. Automatic decompression is disabled and non-identity content encoding is rejected at this boundary.
9. Basic media signature + declared content type is only an ingest gate, not complete codec/container safety.
10. Temporary-file descriptor ownership and network cleanup must be cancellation-safe.
11. Content-addressed finalization must not blindly overwrite an existing digest artifact.
12. If cancellation arrives while content-addressed promotion/finalization is in flight, the promotion operation must be shielded/settled before cancellation propagates so cleanup observes the actual committed filesystem state.
13. Once a final content-addressed artifact becomes visible to concurrent consumers, publication is an **irrevocable commit point**; cancellation must not remove an artifact already adopted by another fetch.
14. Helper processes use argv execution, minimal environment, finite runtime/output limits, and dedicated POSIX process-group termination on timeout, output-limit failure, and cancellation.
15. Production still requires stronger media-worker isolation: CPU/memory/filesystem/network restrictions, ephemeral scratch space, and minimal credentials.

---

## PoC D — async platform lifecycle / UNKNOWN reconciliation — PASS

Validated decisions:

1. `operation_key` is the primary logical publication identity and outlives any provider response/external ID.
2. The first accepted request binds that `operation_key` immutably to its `target_id`. Reusing the same operation key with a different target is a consistency error and must be rejected rather than silently joining the original lifecycle.
3. Duplicate and concurrent starts for the same operation key **and the same bound target** join one serialized lifecycle and produce at most one publish dispatch for that start phase.
4. Platform adapters return **typed mutation and reconciliation outcomes**, not raw transport/HTTP meaning directly to orchestration.
5. Synchronous success becomes `CONFIRMED`; async acceptance becomes `PROVIDER_ACCEPTED`/`PENDING` and advances only from callback/reconciliation evidence.
6. An ambiguous result, local cancellation after dispatch begins, `TimeoutError`, `ConnectionError`, or another exception after dispatch may have begun becomes **`UNKNOWN`** before the local error propagates.
7. Repeated start while `UNKNOWN` never republishes blindly.
8. Inconclusive reconciliation preserves the current unknown/pending state.
9. Only adapter-level `PROVED_ABSENT` or a typed known-safe pre-mutation failure can authorize `FAILED_SAFE`.
10. Retry authorization and retry execution are separate. `FAILED_SAFE` does not auto-publish; retry is explicit, bounded, and reuses the same operation key.
11. `CONFIRMED` and permanent failure are monotonic/terminal for the tested lifecycle.
12. Duplicate callback event IDs are idempotent; late pending callbacks cannot regress confirmed state.
13. A generic HTTP 404 is not automatically `PROVED_ABSENT`; each adapter must define evidence strong enough for its provider consistency model.

---

## PoC E — usage concurrency / reservations / ledger — PASS

Validated decisions:

1. **PostgreSQL is the correctness authority for expensive tenant usage quota.** Redis may assist with non-authoritative caching/throttling but cannot own canonical commercial usage state.
2. Expensive work reserves scarce quota **atomically before execution**. A read-then-act remaining-quota check is insufficient under concurrency.
3. One immutable `operation_key` binds one logical reservation to exactly one tenant, metric, and quantity. Reuse with different binding data is a consistency error.
4. Duplicate/concurrent reserve for the same bound operation joins the persisted reservation rather than consuming capacity twice.
5. Reservation lifecycle is `RESERVED -> COMMITTED | RELEASED | EXPIRED`; terminal races are serialized against the reservation row so exactly one legal outcome wins.
6. Commit moves reserved capacity to committed capacity and writes the deterministic-dedupe `CHARGE` ledger entry in the same database transaction.
7. Duplicate/concurrent completion cannot create a second charge for the same logical operation.
8. Failed or cancelled work releases reserved capacity idempotently; stale reservations require deterministic expiry/recovery rather than permanent quota leakage.
9. Stale-reservation sweeping may use `FOR UPDATE SKIP LOCKED` so multiple sweepers can cooperate without double-release.
10. `UsageLedger` is append-only accounting history. Corrections and refunds are compensating `ADJUSTMENT` entries; historical charge rows are never silently rewritten or deleted.
11. When multiple distinct adjustments target one original charge, they require **source-level serialization** so concurrent refund checks cannot over-refund the source.
12. Reconciliation must read reservation, ledger, capacity counters, and aggregate evidence from one coherent database transaction/snapshot while protecting the target transition from racing into a false inconsistency.
13. The explicit Architecture 0.10 concurrency gate means **100 simultaneously synchronized workers**, not merely 100 submitted tasks. CI must provide enough PostgreSQL backend capacity so infrastructure does not silently reduce the tested contention.
14. Tenant commercial entitlement usage and shared provider/API quota are different domains. Provider quota coordination uses separate state and cannot mutate tenant billing/entitlement counters.
15. Provider-quota lease identity has a lifecycle: once a lease key is released, duplicate acquisition must not falsely report a new successful acquisition unless an explicit reacquire contract is implemented.
16. PoC test authentication choices do not become production credential policy. Host `trust` in the isolated CI PostgreSQL service proves concurrency/accounting semantics only and carries no production authentication guarantee.

---

## Next gate — Red-Team v2

All five Architecture 0.10 executable PoCs are PASS. The next required gate is **Red-Team v2**, which must attack the composition of the corrected contracts rather than treating each PoC in isolation.

Until Red-Team v2 is complete, its release-blocking findings are resolved, and the validated amendments are folded into one canonical Architecture 1.0 document, Architecture 0.10 + this amendment document remain **pre-1.0**.
