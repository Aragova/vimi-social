# ViMi Social — project context

**Repository:** `Aragova/vimi-social`  
**Status:** Production implementation started  
**Architecture gate:** Red-Team v2 complete; Architecture 1.0 release gate satisfied  
**Source architecture repository:** `Aragova/vimi-social-architecture-poc`  
**Architecture PR #8:** merged into `main`  
**Architecture merge commit:** `6252c6f4e425006f927f7b5e5556c96ecb37d245`

## What we are building

ViMi Social is a standalone multi-tenant SaaS for operating authorized social content across Telegram, X, Instagram, TikTok, YouTube/Shorts, Reddit, Bluesky, and future adapters.

The product covers content ingest, immutable originals and derivatives, media preparation, AI assistance behind controlled tools, human approval, scheduling, multi-platform publication, callback/reconciliation processing, analytics, usage metering/quotas, entitlements, administration, support, audit, account health, and kill switches.

## Product boundary

ViMi Social is separate from the existing Telegram production project. It owns its own repository, PostgreSQL database, object storage, credentials/secrets, Telegram sessions/accounts, Temporal workflows, workers, CI/CD, monitoring, and incident boundary. Patterns may be reimplemented; runtime code and mutable production state must not be shared.

## Validated architecture foundation

Architecture research and executable validation were completed in `Aragova/vimi-social-architecture-poc`:

- PoC A — Temporal durability, stable operation identity, workflow evolution, UNKNOWN reconciliation: PASS.
- PoC B — PostgreSQL RLS/tenant isolation, trusted execution context, support audit boundaries: PASS.
- PoC C — secure remote media ingest and helper-process lifetime/resource controls: PASS.
- PoC D — async provider lifecycle, typed outcomes, explicit safe retry, monotonic callbacks: PASS.
- PoC E — atomic usage reservations, quota concurrency, append-only ledger, expiry/reconciliation: PASS.
- Red-Team v2 — cross-system composition audit and deterministic regressions: PASS.

The final exact-head Architecture gate passed Ruff, strict Pyright, complete Authority + X1–X8 composition regressions, and PoC A–E before merge.

## Initial production shape

Start as a modular-monolith monorepo with multiple process roles:

- `apps/web` — Next.js/TypeScript customer/admin UI;
- API process — Python/FastAPI;
- background worker — Temporal worker;
- isolated media worker;
- PostgreSQL — canonical transactional and commercial usage authority;
- Temporal — durable workflow orchestration;
- S3-compatible object storage — media;
- managed identity provider — authentication/identity boundary;
- Redis only for explicitly non-authoritative cache/rate-limit roles;
- OpenTelemetry-compatible observability.

Do not introduce microservices, Kafka, Kubernetes, sharding, or active-active multi-region by default. Add infrastructure only when measured requirements justify it.

## Current implementation stage

We are at **Production Bootstrap / Vertical Slice 01**.

The first real end-to-end slice is:

1. verified identity from the managed IdP boundary;
2. trusted immutable tenant `ExecutionContext`;
3. top-level tenant-scoped PostgreSQL transaction with RLS;
4. stable `operation_key` creation/binding;
5. atomic tenant usage reservation;
6. persisted publication operation;
7. Temporal workflow start derived from `operation_key`;
8. typed provider dispatch result;
9. ambiguous result -> `UNKNOWN` -> reconciliation, never blind republish;
10. confirmed/safely-failed outcome -> usage commit/release;
11. observable/auditable state surfaced to API/UI.

## Important semantics

### External side effects

`ambiguous external outcome -> UNKNOWN -> reconciliation -> confirmed / pending / proved absent / still unknown`

`UNKNOWN` is not authorization to retry. A retry is allowed only after provider-specific proof of absence or a positively classified safe pre-mutation failure.

### Tenant isolation

Request headers or workflow payload tenant IDs are not authority by themselves. Tenant execution authority is reconstructed from authenticated server-side context. PostgreSQL RLS is enforced with production-like restricted roles.

### Usage/accounting

PostgreSQL owns canonical usage state. Expensive work reserves quota atomically before execution. One `operation_key` cannot consume/charge twice. Ledger history is append-only; corrections are compensating adjustments.

### Media

URLs/uploads are untrusted. Remote fetch requires destination validation and connection pinning, redirect revalidation, bounded streaming, signature/content checks, cancellation-safe promotion/cleanup, and isolated helper processes.

## Documentation precedence

For **current status**, use this file and `docs/README.md`.

For **validated architecture contracts**, use the copied source evidence under `docs/history/architecture-poc/`, especially:

- `docs/history/architecture-poc/docs/architecture/POST_POC_DECISIONS.md`
- `docs/history/architecture-poc/docs/architecture/RED_TEAM_AUDIT_V2.md`
- individual PoC/Red-Team `REPORT.md` files.

Historical files may say that Red-Team v2 or production-repository creation is still pending. Those statements describe the historical point at which the file was written; they do **not** override this current context.

## Next milestone

Complete and review the production foundation plus Vertical Slice 01, with CI enforcing Ruff, strict Pyright, pytest, database/RLS integration tests, and deterministic workflow/reconciliation tests.
