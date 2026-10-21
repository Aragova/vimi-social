# Red-Team v2 — Part 04: remediation and executable verification plan

**Status:** PLAN REVISED AFTER FIFTH INDEPENDENT REVIEW — EXECUTION PENDING

Red-Team v2 currently blocks Architecture 1.0. The remediation order is chosen by blast radius and dependency, not by ease of implementation.

## 1. Mandatory executable composition gates

These are not renamed as PoC F/G/etc. They are **Red-Team v2 composition regressions** required because the five original PoCs intentionally stayed isolated.

### RTV2-X1 — Usage reservation ownership / pre-dispatch fencing + entitlement-admission race

Compose PostgreSQL `UsageReservation` with real Temporal work, a concurrent sweeper, versioned live entitlement state, and a provider mock with an observable irreversible commit point.

Must prove:

- a live owner can renew/hold authority beyond initial TTL;
- stale reservation-owner generation cannot renew or commit;
- sweeper cannot release quota still owned by legitimate active work;
- worker crash before any billable/irreversible step eventually releases capacity;
- **before egress**, the usage record durably leaves ordinary expirable `RESERVED` semantics and enters a state/obligation such as `DISPATCHING` / `SETTLEMENT_REQUIRED` that a generic TTL sweeper cannot release;
- kill the worker immediately after provider acceptance but before local success handling and prove the durable obligation survives and is reconciled rather than expired;
- once billable/irreversible work crossed its commit point, generic expiry cannot make it disappear from accounting;
- second competing job never consumes the same scarce quota concurrently;
- entitlement admission is versioned: `reserve_usage(...)` validates the current entitlement and quota under one serialized PostgreSQL transaction using `expected_entitlement_generation` (or equivalent);
- **entitlement validation/reservation race:** worker observes entitlement generation N, pauses before reservation commit, plan downgrade advances entitlement generation to N+1, then the worker attempts `reserve_usage(expected_entitlement_generation=N, ...)`;
- the downgrade and reservation have one authoritative commit order. If downgrade wins first, the stale reservation attempt fails closed and no expensive/provider work begins. If the reservation commits first while generation N is valid, that just-in-time reservation is the explicit commercial admission/too-late boundary for that already-admitted unit, while later downgrade blocks subsequent reservations;
- tenant/security suspension or actor/account revocation remains a stronger dispatch-time fence and is not bypassed merely because commercial quota was reserved.

A test that begins only after the provider/billable commit point is insufficient: the crash window between egress/acceptance and local state advancement must be exercised explicitly. Likewise, a test that performs live entitlement check and reservation as independent un-serialized steps is insufficient.

Closes: **RT2-01** and provides the executable admission gate for **RT2-07**.

### RTV2-X2 — PostgreSQL outbox → Temporal relay crash windows and binding conflicts

Use a real PostgreSQL outbox and real Temporal development server.

Inject relay process failure:

- before Temporal start;
- after accepted start / before delivered mark;
- during duplicate resend;
- after workflow completion.

Also pre-create a Temporal workflow using the deterministic workflow ID but bind it to a **different operation/generation**. Deliver the outbox event that would collide with that ID and prove the relay does **not** treat every `AlreadyStarted`/ID conflict as success and does not mark the outbox row delivered for a mismatched immutable binding.

Prove one immutable operation → one logical workflow binding with no lost work, while a conflicting binding fails closed/quarantines instead of silently joining.

Closes: **RT2-02**.

### RTV2-X3 — Credential single-flight / immutable secret-version CAS / lost rotated response

Provider mock rotates refresh tokens. Synchronize at least 20 refreshers and inject stale writers/crashes.

Must prove:

- exactly one refresh owner performs the normal provider refresh sequence for one expected credential generation;
- no stale writer can replace a newer active credential reference;
- account disable/revocation uses the same generation fence;
- callers converge on the winning current credential when the provider outcome is known;
- orphan immutable secret versions cannot become active accidentally;
- **lost rotated-response window:** provider consumes refresh token R1 and returns R2, but the worker dies/loses the response before R2 is durably persisted; retrying R1 then returns `invalid_grant`;
- the adapter has an explicit outcome for that provider-specific ambiguity: either a provider-supported idempotent/recoverable refresh mechanism proves the current credential, or the account transitions to typed `REAUTH_REQUIRED`/manual recovery rather than pretending convergence or overwriting state.

