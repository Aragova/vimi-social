# Red-Team v2 composition report

**Status:** FINAL REVIEW CLEAN — EXECUTABLE GATES PASS

## Scope

This report tracks executable composition evidence for RTV2-X1..X8. Review-thread closure is not runtime proof; the final verdict below is based on the clean exact-head executable gate plus a final independent re-review of the reconciled implementation.

## Current executable gate status

- Authority / external-effect authority kernel: **PASS**.
- RTV2-X1 usage ownership / entitlement / settlement: **PASS**.
- RTV2-X2 PostgreSQL -> real Temporal outbox / immutable binding: **PASS**.
- RTV2-X3 rotating credential concurrency: **PASS**.
- RTV2-X4 generation-safe webhook routing: **PASS**.
- RTV2-X5 multi-system DR / provider and object DELETE fencing: **PASS**.
- RTV2-X6 durable publication state / callbacks: **PASS**.
- RTV2-X7 AssetLease / physical ownership / purge fencing: **PASS**.
- RTV2-X8 execution-time blocker matrix / provider handoff: **PASS**.

## Independent review history

The first final implementation review found **5 P1** gaps around process restart, authority/transport TOCTOU, X5 recovery fencing, X7 DELETE handoff, and X8 live-stop boundaries. They were converted to deterministic regressions and remediated.

The second re-review on `c5d976d58dbb793e6982f50faf815830df244327` found **5 P1** manifestations of one systemic issue: irreversible egress still depended in places on rollbackable/local/session authority. Those were remediated with durable shared transport authority and real PostgreSQL-session-loss injection.

The exhaustive review on `42c1917116d52926abd22874f269544b3caab32d` then found **6 P1 + 1 P2** around paired authority rollback/fork, transport-fence rollback/fork, process-local X5 fallbacks, X5/X7/X8 raw-egress bypasses, and X8 binding/arming recovery. Those findings were converted to executable regression coverage and remediated.

Subsequent final-review findings around authority identity immutability, authority-session loss, recovery high-watermarks, accepted-handoff preservation, X1 PITR usage reconstruction, X5 asset/delete admission, and X8 live-stop durability were also converted into deterministic regressions. All review threads are resolved against current executable evidence.

The final independent re-review of the reconciled executable head found **no new P1/P2/Critical/High release blocker**.

## Final systemic remediation

### External monotonic authority

Authority epoch/root history, effect identity, accepted transport evidence, transport generations, immutable attempt bindings, usage obligations, and live-stop commitments are protected by the dedicated external authority PostgreSQL domain rather than rollbackable application state. Runtime DML is restricted so authority identities and monotonic state cannot be rewritten backwards.

The architecture-lab external database models the required linearizable monotonic authority and fail-closed protocol behavior. It does **not** select a production physical quorum, backup, replication, consensus, or disaster-recovery topology.

### X1 usage recovery

External usage obligations are retained independently of rollbackable business rows. Before quota can reopen or stale reservations expire, restored/missing X1 reservations are reconciled from external effect authority and capacity accounting is reconstructed fail-closed. PITR regressions cover both a rewound RESERVED row and a completely missing reservation.

### X5 / X7 destructive recovery

Release-valid X5 construction requires externally shared transport authority. Accepted provider and DELETE handoffs cannot be reclassified as pre-I/O merely because business state is restored or recovery begins. Combined recovery advances destructive authority above the surviving external high-watermark; X5 asset admission cannot cross an accepted DELETE.

Base/legacy X7 raw DELETE remains fail-closed; only the externally fenced shared path may cross destructive egress. PostgreSQL-session-loss regressions prove recovery-first yields zero physical DELETE calls.

### X8 live-stop and provider handoff

Base X8 provider egress and base live-stop mutation are fail-closed. Live-stop publication freezes new transport bindings, persists an external commitment outside business-PG rollback, and remains authoritative both before and after transport binding. Duplicate workers cannot overwrite accepted/UNKNOWN provider outcomes with BLOCKED. Backend/session-loss and rollback regressions require zero provider mutation when the blocker wins.

### Package / CI integrity

Release guards install through normal package import semantics, including direct-submodule import coverage. The final Red-Team workflow runs one clean composition suite on a fresh Temporal server; diagnostic reruns that could pollute state are not part of the release gate.

## Exact machine evidence

Final executable evidence head before this documentation-only reconciliation: `fc8ca29f3853e3066e781984c481e05765d95545`.

- Red-Team v2 Composition run `39610263272`: **PASS**.
- Ruff: **PASS**.
- strict Pyright: **PASS**.
- `Authority + X1-X8 composition regressions`: **PASS**.
- PoC A `39610263143`: **PASS**.
- PoC B `39610263085`: **PASS**.
- PoC C `39610263175`: **PASS**.
- PoC D `39610262686`: **PASS**.
- PoC E `39610262877`: **PASS**.

This report/audit reconciliation changes documentation only. The resulting branch head must itself receive the same exact-head CI matrix; that final docs-head evidence is recorded in PR #8 without another self-referential documentation commit.

## Final review result

The final exact-head review rechecked the execution-critical authority/egress install order, the final X1/X5/X8 closure regressions, package/direct-import guards, review-thread dispositions, and the exact machine evidence above. No new P1/P2/Critical/High release blocker was found, and all previously open review threads are resolved against executable coverage.

Any future architecture or production implementation may of course uncover new issues; that does not invalidate the bounded Red-Team v2 acceptance criterion for this PoC repository.

## Verdict

```text
PoC A-E: PASS
Authority kernel: PASS
RTV2-X1: PASS
RTV2-X2: PASS
RTV2-X3: PASS
RTV2-X4: PASS
RTV2-X5: PASS
RTV2-X6: PASS
RTV2-X7: PASS
RTV2-X8: PASS
Executable Red-Team v2 composition: PASS
First final implementation review: 5 P1 -> REMEDIATED
Second final re-review: 5 P1 -> REMEDIATED
Third exhaustive review: 6 P1 + 1 P2 -> REMEDIATED
Follow-up final review: CLEAN
Red-Team v2 final gate: PASS
Architecture 1.0: READY TO FREEZE
PR #8 merge: REQUIRES USER APPROVAL
```
