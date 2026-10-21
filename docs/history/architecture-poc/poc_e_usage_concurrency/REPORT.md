# PoC E — Result Report

**Status:** PASS — CI VERIFIED — INDEPENDENT RE-REVIEW CLEAN

## Hypothesis

PostgreSQL-backed usage reservations can prevent tenant quota oversubscription under concurrency while an append-only, deduplicated usage ledger prevents double billing across retries and duplicate completion.

The same design must recover stale reservations deterministically and keep tenant commercial entitlements separate from shared provider quota coordination.

## Verified environment

The corrected executable implementation was verified by GitHub Actions run `38915137843` (`PoC E - Usage Concurrency`, run #9) against executable head `1326f91fd33a6cfea07ab6f9dabcd920f0d95b45` after the 100-way concurrency evidence gap was fixed.

- GitHub runner: Ubuntu 24.04.5 LTS
- Python: 3.12.15
- PostgreSQL: 18.6 (`postgres:18` service container)
- PostgreSQL `max_connections`: 160 for the 100-way concurrency acceptance test
- Ruff: 0.17.1 — PASS
- Pyright: 1.1.414 — PASS (`0 errors, 0 warnings, 0 informations`)
- pytest: 8.4.2 — PASS (`18 passed in 3.54s`)
- PoC A regression run #92: PASS
- PoC B regression run #69: PASS
- PoC C regression run #42: PASS
- PoC D regression run #15: PASS

The later reviewed documentation/evidence head `9c2744ed8a772e5b30928c851513efb682279bd1` also completed the full regression matrix successfully:

- PoC A run #94: PASS
- PoC B run #71: PASS
- PoC C run #44: PASS
- PoC D run #17: PASS
- PoC E run #11: PASS, including PostgreSQL concurrency setup, Ruff, strict Pyright, and pytest

## Independent review

Final Codex correctness review completed on head `9c2744ed8a772e5b30928c851513efb682279bd1` with:

- `has_any_findings=false`
- `has_unresolved_findings=false`

All five review threads raised during PoC E are resolved. No finding was waived.

## Implemented contract

The PoC uses PostgreSQL as the correctness authority for tenant usage capacity.

- `UsageCapacity` tracks quota, currently reserved quantity, and committed quantity per tenant/metric.
- `UsageReservation` binds one immutable `operation_key` to tenant/metric/quantity and moves from `RESERVED` to exactly one terminal state: `COMMITTED`, `RELEASED`, or `EXPIRED`.
- reservation uses a database uniqueness constraint plus an atomic conditional capacity update, so independent workers serialize on authoritative PostgreSQL state rather than an in-memory counter;
- the 100-way quota test starts 100 worker threads behind one barrier and the CI PostgreSQL instance is configured with enough backend capacity for those attempts to contend concurrently;
- commit and release lock the reservation row before terminal transition;
- commit writes one deterministic-dedupe `CHARGE` row to an append-only `UsageLedger` in the same database transaction as capacity/reservation state;
- corrections/refunds are separate `ADJUSTMENT` ledger rows and existing ledger history is protected by a database trigger against UPDATE/DELETE;
- distinct adjustments for one source reservation serialize on the mutable source reservation row so the source-total check cannot race into over-refund;
- stale reservations are selected with `FOR UPDATE SKIP LOCKED`, released, and marked `EXPIRED` idempotently;
- reconciliation locks and reads reservation/ledger/counter evidence in one database transaction;
- `ProviderQuotaCoordinator` uses separate tables/state from tenant usage accounting so shared provider limits do not become commercial entitlement state;
- a released provider lease key is not treated as a successful reacquisition.

## Automated verification

The CI-verified suite contains 18 deterministic architecture tests covering:

- 100 simultaneously synchronized quota competitors against limited tenant quota;
- concurrent duplicate reserve idempotency;
- immutable operation-key binding;
- 10-way duplicate/concurrent completion with exactly one charge;
- concurrent idempotent failure release;
- commit-vs-release race;
- compensating refund/adjustment after commit;
- two distinct concurrent refunds against one source charge cannot over-refund it;
- stale reservation expiry and repeated sweeper execution;
- commit discovering an already expired reservation;
- commit-vs-expiry race;
- reconciliation racing commit without transient false inconsistency;
- injected capacity drift detected by reconciliation;
- database-enforced append-only ledger UPDATE/DELETE rejection;
- runtime test role has no stored password and is not superuser/BYPASSRLS;
- separation of two tenant entitlements from one shared provider quota bucket;
- concurrent shared-provider quota acquisition without oversubscription;
- released provider lease keys cannot be reused as false successful acquisitions.

## Findings from independent review

### 1. Concurrent adjustment race

Distinct negative adjustment keys could both inspect one source charge under shared locking and over-refund it. Distinct adjustments now serialize by taking an exclusive lock on the mutable source `UsageReservation` row while calculating source totals and writing the compensating ledger entry. A coordinated two-refund regression proves the competing over-refund is rejected.

### 2. Released provider lease reuse

A duplicate acquire after `release()` could return the old lease identifier without restoring provider `in_use`, falsely reporting acquisition while a different lease could occupy the real slot. Reuse of a released lease key is now rejected, and a new lease key is required to acquire capacity again.

### 3. Checked-in database credential

The initial test role/password and password-bearing DSN violated the repository no-plaintext-secrets rule. The isolated PostgreSQL CI service now uses host `trust` only for this disposable test database, the runtime role has `PASSWORD NULL`, and a regression test verifies the role is non-superuser, `NOBYPASSRLS`, and has no stored password. No production authentication guarantee is inferred from this setup.

### 4. Reconciliation snapshot race

Reservation state was originally read on a different connection from ledger/counter evidence, allowing a normal concurrent commit to create a transient false inconsistency. Reconciliation now locks the target reservation and reads reservation, ledger, capacity, and aggregate evidence in one database transaction. A coordinated commit/reconcile regression covers the race.

### 5. The original “100 concurrent jobs” test did not prove 100-way concurrency

The earlier test submitted 100 tasks through only 32 worker threads and had no start barrier, so it could not support the explicit Architecture 0.10 acceptance claim. The corrected test creates 100 workers and uses `Barrier(100)` immediately before `reserve()`. CI raises PostgreSQL `max_connections` to 160 before the suite, so the database does not reduce the intended 100-way contention.

## Architecture 1.0 implications

- PostgreSQL remains the correctness authority for expensive tenant usage quota; Redis may not own canonical entitlement/usage state.
- Scarce tenant quota is reserved atomically before expensive work begins.
- One immutable operation key binds one logical usage reservation to tenant/metric/quantity.
- Duplicate workflow/activity delivery joins the same reservation and cannot create another charge.
- Commit/release/expiry are serialized terminal transitions and must keep capacity counters consistent with the winning state.
- Committed usage is represented by append-only deduplicated ledger entries.
- Corrections/refunds are compensating entries, not UPDATE/DELETE of historical usage.
- Source-level serialization is required when multiple distinct adjustments can affect one original charge.
- Stale reservations require deterministic expiry/recovery and reconciliation.
- Reconciliation must observe coherent transactional evidence rather than mixing database snapshots.
- Tenant commercial entitlement capacity and shared provider/API quota coordination are separate architectural concerns.
- Provider-quota lease identity has an explicit lifecycle and a released lease key cannot masquerade as a newly acquired lease.

## Limitations

This PoC validates PostgreSQL concurrency/accounting semantics with deterministic failure injection. It does not prove payment-provider settlement, invoice correctness, production subscription lifecycle, real social-provider rate-limit interpretation, Redis behavior, or Temporal crash/versioning behavior already covered by PoC A.

PoC B separately supplies tenant-isolation/RLS evidence; PoC E intentionally does not repeat that experiment. PostgreSQL host `trust` authentication is used only for the isolated CI database because authentication itself is not the PoC E hypothesis; no production credential model is inferred from it.

The minimal provider-quota coordinator proves separation and atomic shared-capacity acquisition semantics only. It does not prove production provider header interpretation, distributed fairness policy, outage recovery, or backlog drain behavior.

## Final verdict

**PASS.** The Architecture 0.10 PoC E usage-concurrency/reservation gate is supported by machine-verified PostgreSQL concurrency tests and a clean independent re-review. The next architecture gate is **Red-Team v2** before Architecture 1.0 can be frozen.

The PR still requires the repository's final documentation-only A/B/C/D/E CI pass before squash merge; that merge gate does not change the PoC verdict unless it exposes a regression.
