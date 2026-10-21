# Red-Team v2 — Part 09: fourteenth-review non-bypassable handoff closure

**Status:** NORMATIVE ADDENDUM — SYSTEMIC RESPONSE TO FOURTEENTH INDEPENDENT REVIEW — EXECUTION PENDING

This part is a normative amendment to Parts 04–08. Where Part 09 is stricter, **Part 09 wins**. It addresses all six findings returned together by the fourteenth independent Codex review of `bfe7e69...` (5 P1 + 1 P2) and hardens the whole handoff protocol rather than patching only the exact examples.

It strengthens executable closure requirements for **RT2-01, RT2-05, RT2-08, RT2-12, RT2-14, and RT2-16**, while preserving the Part-08 External Effect Handoff Protocol.

---

## 1. Root architectural correction: workers never own raw external egress

Part 08 allowed the handoff controller to be implemented with a database row/advisory lock. Round 14 correctly exposed a fatal ownership-loss variant: the database session may disappear, the server releases the lock, but the application worker can remain alive long enough to continue from its stale local decision and call the transport.

Architecture 1.0 therefore adopts a stronger invariant:

> **A workflow/activity/worker is not allowed to possess a bypass path to an irreversible external transport.**

Every covered provider mutation, destructive object-store operation, and billable external request must pass through a **non-bypassable Egress Handoff Gateway** (name non-normative) that owns the final transport capability.

The worker may prepare an immutable attempt and request handoff, but only the gateway/controller may perform actual enqueue/send. Production provider credentials, object-store destructive capability, proxy route, or equivalent transport authority used for these effects must be scoped so ordinary workers cannot invoke the irreversible path directly.

The gateway accepts a handoff only with a current **monotonic fencing token** for the immutable attempt. At minimum the token binds:

```text
attempt_id
logical effect identity
handoff_generation / fence
recovery_epoch
applicable policy/account/object generations
protocol_version
```

A stale owner that loses its lock/session/lease cannot send merely because it still has a Python object containing an earlier `allowed=True` result. Its stale fencing token is rejected by the gateway before transport acceptance.

If the selected infrastructure cannot enforce fencing at the transport-owning gateway, then the implementation must keep the conflicting transition unresolved until the transport primitive returns and must prove that no other component can enqueue outside that primitive. A process-local assertion is insufficient.

### Mandatory ownership-loss failure injection

RTV2-X5/X8 must deterministically exercise:

1. `HANDOFF_ARMED` exists;
2. worker/controller obtains handoff ownership and passes final validation;
3. pause after validation but before enqueue;
4. forcibly drop the backing DB/control-plane session or lease while leaving the worker process alive;
5. recovery/cancellation/blocker obtains the newly available serialization order and advances the fence;
6. stale worker resumes using its old local decision/token;
7. gateway rejects the stale token and records **zero external transport accepts**.

Also exercise the converse ordering where gateway acceptance with the current token wins before ownership loss; that request remains an ambiguous reconciliation obligation rather than being falsely cancelled.

---

## 2. Destructive object generation has one admission domain for DELETE, leases and references

Round 14 exposed that recovery-time reference reconstruction was serialized with DELETE, but **normal live** `AssetLease` acquisition/reference adoption could still race after the delete worker's final no-reference/no-lease validation and before DELETE transport acceptance.

Architecture 1.0 therefore defines one authoritative **ObjectGenerationAdmission** domain per immutable `object_generation`.

The following operations must contend in that same domain:

- acquire/renew an `AssetLease`;
- create/adopt/rebind a live `Asset` reference to that exact immutable generation;
- mark an object generation delete-eligible;
- create/arm a destructive delete attempt;
- final DELETE handoff acceptance;
- recovery-time reference reconstruction;
- terminal deletion/tombstone completion.

Conceptual object-generation state:

```text
LIVE(generation=f)
  -> DELETE_INTENT(f+1)
  -> DELETE_HANDOFF_ARMED(f+1)
  -> DELETE_ACCEPTED_UNKNOWN(f+1)
  -> DELETED(f+1)

or, before transport acceptance only:

DELETE_INTENT / DELETE_HANDOFF_ARMED
  -> DELETE_REVOKED(f+1)
  -> LIVE(generation=f+2)
```

