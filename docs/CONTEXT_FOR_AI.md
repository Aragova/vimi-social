# ViMi Social — Context for AI / new chat

If you are a new AI agent or chat session, read these first:

1. `docs/PRODUCT_VISION.md`
2. `AGENTS.md`
3. `docs/PROJECT_STATUS.md`

## What this project is

ViMi Social is a production **Telegram-first** multi-tenant SaaS for AI-assisted social-media content operations and publishing/orchestration. Architecture work was intentionally done first in a separate disposable repository (`Aragova/vimi-social-architecture-poc`). That phase is complete. This repository (`Aragova/vimi-social`) is where the real product is now being built.

The Telegram bot is the **primary customer interface**. It should provide onboarding, storefront/tariffs/subscription entry points, content intake, agent tasks, publication configuration, approvals, progress/status, history, usage and day-to-day control.

Web/Next.js is secondary: marketing landing, optional linked account/dashboard, browser-required integration flows, richer analytics/admin views where justified. Normal MVP use must not require leaving Telegram.

## Where we are

On 2026-10-21 architecture PR #8 was merged after exact-head Composition + PoC A–E CI passed. The architecture laboratory is closed as the active development target. Production repository foundation PR #1 is open and its latest CI has passed. We are at Telegram-first production foundation / vertical slice 1.

## Chosen production shape

- Modular-monolith monorepo initially.
- First-class Telegram bot interface/process.
- Python 3.12+ backend, FastAPI/application services.
- PostgreSQL, SQLAlchemy 2, psycopg 3, Alembic.
- Temporal for durable orchestration.
- Isolated media worker boundary.
- Next.js + TypeScript retained as a secondary web surface.
- Telegram identity is the first interaction identity for bot-originated customer flows; Telegram identifiers are resolved server-side into ViMi user/workspace/tenant authority.
- Managed IdP may still be used for web/admin experiences.
- S3-compatible object storage.
- GitHub Actions, Ruff, strict Pyright, pytest, OpenTelemetry.

## Architecture invariants already decided

1. Stable external `operation_key` is the logical identity for publication/workflow operations.
2. Irreversible external mutations are not blindly retried after ambiguity.
3. Ambiguous mutation outcomes become `UNKNOWN` and require reconciliation.
4. PostgreSQL is the correctness authority for tenant commercial usage.
5. Quota is reserved atomically before expensive work; ledger history is append-only.
6. Tenant DB context is transaction-local; application roles cannot bypass RLS.
7. Telegram/provider/webhook claims do not authorize arbitrary tenant selection; ownership is resolved server-side.
8. Remote media is hostile input and must pass SSRF/DNS pinning, redirect, streaming and isolation controls.
9. Privileged cross-tenant access requires durable/non-rollbackable audit evidence before results leave the trusted boundary.
10. Durable authority/fencing prevents stale actors and raw I/O paths from bypassing accepted delete/live-stop/recovery decisions.
11. Bot handlers are interface code, not the home of business/domain logic.

## Current task

Implement Telegram-native vertical slice 1:

```text
Telegram /start
-> trusted Telegram ingress
-> server-side Telegram identity/workspace resolution
-> onboarding/main menu
-> content upload
-> destination/options
-> tenant RLS transaction
-> atomic usage reservation
-> persisted publication operation
-> Temporal workflow start
-> provider dispatch
-> bot progress/status
-> UNKNOWN-safe reconciliation
-> final result in Telegram
```

The first VM/staging deployment should happen as soon as that path works end-to-end for one real destination. Do not wait for a complete web dashboard or every social platform.

## Product behavior expected from the bot

The bot should feel like the product itself, not a thin command console. Prefer guided flows, inline keyboards, previews and concise status cards. It should eventually cover:

- welcome/onboarding and product explanation;
- plan comparison, subscription/storefront entry points and usage;
- content upload directly in Telegram;
- agent-assisted content discovery/preparation tasks within authorization/provenance/policy boundaries;
- destination/account selection;
- scheduling and publication options;
- approval/preview;
- publication status and reconciliation;
- history, connected accounts and selected analytics;
- support/help entry points.

## Historical documentation map

- `docs/history/architecture-poc/README.md` and `ROADMAP.md`
- `docs/history/architecture-poc/product/PRODUCT_CONCEPT.md`
- `docs/history/architecture-poc/architecture/ARCHITECTURE_BASELINE_0_10.md` + split parts
- `docs/history/architecture-poc/architecture/POST_POC_DECISIONS.md`
- `docs/history/architecture-poc/architecture/RED_TEAM_AUDIT_V1.md` + split parts
- `docs/history/architecture-poc/architecture/RED_TEAM_AUDIT_V2.md` + split parts
- `docs/history/poc-a` through `poc-e`
- `docs/history/red-team-v2`

The copied documents are historical evidence. `docs/PRODUCT_VISION.md` is the live product/interface source of truth and `docs/PROJECT_STATUS.md` is the live phase/status document. Historical references to Next.js as the main customer frontend are superseded only on interface priority; validated architecture contracts remain in force.