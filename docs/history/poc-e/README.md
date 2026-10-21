# PoC E — Usage Concurrency / Reservations

## Hypothesis

ViMi Social can enforce scarce tenant usage quota under heavy concurrency by reserving capacity atomically in PostgreSQL before expensive work, while an append-only usage ledger provides idempotent accounting that cannot double-charge retries or duplicate completion.

The reservation mechanism must recover stale work deterministically and must remain a separate concern from provider-wide/shared API quota coordination.

## Architecture questions

This PoC is the final executable gate from Architecture 0.10. It must answer:

- Can 100 concurrent workers compete for one tenant quota without oversubscription?
- Can duplicate/retried delivery reuse one logical reservation rather than reserve twice?
- Can successful completion commit usage exactly once even when completion is repeated concurrently?
- Can failed/cancelled work release quota exactly once?
- Can stale reservations expire and return capacity without racing a legitimate commit?
- Can reservation state and the immutable UsageLedger be reconciled deterministically?
- Can corrections/refunds be represented as compensating ledger entries instead of historical mutation?
- Can tenant entitlement capacity remain distinct from provider-global/app/account quota coordination?

## Authority and boundaries

Architecture 0.10 makes PostgreSQL authoritative for expensive usage quota.

```text
Tenant entitlement / usage
        ↓
PostgreSQL UsageCapacity
        ↓
UsageReservation
        ↓
expensive work
   ┌────┴────┐
   ↓         ↓
success    failure/cancel
   ↓         ↓
COMMIT     RELEASE
   ↓
UsageLedger append-only charge
```

Provider quotas are deliberately separate:

```text
Tenant UsageCapacity != ProviderQuotaCoordinator
```

A tenant can have commercial entitlement available while a provider-wide API quota is unavailable, and vice versa. PoC E proves the separation of those decisions; it does not implement a production provider rate-limit service.

## Reservation state contract

```text
RESERVED
  ├── commit  -> COMMITTED
  ├── release -> RELEASED
  └── expire  -> EXPIRED
```

`COMMITTED`, `RELEASED`, and `EXPIRED` are terminal for one reservation.

The first successful reservation binds `operation_key` immutably to:

```text
tenant_id
metric
quantity
```

An identical retry joins the existing reservation. Reusing the same operation key with different identity/quantity is a conflict.

## Ledger contract

`UsageLedger` is append-only.

A successful reservation commit creates exactly one billable ledger entry using a deterministic unique `usage_dedupe_key` derived from immutable operation identity. Duplicate completion must not create a second charge.

Corrections/refunds are compensating ledger entries with their own deterministic dedupe keys. Existing ledger rows are never silently updated or deleted.

## PASS criteria

Automated tests must prove all of the following:

1. PostgreSQL is the authority for tenant quota; no in-memory/Redis counter is needed for correctness.
2. With a limited quota and 100 concurrent reservation attempts, accepted reservations never exceed the configured capacity.
3. Concurrent duplicate reservation attempts for one `operation_key` reserve capacity once and return one logical reservation.
4. Reusing an existing operation key with a different tenant, metric, or quantity is rejected.
5. Repeated and concurrent commit calls create exactly one billable ledger charge and consume quota once.
6. Repeated and concurrent release calls return reserved capacity once and never create a billable charge.
7. A commit-vs-release race produces exactly one legal terminal state with counters and ledger consistent with that winner.
8. Expired/stale reservations return capacity exactly once; commit racing expiry cannot both charge and release the same reservation.
9. Reservation recovery/expiry is deterministic and idempotent when the sweeper is retried.
10. Normal reservation/commit/release/expiry paths reconcile cleanly against the ledger; injected inconsistent state is detected rather than silently accepted.
11. Ledger UPDATE/DELETE is rejected; a refund/correction is a new compensating ledger row.
12. Duplicate workflow/activity delivery simulated at the usage boundary cannot double-reserve or double-charge.
13. Tenant entitlement reservation state is independent from a separately coordinated provider quota bucket shared across tenants.
14. The report does not claim payment-provider correctness, real billing settlement, Temporal durability, or production rate-limit behavior that this PoC does not exercise.

## Required failure/concurrency scenarios

At minimum the suite must exercise:

```text
limited video quota
100 concurrent jobs
concurrent duplicate reserve
10x duplicate completion/retry
concurrent commit vs release
worker failure -> release
stale reservation expiry
commit vs expiry race
conflicting operation-key reuse
ledger mutation attempt
compensating refund/adjustment
shared provider quota across multiple tenants
```

## Non-goals

- no real payment provider;
- no production invoice/subscription implementation;
- no real social-network API quota calls;
- no repeat of Temporal crash/versioning tests from PoC A;
- no repeat of tenant RLS proof from PoC B;
- no Redis correctness dependency;
- no production plan catalogue/UI;
- no attempt to turn this PoC into the production billing subsystem.

## Evidence policy

PoC E may be marked **PASS** only after:

- deterministic tests and explicit concurrency/failure injection pass in GitHub Actions;
- Ruff and strict Pyright pass;
- PoC A/B/C/D regressions remain green after shared project configuration changes;
- an independent correctness review finds no unresolved architecture finding;
- `REPORT.md` records only machine-verified evidence.
