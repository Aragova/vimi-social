# 51. Red-team result by architecture area

| Area | Verdict | Required action |
|---|---|---|
| Modular monolith | **KEEP** | Add stronger fitness tests |
| PostgreSQL | **KEEP** | Formal DB-role/RLS/pooling pattern |
| Temporal | **KEEP** | Add workflow versioning + deterministic IDs |
| Transactional outbox | **KEEP** | Explicit at-least-once + dedupe |
| Redis | **KEEP OPTIONAL** | Define failure semantics per use |
| Object Storage | **KEEP** | Add immutable keys, leases, ingest states |
| Managed IdP | **KEEP** | Harden invite/identity semantics |
| AuthorizationService | **KEEP** | Execution-time revalidation |
| UsageLedger | **KEEP** | Add UsageReservation |
| Platform Adapter | **KEEP** | Add mutation phases and quota integration |
| UNKNOWN state | **KEEP / STRENGTHEN** | Reconciliation becomes mandatory |
| AI Tool Gateway | **KEEP** | Add data-governance and prompt-injection controls |
| Media isolation | **KEEP / STRENGTHEN** | Dedicated fetcher + resource-bomb controls |
| Design System | **KEEP** | No architecture blocker |
| Kafka | **DO NOT ADD** | No demonstrated need |
| Kubernetes | **DO NOT ADD** | No demonstrated need |
| ClickHouse | **DO NOT ADD** | No demonstrated need |
| OpenFGA | **DO NOT ADD** | Keep abstraction only |
| Microservices | **DO NOT ADD** | Current modular monolith appropriate |

---

# 52. Required Architecture Baseline 0.10 additions

Before Architecture 1.0, add the following sections to the baseline.

## 52.1 ExecutionContext

```text
ExecutionContext
────────────────
tenant_id
actor_id
privileged_actor_id?
correlation_id
operation_id
origin
```

Rules for HTTP, workflow, webhook and admin execution.

## 52.2 DB role model

```text
migration_owner
application_role
control_plane_role
read_only_ops_role
```

and exact RLS/pooling expectations.

## 52.3 Workflow identity and versioning

- deterministic workflow IDs;
- outbox event dedupe;
- workflow version compatibility;
- worker deployment strategy;
- long-lived workflow policy.

## 52.4 Usage reservations

Add:

```text
UsageReservation
```

beside `UsageLedger`.

## 52.5 Provider quota service

Add:

```text
PlatformQuotaCoordinator
```

distinct from tenant worker fairness.

## 52.6 Credential concurrency model

Add:

```text
credential_version
single-flight refresh
CAS update
```

## 52.7 Safe media ingest

Separate:

```text
UploadIngest
RemoteMediaFetcher
MediaVerifier
MediaWorker
```

## 52.8 Asset lifecycle

Add:

```text
PENDING_UPLOAD
UPLOADED
VERIFIED
READY
DELETE_REQUESTED
PURGED
```

plus active leases/references.

## 52.9 AI processing policy

Add DataClassification → allowed AI providers/models.

## 52.10 DR cross-system reconciliation

Formal PostgreSQL + Temporal + Object Storage + external-platform recovery procedure.

---

# 53. New architecture entities recommended

Add these to Domain Model review:

```text
ExecutionContext         (runtime value object)
UsageReservation
WebhookInbox
OutboxEvent
PlatformQuotaState
CredentialVersion
AssetLease
SupportSession
EntitlementDecision
AIProcessingPolicy
```

Potential infrastructure/domain records:

```text
workflow_binding
provider_event
reconciliation_case
```

`ReconciliationCase` may be valuable for any operation left in `UNKNOWN`.

---

# 54. Revised critical publication path

After red-team changes:

```text
User request
    ↓
AuthorizationService
    ↓
TenantContext
    ↓
Create ContentVersion
    ↓
Preflight
    ↓
Approval(version-bound)
    ↓
Entitlement decision/reservation
    ↓
PublicationTarget
    ↓
DB transaction
    ├ domain state
    └ OutboxEvent(event_id)
    ↓
Outbox relay
    ↓ deterministic workflow_id
Temporal
    ↓
execution-time checks
    ├ tenant active
    ├ account healthy
    ├ entitlement/reservation valid
    ├ content version approved
    └ provider quota available
    ↓
PublicationAttempt
    ↓
NOT_STARTED
    ↓
STARTED
    ↓
provider request
    ├ CONFIRMED
    ├ PENDING
    ├ REJECTED
    └ UNKNOWN
          ↓
     reconciliation
          ├ CONFIRMED
          ├ SAFE_RETRY
          └ NEEDS_REVIEW
```