Single-flight + PostgreSQL CAS alone is not considered proof for the lost-R2 window.

Closes: **RT2-03**.

### RTV2-X4 — Account-generation-safe webhook routing with generation-less payloads

Compose server-side ownership mapping with disconnect/reconnect to another tenant and delayed old-generation events.

Tests must use provider-realistic delayed payloads that **do not carry an internal ViMi connection generation**. Cover both:

- an event/object ID that can be correlated through immutable historical `ExternalPost` / provider-object mapping to the old connection generation;
- an old account-level event that is not safely correlatable to any immutable generation.

Prove the first routes only to its historical generation and the uncorrelatable event fails closed/quarantines. Neither may fall through to the current `(provider, external_account_id) -> current tenant` mapping and mutate Tenant B.

Closes: **RT2-04**.

### RTV2-X5 — Multi-system disaster recovery / execution and data fencing

Compose a simulated PostgreSQL PITR boundary with live Temporal work, an independently versioned object store, an immutable secret store, and a fake provider mutation counter. PostgreSQL is deliberately restored to an earlier point while the other systems retain newer state.

Must prove all of the following.

#### Temporal / provider egress

- a stale pre-recovery activity cannot obtain a new dispatch permit after the recovery epoch bump;
- replayed outbox work reconciles under the new epoch;
- **pre-issued permit race:** a worker obtains a short-lived dispatch permit under epoch N, pauses, recovery advances to epoch N+1, then the worker attempts provider egress;
- the old permit cannot be used after the recovery cutover;
- **validation/consumption cutover race:** a worker reads/validates epoch N successfully, pauses **after validation but before permit consumption/dispatch commit**, recovery attempts to advance to N+1, and then the worker resumes;
- permit consumption / dispatch commitment and recovery-epoch advancement must have one authoritative serialization order. A validate-then-send sequence with an unprotected gap is not sufficient;
- one acceptable protocol is an atomic/serialized `consume_dispatch_permit(expected_epoch, operation_key)` that durably records an in-flight dispatch obligation under the same control-plane serialization primitive used by the epoch bump. If the bump commits first, old-epoch consumption fails. If consumption commits first, recovery treats that operation as in-flight/possibly dispatched and cannot declare the cutover complete until it is reconciled;
- **post-consumption/pre-egress race:** after an epoch-N permit has been durably consumed and the in-flight obligation exists, pause the worker before provider egress and begin recovery. Recovery may not complete merely because a provider lookup currently shows no external result;
- every already-consumed old-epoch dispatch must be either drained through egress and reconciled before recovery completes, or durably transitioned to a terminal/revoked disposition that the actual egress gateway checks before mutation so the paused worker cannot later resume and send;
- if recovery cannot prove the committed worker has been drained or durably fenced from future egress, the operation remains `UNKNOWN` / `RECOVERY_PENDING` and recovery remains blocked. A transient observation of provider absence is never proof that the committed dispatch can no longer happen;
- the alternative remains a full drain protocol: stop new permit issuance, wait at least the maximum permit lifetime, identify/reconcile every already-consumed/in-flight permit, and prove no old committed worker can subsequently egress before advancing/resuming under the new epoch;
- failure to read or serialize against the live recovery fence fails closed for irreversible mutation.

The executable gate must include barriers **before validation**, **after successful validation but before consumption/dispatch commit**, and **after durable permit consumption but before provider egress**. Recovery completion itself is part of the assertion: an epoch-N committed dispatch cannot outlive the recovery cutover as an unfenced future provider mutation.

#### Provider-ahead state after PostgreSQL PITR

Inject an external-side-effect ordering where:

1. a social provider has already accepted/created a publication **after** the PostgreSQL restore point;
2. the local success/attempt state is present before the failure;
3. PITR restores PostgreSQL to an earlier state in which the operation/outbox appears pending/not-dispatched;
4. Temporal/provider evidence survives newer than the restored database.

