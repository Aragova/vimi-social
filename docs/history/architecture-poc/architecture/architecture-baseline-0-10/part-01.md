# ViMi Social — Architecture Baseline 0.10

**Status:** Revised baseline after Architecture Red-Team Audit v1  
**Date:** 2026-10-16  
**Supersedes:** Architecture Baseline 0.9  
**Next gate:** Five executable PoCs → Red-Team v2 → Architecture 1.0

---

# 1. Purpose

Architecture Baseline 0.10 incorporates all Critical and High findings from Red-Team Audit v1.

This version is no longer only a conceptual architecture. It defines the safety contracts required before production code exists:

- immutable execution context;
- production-like PostgreSQL role/RLS model;
- deterministic workflow identity;
- Temporal workflow evolution policy;
- explicit external mutation phases;
- OAuth credential concurrency control;
- usage reservation and deduplication;
- provider quota coordination;
- webhook ordering and replay protection;
- secure media ingress;
- asset leases and deletion lifecycle;
- AI data-governance policy;
- disaster-recovery reconciliation;
- external-account ownership policy;
- approval/version race prevention;
- migration and rollback compatibility.

Architecture 0.10 is the document against which the technical PoCs are built.

---

# 2. Product boundary

ViMi Social is a new standalone SaaS product.

It has:

- a separate repository;
- separate runtime services;
- separate PostgreSQL database;
- separate object storage namespace/bucket;
- separate credentials;
- separate Telegram sessions/accounts;
- separate CI/CD;
- separate deployment lifecycle.

The existing ViMi Telegram production project is treated as an external legacy product.

There is no runtime import or database dependency between the two systems.

Allowed reuse:

```text
existing ViMi experience
        ↓
review design/logic
        ↓
reimplement cleanly
        ↓
new ViMi Social tests/contracts
```

Forbidden reuse:

```python
from telegram_forwarder_bot import ...
```

in ViMi Social production runtime.

---

# 3. Architectural priorities

Every major decision is judged against:

1. **Isolation**
2. **Correctness**
3. **Evolvability**
4. **Observability**
5. **Security**
6. **Operability**
7. **Simplicity**

When two goals conflict, correctness and tenant isolation override convenience.

---

# 4. Top-level architecture

```text
                               ViMi Social
                                   │
                       ┌───────────┴───────────┐
                       │                       │
                  Customer UI             Public API
                       │                       │
                       └───────────┬───────────┘
                                   ↓
                              FastAPI App
                                   │
       ┌───────────────────────────┼───────────────────────────┐
       │                           │                           │
  Identity/Tenancy            Product Domain              Control Plane
  Authorization              Content                    Admin/Support
  Entitlements               Approvals                  Platform Health
  Usage                      Scheduling                 Feature Flags
       │                           │                           │
       └───────────────────────────┼───────────────────────────┘
                                   ↓
                           Managed PostgreSQL
                           canonical business state
                                   │
                         Transactional Outbox
                                   │
                                   ↓
                            Temporal Cloud
                    durable workflows / activities
              ┌────────────────────┼─────────────────────┐
              ↓                    ↓                     ↓
          AI workers          Media workers        Platform workers
              │                    │                     │
              │                    ↓                     ├ Telegram
              │             Object Storage               ├ X
              │                                          ├ Instagram
              └──── Model Providers                      ├ TikTok
                                                         ├ YouTube
                                                         ├ Reddit
                                                         └ Bluesky

Optional supporting services:
- Redis for cache/rate limiting/ephemeral coordination;
- managed Secret Store/KMS;
- OpenTelemetry pipeline;
- email/notification provider.
```

---

# 5. Modular-monolith deployment model

One repository, several deployable processes:

```text
vimi-web
vimi-api
vimi-worker
vimi-media-worker
```

These processes share versioned application/domain packages.

This is not a microservice architecture.

A module may be physically extracted only after:

```text
measured operational problem
       ↓
existing boundaries insufficient
       ↓
ADR
       ↓
extraction
```

Acceptable reasons include:

- security isolation;
- independent scale profile;
- separate release cadence;
- separate team ownership;
- measurable contention.

---

# 6. Repository baseline

```text
vimi-social/
│
├── apps/
│   ├── web/
│   ├── api/
│   ├── worker/
│   └── media-worker/
│
├── backend/
│   └── src/
│       └── vimi_social/
│           ├── identity/
│           ├── tenancy/
│           ├── authorization/
│           ├── billing/
│           ├── entitlements/
│           ├── usage/
│           ├── content/
│           ├── approvals/
│           ├── scheduling/
│           ├── publishing/
│           ├── platforms/
│           │   ├── telegram/
│           │   ├── x/
│           │   ├── instagram/
│           │   ├── tiktok/
│           │   ├── youtube/
│           │   ├── reddit/
│           │   └── bluesky/
│           ├── platform_registry/
│           ├── media/
│           ├── ai/
│           ├── analytics/
│           ├── audit/
│           ├── notifications/
│           ├── webhooks/
│           ├── outbox/
│           └── observability/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── architecture/
│   ├── tenant_isolation/
│   ├── workflows/
│   ├── media_corpus/
│   ├── security/
│   └── e2e/
│
├── migrations/
├── docs/
│   ├── adr/
│   ├── architecture/
│   ├── security/
│   └── runbooks/
├── infra/
│
├── AGENTS.md
├── ARCHITECTURE.md
├── SECURITY.md
├── CONTRIBUTING.md
└── pyproject.toml
```

---

# 7. Hard dependency rules

Allowed dependency direction:

```text
Transport/UI
    ↓
Application Services
    ↓
Domain
    ↓
Ports / Contracts
    ↓
Infrastructure Adapters
```

Hard rules:

- no platform module imports another platform module's internals;
- no AI component reads secrets directly;
- no AI component receives raw DB connection/session;
- no controller owns business rules;
- no UI accesses PostgreSQL directly;
- no media renderer publishes externally;
- no billing module calls a platform API;
- no platform adapter updates arbitrary domain status directly;
- no tenant-owned repository accepts untrusted free-form tenant IDs;
- no external mutation exists without retry/idempotency/unknown-outcome strategy;
- no plaintext credentials are logged, audited, exposed to browser, or persisted in Temporal history;
- no runtime dependency exists on the legacy ViMi repository.

Architecture tests enforce these rules.

---

# 8. ExecutionContext — mandatory runtime boundary

Every meaningful request/workflow/activity has an immutable trusted context:

```text
ExecutionContext
────────────────────────
tenant_id
actor_id
actor_type
privileged_actor_id?
correlation_id
operation_id
origin
```

Examples of `origin`:

```text
http
temporal
webhook
scheduler
admin
system
```

Rules:

- user input never supplies authoritative `tenant_id`;
- HTTP layer builds context from authenticated membership;
- Temporal workflows store only trusted identifiers created by the server;
- activities reconstruct/verify context before loading tenant data;
- webhook handlers resolve tenant from trusted account mappings;
- support impersonation records both effective and privileged actors.

Background processing does not bypass authorization merely because it is "internal".

---

# 9. PostgreSQL role model

Production database roles are separated.

```text
vimi_migration_owner
  - owns schemas/tables
  - used only by migration process

vimi_app
  - normal API/worker role
  - no BYPASSRLS
  - does not own tenant tables

vimi_control_plane
  - elevated operational access
  - limited to explicit admin paths
  - fully audited

vimi_readonly_ops
  - optional read-only operational role
```

Application code never runs as PostgreSQL superuser.

---
