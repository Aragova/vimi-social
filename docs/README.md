# ViMi Social documentation

## Current truth

Start with:

1. [`../PROJECT_CONTEXT.md`](../PROJECT_CONTEXT.md) — current project stage, stack, active vertical slice, and precedence rules.
2. [`../AGENTS.md`](../AGENTS.md) — mandatory engineering/architecture rules for humans and AI coding agents.
3. This index.

**Current stage:** production implementation has started. Architecture PoCs A–E and Red-Team v2 are complete and the architecture PR was merged. The old architecture repository is now historical executable evidence, not the active codebase.

## Historical architecture evidence

The complete documentation set from `Aragova/vimi-social-architecture-poc` is preserved under:

[`history/architecture-poc/`](history/architecture-poc/)

It is intentionally copied as historical source material so future engineers, coding agents, and chat sessions can reconstruct why the production contracts exist.

Important starting points inside the history:

- `history/architecture-poc/docs/product/PRODUCT_CONCEPT.md`
- `history/architecture-poc/docs/architecture/ARCHITECTURE_BASELINE_0_10.md`
- `history/architecture-poc/docs/architecture/POST_POC_DECISIONS.md`
- `history/architecture-poc/docs/architecture/RED_TEAM_AUDIT_V1.md`
- `history/architecture-poc/docs/architecture/RED_TEAM_AUDIT_V2.md`
- `history/architecture-poc/poc_a_temporal/REPORT.md`
- `history/architecture-poc/poc_b_tenant_isolation/REPORT.md`
- `history/architecture-poc/poc_c_secure_media_ingest/REPORT.md`
- `history/architecture-poc/poc_d_async_platform_lifecycle/REPORT.md`
- `history/architecture-poc/poc_e_usage_concurrency/REPORT.md`
- `history/architecture-poc/red_team_v2_composition/REPORT.md`

## Precedence rule

Historical documents are preserved faithfully and may contain status statements that were correct when they were written, such as “Red-Team v2 in progress” or “production repository not created yet”. Those are historical statements.

For current status, always prefer:

1. `PROJECT_CONTEXT.md`;
2. current production code/tests/CI;
3. this documentation index;
4. historical architecture evidence for design rationale and invariants.

When changing an architecture invariant, do not silently contradict validated historical evidence. Add an ADR/current decision explaining why the production contract changed and add executable tests for the new contract.
