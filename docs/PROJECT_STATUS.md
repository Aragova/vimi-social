# ViMi Social — Project Status

**Updated:** 2026-10-21
**Repository:** `Aragova/vimi-social`
**Phase:** Production implementation — foundation / vertical slice 1

## Completed

- Architecture Baseline 0.9 and 0.10 produced.
- Red-Team v1 completed.
- Executable PoCs A–E completed and passed:
  - A: Temporal durability, identity, workflow evolution and UNKNOWN handling.
  - B: PostgreSQL tenant isolation / RLS.
  - C: secure media ingest.
  - D: async platform lifecycle / reconciliation.
  - E: usage concurrency / reservations / ledger.
- Post-PoC decisions captured.
- Red-Team v2 composition audit completed, release-blocking findings remediated, final exact-head CI passed.
- PR #8 in `Aragova/vimi-social-architecture-poc` merged to `main` on 2026-10-21. Merge commit: `6252c6f4e425006f927f7b5e5556c96ecb37d245`.
- Production repository `Aragova/vimi-social` created.
- Historical architecture/PoC documentation copied into this repository so future AI sessions do not depend on the laboratory repository.

## Current goal

Build the first real production vertical slice, not another PoC:

`verified IdP context -> tenant RLS transaction -> atomic usage reservation -> persisted publication operation -> Temporal workflow start -> UNKNOWN-safe lifecycle/reconciliation`.

## Immediate implementation sequence

1. Production monorepo/tooling bootstrap and CI.
2. Verified IdP -> immutable `ExecutionContext` boundary. No caller-supplied tenant authority.
3. PostgreSQL schema, production-like roles, RLS and tenant transaction helper.
4. Usage capacity/reservation/ledger primitives with stable operation identity.
5. Publication aggregate/state machine persisted in PostgreSQL.
6. Temporal workflow keyed by stable `operation_key`.
7. Provider adapter contract with typed accepted/confirmed/unknown/safe-failure outcomes.
8. Reconciliation path; UNKNOWN must never blindly republish.
9. End-to-end tests covering duplicate starts, concurrency, tenant isolation and ambiguous provider outcomes.

## Definition of done for vertical slice 1

- A verified identity can create one tenant-scoped publication command.
- Reusing the same `operation_key` with different binding data fails closed.
- Concurrent duplicate starts do not double-reserve or double-dispatch.
- Cross-tenant reads/writes are blocked by both application context and RLS.
- Capacity is reserved before expensive/external work.
- Provider acceptance with lost response becomes UNKNOWN, not retry authorization.
- Reconciliation can move UNKNOWN forward only from typed provider evidence.
- Ruff, strict Pyright and pytest pass in CI.

## What not to do

- Do not restart architecture discovery as the default next step.
- Do not copy PoC implementation wholesale into production; port contracts and tests deliberately.
- Do not introduce temporary insecure tenant headers, blind retries, mutable billing history or unrestricted media/network access.

## Historical evidence

The complete copied architecture documentation lives under `docs/history/architecture-poc/`. PoC README/REPORT documents live under `docs/history/poc-*` and `docs/history/red-team-v2/`.