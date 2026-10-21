# ViMi Social — Architecture Red-Team Audit v1

**Target:** Architecture Baseline 0.9  
**Date:** 2026-10-16  
**Status:** Completed — baseline requires changes before Architecture 1.0  
**Method:** adversarial architecture review focused on multi-tenancy, distributed side effects, workflow durability, media security, AI boundaries, billing correctness, operations and recovery.

---

# 1. Executive summary

Architecture Baseline 0.9 is directionally strong. The largest risks are **not** the choice of Python, PostgreSQL, Temporal, Next.js or FFmpeg. The largest risks are the boundaries between systems:

- PostgreSQL ↔ Temporal;
- local state ↔ irreversible external publication;
- tenant authorization ↔ background jobs;
- OAuth credentials ↔ concurrent workers;
- object storage ↔ retention/deletion;
- AI reasoning ↔ privileged tools;
- usage metering ↔ concurrent expensive jobs;
- deployment ↔ long-running Temporal workflows.

The red-team review found several issues that must be explicitly designed before freezing Architecture 1.0.

### Severity summary

| Severity | Count | Meaning |
|---|---:|---|
| **CRITICAL** | 9 | Can cause cross-tenant exposure, duplicate publication, incorrect billing, credential corruption, or unsafe recovery |
| **HIGH** | 20 | Can cause data loss, major operational incidents, security weaknesses, or systemic user-facing failure |
| **MEDIUM** | 15 | Important for resilience, maintainability and premium UX but not a release blocker for the first internal prototype |
| **LOW** | 4 | Useful hardening / future-scale consideration |

**Architecture 0.9 verdict:** **PASS WITH REQUIRED CHANGES**.  
It should **not** be frozen as Architecture 1.0 yet.

---

# 2. Mandatory changes before Architecture 1.0

The audit requires adding or strengthening the following concepts:

1. **Immutable ExecutionContext** for every background workflow/activity.
2. **Database-enforced tenant isolation pattern** with explicit application/migration/admin DB roles.
3. **Deterministic workflow IDs + outbox deduplication** between PostgreSQL and Temporal.
4. **Temporal workflow versioning / worker versioning policy**.
5. **External mutation safety model**: `NOT_STARTED / STARTED / ACCEPTED / UNKNOWN / CONFIRMED`.
6. **OAuth credential concurrency control**.
7. **Usage reservation**, not only post-factum UsageLedger.
8. **Provider quota coordinator** separate from tenant fairness.
9. **Webhook ordering/replay model**.
10. **Safe remote media fetch service** with redirect and DNS-rebinding protection.
11. **Object lease / reference model** preventing retention jobs from deleting in-flight assets.
12. **Deletion/tombstone lifecycle** coordinated with active workflows.
13. **AI data-governance policy** controlling which model providers may receive which data classes.
14. **Temporal ↔ PostgreSQL disaster-recovery reconciliation procedure**.
15. **RLS + connection-pool safety contract**.
16. **Global uniqueness policy for connected external social accounts**.
17. **Atomic approval/version concurrency controls**.
18. **Deployment compatibility contract for long-running workflows and DB migrations**.

These changes are described in detail below.

---

# 3. Critical finding RT-01 — Tenant context loss in background execution

## Attack/failure scenario

User in Tenant A starts a scheduled publication.

The HTTP request is correctly authorized, but several hours later a Temporal worker processes the workflow. The worker receives only:

```text
publication_id
```

and loads related objects without a strongly bound tenant scope.

A bug in a repository query or incorrectly reused ID could access Tenant B.

## Risk

**CRITICAL — cross-tenant data exposure / wrong-account publication.**

The biggest tenant risk often appears outside HTTP requests, because background workers no longer have the original web authorization middleware.

## Required change

Introduce an immutable:

```text
ExecutionContext
────────────────
tenant_id
actor_id
actor_type
correlation_id
request_origin
operation_id
```

Every workflow/activity operating on tenant-owned resources receives or reconstructs a trusted server-generated `ExecutionContext`.

Repositories must use:

```text
TenantContext
```

rather than accepting a free-form `tenant_id`.

Background workers must never derive tenant ownership from user-controlled workflow payload.

## Acceptance test

- Create two tenants with identical local numeric/reference values.
- Execute workflow for Tenant A.
- Attempt to load Tenant B resource by ID.
- Repository must deny or return not found.
- Repeat through HTTP, Temporal activity, webhook handler and admin support path.

---

# 4. Critical finding RT-02 — RLS can silently fail if DB roles are wrong

## Scenario

Baseline says RLS is defense-in-depth.

However PostgreSQL table owners, superusers and roles with `BYPASSRLS` can bypass row policies. A production application role that accidentally owns tables can therefore neutralize the isolation layer.

Connection pooling can also leak session settings if tenant context is implemented carelessly.

## Risk

**CRITICAL — false confidence in tenant isolation.**

## Required design

Use separate roles:

```text
vimi_migration_owner
    owns schema/tables

vimi_app
    no BYPASSRLS
    does not own tenant tables

vimi_control_plane
    privileged, narrowly scoped and audited
```

Tenant context must be set transaction-locally, e.g. conceptually:

```text
BEGIN
SET LOCAL app.tenant_id = ...
...
COMMIT
```

Pool connections must be reset safely on return.

For RLS-protected tables, CI integration tests must run using the **actual production-like app role**, not a superuser.

## Acceptance test

Run cross-tenant test suite with:

- migration owner;
- app role;
- control-plane role.

Verify app role cannot bypass RLS even if application WHERE clause is intentionally removed.

---

# 5. Critical finding RT-03 — Outbox → Temporal can create duplicate workflows

## Scenario

Transaction commits:

```text
publication scheduled
outbox event created
```

Outbox relay calls Temporal to start workflow.

Temporal accepts it.

Before relay marks the outbox row delivered, relay crashes.

On restart it sends the same event again.

## Risk

**CRITICAL — duplicate publication workflows.**

Outbox delivery is inherently at-least-once unless deduplication is designed.

## Required change

Every event gets immutable:

```text
event_id
```

Every externally meaningful workflow gets deterministic:

```text
workflow_id
```

Example:

```text
publication-target:{publication_target_id}:v1
```

Outbox relay may resend indefinitely, but Temporal start must be idempotent against the same workflow identity.

Do not rely on `outbox.delivered_at` for exactly-once semantics.

## Acceptance test

Crash relay:

1. before Temporal start;
2. after Temporal accepted start;
3. before DB marks outbox delivered.

All three cases must result in exactly one logical workflow.

---

# 6. Critical finding RT-04 — Long-running Temporal workflows and code deployment

## Scenario

TikTok workflow starts under release `2026.10.1`.

It sleeps/polls for platform processing.

While sleeping, production deploys `2026.10.2`, where workflow branching logic has changed.

Temporal workflow replay requires deterministic compatible code.

## Risk

**CRITICAL — workflow nondeterminism / stuck production workflows.**

## Required change

Architecture needs an explicit workflow evolution policy:

```text
Workflow Definitions are versioned contracts.
```

Use one or more of:

- Temporal Worker Versioning;
- versioned workflow types;
- compatible workflow patch/version markers;
- separate task queues during migration.

Rules:

- running workflows must remain replayable;
- no arbitrary I/O inside workflow code;
- large media or secrets never stored in workflow history;
- long-lived workflows may `continue-as-new` when necessary;
- deployment cannot delete code required by currently running workflows.

## Acceptance test

Start workflow on old release, deploy new release mid-execution, then complete workflow without replay error or duplicate side effect.

---