---

# 55. Revised media path

```text
User upload / remote URL
        ↓
UploadIngest / RemoteMediaFetcher
        ↓
quarantine
        ↓
MediaVerifier
        ↓
Asset = VERIFIED
        ↓
Object Storage immutable key
        ↓
Media Worker
        ↓
RenderRecipe
        ↓
DerivedAsset
        ↓
hash verification
        ↓
READY
```

Remote URL never enters FFmpeg directly.

---

# 56. Revised AI path

```text
Untrusted Content
      ↓
AI Input Builder
      ↓
Data Classification Policy
      ↓
Approved Model Provider
      ↓
Model
      ↓
Typed Tool Request
      ↓
AI Tool Gateway
      ├ tenant enforcement
      ├ authorization
      ├ entitlement
      ├ budget
      ├ validation
      └ audit
      ↓
Application Service
```

---

# 57. Architecture 1.0 blockers

Architecture 1.0 must **not** be frozen until all of these have explicit design answers:

- [ ] DB role/RLS transaction model
- [ ] deterministic Temporal workflow identity
- [ ] Temporal workflow deployment/versioning
- [ ] publication unknown-outcome reconciliation
- [ ] OAuth refresh concurrency
- [ ] usage reservation/deduplication
- [ ] provider quota coordination
- [ ] webhook ordering/replay
- [ ] remote media SSRF protection
- [ ] media resource limits
- [ ] object retention/workflow leases
- [ ] deletion/in-flight workflow interaction
- [ ] AI data governance
- [ ] DR PostgreSQL/Temporal reconciliation
- [ ] external social account ownership rule
- [ ] execution-time authorization/entitlement policy
- [ ] migration + rollback compatibility policy

---

# 58. PoC plan updated by the audit

The four earlier PoCs are still correct, but should be expanded.

## PoC A — Temporal durability + versioning

Test:

1. workflow scheduled;
2. worker dies;
3. resumes;
4. deployment occurs mid-workflow;
5. activity returns unknown external outcome;
6. reconciliation resolves it;
7. duplicate outbox event does not create duplicate workflow.

## PoC B — Tenant isolation

Test:

- app role + RLS;
- pooled connections;
- Temporal worker context;
- webhook context;
- support/control-plane context;
- intentional missing WHERE clause.

## PoC C — Media isolation

Test:

- normal upload;
- remote media URL;
- redirect SSRF;
- DNS rebinding;
- oversized stream;
- malformed codec;
- extreme resolution;
- worker CPU/RAM/time limits;
- object lease during long workflow.

## PoC D — Async platform mock

Provider mock supports:

```text
accepted + response
accepted + lost response
pending
webhook duplicate
webhook out of order
429
500
auth expired
token rotation
```

System must end in correct target state without duplicate external post.

## PoC E — Usage concurrency

New PoC required.

Simulate:

- 100 simultaneous expensive jobs;
- limited quota;
- retries;
- failures/refunds.

Verify reservation and ledger correctness.

---

# 59. Final red-team verdict

The core architecture survives the adversarial review.

No evidence was found that ViMi Social should switch to:

- microservices;
- Kafka;
- Kubernetes;
- ClickHouse;
- event sourcing;
- custom auth;
- a different primary database.

The biggest improvements are **correctness mechanisms**, not additional infrastructure.

Architecture should evolve:

```text
0.9
 ↓
Red-Team v1
 ↓
0.10 with required corrections
 ↓
PoC verification
 ↓
Red-Team v2 on corrected design
 ↓
Architecture 1.0
```

---

# 60. Next stage

**Next action:** produce **Architecture Baseline 0.10**, incorporating every Critical/High red-team requirement.

After 0.10:

1. run the five PoCs;
2. record actual results;
3. perform Red-Team v2;
4. freeze Architecture 1.0 only after the design survives both paper review and executable proof.
