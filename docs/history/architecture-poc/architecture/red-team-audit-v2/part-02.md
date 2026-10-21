# Red-Team v2 — Part 02: Critical release-blocking findings

**Status:** OPEN  
**Critical findings:** 5

These findings do not mean PoCs A–E failed. They identify places where individually correct contracts can still compose unsafely or where a Critical Architecture 0.10 requirement remained paper-specified rather than machine-verified.

---

# RT2-01 — Usage reservation can expire while expensive or irreversible work is still alive

**Severity:** CRITICAL  
**Boundary:** UsageReservation + Temporal execution + external/expensive work  
**Disposition:** OPEN

## Attack/failure scenario

A worker reserves tenant quota and starts a long render, AI call, upload, or social publish flow.

The work legitimately lasts longer than the reservation TTL, or the worker is temporarily disconnected while the external provider continues processing.

The stale-reservation sweeper sees an expired `RESERVED` row and releases capacity. A second job then reserves the newly available quota. The first job is still running and may consume real provider/compute cost or create an irreversible external side effect.

When the first job eventually tries to commit usage, the reservation may already be `EXPIRED`, producing either unbillable successful work or a policy conflict after the tenant quota has already been reused.

## Why current evidence does not cover it

PoC E correctly proves deterministic reservation expiry and idempotent release in isolation. That is not the same as proving that expiry is safe while a real Temporal-owned unit of expensive work remains active. The PoC reservation has an expiry timestamp but no workflow-owner lease generation or fencing token.

PoC A separately proves durable Temporal recovery, but it does not compose a live usage reservation with the long-running activity and sweeper.

## Impact

Quota can be reused while the original work is still creating cost. This can produce plan bypass, unbillable external work and direct financial loss under concurrency.

## Required Architecture 1.0 change

Usage admission needs an ownership/fencing contract, not only a timestamp.

At minimum define:

```text
reservation_id
operation_key
owner_generation / fence_token
lease_expires_at
state
```

Rules:

1. a live owner renews its lease while expensive work is legitimately active;
2. sweeper expiry is legal only when the owner lease is stale and the expected generation still matches;
3. a worker that loses reservation authority may not begin another billable or irreversible step;
4. **before egress**, a billable/irreversible operation must durably leave ordinary expirable `RESERVED` semantics and enter a dispatch/settlement obligation that a generic TTL sweeper cannot release;
5. once an external/billable step has crossed its commit point, the obligation is reconciled/settled rather than expired;
6. each usage metric defines its billable commit point explicitly.

## Required executable verification

Use real PostgreSQL + Temporal and inject:

- work lasting beyond the initial reservation TTL;
- concurrent sweeper execution;
- worker crash/restart;
- lease renewal loss;
- durable pre-dispatch transition, then provider acceptance followed by immediate worker death before local success handling;
- second competing reservation.

Prove that capacity is never made available to a second job while the first still has authority or an unresolved billable obligation, and that confirmed/possibly-confirmed billable work cannot become free because a timer fired.

---

# RT2-02 — Transactional outbox → Temporal crash-window composition is still unproved

**Severity:** CRITICAL  
**Boundary:** PostgreSQL transactional outbox + deterministic Temporal workflow identity  
**Disposition:** OPEN — release-blocking evidence gap

## Attack/failure scenario

The domain transaction commits an `OutboxEvent`.

The relay starts the Temporal workflow successfully and crashes before marking the event delivered. On restart it sends the same event again.

A related edge case occurs after a workflow has already completed or after recovery/PITR: the relay observes an old/replayed outbox event and receives an "already exists" / workflow-ID conflict from Temporal. Treating every conflict as success without verifying the immutable binding can suppress required work or attach an event to the wrong logical generation.

## Why current evidence does not cover it

PoC A proves deterministic workflow identity and duplicate-start protection directly at the Temporal boundary. It does not run a real PostgreSQL transactional outbox relay through the crash windows defined by Architecture 0.10 / Red-Team v1 RT-03.

The distinction matters because correctness depends on the persisted event → operation → workflow binding, not only on Temporal rejecting a second start request.

## Required Architecture 1.0 change

Define a durable immutable binding:

```text
OutboxEvent.event_id
operation_key
workflow_id
workflow_generation
```

Rules:

