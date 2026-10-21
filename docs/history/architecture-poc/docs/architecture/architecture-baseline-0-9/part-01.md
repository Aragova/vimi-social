# ViMi Social — Architecture Baseline 0.9

**Status:** Draft for architecture red-team review  
**Date:** 2026-10-16  
**Scope:** New standalone SaaS product. No runtime dependency on the existing ViMi Telegram production project.

---

## 1. Product definition

**ViMi Social** is a multi-tenant, AI-assisted content operating system for:

- ingesting authorized content;
- storing immutable originals and versioned derivatives;
- preparing platform-specific variants;
- approval workflows;
- scheduling;
- multi-platform publishing;
- analytics and feedback;
- usage metering and future SaaS billing;
- administration and support through a dedicated control plane.

Initial platform set:

- Telegram
- X
- Instagram
- TikTok
- YouTube / Shorts
- Reddit
- Bluesky

The existing ViMi Telegram project is a separate product and remains operationally independent.

### 1.1 Non-goals for the first production version

The first production version will **not** require:

- microservices for every domain;
- Kubernetes;
- Kafka;
- ClickHouse;
- database sharding;
- multi-region active-active;
- OpenFGA or another relationship-graph authorization engine;
- self-hosted Temporal;
- custom password/MFA infrastructure;
- event sourcing as the main persistence model.

These may be added only after an observed need and an ADR.

---

## 2. Architectural priorities

All major design decisions are evaluated against seven properties:

1. **Isolation** — tenant, platform, failure, resource and credential isolation.
2. **Correctness** — explicit states, versioning, idempotency and reconciliation.
3. **Evolvability** — providers and internal components can be replaced behind contracts.
4. **Observability** — important operations are traceable end-to-end.
5. **Security** — least privilege, untrusted-input isolation and auditable privileged actions.
6. **Operability** — retries, recovery, kill switches, support tooling and disaster recovery.
7. **Simplicity** — infrastructure is added only for a demonstrated need.

---

## 3. Top-level architecture

```text
                           ViMi Social
                                │
                    ┌───────────┴───────────┐
                    │                       │
               Customer UI             Public/API
                    │                       │
                    └───────────┬───────────┘
                                ↓
                            API App
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
   Identity/Tenancy        Product Domain          Control Plane
   Authorization           Content                 Admin/Support
   Entitlements            Approvals               Platform Health
   Usage                   Scheduling              Feature Flags
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                ↓
                        Managed PostgreSQL
                        Canonical state
                                │
                      Transactional Outbox
                                │
                                ↓
                         Temporal Cloud
                   Durable workflows/activities
              ┌─────────────────┼──────────────────┐
              ↓                 ↓                  ↓
          AI workers       Media workers       Platform workers
              │                 │                  │
              │                 │        ┌─────────┼─────────┐
              │                 │        ↓         ↓         ↓
              │                 │      Telegram    X      Instagram...
              │                 ↓
              │           Object Storage
              │
              └────── Model providers

Redis: optional cache/rate-limit/ephemeral coordination.
Secret manager/KMS: OAuth/API credentials.
OpenTelemetry: traces, logs, metrics.
```

---

## 4. Deployment model

Start as a **modular monolith in one repository** with multiple deployable processes:

```text
vimi-api
vimi-web
vimi-worker
vimi-media-worker
```

This is intentionally **not** a microservice architecture.

A module may be extracted into an independent service only when there is a measurable reason such as:

- independent scaling profile;
- security isolation;
- release independence;
- operational ownership by a separate team;
- unacceptable coupling or resource contention.

Extraction requires an ADR.

---

## 5. Repository baseline

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
│           ├── media/
│           ├── ai/
│           ├── analytics/
│           ├── platform_registry/
│           ├── audit/
│           ├── notifications/
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

## 6. Module boundaries

### 6.1 Dependency direction

Allowed conceptual direction:

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

Platform adapters implement publishing contracts; they do not own domain state transitions.

### 6.2 Hard rules

- Platform modules may not import internals of other platform modules.
- AI modules may not access credential storage directly.
- HTTP controllers may not contain domain business logic.
- UI may not access the database directly.
- Media rendering may not publish to social platforms.
- Billing may not call platform APIs.
- External mutations must define idempotency and unknown-outcome handling.
- Tenant-owned repositories must require a `TenantContext`.
- Credentials must never be serialized into logs, Temporal workflow payloads or analytics events.
- No runtime dependency on the existing ViMi Telegram project.

Architecture tests must enforce these rules.

---

## 7. Code quality rules

File size is a **guardrail**, not an absolute design rule.

Typical guidance:

- `<300 LOC`: normal;
- `300–400`: normal if cohesive;
- `400–600`: architecture review;
- `>600`: strong signal of a possible God module;
- long functions/high cyclomatic complexity trigger review.

Primary quality metrics:

- cohesion;
- coupling;
- dependency cycles;
- public surface size;
- fan-in/fan-out;
- complexity;
- testability;
- type safety.

No artificial file fragmentation merely to satisfy a line count.

---

## 8. Technology baseline

| Area | Baseline |
|---|---|
| Backend | Python 3.12/3.13 after SDK compatibility validation |
| HTTP API | FastAPI |
| Validation | Pydantic v2 |
| ORM | SQLAlchemy 2 |
| PostgreSQL driver | psycopg 3 |
| Database | Managed PostgreSQL |
| Workflow execution | Temporal Cloud |
| Durable simple jobs | Temporal Standalone Activities where suitable |
| Cache/rate limiting | Redis only when justified |
| Media | FFmpeg / ffprobe in isolated workers |
| Storage | S3-compatible object storage |
| Frontend | Next.js + TypeScript strict |
| API contract | REST + OpenAPI |
| Authentication | Managed identity provider |
| Authorization | ViMi AuthorizationService |
| Secrets | Managed Secret Store/KMS-class solution |
| Observability | OpenTelemetry |
| Migrations | Alembic, expand/contract strategy |
| Python lint | Ruff |
| Type checking | Pyright |
| Testing | pytest + Playwright + contract/architecture/security suites |
| CI/CD | GitHub Actions |
| Deployment | Immutable Docker images |
| Supply chain | SBOM + dependency/secret/code scanning + provenance |
| IaC | Terraform/OpenTofu when repeatable staging is established |

---