Rules:

1. lease/reference acquisition carries the expected object admission generation/fence;
2. once destructive handoff is armed, **new** lease/reference acquisition for that generation is rejected or blocks on the same controller until deletion is revoked or terminally resolved;
3. a delete cannot pass final validation, then allow a new lease/reference to commit behind its back and still enqueue from stale state;
4. if lease/reference acquisition wins the serialization order first, delete validation/acceptance must fail and external DELETE count is zero;
5. if DELETE transport acceptance wins first, a later lease/reference acquisition cannot claim the bytes are safely live; it must fail or enter recovery quarantine until the destructive attempt is terminal;
6. a pre-accept delete may be revoked and the object reopened only with a **new monotonic admission generation**, so stale delete tokens remain fenced;
7. version-specific object identity from Part 08 remains mandatory; a stale delete for generation N cannot target recreated generation N+1 at the same logical path.

### Mandatory live-lease race

RTV2-X7 and the destructive branch of X5 must include the exact ordering:

- object initially has no lease/reference that blocks GC;
- delete worker arms and passes final no-reference/no-lease validation;
- pause after validation/before transport acceptance;
- normal workflow attempts `acquire_asset_lease` or reference adoption;
- race both through `ObjectGenerationAdmission`;
- lease/reference-first => delete acceptance zero;
- delete-accept-first => lease/reference cannot become a normal valid live claimant until terminal destructive reconciliation.

Testing only an already-existing lease is insufficient.

---

## 3. Hidden retries require downstream idempotency proof, not merely key reuse

Part 08 required retries to reuse the same key. Round 14 correctly notes that reusing a key is useless if the **destination** does not enforce that key, or its deduplication horizon expires while an old attempt can still be replayed.

Architecture 1.0 therefore classifies every mutating adapter into exactly one of two modes.

### Mode A — downstream-idempotent transport

Automatic/controlled retry is permitted only when adapter evidence proves:

- the final side-effecting destination enforces the supplied idempotency identity;
- every intermediate retry source (SDK, HTTP stack, redirect handler, proxy, service mesh, failover layer, queue) preserves that same identity;
- the downstream deduplication lifetime is **at least as long as the maximum possible retry/replay/recovery horizon** for that attempt, or the architecture retains attempt state so replay after dedupe expiry is forbidden;
- two identical deliveries under the same key cannot create two logical mutations/charges.

The contract must be provider/adapter specific; an HTTP header existing is not proof that the destination honors it.

### Mode B — non-idempotent transport

If end-to-end deduplication cannot be proven, opaque mutating retries are disabled end to end:

- SDK mutating retries = off;
- automatic redirect replay of mutating bodies = off unless proven safe;
- proxy/service-mesh replay = off for that route or configured non-replayable;
- failover does not resend an ambiguous mutation automatically;
- connection reset/timeout after possible transmission becomes `ACCEPTED_UNKNOWN`/`UNKNOWN`;
- a fresh transport attempt is forbidden until adapter-specific terminal evidence proves the old attempt cannot execute.

The gateway must not convert an ambiguous Mode-B result into "try again on another endpoint".

### Mandatory retry-source tests

For at least one deliberately non-idempotent controlled transport, the suite injects separately:

1. SDK retry trigger;
2. redirect/replay trigger;
3. proxy or gateway retry trigger;
4. failover transport trigger;
5. connection reset after possible request transmission.

PASS in Mode B requires exactly one transport accept attempt or an `UNKNOWN` obligation with **no automatic second mutation**. For Mode A, tests must demonstrate destination-side dedupe under repeated delivery with the same immutable key and must test the configured retry horizon boundary.

---

## 4. UsageReservation and ExternalEffectJournal use a serialized bridge protocol