Before the restored operation may dispatch again, recovery must reconcile using immutable operation identity and provider evidence/idempotency capability. If prior success/absence cannot be proved, the restored operation enters typed `UNKNOWN` / `RECOVERY_PENDING` and is not blindly replayed. Provider-ahead evidence must be rebound to the restored logical operation where safe; an outbox replay alone is never proof that a second mutation is allowed.

Prove that the provider mutation counter remains one for the logical operation across PITR and recovery.

#### PostgreSQL PITR / object storage

Inject both directions of divergence:

1. PostgreSQL PITR resurrects an `Asset` reference whose underlying blob/object version was purged after the restore point;
2. PostgreSQL PITR removes a newer valid reference while the corresponding newer object/version still exists and could later be collected as an orphan.

Prove that publishing/processing and retention stay **disabled** until a post-restore inventory reconciliation classifies every affected reference/object generation. Missing referenced bytes become an explicit recovery/data-loss state, not a silent 404.

For a newer object whose valid PostgreSQL reference was lost by PITR, a finite quarantine/grace period by itself is **not** evidence that deletion is safe. Recovery must either:

- deterministically reconstruct/rebind the lost `Asset`/reference from an independent durable source such as immutable object metadata/manifest, retained outbox/event evidence, provider/workflow history, or another explicitly defined recovery index; or
- keep the object fail-closed from GC with an unresolved recovery disposition until explicit evidence proves that it is truly orphaned.

GC may resume only for objects with a positive safe-to-delete disposition. Time elapsed since restore is not sufficient authority. Object versioning/retention policy and the recovery cut line must be explicit.

#### PostgreSQL PITR / immutable Secret Store / provider credential state

Inject the ordering:

1. provider consumes refresh token R1 and issues R2;
2. R2 is durably stored as a new immutable secret version and PostgreSQL active pointer advances to R2;
3. PostgreSQL is restored to a snapshot that still points to R1 while provider and Secret Store remain at R2.

Prove recovery does not blindly use restored R1. Before publishing resumes, the credential reconciler must deterministically discover and validate the newest admissible immutable credential generation, CAS/rebind PostgreSQL to it when provable, or transition the account to a typed fail-closed recovery state such as `REAUTH_REQUIRED`. A restored stale pointer is never authority by itself.

A DR test covering only PostgreSQL + Temporal is insufficient. Recovery is complete only when PostgreSQL, Temporal, object storage, Secret Store, and external-side-effect evidence have an explicit reconciled disposition.

Closes: **RT2-05** and the DR dimensions of **RT2-03/RT2-08**.

### RTV2-X6 — Durable publication-state race

Use PostgreSQL + Temporal + callback processor. Inject provider accepted/lost response, DB write failure, activity timeout and callback confirmation in conflicting orders.

Prove monotonic persisted state and no blind duplicate external mutation. In particular, a later `UNKNOWN` write cannot overwrite already persisted `CONFIRMED`, and callback evidence that arrives before provider-response persistence must remain usable.

Closes: **RT2-06**.

### RTV2-X7 — Asset lease / deletion race

Compose immutable asset storage metadata, active lease and deletion/retention worker. Prove an in-use asset is not purged and content-hash adoption cannot cause one owner to delete another valid reference.

Closes executable part of **RT2-08**. Cross-system restore/version divergence is covered separately inside **RTV2-X5**.

### RTV2-X8 — Execution-time authorization/account/resource freshness and serialized egress commitment

Compose authenticated Temporal execution context from PoC B with live membership/resource authorization, a versioned dispatch-policy/authorization generation, immutable platform-account generation, and an irreversible publication step.

The dispatch-policy generation is authoritative for every state whose policy can block the operation at egress time. At minimum, actor membership/permission revocation, tenant suspension, and target/resource disable/eligibility changes either advance that same generation or use separate permit-bound generations that participate in the same serialized dispatch commitment.

Exercise at least five orderings:

1. **actor revocation before live authorization check:** actor is authorized when work is scheduled, the trusted workflow envelope remains valid, membership/permission is revoked, then the workflow resumes;
2. **actor revocation after successful live check but before egress commitment:** the worker passes the live authorization check, pauses, the revocation commits, then the worker attempts to consume/commit authorization for provider egress;
3. **actor revocation racing inside permit consumption:** the worker reads dispatch-policy generation N and enters permit validation, pauses before consumption/dispatch-commit is durably serialized, a revocation attempts to advance generation to N+1, then both sides resume;
4. **account-generation change racing inside permit consumption:** the worker validates active platform-account generation N and credentials, pauses before consumption/dispatch-commit is durably serialized, account disable/reconnect advances/tombstones generation N and creates N+1, then both sides resume;
5. **tenant/resource blocking mutation racing inside permit consumption:** after successful live validation, pause before dispatch commitment while tenant suspension or target/resource disable advances the relevant dispatch-policy generation, then resume permit consumption.

Must prove:

- authenticity of the envelope is not treated as permanent authorization;
- execution-time checks revalidate tenant active state, target/account ownership, resource eligibility and the product's explicit creator-revocation policy;
- every blocking tenant/resource mutation that can invalidate current authority participates in the same versioned fence used by final dispatch; a mutation cannot commit after the live check without invalidating the stale permit;
- a blocking actor/account/tenant/resource change reaches a typed blocked/cancelled state before irreversible dispatch when the change wins the serialization order;
- no stale cached permission snapshot, stale tenant/resource state, or stale platform-account generation can authorize the provider mutation;
- the final provider egress is covered by a **versioned authorization/dispatch permit or equivalent fence** tied to the authoritative dispatch-policy generation and immutable account generation;
- permit consumption / dispatch commitment, blocking dispatch-policy generation changes, and account disable/reconnect generation changes use one authoritative serialization order for the affected operation/account. A last-moment read followed by an unprotected send is insufficient;
- if actor revocation, tenant suspension, target/resource disable, or account-generation N+1 commits before consumption commits, the stale permit cannot be consumed and provider egress is forbidden;
- if permit consumption/dispatch commitment commits first while every bound generation is still valid, that operation has crossed ViMi's explicit too-late boundary. A later blocking mutation may prevent future dispatches but does not falsely rewrite the already-committed operation as never sent; it is audited and reconciled;
- provider egress occurs only after the durable consumption/dispatch-commit record exists, so a crash after commitment creates a reconciliation obligation rather than an untracked request;
- historical creation authorization remains available for audit without becoming current authority.

The executable gate must place deterministic barriers **between actor/dispatch-policy-generation validation and permit consumption**, **between account-generation validation and permit consumption**, and for at least one non-actor blocking state (**tenant suspension or target/resource disable**) before permit consumption. Each generation-changing transaction must race dispatch commitment and prove one authoritative commit order.

Closes: **RT2-16** and the executable dispatch-race part of **RT2-12**.

## 2. Architecture decisions required before/alongside tests

### A. Entitlement timing / commercial admission boundary

Adopt initial production policy:

```text
schedule: record historical EntitlementDecision
execution: revalidate live entitlement
just before expensive work: atomically validate entitlement generation + reserve scarce quota
```

No indefinite scarce-quota hold merely because work was scheduled far in advance.

The quota reservation transaction is the explicit commercial admission boundary for an ordinary plan downgrade. `reserve_usage(expected_entitlement_generation=...)` and the entitlement-generation change must serialize against the same authoritative PostgreSQL state. If downgrade commits first, stale admission fails. If reservation commits first while entitlement is valid, that already-admitted unit may proceed under its reservation/lease while future admissions use the downgraded policy. Tenant/security suspension and actor/account revocation remain independent stronger dispatch-time fences.

### B. Account connection generation

Disconnect never rebinds the historical PlatformAccount ownership row. Reconnect creates a new immutable connection generation. Webhook routing must work even when provider payloads do not contain ViMi's generation identifier, using immutable historical object correlation or fail-closed quarantine.

