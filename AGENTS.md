# AGENTS.md — ViMi Social production repository

## Purpose

This is the production ViMi Social SaaS repository. It is not an architecture laboratory. New work must deliver product capability while preserving the validated Architecture 1.0 contracts.

## Mandatory reading order

Before changing code, read:

1. `docs/PRODUCT_VISION.md`
2. `docs/PROJECT_STATUS.md`
3. `docs/CONTEXT_FOR_AI.md`
4. `docs/history/architecture-poc/architecture/POST_POC_DECISIONS.md`
5. `docs/history/architecture-poc/architecture/RED_TEAM_AUDIT_V2.md`
6. Relevant detailed baseline/audit parts under `docs/history/architecture-poc/architecture/`

## Product interface contract

- ViMi Social is **Telegram-first**.
- The Telegram bot is the primary customer product surface: onboarding, storefront, tariffs/subscriptions, content intake, agent tasks, publication setup, approvals, status, history, usage and day-to-day control.
- A user must not be forced into a web dashboard for the normal MVP workflow.
- Web/Next.js is secondary: marketing landing, optional linked account/dashboard, richer analytics/admin views, and browser-required integration flows.
- Bot handlers are an interface layer only. Business rules belong in application/domain services and durable workflows.
- Telegram identity/update data must be resolved server-side into ViMi user/workspace/tenant authority. Never accept an arbitrary tenant ID from the client.
- Historical documents describing Next.js as the main customer frontend are superseded only on interface priority by `docs/PRODUCT_VISION.md`; their validated security/reliability contracts remain in force.

## Non-negotiable architecture contracts

- Never trust caller-controlled tenant IDs. Tenant/execution context must come from verified server-side identity or immutable trusted envelopes.
- PostgreSQL RLS is a defense-in-depth tenant boundary; application roles are non-owner, non-superuser and NOBYPASSRLS.
- External side effects use stable `operation_key` identity and explicit idempotency/unknown-outcome handling.
- Ambiguous provider outcomes become `UNKNOWN`; UNKNOWN never authorizes blind retry. Reconcile first.
- Expensive tenant work reserves quota atomically before execution. PostgreSQL is the commercial-usage correctness authority.
- Usage ledger is append-only; corrections/refunds are compensating adjustments.
- Webhook tenant claims are untrusted; resolve ownership server-side.
- Remote media is untrusted; preserve SSRF/DNS pinning, redirect revalidation, bounded streaming and isolated processing contracts.
- Privileged support access requires non-rollbackable external audit evidence before data leaves the trusted boundary.
- Raw external I/O must not bypass the durable authority/fencing contracts validated by Red-Team v2.
- No plaintext secrets or production credentials in source, fixtures, logs or docs.

## Engineering workflow

- Work in small vertical slices that end in executable behavior and tests.
- Prefer deterministic tests and explicit failure injection for durability/concurrency behavior.
- Ruff and strict Pyright must remain green for Python production code.
- Do not weaken a test to make CI pass.
- Do not add test-only runtime paths, PYTHONPATH hacks, or security bypasses.
- Keep domain types explicit; avoid unstructured dictionaries for important state.
- Avoid broad `except Exception` as normal control flow.
- Every irreversible external mutation must define retry, idempotency and reconciliation semantics before implementation.

## Source of truth

`docs/PRODUCT_VISION.md` is the product/interface source of truth. `docs/PROJECT_STATUS.md` is the current-stage source of truth. Historical PoC documents explain why contracts exist but do not mean the production project is still in PoC phase.