Round 14 exposed a cross-store gap: business PostgreSQL usage authority and the independent effect journal cannot be updated as unrelated writes. The worker could arm an effect, crash before converting `RESERVED`, and allow the TTL sweeper to release capacity while an external billable attempt remains eligible/ambiguous.

Architecture 1.0 therefore defines a **UsageEffectBridge** serialized by the same control-plane controller used for the effect attempt.

The safe ordering is intentionally conservative:

```text
A. acquire bridge ownership for (reservation_id, expected_owner_generation)
B. create independent-journal PREPARED guard for attempt_id
   # no transport acceptance is possible yet
C. transactionally in PostgreSQL:
     validate reservation owner generation + entitlement/account prerequisites
     transition RESERVED -> EFFECT_BOUND / SETTLEMENT_REQUIRED
     bind reservation_id <-> attempt_id
D. promote journal PREPARED -> HANDOFF_ARMED
E. only now may final egress handoff begin
```

The important invariant is that **journal protection appears before transport eligibility**, while the PostgreSQL reservation becomes non-expirable before `HANDOFF_ARMED`.

The stale-reservation sweeper is itself a contender in the bridge serialization domain. Before `RESERVED` may become `EXPIRED`, it must acquire the bridge authority for the expected reservation generation and prove there is no unresolved independent journal guard/attempt for that reservation/operation.

Therefore these races have one authoritative order:

- sweeper-first: reservation expiry commits before any PREPARED guard; later bridge creation with the stale reservation generation fails and no effect may arm;
- bridge-first: PREPARED guard exists while bridge ownership is held, so sweeper cannot free the reservation behind it; PostgreSQL conversion either succeeds and later arms, or the bridge resolves the PREPARED guard to terminal no-effect before capacity is released.

### Crash semantics between bridge phases

- crash after B before C: external transport is impossible because state is only PREPARED. Cleanup may resolve to `TERMINAL_NO_EFFECT` **only after** the controller proves no valid handoff token/transport acceptance was ever issued for that attempt; then the reservation may expire/release safely;
- crash after C before D: PostgreSQL capacity remains `EFFECT_BOUND/SETTLEMENT_REQUIRED`; no transport is yet allowed; recovery either completes arming or proves terminal no-effect and releases according to policy;
- crash after D: ordinary TTL expiry is forbidden; reconciliation/settlement rules apply.

### PITR semantics

If PostgreSQL PITR rewinds C while the independent journal still contains PREPARED/HANDOFF_ARMED/UNKNOWN for the same reservation/operation, the surviving journal guard wins conservatively: restored quota must **not** be made reusable until recovery rebinds an equivalent non-expirable usage obligation or proves terminal no-effect.

The sweeper must therefore consult the independent bridge/journal through the serialized controller; a point-in-time `SELECT` followed by expiry is not sufficient.

### Mandatory X1/X5 bridge matrix

Inject process death and PITR at each cut:

```text
before B
B -> C
C -> D
after D / before transport accept
after transport accept / before settlement
PostgreSQL PITR back across C while B/D survives
```

For every case prove: no quota double-use, no billable effect becomes free, no permanently stranded capacity once terminal no-effect is positively proven, and no generic TTL expiry of an ambiguous effect.

---

## 5. Journal arming is serialized with recovery start and the inventory cut

Round 14 exposed a late-arrival problem: recovery can scan the journal, then a stale old-epoch worker can create `HANDOFF_ARMED` after that scan. Even if it never sends, recovery has completed against an incomplete inventory.

Architecture 1.0 therefore gives the independent handoff controller an explicit **recovery arm gate**:

```text
RUNNING(epoch=N)
  -> ARMING_FROZEN(epoch=N)
  -> INVENTORY_CUT(epoch=N)
  -> RECONCILING
  -> RUNNING(epoch=N+1)
```

Rules:

1. `create PREPARED`, `promote HANDOFF_ARMED`, and final handoff acquisition validate the live control-plane recovery epoch;
2. recovery transition `RUNNING -> ARMING_FROZEN` serializes against those mutations in the same control-plane domain;
3. once `ARMING_FROZEN(N)` commits, no new N attempt may become PREPARED/HANDOFF_ARMED and no N attempt may obtain final handoff ownership;
4. recovery waits for any arm transaction that had already won the serialization order to finish and become visible;
5. only then is the journal `INVENTORY_CUT(N)` established;
6. every PREPARED/HANDOFF_ARMED/ACCEPTED_UNKNOWN row at or before the cut receives an explicit disposition or remains quarantined and blocks affected work;
7. no old-epoch row may appear after the cut;
8. new-epoch arming remains disabled until recovery explicitly enters `RUNNING(N+1)`.

A PREPARED row is not automatically ambiguous external I/O: if the architecture proves no handoff token was ever issued and the recovery freeze wins before promotion/ownership, it can be terminally revoked/no-effect. But worker death alone is not that proof.

### Mandatory late-arm ordering

X5 must pause an old-epoch attempt between PREPARED and HANDOFF_ARMED, start recovery, and race `ARMING_FROZEN` against promotion. It must also pause before PREPARED creation and race the freeze against creation.

PASS requires one of two serial outcomes only:

- recovery freeze wins -> stale create/promotion fails and transport accept count is zero;
- arm mutation wins before freeze -> row is included in the inventory cut and cannot appear as an unaccounted late obligation.

---

## 6. Mixed-version workers cannot bypass the new handoff protocol

Round 14 exposed that RT2-14's N/N-1 rollout could let an older worker execute the legacy direct-dispatch path while new workers use the journal/gateway.

Architecture 1.0 therefore separates **protocol compatibility** from ordinary application binary compatibility.

The Egress Handoff Gateway has a minimum accepted `handoff_protocol_version`. Once Part-08/09 protocol enforcement is activated, a request lacking:

- a valid surviving journal attempt;
- current fencing token;
- supported protocol version;
- required immutable generation bindings;

is rejected before external transport acceptance.

Ordinary workers do not hold bypass credentials, so a legacy binary cannot skip the gateway.

### Initial migration from legacy dispatch to Handoff v2

The first production adoption uses an explicit cutover, not an unsafe mixed path:

```text
LEGACY_DRAIN
  -> stop creating new legacy egress-capable work
  -> drain/reconcile all legacy in-flight external attempts
  -> prove zero legacy worker has direct egress authority
  -> HANDOFF_V2_REQUIRED
```

After `HANDOFF_V2_REQUIRED`:

- legacy direct dispatch never becomes allowed again merely because an old binary is rolled back;
- rollback to a binary that does not implement the gateway protocol may serve non-egress functions, but irreversible egress fails closed;
- re-enabling a legacy bypass requires a new explicit architecture/recovery decision and is not an automatic rollback action.

### Future N/N-1 compatibility

After Handoff v2 is the baseline, every supported N and N-1 application release must understand the same external-effect journal/gateway invariants. Schema/enum evolution may be expand/contract, but N-1 cannot ignore active attempt states or mint an unjournaled mutation.

### Mandatory mixed-version tests

RTV2-X5/X8 plus the RT2-14 deployment gate must execute:

1. new worker creates/arms an attempt; N-1 worker receives duplicate/restored work -> N-1 must join/reconcile or fail closed, never direct-send;
2. N-1 legacy worker tries to dispatch after `HANDOFF_V2_REQUIRED` -> gateway rejects, zero provider accepts;
3. rolling rollback starts old binary while an `ACCEPTED_UNKNOWN` attempt exists -> no fresh mutation is allowed;
4. new + old workers race the same operation -> journal uniqueness + gateway fencing yields one logical attempt;
5. schema/state includes a newer journal disposition unknown to N-1 -> N-1 fails closed rather than mapping it to retryable/pending.

---

## 7. Journal/controller availability, retention and split-brain are fail-closed contracts

The systemic self-audit also fixes adjacent consequences of making the journal/controller authoritative.

