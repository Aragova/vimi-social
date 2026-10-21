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

Architecture research and executable PoCs A–E are complete. Red-Team v2 composition review is complete and architecture PR #8 was merged at `6252c6f4e425006f927f7b5e5556c96ecb37d245` on 2026-10-21.

Production foundation PR #1 exists and its latest verified CI passed, but it predates the fully clarified product concept. It is being aligned/hardened rather than discarded.

Start here:

1. `docs/PRODUCT_VISION.md` — canonical product/source/automation/internationalization concept.
2. `docs/PROJECT_STATUS.md` — live implementation stage and next work.
3. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md` — KEEP / CHANGE / DEFER review of PR #1.
4. `AGENTS.md` — mandatory rules for AI/coding agents.
5. `docs/CONTEXT_FOR_AI.md` — compact handoff for a new AI/chat session.
6. `docs/history/` — validated architecture/PoC evidence.

## Production shape

Initial modular monolith with:

- first-class Telegram bot process/interface;
- Python/FastAPI application services;
- PostgreSQL + RLS, SQLAlchemy/psycopg/Alembic;
- Temporal durable workflows;
- isolated media workers;
- typed Source Connector Registry;
- independent destination/provider adapters;
- S3-compatible object storage;
- GitHub Actions, Ruff, strict Pyright, pytest and OpenTelemetry;
- Next.js as a secondary web surface.

## First real product slice

```text
Telegram /start
-> server-side Telegram identity/workspace resolution
-> localized menu
-> AI Search task
-> one real authorized source connector
-> candidate normalization/curation
-> media + scene analysis
-> adult classification + destination policy preflight
-> one usable compliant variant
-> Telegram preview/approval
-> usage reservation + persisted operation
-> Temporal
-> one real destination adapter
-> publication/status/reconciliation
```

Deploy to staging/VM as soon as this works end-to-end. Manual Upload and Telegram Source Feed follow early through the same downstream pipeline.

Do not reopen broad architecture research unless production evidence demonstrates a concrete defect in an Architecture 1.0 contract.