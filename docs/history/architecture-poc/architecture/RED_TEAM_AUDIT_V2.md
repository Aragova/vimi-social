# ViMi Social — Architecture Red-Team Audit v2

**Target:** Architecture Baseline 0.10 + validated PoC A–E amendments  
**Base commit:** `72251c888f450b581853dc824e38852bc54cc6e0`  
**Status:** FINAL PASS — EXECUTABLE GATES GREEN; FINAL INDEPENDENT REVIEW CLEAN  
**Purpose:** Attack the composition of the corrected Architecture 0.10 contracts before Architecture 1.0 is frozen.

The normative audit is preserved in ordered parts:

1. [Part 01 — charter, evidence model and attack matrix](red-team-audit-v2/part-01.md)
2. [Part 02 — Critical release-blocking findings](red-team-audit-v2/part-02.md)
3. [Part 03 — High/Medium composition findings and evidence gaps](red-team-audit-v2/part-03.md)
4. [Part 04 — remediation and executable verification plan](red-team-audit-v2/part-04.md)
5. [Part 05 — sixth–tenth-review normative hardening](red-team-audit-v2/part-05.md)
6. [Part 06 — eleventh-review external-handoff hardening](red-team-audit-v2/part-06.md)
7. [Part 07 — twelfth-review crash-safe transport handoff](red-team-audit-v2/part-07.md)
8. [Part 08 — thirteenth-review systemic external-effect closure](red-team-audit-v2/part-08.md)
9. [Part 09 — fourteenth-review non-bypassable handoff closure](red-team-audit-v2/part-09.md)
10. [Part 10 — fifteenth-review external-authority and anti-rollback closure](red-team-audit-v2/part-10.md)
11. [Part 11 — sixteenth-review authority-root anti-fork and anti-rollback closure](red-team-audit-v2/part-11.md)

Parts 05–11 are normative amendments to Part 04. Where a later part is stricter, the later part wins.

## Final verdict

**RED-TEAM V2 FINAL GATE: PASS. ARCHITECTURE 1.0 IS READY TO FREEZE AFTER PR #8 MERGE.**

PoC A–E pass. The Red-Team v2 composition suite has executable PASS evidence for AuthorityRoot and RTV2-X1..X8. The implementation findings discovered by the final review rounds were converted into deterministic regressions and remediated. The final independent re-review of the reconciled executable implementation found **no new P1/P2/Critical/High release blocker**, and all PR review threads are resolved against executable evidence.

PR #8 must still not be merged without explicit user approval.

## Review history and implementation closure

The specification underwent sixteen adversarial review rounds recorded in Parts 01–11. Implementation then underwent multiple final review/remediation rounds:

- first final implementation review: **5 P1**, remediated with deterministic regressions;
- second re-review on `c5d976d58dbb793e6982f50faf815830df244327`: **5 P1**, remediated systemically around process-shared transport authority and real DB-session-loss boundaries;
- exhaustive review on `42c1917116d52926abd22874f269544b3caab32d`: **6 P1 + 1 P2**, remediated as one external-authority / no-raw-bypass package;
- follow-up findings on authority identity immutability, authority-session loss, recovery high-watermarks, accepted-handoff preservation, X1 PITR reconstruction, X5 destructive admission, and X8 live-stop rollback durability were converted to executable regressions and closed;
- final exact-head re-review: **CLEAN — no new P1/P2/Critical/High blocker**.

## Current executable architecture

### External monotonic authority

Release-valid authority does not depend on rollbackable local SQLite witnesses. A dedicated external authority PostgreSQL domain owns or protects:

- authority-root epoch and hash-chain state;
- effect `ARMED` / terminal identity commitments;
- accepted transport evidence;
- transport-fence generations;
- immutable logical-operation -> transport-generation bindings;
- external usage obligations needed for X1 PITR reconstruction;
- durable live-stop commitments needed for X8 rollback safety.

The runtime role is least-privileged: authority identity and monotonic state cannot be rewritten backwards, terminal effect evidence cannot be silently revived, and authority loss fails closed before irreversible egress.

This separate database is an **architecture-laboratory model** of the required linearizable monotonic authority. It proves logical fault-domain separation and fail-closed behavior; it does **not** prove or select production physical quorum, replication, backup, consensus, or DR topology.

### Non-bypassable irreversible egress

