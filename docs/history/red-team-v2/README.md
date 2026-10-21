# Red-Team v2 executable composition suite

This directory is the executable composition gate for the Red-Team v2 audit. It is **not** PoC F and it is not production code.

## Hypothesis

Architecture 0.10 plus the PoC A–E amendments can be composed without allowing stale authority, rollback/fork, replay, quota release, ownership change, database-session loss, or destructive lifecycle races to create an untracked irreversible external effect.

## PASS / FAIL

Executable PASS requires deterministic evidence for RTV2-X1..X8, real PostgreSQL/Temporal where the gate requires them, externally fenced irreversible egress, fail-closed authority loss, Ruff, strict Pyright, and PoC A–E regression PASS on the exact evidence head.

Any ordering that permits duplicate/unaccounted external effect, stale authority reuse, rollback/fork resurrection, free billable work, stale provider acceptance, or deletion after a recovery/blocker winner is FAIL.

## Current status

**All executable RTV2-X1..X8 gates are PASS. Red-Team v2 is still not final PASS because one clean independent re-review of the reconciled exact head remains mandatory.**

The latest exhaustive review of head `42c1917116d52926abd22874f269544b3caab32d` found **6 P1 + 1 P2**. The remediation now provides:

- a dedicated external monotonic authority database for root epoch/history, effect identity, transport acceptance, transport fence generations, and immutable bindings;
- paired local-rollback/fork resistance and fail-closed external-authority outage tests;
- database-side monotonic guards and least-privilege runtime DML;
- rejection of omitted/default **and explicitly process-local** X5 fences, including combined recovery;
- X5 object DELETE fenced after final DB validation, including real backend termination before raw I/O;
- fail-closed base/legacy X7 DELETE and X8 provider routes with zero-mutation regressions;
- X8 immutable transport binding before local `HANDOFF_ARMED`, with crash recovery in the bind-to-arm gap;
- real `pg_terminate_backend()` regressions proving recovery/live-stop winners prevent X7/X8 raw mutation.

The separate PostgreSQL authority database is an architecture-lab model of a linearizable monotonic control plane. It proves logical separation and fail-closed behavior; it does **not** prove a production physical quorum, replication, backup, consensus, or DR topology.

## Current machine evidence

Executable remediation head `46782adafdf9abe15ae8904225c3e19e35dd7ed2`:

- Red-Team v2 Composition `39583055833`: **PASS**;
- Ruff: **PASS**;
- strict Pyright: **PASS**;
- full Authority + RTV2-X1..X8 regressions: **PASS**;
- PoC A `39583055563`: **PASS**;
- PoC B `39583055504`: **PASS**;
- PoC C `39583055523`: **PASS**;
- PoC D `39583055633`: **PASS**;
- PoC E `39583055655`: **PASS**.

The documentation-reconciliation head must pass the same exact-head CI before the final independent review is treated as release evidence.

## Remaining gate action

Run one fresh exhaustive independent re-review of the reconciled exact head, explicitly attacking authority rollback/fork/partition/direct-DML, package-init or mixed-version legacy bypass, X5 local-fence fallback, X5 DELETE session loss, X7/X8 raw/fallback routes, X8 bind-before-arm, UNKNOWN/PITR/hidden-retry classes, and every X1..X8 report claim.

Only a clean re-review plus final evidence reconciliation may change Red-Team v2 to final PASS and allow Architecture 1.0 freeze.

**PR #8 must not be merged without explicit user approval. Production repository creation remains prohibited before Architecture 1.0 freeze.**
