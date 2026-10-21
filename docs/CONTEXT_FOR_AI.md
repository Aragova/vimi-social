# ViMi Social — Context for AI / new chat

If you are a new AI agent or chat session, read these first:

1. `docs/PRODUCT_VISION.md`
2. `AGENTS.md`
3. `docs/PROJECT_STATUS.md`

## What this project is

ViMi Social is a production **Telegram-first, AI-first** multi-tenant SaaS for automated social-media content discovery, preparation, adaptation and publishing/orchestration.

The Telegram bot is the **primary customer interface**. It provides onboarding, storefront/tariffs/subscription entry points, AI task intake, candidate previews, approvals, publication configuration, status/history, usage and day-to-day control.

The primary content source is **AI-assisted discovery/automation**. The normal user journey begins with an intent/task, not a finished upload. Manual content upload remains a secondary path and must reuse the same downstream analysis/adaptation/publication pipeline.

Adult/18+ content is an expected and frequent workload. The system must therefore treat explicitness classification, platform eligibility and compliant variant generation as first-class product behavior.

Web/Next.js is secondary: marketing landing, optional linked account/dashboard, browser-required integration flows, richer analytics/admin views where justified. Normal MVP use must not require leaving Telegram.

## Where we are

On 2026-10-21 architecture PR #8 was merged after exact-head Composition + PoC A–E CI passed. The architecture laboratory is closed as the active development target. Production repository foundation PR #1 is open and its latest CI has passed. We are at Telegram-first, AI-first production foundation / vertical slice 1.

## Chosen production shape

- Modular-monolith monorepo initially.
- First-class Telegram bot interface/process.
- Python 3.12+ backend, FastAPI/application services.
- PostgreSQL, SQLAlchemy 2, psycopg 3, Alembic.
- Temporal for durable orchestration.
- Isolated media worker boundary.
- Specialized AI components (`Scout`, `Curator`, `SceneRanker`, `VariantPlanner`, `CaptionGenerator`, `AnalyticsInsight`) behind controlled typed tools.
- Platform capability/compliance preflight before publication.
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
12. AI agents do not receive unrestricted shell/database/secrets/network authority; they act through typed application tools and budgets.
13. Adult-content adaptation is compliance transformation, not moderation evasion. If a destination cannot accept either the original or a genuinely compliant derivative, block it.

## Current task

Implement Telegram-native, AI-first vertical slice 1:

```text
Telegram /start
-> trusted Telegram ingress
-> server-side Telegram identity/workspace resolution
-> onboarding/main menu
-> user describes desired content/task
-> Scout discovers candidates from an authorized source
-> Curator ranks/filters candidates
-> MediaProbe + SceneDetector + SceneRanker
-> adult/content classification + platform compliance preflight
-> VariantPlanner proposes a direct or compliant adapted variant
-> Telegram preview/approval
-> tenant RLS transaction
-> atomic usage reservation
-> persisted operation
-> Temporal workflow start
-> provider dispatch
-> bot progress/status
-> UNKNOWN-safe reconciliation
-> final result in Telegram
```

Manual upload is secondary and reuses the pipeline starting at provenance/media analysis.

The first VM/staging deployment should happen as soon as that AI-first path works end-to-end for one authorized source and one real destination. Do not wait for a complete web dashboard or every social platform.

## Product behavior expected from the bot

The bot should feel like the product itself, not a thin command console. Prefer guided flows, inline keyboards, previews and concise status cards. It should eventually cover:

- welcome/onboarding and product explanation;
- plan comparison, subscription/storefront entry points and usage;
- AI task creation as the main content input;
- candidate discovery and ranked previews;
- scene selection/clipping and platform-specific adaptation;
- adult/explicitness classification and per-destination eligibility;
- direct publication where allowed;
- compliant derivative generation where the original is not allowed but an allowed version can be produced;
- destination blocking with clear reason when no compliant version is possible;
- optional manual upload;
- destination/account selection and recommendations;
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

The copied documents are historical evidence. `docs/PRODUCT_VISION.md` is the live product/UI/automation source of truth and `docs/PROJECT_STATUS.md` is the live phase/status document. Historical references to Next.js or manual upload as the dominant customer path are superseded on product priority; validated architecture contracts remain in force.