- X5 rejects omitted/default and explicitly process-local `DispatchEpochFence()` construction; combined recovery is guarded identically.
- X5 provider mutation requires shared external transport authority.
- X5 object DELETE requires external transport authority after final DB validation; backend termination plus recovery winner yields zero DELETE calls.
- accepted X5 provider/DELETE handoffs remain unresolved obligations and cannot be cancelled as pre-I/O after transport acceptance.
- X5 combined recovery advances destructive authority above the surviving external high-watermark.
- X5 asset admission cannot cross an accepted DELETE for the same immutable object generation.
- base/legacy X7 raw DELETE fails closed; only the shared externally fenced service may delete.
- base/legacy X8 raw provider mutation and base live-stop mutation fail closed.
- X8 external transport binding is recoverable across bind-before-arm crashes.
- X8 live-stop publication freezes new bindings and survives business-database rollback both before and after transport binding.
- duplicate X8 workers cannot overwrite accepted/UNKNOWN outcomes with BLOCKED.
- fresh-process direct-submodule import is regression-tested so package installation cannot skip release guards.

These package guards prove the architecture-lab software boundary. Production Handoff-v2 still requires the Parts 09–11 external raw-route denial contracts for genuinely old/pre-protocol binaries and credentials.

### Usage / recovery boundary

X1 stores sufficient external usage metadata to reconcile rollbackable business state before quota admission or TTL expiry. Deterministic PITR regressions cover both a restored RESERVED row that lost effect binding and a completely missing reservation/capacity increment while the external effect authority survives. Quota remains closed until accounting is reconstructed.

### Session-loss boundary

X5, X7 and X8 include deterministic failure injection at the final database-validation -> raw-I/O gap. Real PostgreSQL backend termination is used where relevant. Recovery/live-stop wins through independent transport authority and stale workers perform zero raw mutation.

## Required executable evidence

RTV2-X1..X8 remain mandatory. The final evidence set includes:

- process restart and authority reconstruction;
- paired local authority and transport-store rollback/fork;
- competing authority allocators;
- external-authority outage / fail-closed behavior;
- direct-DML anti-rollback and authority-identity protection;
- omitted/default and explicit process-local X5 fence rejection;
- accepted X5 provider/DELETE handoff preservation during recovery;
- combined recovery/destructive-fence high-watermark handling;
- X1 PITR reconstruction before quota reopen/expiry;
- X5 object DELETE backend-loss/recovery ordering;
- X5 asset admission vs accepted DELETE;
- base X7/X8 legacy-route zero-mutation tests;
- X8 live-stop binding freeze and business-PG rollback durability;
- X8 duplicate-worker accepted/UNKNOWN preservation;
- X8 bind-before-arm crash recovery;
- direct-submodule import guard coverage;
- real PostgreSQL/Temporal composition where required;
- Ruff, strict Pyright and PoC A–E regressions on the exact executable evidence head.

## Final executable machine evidence

Executable evidence head immediately before this documentation-only reconciliation: `fc8ca29f3853e3066e781984c481e05765d95545`.

- Red-Team v2 Composition `39610263272`: **PASS**;
- Ruff: **PASS**;
- strict Pyright: **PASS**;
- Authority + RTV2-X1..X8: **PASS**;
- PoC A `39610263143`: **PASS**;
- PoC B `39610263085`: **PASS**;
- PoC C `39610263175`: **PASS**;
- PoC D `39610262686`: **PASS**;
- PoC E `39610262877`: **PASS**.

The reconciliation changes only report/audit status and evidence text. The resulting branch head must receive the same exact-head CI matrix once; that final docs-head evidence is recorded in PR #8 so the documentation does not require a self-referential follow-up commit.

## Final review disposition

The final independent re-review covered the current execution-critical authority/egress installation path, final X1/X5/X8 closure regressions, package/direct-import guards, review-thread dispositions and exact CI evidence. No new P1/P2/Critical/High blocker was found. All previously open review threads are resolved.

This closes the Red-Team v2 gate for the architecture PoC repository. It is not a claim that future production implementation can never reveal another defect; production work must preserve these invariants and continue testing them as real adapters/infrastructure replace the lab models.

## Merge policy

Do **not** merge PR #8 until:

- the documentation-only final head passes Red-Team Composition, Ruff, strict Pyright and PoC A–E;
- report/audit/PR claims match that final exact-head evidence;
- the user explicitly approves merge.

After those conditions are satisfied, PR #8 is ready to merge and Architecture 1.0 may freeze so implementation work can begin.
