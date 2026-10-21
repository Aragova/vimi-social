# Red-Team v2 — Part 03: High/Medium composition findings and evidence gaps

**Status:** OPEN

---

# RT2-06 — Publication lifecycle semantics are proven in memory and Temporal separately, not as one durable PostgreSQL state machine

**Severity:** HIGH  
**Boundary:** PoC A Temporal durability + PoC D publication lifecycle + PostgreSQL business state + webhook races  
**Disposition:** OPEN

PoC D intentionally uses an in-memory serialized operation owner. PoC A proves durable Temporal behavior separately. Architecture 0.10 still needs the production persistence protocol that composes them.

Failure windows include:

- `STARTED` persisted, worker crashes before provider I/O;
- provider accepts, then DB update fails;
- activity times out and workflow wants `UNKNOWN` while a webhook concurrently confirms the post;
- callback arrives before provider response/external ID is persisted;
- DB is temporarily unavailable while Temporal has newer execution evidence.

Architecture 1.0 must define one monotonic PostgreSQL transition contract (row version / compare-and-swap or row lock) that accepts workflow and webhook evidence without regression. A later `UNKNOWN` write must not overwrite `CONFIRMED`; a DB failure after provider dispatch must produce a durable reconciliation obligation rather than a blind restart path.

**Verification:** real PostgreSQL + Temporal + callback test with coordinated crash/DB-failure/callback ordering.

---

# RT2-07 — Entitlement policy is parameterized but not actually chosen

**Severity:** HIGH  
**Boundary:** scheduled work + membership/plan changes + UsageReservation timing  
**Disposition:** OPEN

Architecture 0.10 lists three possible product policies:

```text
RESERVE_AT_SCHEDULE
REVALIDATE_AT_EXECUTION
GRACE_EXISTING_SCHEDULES
```

but does not choose the product's default semantics. This becomes dangerous when composed with finite reservation expiry: reserving scarce quota days before execution either leaks/locks quota or requires renewal semantics very different from just-in-time work.

A separate TOCTOU exists even after choosing execution-time revalidation: a worker can read entitlement generation N, pause while a downgrade commits generation N+1, then reserve quota and begin expensive work from the stale decision unless entitlement change and reservation admission have one authoritative order.

**Required Architecture 1.0 decision:** default to **execution-time revalidation + just-in-time quota reservation immediately before the expensive step**. Scheduling records the historical `EntitlementDecision`, but does not hold scarce usage quota indefinitely. If the product later sells guaranteed scheduled capacity, model that as a separate explicit commercial commitment/reservation with its own duration/refund rules.

For the initial production policy, plan entitlement uses an explicit versioned admission boundary:

- each entitlement-changing plan/membership state carries an authoritative `entitlement_generation` (or equivalent version);
- `reserve_usage(...)` validates the current entitlement and reserves scarce quota in one serialized PostgreSQL admission transaction using the expected generation;
- a plan downgrade/generation change and reservation admission therefore have one authoritative commit order;
- if downgrade to generation N+1 commits first, a reservation based on N fails closed to a typed entitlement-blocked/retry-decision state and no expensive work starts;
- if the just-in-time reservation commits first while N is valid, that reservation is the explicit commercial admission / too-late boundary for that already-admitted unit of work. A later ordinary plan downgrade blocks future reservations but does not retroactively erase the in-flight reservation;
- security-sensitive suspension/revocation remains a stronger dispatch-time policy and may still block egress under the authorization/account-generation fences even when commercial quota was already reserved.

Creator permission revocation, tenant suspension and plan downgrade therefore have explicit, distinct execution-time semantics rather than sharing a generic failure path.

**Verification:** RTV2-X1 must place a deterministic barrier between entitlement-generation validation and reservation commit, race a downgrade against `reserve_usage(expected_entitlement_generation=N, ...)`, and prove exactly one serialized outcome. If downgrade wins there is no reservation/egress. If reservation wins first, the one admitted operation may continue under its usage lease/fence while subsequent reservations observe the new downgraded generation.

---

# RT2-08 — AssetLease/deletion composition remains paper-only and physical blob ownership is ambiguous

**Severity:** HIGH  
**Boundary:** PoC C content-addressed finalization + Asset + AssetLease + retention/deletion  
**Disposition:** OPEN

PoC C proves secure ingest and a content-addressed final artifact commit point. Its final report does not claim executable `AssetLease` / retention / deletion coordination, even though Architecture 0.10 planned that boundary.