For irreversible egress, account disable/reconnect generation changes serialize with dispatch-permit consumption. An old generation cannot pass a check, lose the race to N+1, and then still dispatch.

### C. Support audit sink

Choose a caller-non-rollbackable durable audit sink and make privileged reads fail closed until it acknowledges the audit operation.

### D. Physical asset ownership

Initial production baseline should use tenant-scoped immutable object ownership. Global physical dedupe is deferred unless a global Blob/reference/lease model is explicitly introduced.

### E. Provider fairness

Define provider-scoped leases + per-tenant fairness + bounded jittered backlog drain. Provider metadata uncertainty uses a conservative fallback.

### F. Billable external-call safety

Apply operation identity / ambiguous-result handling not only to social publish but to any externally billable, non-idempotent request (notably AI/model calls).

### G. Mixed-version deployment

Specify N/N-1 schema + workflow compatibility and require an executable migration/rollback fitness gate in the production repository.

### H. Authorization/account/resource freshness / serialized dispatch boundary

A trusted `ExecutionContext` proves provenance/identity, not perpetual permission. Security-sensitive execution-time facts are revalidated from current authoritative state. Every tenant/resource mutation that policy defines as blocking at egress time advances the authoritative dispatch-policy generation (or an equivalent permit-bound generation). The final irreversible egress uses a versioned permit whose **consumption/dispatch commitment is serialized with blocking dispatch-policy changes and account disable/reconnect generation changes**. That serialized commit order, not a non-atomic last-moment read, defines whether a blocking change wins. Provider egress occurs only after the durable dispatch commitment exists; later revocation/suspension/disable/reconnect is then handled as too late for that already-committed request and the operation is reconciled/audited.

### I. Disaster-recovery cross-system reconciliation

PostgreSQL PITR is never treated as a complete restore by itself. Before retention workers or irreversible publishing resume, recovery reconciles the restored database against Temporal histories, object-store versions/inventory, immutable Secret Store generations, and external provider evidence.

The recovery cutover has two serialized boundaries: epoch advancement vs permit consumption, and recovery completion vs every already-consumed old-epoch dispatch. A committed old-epoch dispatch may not remain capable of future egress after recovery is declared complete. Recovery must either drain it through provider egress and reconcile it, or durably revoke/fence it such that the actual egress gateway will reject a late-resuming worker. A transient provider absence observation is not sufficient proof of safety.

Newer objects/secrets are not destroyed merely because the restored database no longer references them. A PITR-forgotten object reference must be reconstructed/rebound from durable evidence or remain fail-closed from GC until orphanhood is explicitly proven. Provider-ahead external mutations must be reconciled under stable operation identity before restored outbox/work can dispatch again.

## 3. Planned branch/CI shape

The Red-Team v2 branch may add a small isolated package such as:

```text
red_team_v2_composition/
```

It is still architecture-lab code, not production implementation.

A dedicated workflow should run:

```text
Ruff
strict Pyright
RTV2 composition pytest
PoC A regression
PoC B regression
PoC C regression
PoC D regression
PoC E regression
```

The tests should reuse the existing Temporal/PostgreSQL development infrastructure where justified and add deterministic fake/versioned object-store and Secret-Store boundaries for recovery composition. They must not introduce production coupling between the original PoCs.

## 4. Review policy

After the first implementation pass:

1. all mandatory Red-Team composition CI green;
2. independent Codex review of code + audit claims;
3. every review finding either fixed or explicitly classified under the v2 severity policy;
4. rerun complete A–E + RTV2 matrix;
5. update this audit with machine evidence;
6. only then issue the final Red-Team v2 verdict.

## 5. Current verdict

```text
PoC A–E: PASS
Red-Team v2: FAIL / IN PROGRESS
Architecture 1.0: BLOCKED
```

The next engineering action remains **RTV2-X1 through X8**. X1 proves entitlement-generation vs quota-admission serialization, X5 is a multi-system DR gate that also fences already-consumed old-epoch dispatches through recovery completion, and X8 proves actor/account/tenant/resource blocking races against one serialized dispatch commitment.