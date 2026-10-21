# ViMi Social — product concept

**Status:** Pre-production concept validated through architecture PoCs  
**Product:** Standalone multi-tenant SaaS  
**Current gate:** Architecture validation; production repository intentionally not created yet

## 1. Product definition

ViMi Social is a **multi-tenant AI-assisted content operating system** for preparing, adapting, scheduling, publishing, and analyzing authorized social content across multiple platforms.

Initial platform family:

- Telegram;
- X;
- Instagram;
- TikTok;
- YouTube / Shorts;
- Reddit;
- Bluesky.

The system should let one team operate a single content workflow while each platform adapter owns its own capabilities, limits, credentials, publication semantics, reconciliation logic, and compliance rules.

## 2. Core product capabilities

The intended product covers:

1. authorized content ingest from supported sources;
2. immutable originals plus versioned derivatives;
3. media preparation and platform-specific variants;
4. AI-assisted captions, metadata, classification, and workflow assistance behind controlled tool boundaries;
5. human approval and version concurrency;
6. scheduling with timezone-correct execution;
7. multi-platform publication;
8. UNKNOWN-outcome reconciliation rather than blind retry of irreversible actions;
9. webhook/callback processing;
10. analytics and feedback;
11. usage metering, reservations, quotas, entitlements, and future billing;
12. administration, support, audit, kill switches, and account-health tooling.

## 3. Users and authorization

ViMi Social is multi-tenant from day one.

The product model separates:

- **identity/authentication** — managed identity provider;
- **RBAC** — what a user is allowed to do in a tenant;
- **subscription entitlements** — which product capabilities/limits the tenant has purchased;
- **execution-time policy** — whether a scheduled/background action is still allowed when it actually runs.

Expected administrative layers include a platform-level main administrator/control plane, tenant administrators, and ordinary tenant users. Privileged support access must be narrow, reason-bound, and auditable.

## 4. Product boundary: ViMi Social vs ViMi Core

The existing Telegram production project and ViMi Social are separate products.

ViMi Social owns its own:

- repository and codebase;
- deployment lifecycle;
- PostgreSQL database;
- object storage;
- secrets and credentials;
- Telegram sessions/accounts;
- Temporal workflows;
- workers and media workers;
- CI/CD;
- monitoring and incident boundary.

Patterns can be studied and reimplemented, but production ViMi Social must not import runtime code or share mutable operational state with the existing Telegram project.

## 5. Architecture shape

Initial production shape is a **modular monolith with multiple process roles**, not a microservice fleet:

- API/web process;
- background worker;
- isolated media worker;
- Next.js customer/admin frontend;
- managed PostgreSQL as canonical transactional storage;
- Temporal Cloud for durable workflows;
- object storage for media;
- Redis only where an explicitly ephemeral cache/rate-limit role is justified;
- OpenTelemetry-based observability.

Microservices, Kubernetes, Kafka, sharding, multi-region active-active, and similar infrastructure are deferred until measured need exists.

## 6. Reliability philosophy

External social publication is treated as an irreversible distributed side effect.

The central rule is:

```text
ambiguous external outcome
→ UNKNOWN
→ reconciliation
→ confirmed / pending / proved absent / still unknown
```

There is no blind automatic second publish after an ambiguous timeout, lost response, connection error, or local cancellation after dispatch has begun.

A stable `operation_key` is the logical publication identity. Safe retry is explicit, bounded, and authorized only by a known-safe pre-mutation failure or provider-specific proof that the external mutation did not happen.

## 7. Security philosophy

Key boundaries include:

- PostgreSQL RLS as defense-in-depth for tenant isolation;
- trusted/authenticated execution context for background work;
- server-side tenant resolution for provider callbacks;
- isolated untrusted media ingest and media processing;
- least-privilege credential access;
- narrow privileged support interfaces with non-rollbackable audit evidence;
- AI tool gateway and data-governance rules rather than unrestricted agent access;
- explicit data classification, retention, deletion, and asset provenance.

## 8. UX direction

The product should present a premium SaaS workflow rather than exposing infrastructure complexity. Partial platform success must be understandable: users need to see which targets are confirmed, pending, unknown, safely retryable, or permanently failed without turning distributed-system states into confusing technical errors.

## 9. Current delivery path

```text
Architecture Baseline 0.10
        ↓
PoC A — Temporal durability             PASS
PoC B — tenant isolation / RLS          PASS
PoC C — secure media ingest             PASS
PoC D — async publication lifecycle     PASS
PoC E — usage reservations/concurrency  PENDING
        ↓
Red-Team v2
        ↓
Architecture 1.0
        ↓
production repository and implementation
```

## 10. Source of detailed truth

This concept document is the compact product view. Detailed contracts live in:

- `docs/architecture/ARCHITECTURE_BASELINE_0_10.md`;
- `docs/architecture/POST_POC_DECISIONS.md`;
- the individual PoC `REPORT.md` files.