A second ambiguity is physical deduplication scope. A content hash is an integrity identity, but if two tenants are allowed to reference one shared physical blob, deleting one tenant's asset must never delete bytes still referenced by another tenant.

**Required Architecture 1.0 change:** choose one explicit storage ownership model. The safer first production baseline is tenant-scoped immutable object ownership; do not infer global cross-tenant physical deduplication from PoC C. If global Blob dedupe is later introduced, it requires a separate global immutable Blob record plus per-tenant Asset references and GC only after all references/leases are gone.

Deletion remains tombstone-based and purge requires no active lease/reference.

**Verification:** active workflow lease vs retention/delete race, plus concurrent identical-content adoption without removing another valid reference. Disaster-recovery divergence between PostgreSQL references and object-store versions is verified separately by RTV2-X5 before retention resumes after PITR.

---

# RT2-09 — Webhook signature/freshness/replay security is specified but not executable evidence

**Severity:** HIGH  
**Boundary:** provider webhook ingress + WebhookInbox + tenant resolution + callback lifecycle  
**Disposition:** OPEN

PoC B proves trusted tenant resolution. PoC D proves event-ID idempotency and monotonic callback state. Neither proves the Architecture 0.10 ingress sequence:

```text
verify signature
freshness/replay check
persist inbox
dedupe
```

Architecture 1.0 must define provider-specific verification ports, timestamp/nonce tolerance where available, signing-key rotation, event-ID namespace scope, and behavior when the same event ID arrives with a different payload hash. Invalid/unverifiable webhooks may be stored only in a quarantined security record and must not enter the domain transition path.

Provider-specific contract tests are required as adapters are implemented; at least one generic signed-webhook composition test should exist in the production foundation.

---

# RT2-10 — Final non-rollbackable support-audit sink is still undefined

**Severity:** HIGH  
**Boundary:** privileged support read + PostgreSQL transaction + external audit evidence  
**Disposition:** OPEN

PoC B correctly discovered that a transactional audit row can be rolled back after privileged data is read. The PoC uses a PostgreSQL server log marker only as evidence that rollback-resistant signaling is possible and explicitly says it is not the production design.

Architecture 1.0 must choose the actual **audit-before-release** protocol:

```text
privileged request
  ↓
validate support session + reason + scope
  ↓
create durable caller-non-rollbackable audit evidence
  ↓ only after durable acknowledgement
release privileged result
```

If the audit sink is unavailable, privileged data access fails closed. Delivery is idempotent by support-operation key and carries both privileged and effective actor identities.

---

# RT2-11 — Provider quota atomicity is proven; fairness and outage/backlog behavior are not

**Severity:** HIGH  
**Boundary:** ProviderQuotaCoordinator + tenant fairness + outage recovery  
**Disposition:** OPEN

PoC E proves separation from commercial tenant quota and atomic shared-capacity acquisition. Its report explicitly does not prove real provider rate-limit interpretation, distributed fairness, outage recovery or backlog drain.

Architecture 0.10 already requires gradual jittered catch-up. Architecture 1.0 must make the scheduling contract concrete enough that one tenant cannot monopolize a recovered provider budget.

Required concepts include scoped provider quota leases, bounded per-tenant concurrency/share, fair queueing or equivalent scheduling discipline, conservative behavior when quota metadata is uncertain, and a maximum backlog-drain rate after outage.

This can remain provider-adapter-specific in exact numbers, but the fairness/fail-closed shape cannot be deferred.

---

# RT2-12 — Account disable/revocation has an unavoidable TOCTOU window that needs explicit dispatch semantics

**Severity:** HIGH  
**Boundary:** account health + credential version + execution-time revalidation + irreversible provider call  
**Disposition:** OPEN

Architecture 0.10 says to recheck account/credential version before irreversible mutation. A check alone is not atomic with a remote provider call: the account can be disabled or reconnected immediately after the check.

Architecture 1.0 needs an account-generation/dispatch-permit contract. The final account-generation authorization and dispatch commitment must have an authoritative serialization order with account disable/reconnect, not merely a last-moment read.

The dispatch permit/commit is bound to the expected immutable `account_generation` (and winning credential generation where relevant). Account disable/reconnect advances or tombstones that authoritative generation using the same serialization domain as permit consumption:

- if disable/reconnect to generation N+1 commits first, a permit based on account generation N cannot be consumed and old credentials cannot dispatch;
- if dispatch commitment for generation N commits first while N is still active, the request has crossed ViMi's explicit too-late boundary and is durably tracked as in-flight/possibly sent; the later disable/reconnect blocks future work but the committed request must reconcile rather than being falsely reported as prevented;
- a read/check of account generation followed by an unprotected send is insufficient.

**Verification:** RTV2-X8 must place a barrier between account-generation validation and permit consumption, race account disable/reconnect against the consumption transaction, and prove one authoritative serialization order with no old-generation provider call when the generation change wins.

This contract composes with RT2-03 credential fencing, RT2-04 account generations, and RT2-16 authorization-generation fencing.

---

# RT2-13 — AI provider calls do not yet inherit the same UNKNOWN/cost-safety model as publication

**Severity:** HIGH  
**Boundary:** AIRun + external model provider + UsageReservation + retries  
**Disposition:** OPEN / may be accepted as implementation gate before AI delivery, but the Architecture 1.0 contract must be explicit

Architecture 0.10 gives `AIRun.operation_key`, budgets and provider-specific retry policy, but an AI/model request can have the same ambiguity as publishing: the provider may have completed and billed a request while the response is lost.

Architecture 1.0 should apply the external-side-effect rule to **billable model calls**:

- reserve budget/quota before the call;
- use provider idempotency keys when available;
- on ambiguous post-dispatch timeout do not blindly issue another expensive request unless the provider contract proves it safe;
- record attempt identity and settle actual usage when evidence becomes available;
- keep Tool Gateway authorization/data policy independent from retry/cost semantics.

No AI implementation may rely on generic SDK retries for a non-idempotent/billable request without an adapter-specific proof.

---

# RT2-14 — Workflow-version proof does not cover mixed schema/code rollback compatibility

**Severity:** HIGH  
**Boundary:** Temporal long-running workflow + PostgreSQL migration + rolling deployment/rollback  
**Disposition:** OPEN

PoC A proves compatible workflow-code evolution. Architecture 0.10 separately specifies expand/contract migration and rollback windows. No current executable evidence composes old/new workers with old/new database shape and new domain enum/state values during rolling deployment.

Architecture 1.0 must define a compatibility matrix for at least N and N-1 application releases, including workflow history and schema/state readers. The production repository CI must include a migration/rollback fitness test before the first real deploy pipeline is considered complete.

---

# RT2-15 — Workflow identity examples in the baseline still conflict with the post-PoC operation-key rule

**Severity:** MEDIUM  
**Boundary:** documentation / implementation guidance  
**Disposition:** OPEN until Architecture 1.0 reconciliation

Architecture 0.10 still shows examples such as:

```text
publication-target:{target_id}:v1
```

while PoC A/D established that the durable logical identity is the stable external `operation_key` and that a mismatched target is a consistency error.

Document precedence currently makes the post-PoC rule authoritative, so this is not an immediate runtime bug. Architecture 1.0 must remove the conflicting target-ID identity examples so production code cannot choose the obsolete rule accidentally.

---

# RT2-16 — Authentic Temporal context can preserve stale authorization after scheduling

**Severity:** HIGH  
**Boundary:** RLS + authenticated Temporal execution context + live AuthorizationService/tenant/resource state + irreversible dispatch  
**Disposition:** OPEN

## Attack/failure scenario

An actor is authorized at schedule time and ViMi creates a correctly authenticated background execution envelope. Before execution, the actor is removed from the tenant, loses the relevant permission, the target/account authorization changes, the tenant is suspended, or the target/resource is disabled. Hours later the Temporal workflow resumes. Its envelope is still authentic and tenant-bound, but the authorization facts represented by the old scheduling decision are stale.

A second race exists even when the worker correctly performs a live check: the check can succeed, then the worker can pause while a blocking state change commits, and only afterward perform provider egress.

A third race exists **inside the permit path itself**: the worker reads dispatch-policy generation N and begins validating/consuming a dispatch permit, a blocking actor/tenant/resource mutation commits generation N+1 before consumption is durably committed, and the worker then proceeds. If validation and consumption are not serialized with every blocking generation change, both sides can believe they won.

The same serialized dispatch boundary must also carry the immutable platform-account generation. Otherwise authorization can be fresh while the worker still sends with a disabled/reconnected account generation.

If the worker treats a valid signed envelope, historical permission snapshot, a previously successful live check, or a non-atomic permit validation as permanent authority, it can perform a future irreversible publication that current policy would deny.

## Why current evidence does not cover it