- workflow identity is derived from the stable `operation_key` contract validated by PoC A/D;
- `delivered_at` is operational metadata, never exactly-once authority;
- relay retry after `AlreadyStarted` is accepted only if the existing workflow binding matches the same operation and generation;
- a completed workflow ID is not silently reused for a semantically new operation;
- outbox replay after recovery must be reconciled against the binding rather than assumed safe from ID collision alone.

## Required executable verification

Real PostgreSQL + Temporal relay test with process kill:

1. before workflow start;
2. after Temporal accepted start but before DB delivery mark;
3. while handling an already-started workflow;
4. after workflow completion with duplicate event delivery;
5. pre-create the deterministic workflow ID with a conflicting immutable operation/generation binding and prove the relay does not mark the outbox event delivered.

All valid-duplicate cases must converge to exactly one logical workflow for one operation with no lost work and no second external mutation path; a conflicting binding must fail closed rather than silently join.

---

# RT2-03 — OAuth refresh concurrency is a mandatory Critical contract but has no executable proof

**Severity:** CRITICAL  
**Boundary:** CredentialVersion + secret storage + concurrent platform workers  
**Disposition:** OPEN — release-blocking evidence gap

## Attack/failure scenario

Twenty workers discover an expired access token at the same time. The provider rotates refresh tokens.

Worker A refreshes successfully and receives refresh token R2. Worker B, which started from old state R1, finishes later and attempts to publish stale credential state or overwrite the active pointer. A crash can also occur after writing a new immutable secret version but before updating PostgreSQL metadata, or vice versa.

A distinct ambiguity occurs if the provider consumes R1 and returns R2 but the worker dies or loses the response before R2 is durably persisted. Retrying consumed R1 may produce `invalid_grant`; single-flight and PostgreSQL CAS cannot reconstruct a credential value that was never captured.

A disaster-recovery variant occurs if R2 is durably present in the immutable Secret Store and provider state, but PostgreSQL PITR restores the active pointer to old consumed R1.

## Why current evidence does not cover it

Architecture 0.10 §24 explicitly requires single-flight refresh + compare-and-swap and states that concurrent refresh tests are mandatory.

The original PoC D acceptance plan included auth expiry / rotating refresh-token behavior, but the final PoC D report intentionally limits its claim to publication lifecycle semantics and does not validate credential refresh concurrency or secret-store/DB composition.

The design is therefore plausible but not yet proven against the original Critical RT-06 failure mode or its PITR composition.

## Required Architecture 1.0 change

Preserve the existing `credential_version` model and make the cross-store update protocol explicit:

1. acquire single-flight refresh ownership for the platform-account generation;
2. reload current credential version;
3. perform provider refresh only if still required;
4. write the returned credential as a **new immutable secret version/reference**;
5. CAS the PostgreSQL active credential pointer from the expected old version to the new immutable reference;
6. if CAS loses, never overwrite the winner; expire/garbage-collect the orphan secret version and reload current state;
7. callers receive the winning current credential version when provable;
8. account disable/revocation and refresh use the same account-generation fence;
9. lost rotated-response ambiguity must have provider-specific recovery/idempotency evidence or a typed fail-closed `REAUTH_REQUIRED`/manual-recovery outcome;
10. after PostgreSQL PITR, the restored active pointer is not authority until reconciled against immutable secret generations/provider evidence; a provably newer valid immutable version may be rebound with CAS, otherwise publishing remains blocked.

Never update a mutable shared secret value in place before ownership is established.

## Required executable verification

Provider mock rotates refresh tokens. Run at least 20 synchronized refresh attempts plus injected crashes/stale writers.

Prove:

- exactly one provider refresh sequence wins in the normal path;
- no stale writer can replace a newer credential;
- all successful callers converge on the latest valid version when its outcome is known;
- an account disabled during refresh cannot emerge enabled with a newly written credential;
- orphan secret versions cannot become active accidentally;
- lost-R2 response cannot be misclassified as successful convergence;
- PostgreSQL PITR to R1 while Secret Store/provider retain R2 cannot cause restored R1 to be used for publishing; recovery deterministically rebinds a provable current version or fails closed.

---

# RT2-04 — Late webhook after account reassignment can cross a tenant boundary

**Severity:** CRITICAL  
**Boundary:** PlatformAccount ownership + webhook server-side resolution + account reconnect lifecycle  
**Disposition:** OPEN

## Attack/failure scenario

Tenant A owns external account `@brand` and publishes content.

Tenant A disconnects the account. Later Tenant B legitimately connects the same provider account after ownership changes outside ViMi.

