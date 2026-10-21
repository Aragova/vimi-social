# ViMi Social — Context for AI / new chat

If you are a new AI agent or chat session, read this file first, then `AGENTS.md` and `docs/PROJECT_STATUS.md`.

## What this project is

ViMi Social is a production SaaS for multi-tenant social-media publishing/orchestration. Architecture work was intentionally done first in a separate disposable repository (`Aragova/vimi-social-architecture-poc`). That phase is complete. This repository (`Aragova/vimi-social`) is where the real product is now being built.

## Where we are

On 2026-10-21 architecture PR #8 was merged after exact-head Composition + PoC A–E CI passed. The architecture laboratory is closed as the active development target. We are at production foundation / vertical slice 1.

## Chosen production shape

- Modular-monolith monorepo initially.
- Python 3.12+ backend, FastAPI.
- PostgreSQL, SQLAlchemy 2, psycopg 3, Alembic.
- Temporal for durable orchestration.
- Next.js + TypeScript frontend.
- Managed IdP; tenant authority is server-derived, never trusted from a raw client tenant header.
- S3-compatible object storage.
- GitHub Actions, Ruff, strict Pyright, pytest, OpenTelemetry.

## Architecture invariants already decided

1. Stable external `operation_key` is the logical identity for publication/workflow operations.
2. Irreversible external mutations are not blindly retried after ambiguity.
3. Ambiguous mutation outcomes become `UNKNOWN` and require reconciliation.
4. PostgreSQL is the correctness authority for tenant commercial usage.
5. Quota is reserved atomically before expensive work; ledger history is append-only.
6. Tenant DB context is transaction-local; application roles cannot bypass RLS.
7. Webhook tenant claims are not authority; resolve ownership from server-side mappings.
8. Remote media is hostile input and must pass SSRF/DNS pinning, redirect, streaming and isolation controls.
9. Privileged cross-tenant access requires durable/non-rollbackable audit evidence before results leave the trusted boundary.
10. Durable authority/fencing prevents stale actors and raw I/O paths from bypassing accepted delete/live-stop/recovery decisions.

## Current task

Implement vertical slice 1:

`verified IdP context -> tenant RLS transaction -> atomic usage reservation -> persisted publication operation -> Temporal workflow start -> UNKNOWN-safe lifecycle/reconciliation`.

Do not spend another cycle re-proving the whole architecture. Consult historical docs when a contract's rationale is needed, then implement product behavior.

## Historical documentation map

- `docs/history/architecture-poc/README.md` and `ROADMAP.md`
- `docs/history/architecture-poc/product/PRODUCT_CONCEPT.md`
- `docs/history/architecture-poc/architecture/ARCHITECTURE_BASELINE_0_10.md` + split parts
- `docs/history/architecture-poc/architecture/POST_POC_DECISIONS.md`
- `docs/history/architecture-poc/architecture/RED_TEAM_AUDIT_V1.md` + split parts
- `docs/history/architecture-poc/architecture/RED_TEAM_AUDIT_V2.md` + split parts
- `docs/history/poc-a` through `poc-e`
- `docs/history/red-team-v2`

The copied documents are historical evidence. `docs/PROJECT_STATUS.md` is the live phase/status document.