- If the journal/controller cannot be read or written, **new irreversible handoff fails closed**; workers do not fall back to direct provider/object-store calls.
- Controller leadership/ownership uses monotonically fenced generations. Network partition or split-brain cannot yield two gateways whose tokens are simultaneously current for one immutable attempt.
- Journal attempt records and idempotency identity are retained for at least the maximum of: provider retry/dedupe horizon, webhook/callback delay horizon, DR/PITR reconciliation horizon, and product/legal accounting retention needed to prevent unsafe replay. Record GC cannot silently permit a still-replayable old effect to be treated as fresh.
- Deleting journal evidence requires positive terminal state plus proof that no supported replay source (outbox, Temporal history, queue, retry layer, rollback worker) can recreate an external mutation from that identity.
- Clock expiry alone is not terminal proof for HANDOFF_ARMED/ACCEPTED_UNKNOWN.

These are architecture contracts; exact storage technology and retention durations remain deployment decisions.

---

## 8. Expanded deterministic evidence matrix

Part 08 A–H remains mandatory. Part 09 adds orthogonal dimensions that must be explicitly covered rather than inferred:

### Handoff ownership/fencing dimension

- normal owner retains authority;
- DB/control-plane session lost while process survives;
- stale owner resumes after fence generation advances;
- controller leader/fence changes during pre-enqueue pause.

### Object lifecycle dimension

- existing active lease;
- **new lease acquisition after delete final validation**;
- new reference/adoption after delete final validation;
- recovery reference reconstruction;
- accepted delayed DELETE;
- logical key reuse with a new immutable object generation.

### Retry dimension

- no retry;
- SDK retry;
- redirect replay;
- proxy/service-mesh retry;
- failover replay;
- possible-transmission connection reset;
- retry after destination dedupe horizon (must remain forbidden unless proof covers it).

### Usage bridge dimension

- sweeper wins before PREPARED;
- PREPARED wins before sweeper;
- crash B->C;
- crash C->D;
- crash after D;
- PITR rewinds PostgreSQL binding while independent journal survives.

### Recovery inventory dimension

- freeze before PREPARED;
- freeze between PREPARED and HANDOFF_ARMED;
- arm wins immediately before freeze;
- inventory cut after all winning arm transactions drain;
- verify no old-epoch late row appears after cut.

### Worker-version dimension

- N only;
- N + compatible N-1;
- pre-protocol legacy worker after v2 enforcement;
- rollback while UNKNOWN exists;
- unknown-new-state handling by N-1.

The suite does not need the full Cartesian product of every dimension, but every named risky ordering above requires a deterministic test, and each external-effect transport must satisfy the same non-bypassable gateway invariants.

---

## 9. Fourteenth-review closure criteria

The Round-14 review findings are considered incorporated only when the specification and executable evidence require all of the following together:

1. **End-to-end retry safety:** downstream destination dedupe is proven for the whole replay horizon, or mutating automatic retries are disabled and ambiguity becomes UNKNOWN.
2. **Live lease/reference safety:** normal AssetLease/reference acquisition contends with DELETE acceptance; post-validation acquisition cannot be deleted from stale state.
3. **Ownership-loss fencing:** loss of DB/session/lease while the process survives cannot authorize a stale enqueue; the transport-owning gateway rejects stale fencing tokens.
4. **Usage/journal atomic safety:** sweeper expiry and effect arming have one serialized bridge order; crash/PITR between stores cannot free quota behind an ambiguous billable attempt.
5. **Recovery inventory completeness:** PREPARED/HANDOFF_ARMED creation/promotions serialize with ARMING_FROZEN and the inventory cut; no old-epoch late journal row can appear after the cut.
6. **Mixed-version safety:** N/N-1/rollback cannot bypass journal/gateway requirements; legacy egress is drained then permanently rejected after Handoff-v2 enforcement.

Additionally, the systemic contract requires non-bypassable external transport capability, monotonic fencing, fail-closed controller unavailability, and safe journal-retention/replay rules.

Until these contracts have executable evidence, the verdict remains:

```text
PoC A–E: PASS
Red-Team v2: FAIL / IN PROGRESS
Architecture 1.0: BLOCKED
```