A delayed webhook for Tenant A's old publication arrives after Tenant B's connection is active.

Architecture 0.10 correctly says the webhook must ignore tenant claims from the payload and resolve ownership server-side. But if server-side resolution uses only the **current** `(provider, external_account_id) -> PlatformAccount -> tenant` mapping, the old event can now resolve to Tenant B and mutate/reconcile the wrong tenant.

## Why current evidence does not cover it

PoC B proves that webhook payload tenant claims are ignored and that ownership is resolved through a narrow server-side mapping. It does not exercise ownership-generation change or delayed events from a previous connection.

PoC D proves duplicate/out-of-order callback monotonicity for one logical operation, not cross-generation account reassignment.

## Required Architecture 1.0 change

External-account ownership must be generation-aware and historical bindings must not be destructively rebound.

Define an immutable connection identity such as:

```text
platform_account_connection_id
provider
external_account_id
account_generation
owning_tenant_id
connected_at
disconnected_at?
```

Rules:

- disconnect tombstones the old connection generation;
- reconnect creates a new generation rather than changing tenant ownership of the historical row;
- `ExternalPost`, provider request mappings and webhook correlation are pinned to the connection generation that created them;
- delayed events for old generations are reconciled against that historical generation or quarantined;
- an unmatched old event must never fall through to "current owner" mutation;
- webhook routing cannot assume the provider payload carries ViMi's generation; historical provider object/event correlation or fail-closed quarantine is required.

## Required executable verification

Create Tenant A connection, publish/map an external object, disconnect it, connect the same provider account to Tenant B, then deliver Tenant A's delayed callback/event using a provider-realistic payload with **no internal ViMi generation**.

Cover both an event/object that can be mapped historically and an uncorrelatable account-level event. Assert zero Tenant B mutation; the former routes to the historical generation and the latter quarantines/fails closed.

---

# RT2-05 — Disaster recovery lacks a serialized execution cutover and cross-system reconciliation protocol

**Severity:** CRITICAL  
**Boundary:** PostgreSQL PITR + Temporal history + live workers + Object Storage + Secret Store + external providers  
**Disposition:** OPEN

## Attack/failure scenario

PostgreSQL is restored from 15:02 to 14:55 while Temporal, object storage, Secret Store and external providers can all retain state newer than 14:55.

### Stale workflow/provider mutation

Architecture 0.10 says to enable a global publishing kill switch, isolate workflows, reconcile, and then resume. But a worker may already have loaded an old execution decision, may be partitioned from the control plane, or may hold a dispatch permit issued before the recovery cutover. If the kill-switch state itself lives in the restored PostgreSQL snapshot, PITR can also roll it back to an earlier `OFF` value.

A last-moment epoch read is not enough: a worker can validate epoch N, pause, recovery can commit N+1, and the worker can then send the provider request unless permit consumption/dispatch commitment is serialized with the recovery cutover.

Even serialized permit consumption is not enough by itself. If an epoch-N dispatch commitment wins, the worker can pause **after consumption but before provider egress**. Recovery must not observe temporary provider absence, declare the obligation safe, complete cutover, and then allow that paused old worker to resume and mutate the provider after recovery.

A separate provider-ahead case exists when the provider already accepted a publication after the restore point, but PITR resurrects local outbox/operation state that says the work is still pending. Replaying that restored work without reconciliation can duplicate the surviving provider side effect.

### PostgreSQL/object-store divergence

PITR can resurrect an `Asset` row whose referenced object was purged after the restore point. The inverse is also possible: the restored database forgets a newer valid Asset/reference while the newer object remains in storage and is later misclassified by GC as an orphan. A finite quarantine delay does not prove that such a surviving object is actually orphaned.

### PostgreSQL/Secret-Store/provider credential divergence

A refresh may consume R1, store R2 as an immutable secret and advance PostgreSQL to R2. PITR can then restore PostgreSQL to a snapshot pointing at consumed R1 while provider and Secret Store remain at R2. Fresh work that trusts the restored pointer can fail or corrupt credential recovery even though the valid newer secret still exists.

## Impact

Unsafe recovery can create duplicate/orphan external publications, broad credential outages, irreversible deletion of recoverable customer content, or restored references to missing bytes exactly when the system is already degraded.

## Required Architecture 1.0 change

Introduce a **recovery/dispatch fence** that is not rolled back together with the business database and define recovery as a multi-system reconciliation protocol, not a database-only restore.