PoC B proves that background tenant context is authenticated and tampering is rejected. It explicitly does not make stale permission snapshots permanent authority. Architecture 0.10 requires execution-time revalidation for tenant/account/content/entitlement conditions, but no current composition test proves an authoritative serialization order between dispatch commitment and all policy-defined blocking actor/tenant/resource mutations plus concurrent account-generation changes.

## Impact

Unauthorized future side effect after legitimate permission revocation, tenant suspension, target/resource disable, account disable or account reconnect.

## Required Architecture 1.0 change

Treat `ExecutionContext` authenticity and authorization freshness as separate contracts:

- signed/trusted context proves actor/tenant/operation provenance;
- immediately before irreversible action, revalidate current authoritative tenant state, platform-account ownership/generation, target/resource eligibility and the product's explicit creator-revocation policy;
- define one authoritative **dispatch-policy generation** for every policy state whose mutation can block egress, or bind separate tenant/resource generations into the same permit; actor permission revocation, tenant suspension, and target/resource disable/eligibility changes must invalidate stale permits;
- the final irreversible egress must be covered by a short-lived **versioned authorization/dispatch permit or equivalent fence** bound to the dispatch-policy generation(s) and immutable account generation;
- **permit consumption / dispatch commitment, all blocking dispatch-policy generation changes, and account-generation disable/reconnect changes must have one authoritative serialization order for the affected operation/account**;
- if actor revocation, tenant suspension, target/resource disable, or account-generation change commits first, the stale permit cannot be consumed and provider egress is forbidden;
- if dispatch commitment commits first while all bound generations remain valid, the operation has crossed ViMi's explicit too-late boundary; later blocking changes prevent future operations but this already-committed operation becomes an auditable reconciliation obligation rather than being misreported as never sent;
- provider egress occurs only after the durable dispatch commitment exists, so crash/cancellation after commitment cannot create an untracked request;
- historical creation authorization is retained for audit but never silently promoted to permanent execution authority;
- authorization caches must have versioned invalidation/bounded staleness and cannot authorize final dispatch without the serialized commitment;
- blocked execution uses a typed domain state rather than generic failure.

## Required executable verification

Exercise at least five orderings:

1. schedule while authorized, revoke before workflow dispatch while leaving the signed envelope valid, then resume;
2. allow the live authorization check to succeed, pause before dispatch commitment, commit revocation/generation change, then attempt consumption;
3. place a barrier **between dispatch-policy-generation validation and permit consumption**, race actor revocation against the consumption transaction, and prove the two sides have one serializable commit order;
4. place the same barrier after validating account generation N, race account disable/reconnect to N+1 against permit consumption, and prove an old-generation permit cannot dispatch when the account-generation change wins;
5. after live validation, race at least one non-actor blocking mutation — tenant suspension or target/resource disable — against permit consumption and prove that its generation change invalidates the stale permit when it commits first.

If a blocking generation change wins, the irreversible provider mock is not called. If dispatch commitment wins while all bound policy/account generations are still valid, a later change cannot retroactively erase that committed operation; it must be audited and reconciled under the explicit too-late policy.

**Executable gate:** `RTV2-X8`.

---

# Evidence-integrity cross-check

The first pass confirms additional Architecture 0.10 acceptance-plan/contract areas that must not be described as already machine-proven:

| Original Architecture 0.10 expectation | Actual evidence | Red-Team disposition |
|---|---|---|
| real transactional outbox duplicate delivery → one Temporal workflow | PoC A proves deterministic/duplicate direct start, not the PostgreSQL relay crash windows | RT2-02 Critical executable gate |
| PoC C asset lease prevents cleanup mid-job / production resource isolation | PoC C proves secure ingest and helper bounds but explicitly limits production isolation and does not claim AssetLease composition | RT2-08 High + targeted composition test |
| PoC D auth expiry / rotating refresh token | final PoC D deliberately does not claim credential refresh concurrency | RT2-03 Critical executable gate |
| execution-time authorization after scheduling | PoC B proves authenticated tenant context, not freshness or serialized actor/tenant/resource/account generation vs dispatch commitment | RT2-12/RT2-16 High + RTV2-X8 |
| execution-time entitlement + just-in-time usage admission | PoC E proves atomic quota accounting, not a concurrent plan-downgrade race against entitlement validation/reservation admission | RT2-07 High + RTV2-X1 |

This is an evidence-scope correction, not a downgrade of the local PASS verdicts of A–E.