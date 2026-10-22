# ViMi Social

Production repository for ViMi Social.

## Product direction

ViMi Social is a **Telegram-first, AI-first, automation-first content operating system**.

The Telegram bot is the primary customer interface. Web/Next.js is secondary and may serve landing/marketing, OAuth callbacks, optional dashboards, analytics and administration.

The product has three fundamental source modes:

1. **AI Search** — user describes the task; Scout finds candidates through source-specific connectors.
2. **Manual Upload** — user supplies/forwards content; it enters the same downstream pipeline.
3. **Source Feed** — an authorized Telegram channel/group/topic becomes a persistent queue consumed according to automation policy.

Legal adult/18+ content, including explicit gay adult material, is an expected frequent workload. Destination policy checks and genuinely compliant variant generation are first-class behavior.

The product is international-ready from the beginning: UTC persisted timestamps, IANA timezones for schedules, RU/EN localization architecture, separate UI/content/search languages, region awareness and currency-aware money.

Read `docs/PRODUCT_VISION.md` first for the canonical product concept.

## Current stage

The first real source-to-destination path is implemented through merged PR #7:

```text
Telegram
-> AI Search / Scout
-> official X source connector
-> rights-gated secure media preparation
-> MediaProbe
-> scene analysis + sampled-frame visual moderation
-> destination preflight + VariantPlanner
-> RenderService
-> Telegram preview / explicit approval
-> X v2 media upload + post creation
-> UNKNOWN-safe reconciliation
```

Current `main` after PR #7: `a5d693ab8ec38d14995f25b6cfe1f66c185d626f`.

The active work is **PR #8 — single-VM staging deployment**. The goal is to deploy the existing path to a real VM and exercise it before broad feature expansion.

Start here:

1. `docs/PRODUCT_VISION.md` — canonical product/source/automation/internationalization concept.
2. `docs/PROJECT_STATUS.md` — live implementation stage and next work.
3. `docs/STAGING_VM_RUNBOOK.md` — exact current staging deployment and smoke-test procedure.
4. `AGENTS.md` — mandatory rules for AI/coding agents.
5. `docs/CONTEXT_FOR_AI.md` — compact handoff for a new AI/chat session.
6. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md` — historical foundation alignment decision.
7. `docs/history/` — validated architecture/PoC evidence.

## Production shape

Initial modular monolith with:

- first-class Telegram bot process/interface;
- Python/FastAPI application services;
- PostgreSQL + RLS, SQLAlchemy/psycopg/Alembic;
- Temporal durable workflows;
- isolated media workers;
- typed Source Connector Registry;
- independent destination/provider adapters;
- S3-compatible object storage target for horizontal scale;
- GitHub Actions, Ruff, strict Pyright, pytest and OpenTelemetry;
- Next.js as a secondary web surface.

## Current staging shape

PR #8 builds a deliberate single-VM staging topology:

- Caddy HTTPS ingress;
- Telegram bot;
- core Temporal worker;
- media worker with ffmpeg/ffprobe;
- destination worker;
- internal API;
- PostgreSQL 17;
- Temporal;
- persistent local media/database volumes.

PostgreSQL and Temporal are not published to the public network. Application processes that need Telegram/X/OpenAI receive outbound egress separately from the internal service network.

The staging topology is intentionally not the final horizontally scaled production topology.

## First real staging milestone

The staging milestone is complete only after the real path is manually exercised:

```text
Telegram /start
-> AI Search
-> X candidate
-> rights confirmation
-> media acquisition / analysis / render
-> Telegram preview
-> explicit publish approval
-> one real X post
-> final status / reconciliation
```

Then run controlled worker-restart and ambiguous-publication drills and prove that no duplicate X post is created.

Do not reopen broad architecture research unless production evidence demonstrates a concrete defect in an Architecture 1.0 contract.