Conceptually:

```text
recovery_epoch
publishing_kill_switch
short_lived_dispatch_permit(epoch, operation_key)
durable_dispatch_commit / in_flight_obligation
recovery_inventory_cut
```

Rules:

1. recovery bumps the epoch before affected workflow execution is allowed to continue;
2. every irreversible provider activity obtains authority under the live recovery epoch before external mutation;
3. a workflow/activity carrying an older epoch cannot dispatch even if its Temporal history says it is ready;
4. **permit consumption / durable dispatch commitment and recovery-epoch advancement must be serialized.** If the epoch bump commits first, old-epoch consumption fails. If dispatch commitment commits first, recovery must treat that operation as in-flight/possibly dispatched;
5. recovery may not complete while an already-consumed old-epoch dispatch remains capable of future provider egress. Such an obligation must either be drained through egress and reconciled before completion, or durably moved to a terminal/revoked state that the actual egress gateway checks so a late-resuming worker is rejected;
6. a transient provider lookup returning "not found" is not proof that a committed dispatch cannot still happen later. If the worker cannot be proven drained or durably fenced, the operation remains `UNKNOWN` / `RECOVERY_PENDING` and recovery remains blocked;
7. a mere `validate epoch` followed by a later send is not sufficient. The executable contract must either use an atomic/serialized control-plane consumption primitive plus durable in-flight record and post-consumption fencing/drain, or use a full drain protocol that stops new permits, waits for the maximum permit lifetime and reconciles all already-consumed/in-flight permits before resume;
8. the authoritative recovery fence resides in a control-plane source whose state is not reverted by the same PostgreSQL PITR event;
9. restored outbox rows and existing Temporal workflows are reconciled against the new epoch and immutable operation bindings before restart;
10. provider-ahead side effects that survived beyond the PostgreSQL restore point are reconciled under stable `operation_key` / provider evidence before any restored pending/outbox work can re-dispatch. If prior success or absence cannot be proved, the operation remains typed `UNKNOWN` / `RECOVERY_PENDING` rather than being replayed;
11. retention/GC remains disabled until restored Asset references are reconciled against object versions/inventory; missing referenced bytes become explicit recovery state;
12. a newer object whose valid database reference was lost by PITR is not deletable merely after a grace period. Recovery must reconstruct/rebind the reference from independent durable evidence, or retain the object fail-closed until explicit evidence proves orphanhood;
13. restored credential pointers are reconciled against immutable Secret Store generations/provider evidence before platform dispatch; a provably newer valid secret may be rebound, otherwise the account fails closed to typed recovery/reauth state;
14. inability to read the live fence or complete required reconciliation fails closed for irreversible mutation/retention work.

## Required executable verification

RTV2-X5 must simulate a PostgreSQL PITR cut while newer state survives elsewhere and exercise:

- workflow ready to dispatch;
- recovery epoch bump;
- stale worker attempting to continue;
- a dispatch permit issued under epoch N before cutover and used only after epoch N+1;
- **barrier after successful epoch validation but before permit consumption/dispatch commitment**, racing against the epoch bump, to prove a single serialization order;
- **barrier after durable permit consumption/dispatch commitment but before provider egress**, then start recovery and prove recovery cannot complete from a transient provider-absence observation while the old worker could still resume;
- prove either the old committed dispatch is drained/reconciled before recovery completion or is durably revoked/fenced at the actual egress gateway so a late resume cannot mutate the provider;
- replayed outbox event;
- fresh post-recovery workflow;
- **provider-ahead publication:** provider accepted once after the restore point, then PITR resurrects the logical operation/outbox as pending; recovery must reconcile and keep provider mutation count at one;
- PITR-resurrected Asset pointing to a blob/version deleted after the restore point;
- newer object/version whose database reference disappears after PITR and would otherwise be orphan-GC'd; prove reference reconstruction/rebinding or indefinite fail-closed retention until orphanhood is positively proven;
- provider/Secret Store at credential R2 while restored PostgreSQL points to consumed R1.

Prove stale provider egress is fenced, old committed dispatches cannot survive recovery completion as future mutations, provider-ahead work cannot be blindly replayed, object retention cannot destroy newer recoverable state, missing bytes are surfaced explicitly, and restored stale credential pointers cannot authorize dispatch. Reconciled/new work may resume only after the corresponding multi-system recovery dispositions are complete.