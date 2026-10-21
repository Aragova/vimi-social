# ViMi Social — architecture roadmap

## Current position

```text
Architecture 0.10
        ↓
PoC A  PASS
PoC B  PASS
PoC C  PASS
PoC D  PASS
PoC E  PASS
        ↓
Red-Team v2  IN PROGRESS  ← CURRENT
        ↓
Architecture 1.0  BLOCKED until release findings close
        ↓
production repository
        ↓
implementation and staged delivery
```

## Completed evidence

### PoC A — Temporal durability and identity

Status: **PASS**. Validated deterministic `operation_key` identity, crash recovery, compatible workflow evolution, UNKNOWN handling, and no blind retry of irreversible publish operations.

### PoC B — tenant isolation

Status: **PASS**. Validated production-like PostgreSQL roles/RLS, top-level transaction tenant scoping, trusted background execution context, narrow webhook resolution, and privileged audit requirements.

### PoC C — secure media ingest

Status: **PASS**. Validated destination validation/pinning, redirect revalidation, bounded resource use, basic signature checks, cancellation cleanup, content-addressed finalization, and helper process-group lifetime controls.

### PoC D — async platform lifecycle

Status: **PASS**. Validated typed publication states, `UNKNOWN` reconciliation, explicit bounded safe retry, concurrent-start idempotency, and monotonic callbacks.

### PoC E — usage concurrency and reservations

Status: **PASS**. Validated PostgreSQL-authoritative atomic quota reservation under synchronized 100-way contention, immutable operation-key binding, duplicate reserve/commit/release idempotency, append-only deduplicated usage accounting, compensating adjustments with over-refund prevention, deterministic expiry/recovery, coherent reconciliation, and separation of tenant entitlement usage from shared provider quota coordination.

## Current: Red-Team v2

Red-Team v2 attacks the combined architecture with all executable findings. The audit charter and attack matrix are fixed in [`architecture/RED_TEAM_AUDIT_V2.md`](architecture/RED_TEAM_AUDIT_V2.md).

The first pass currently contains open release-blocking findings. The five PoCs remain PASS; the findings concern composition or mandatory evidence that no isolated PoC proved by itself.

Primary attack boundaries include:

- RLS + Temporal execution context;
- outbox + Temporal workflow identity;
- publication lifecycle + durable PostgreSQL state;
- usage reservations + workflow retries/expiry;
- entitlement revalidation + reservation timing;
- object storage + media processing + deletion/leases;
- credential rotation + concurrent workers;
- webhook ownership + ordering/replay + account generations;
- support privileges + non-rollbackable audit;
- provider quota coordination + tenant fairness;
- disaster recovery + stale-work execution fencing;
- AI billable calls + usage/retry policy;
- deployment/schema compatibility + long-running workflows.

Red-Team v2 must attack the corrected design rather than merely repeat individual PoC tests. Findings that depend on concurrency, crash windows, retries or cross-system ordering require executable composition evidence before they are closed.

## Architecture 1.0 freeze criteria

Architecture 1.0 is frozen only when:

1. PoCs A–E remain PASS with machine evidence;
2. Red-Team v2 has no unresolved Critical finding;
3. every High finding has an implementation/evidence disposition or explicit accepted risk allowed by the v2 severity policy;
4. mandatory Red-Team v2 composition regressions pass in CI;
5. the final audit receives clean independent review;
6. all validated PoC and Red-Team amendments are reconciled into one canonical Architecture 1.0 document;
7. production repository boundaries, dependency rules, CI fitness tests, deployment compatibility, and recovery procedures are specified;
8. remaining deferred decisions are explicitly documented as non-blocking.

Only after that gate should the production ViMi Social repository be created.
