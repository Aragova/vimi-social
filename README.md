# ViMi Social

Production repository for ViMi Social.

## Product direction

ViMi Social is a **Telegram-first AI-assisted content operating system**. The Telegram bot is the primary customer interface and should act as the storefront, onboarding flow, control panel, content inbox, agent-task UI, subscription surface, publication status center, and everyday workspace.

Web/Next.js is secondary. It may be used for marketing/landing pages, optional linked account/dashboard views, richer analytics/admin interfaces, and browser-required integrations, but normal MVP use must not require leaving Telegram.

Read `docs/PRODUCT_VISION.md` first for the canonical current product/UI direction.

## Current stage

Architecture research and executable PoCs A–E are complete. Red-Team v2 composition review is complete and PR #8 from `Aragova/vimi-social-architecture-poc` was merged into its `main` at merge commit `6252c6f4e425006f927f7b5e5556c96ecb37d245` on 2026-10-21.

This repository is now the canonical **production implementation** repository. The architecture PoC repository is historical evidence only.

Start here:

1. `docs/PRODUCT_VISION.md` — canonical product/interface direction.
2. `AGENTS.md` — mandatory rules for AI/coding agents.
3. `docs/PROJECT_STATUS.md` — exact current implementation stage and next slice.
4. `docs/CONTEXT_FOR_AI.md` — compact context for a new AI/chat session.
5. `docs/history/architecture-poc/` — complete documentation copied from the architecture laboratory.
6. `docs/history/poc-a` … `poc-e` and `red-team-v2` — PoC/readout documentation.

## Production shape

Modular-monolith monorepo with Python/FastAPI, PostgreSQL + RLS, SQLAlchemy/psycopg/Alembic, Temporal, a first-class Telegram bot process/interface, isolated media workers, S3-compatible object storage, GitHub Actions and OpenTelemetry. Next.js remains available as a secondary web surface.

The first real production vertical slice is Telegram-native:

`Telegram /start -> server-side Telegram identity/workspace resolution -> onboarding/menu -> content upload -> destination/options -> tenant RLS transaction -> atomic usage reservation -> persisted publication operation -> Temporal workflow -> provider dispatch -> bot status updates -> UNKNOWN-safe reconciliation`.

The first VM/staging deployment should happen as soon as this path works for one real destination. Do not delay it for a complete web dashboard or every social platform.

Do not re-open architecture research unless production evidence demonstrates a concrete defect in an Architecture 1.0 contract.