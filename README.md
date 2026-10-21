# ViMi Social

Production repository for ViMi Social SaaS.

## Current stage

Architecture research and executable PoCs A–E are complete. Red-Team v2 composition review is complete and PR #8 from `Aragova/vimi-social-architecture-poc` was merged into its `main` at merge commit `6252c6f4e425006f927f7b5e5556c96ecb37d245` on 2026-10-21.

This repository is now the canonical **production implementation** repository. The architecture PoC repository is historical evidence only.

Start here:

1. `AGENTS.md` — mandatory rules for AI/coding agents.
2. `docs/PROJECT_STATUS.md` — exact current implementation stage and next slice.
3. `docs/CONTEXT_FOR_AI.md` — compact context for a new AI/chat session.
4. `docs/history/architecture-poc/` — complete documentation copied from the architecture laboratory.
5. `docs/history/poc-a` … `poc-e` and `red-team-v2` — PoC/readout documentation.

## Production direction

Modular-monolith monorepo with Python/FastAPI, PostgreSQL + RLS, SQLAlchemy/psycopg/Alembic, Temporal, Next.js/TypeScript, managed IdP, S3-compatible object storage, GitHub Actions and OpenTelemetry.

The first production vertical slice is:

`verified IdP context -> tenant RLS transaction -> atomic usage reservation -> persisted publication operation -> Temporal workflow start -> UNKNOWN-safe lifecycle/reconciliation`.

Do not re-open architecture research unless production evidence demonstrates a concrete defect in an Architecture 1.0 contract.