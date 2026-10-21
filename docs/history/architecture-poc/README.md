# ViMi Social architecture PoC archive

This directory preserves the documentation/evidence set from the former architecture laboratory repository:

- source repository: `Aragova/vimi-social-architecture-poc`
- source architecture PR: `#8`
- PR #8 was merged after explicit user approval
- architecture merge commit: `6252c6f4e425006f927f7b5e5556c96ecb37d245`
- final PR exact-head before merge: `39957c18c64359a22b99d353127963b57929c562`

## Why this archive exists

The production repository must retain the reasoning and executable evidence behind Architecture 1.0 so a future engineer, coding agent, or chat session can understand not only the intended design but also the failure modes that were actually tested and remediated.

The archive preserves:

- the source repository root `README.md` and `AGENTS.md` under `root/`;
- the complete historical `docs/` documentation tree;
- `README.md` and `REPORT.md` evidence from PoC A–E;
- `README.md` and `REPORT.md` from the Red-Team v2 composition suite.

PoC source code and CI implementation are intentionally not duplicated here as production code. They remain available in the source architecture repository. The documents and reports copied here are the design/evidence record production implementation must preserve.

## Important status rule

Files below this directory are historical snapshots. Some of them correctly say, for their point in time, things such as:

- `Red-Team v2 IN PROGRESS`;
- `Architecture 1.0 BLOCKED`;
- `production repository intentionally not created yet`;
- `PR #8 requires user approval`.

Those statements must **not** be interpreted as the present project state.

For current status always read, in order:

1. `/PROJECT_CONTEXT.md`
2. `/AGENTS.md`
3. `/docs/README.md`
4. current production code/tests/CI

The current production truth is that Red-Team v2 passed, PR #8 was merged, the production repository exists, and production implementation has started.

## Architecture precedence for implementation rationale

When production code touches a validated boundary, start with:

- `docs/architecture/POST_POC_DECISIONS.md`
- `docs/architecture/RED_TEAM_AUDIT_V2.md`
- the relevant Red-Team v2 part(s)
- the relevant PoC/Composition `REPORT.md`

If production intentionally changes a validated architecture invariant, document the new decision in the current production docs/ADR and add executable evidence. Do not silently weaken the historical contract.
