# Red-Team v2 — Part 01: audit charter, evidence model and attack matrix

## 1. Target

Red-Team v2 attacks the **corrected pre-1.0 design**, consisting of:

- Architecture Baseline 0.10;
- `POST_POC_DECISIONS.md` validated by PoCs A–E;
- the actual executable evidence recorded in PoC A–E `REPORT.md` files;
- composition assumptions implied by the roadmap but not necessarily exercised by any single PoC.

The audit does **not** treat a green isolated PoC as proof that two independently correct components compose safely.

## 2. Evidence classes

Every architecture claim encountered by this audit is classified as one of:

```text
POC_PROVEN
    directly exercised by deterministic/machine-verifiable PoC evidence

DESIGN_SPECIFIED
    explicitly specified in Architecture 0.10 but not directly proved by current PoCs

COMPOSITION_PROVEN
    exercised across the actual boundary between two or more contracts

UNRESOLVED
    required behavior is ambiguous, contradictory, or lacks sufficient design/evidence
```

The audit must not silently promote `DESIGN_SPECIFIED` to `POC_PROVEN` or `COMPOSITION_PROVEN`.

## 3. Severity model

### CRITICAL

A credible composition failure can cause one or more of:

- cross-tenant disclosure or mutation;
- duplicate irreversible external publication;
- material double-billing / quota bypass / unbounded financial loss;
- credential corruption enabling systemic publishing failure or wrong-account action;
- unsafe disaster recovery that can repeat external side effects.

**Gate:** every Critical finding is release-blocking. It must be resolved with an explicit architecture change and, where the correctness claim is concurrency/failure-order dependent, new executable evidence before Architecture 1.0.

### HIGH

Can cause major data loss, unauthorized future action, significant billing inconsistency, broad outage, orphaned external state, or a security boundary failure that is narrower than Critical.

**Gate:** every High finding requires either implementation/evidence before freeze or an explicit Architecture 1.0 accepted-risk decision with owner, scope and follow-up gate. Silent deferral is forbidden.

### MEDIUM

Important resilience, operability, maintainability or premium-UX weakness that does not block an internal production foundation once explicitly designed and tracked.

### LOW

Hardening/future-scale improvement whose omission does not invalidate the current Architecture 1.0 foundation.

## 4. Finding format

Each finding must contain:

1. **Boundary attacked**
2. **Attack/failure scenario**
3. **Why existing PoC evidence does or does not cover it**
4. **Impact / severity**
5. **Required architecture change**
6. **Required verification**
7. **Disposition** — OPEN / FIXED / ACCEPTED-RISK / NOT-A-FINDING

No finding may be marked fixed only because prose was changed if the failure depends on concurrency, retries, crash windows or cross-system ordering and therefore requires executable evidence.

## 5. Release criteria for Red-Team v2

Red-Team v2 is PASS only when all of the following are true:

1. every roadmap composition boundary has been attacked;
2. the actual PoC reports have been compared against Architecture 0.10's original acceptance plan so evidence gaps are explicit;
3. no unresolved Critical finding remains;
4. every High finding has a concrete Architecture 1.0 disposition;
5. any newly required executable composition tests are green in CI;
6. the audit receives an independent review with no unresolved release-blocking finding;
7. `POST_POC_DECISIONS.md`, roadmap and the final Architecture 1.0 input set reflect the resolved contracts.

## 6. Fixed attack matrix

The following matrix is fixed before conclusions are written.

| ID | Composition boundary | Adversarial question |
|---|---|---|
| A | RLS + Temporal execution context | Can authenticated tenant context become stale, replayed, rebound or privileged after scheduling? |
| B | PostgreSQL outbox + Temporal identity | Can any crash/PITR window create a second workflow, suppress required work, or bind old execution to restored business state? |
| C | Publication lifecycle + durable orchestration | Can `STARTED/UNKNOWN/CONFIRMED` diverge between PostgreSQL, Temporal history and provider reality? |
| D | Usage reservation + workflow retries | Can quota expire/release while expensive or irreversible work is still legitimately running? Can confirmed work become unbillable? |
| E | Entitlement revalidation + reservation timing | What exactly is promised when plan/membership/entitlement changes between schedule and execution? |
| F | Media/object storage + leases + deletion | Can a valid in-flight or shared asset be purged, orphaned, or exposed across tenant boundaries? |
| G | Credential rotation + concurrent workers | Can refresh/revocation/version changes corrupt credentials or allow a stale worker to dispatch? |
| H | Webhook ownership + ordering/replay | Can delayed events be attributed to the wrong tenant/account generation or regress/repeat side effects? |
| I | Support privilege + non-rollbackable audit | Can privileged data leave the trusted boundary before durable audit evidence exists? |
| J | Provider quota + tenant fairness | Can one tenant/backlog monopolize shared provider quota or can recovery burst re-trigger provider-wide throttling? |
| K | Multi-system disaster recovery + kill switch/fencing | After PostgreSQL PITR, can newer Temporal, Object Storage, Secret Store or provider state cause stale external mutation, missing content, destructive orphan cleanup, or stale credential reuse? |
| L | AI/tool/budget boundaries | Can untrusted content, retries or provider choice cross tenant/secret/data-governance/budget boundaries? |
| M | Deployment/migrations + long-running workflows | Can schema/state/workflow compatibility break safe rollback or replay despite PoC A worker-version evidence? |
| N | Evidence integrity | Did any Architecture 0.10 acceptance claim remain only paper-specified although the PoC plan implied executable proof? |

## 7. Evidence inventory established before findings

### PoC A — Temporal

Directly proves durable workflow identity, worker crash/restart, compatible workflow evolution, ambiguous mutation handling and reconciliation. It does **not by itself** prove a production PostgreSQL transactional outbox relay crash window or PITR composition.

### PoC B — tenant isolation

Directly proves production-like RLS roles, transaction-local tenant context, authenticated background execution envelopes, server-side webhook tenant resolution and a rollback-resistant PostgreSQL log marker. It explicitly does **not** define the final external non-rollbackable support-audit sink or all execution-time authorization-revalidation semantics.

### PoC C — secure media ingest

Directly proves secure remote fetch/pinning/redirect/resource bounds, cancellation cleanup, content-addressed finalization semantics and helper process-tree termination. It explicitly does **not** prove production CPU/RAM/filesystem/network sandboxing. Its final report does not claim executable AssetLease/retention/deletion composition or PostgreSQL-PITR/object-version reconciliation.

### PoC D — platform lifecycle

Directly proves platform-neutral publication state/retry/reconciliation/callback semantics with deterministic mocks. It explicitly does **not** prove provider-specific behavior, webhook authentication, database durability, Temporal recovery, credential refresh concurrency, or Secret-Store/PITR recovery.

### PoC E — usage concurrency

Directly proves PostgreSQL-authoritative reservations/ledger concurrency, expiry/reconciliation and a minimal separate provider-quota coordinator. It explicitly does **not** prove production subscription lifecycle, real provider quota interpretation, distributed fairness, outage recovery or backlog drain behavior.

## 8. Audit rule

The next parts must now attack this matrix without changing the matrix to make the result easier to pass. Clarifications from independent review may make an existing boundary more explicit, but may not remove a hard case or weaken a release criterion.
