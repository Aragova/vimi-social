# AGENTS.md

## Repository purpose

This is the **production ViMi Social repository**. It is not the disposable architecture PoC repository.

ViMi Social is a standalone multi-tenant SaaS for AI-assisted content ingest, preparation, scheduling, publication, reconciliation, analytics, usage metering, administration, and support across social platforms.

## Mandatory context before changing code

Read these files first:

1. `PROJECT_CONTEXT.md` — current project stage and active implementation goal.
2. `docs/README.md` — documentation map and canonical-source rules.
3. `docs/history/architecture-poc/docs/architecture/POST_POC_DECISIONS.md` — validated PoC contracts.
4. `docs/history/architecture-poc/docs/architecture/RED_TEAM_AUDIT_V2.md` — final composition audit summary.
5. Relevant historical PoC `REPORT.md` files when touching the corresponding boundary.

Historical material is preserved under `docs/history/architecture-poc/`. Historical status text is evidence/history, not the current project status.

## Non-negotiable architecture contracts

- PostgreSQL is the canonical correctness authority for transactional state and expensive tenant usage quota.
- Application database roles are non-owner, non-superuser, and `NOBYPASSRLS`; tenant isolation uses RLS as defense in depth.
- Caller-controlled tenant IDs are never trusted as execution authority. Background and API work must reconstruct a trusted immutable execution context.
- A stable `operation_key` identifies one logical external mutation/reservation and binds immutably to its target/binding data.
- Ambiguous external mutation outcomes become `UNKNOWN`; `UNKNOWN` is not retry authorization.
- Irreversible external side effects require reconciliation. No blind automatic retry after dispatch may have begun.
- Usage capacity is reserved atomically before expensive work. Commit/release/expiry are idempotent and accounting history is append-only with compensating adjustments.
- Remote media is untrusted input; destination validation, DNS/address pinning, bounded streaming, media/process isolation, and cancellation-safe cleanup are required.
- Provider/webhook tenant ownership is resolved server-side; payload tenant claims are not authority.
- Privileged support access must be narrow, reason-bound, and backed by non-rollbackable audit evidence before data leaves the trusted boundary.
- AI components must not receive unrestricted shell, database, credential, or secret access.
- ViMi Social must not runtime-import or share mutable operational state with the legacy Telegram production project.

## Engineering rules

- Prefer a modular monolith with clear module/process boundaries until measured need justifies services.
- Python is strictly typed where practical; Ruff, strict Pyright, and pytest are release gates.
- Important domain state uses explicit types, not unstructured dictionaries.
- Avoid broad `except Exception` as normal control flow.
- External APIs/adapters return typed domain outcomes rather than leaking transport semantics into orchestration.
- Tests for concurrency, retries, crash windows, tenant isolation, and UNKNOWN/reconciliation must be deterministic and must not be weakened to make CI green.
- Migrations and long-running workflow changes must preserve deployment/schema/workflow compatibility.
- No plaintext production secrets, credentials, tokens, or real user data in source, fixtures, logs, docs, or CI.

## Current implementation rule

The first production vertical slice is intentionally foundation-first:

`verified identity -> trusted tenant execution context -> RLS transaction -> atomic usage reservation -> persisted publication operation -> Temporal workflow -> typed provider outcome -> UNKNOWN-safe reconciliation -> commit/release usage`

Do not bypass one of these boundaries with a temporary production shortcut. If a dependency such as the managed IdP is not connected yet, fail closed behind an explicit interface/test double rather than trusting request headers.
