# Red-Team v2 — Part 08: thirteenth-review systemic external-effect closure

**Status:** NORMATIVE ADDENDUM — SYSTEMIC SELF-AUDIT AFTER THIRTEENTH INDEPENDENT REVIEW — EXECUTION PENDING

This part is a normative amendment to Parts 04–07. Where Part 08 is stricter, **Part 08 wins**. It incorporates the two Round-13 findings and, instead of patching only those two interleavings, replaces the fragmented check/commit/send model with one common external-effect protocol for every irreversible or billable transport handoff.

It strengthens executable closure requirements for **RT2-01, RT2-05, RT2-06, RT2-08, RT2-12, RT2-13, and RT2-16** and composes with RT2-02/03/04.

## 1. Root rule: no check-then-enqueue gap is release-valid

The following shape is forbidden, no matter how close the statements are in source code:

```text
read fence / cancellation / recovery state
  -> local decision: allowed
  -> enqueue/send external request
```

A blocker can commit between the read and the enqueue. Therefore a "final read immediately before send" is not a serialization boundary.

Architecture 1.0 requires an **External Effect Handoff Controller** (name is non-normative) that owns the contested transition for one immutable effect attempt. The controller serializes:

- recovery epoch/cutover;
- policy/security/ownership blockers that are defined to stop egress;
- cancellation/kill-switch state;
- destructive reference reconstruction/cancellation;
- and the **actual transport acceptance/enqueue decision**.

The controller may be implemented with a database row lock/advisory lock, a single-owner service/actor, or an equivalent primitive, but executable evidence must prove that all contenders use the same authoritative serialization domain for the relevant immutable attempt.

A process-local mutex alone is insufficient for multi-worker correctness.

## 2. Independent ExternalEffectJournal is mandatory for ambiguous side effects

`HANDOFF_ARMED` cannot live only in the same PostgreSQL restore domain that RTV2-X5 deliberately rewinds. A PostgreSQL PITR must not erase the evidence that an external request may already have escaped.

Architecture 1.0 therefore defines an **ExternalEffectJournal** (implementation technology is intentionally not frozen here) with a failure/restore domain independent from the business PostgreSQL PITR cut, or an equivalently durable surviving source such as explicitly proven workflow/control-plane history.

Each irreversible/billable attempt has an immutable journal identity containing at least:

```text
attempt_id
logical operation_key or immutable object_generation
effect_kind
recovery_epoch
owning tenant / historical connection generation where applicable
account_generation where applicable
dispatch-policy generation(s) where applicable
usage/settlement obligation where billable
stable idempotency/reconciliation key
state
```

No credential secret value is stored in the journal.

Minimum monotonic states are conceptually:

```text
PREPARED
  -> HANDOFF_ARMED
     -> REVOKED_BEFORE_ACCEPT
     -> ACCEPTED_UNKNOWN
     -> TERMINAL_SUCCESS
     -> TERMINAL_NO_EFFECT
     -> RECOVERY_QUARANTINED
```

Exact names may differ. The following semantics are mandatory:

- `HANDOFF_ARMED` is durable **before** any transport invocation that might accept the request;
- `HANDOFF_ARMED` and `ACCEPTED_UNKNOWN` are not generically TTL-expirable;
- business-PostgreSQL PITR cannot erase or roll them back;
- a restored pending outbox/workflow cannot create another logical mutation while an unresolved journal attempt exists for the same operation/effect generation;
- only positive terminal evidence can resolve an ambiguous accepted/possibly accepted attempt;
- timeout, worker death, elapsed time, current provider absence, or current object presence are not terminal evidence.

Recovery completion inventories this journal in addition to PostgreSQL, Temporal, Object Storage, Secret Store and provider evidence.

## 3. One authoritative handoff critical section

For provider mutation, destructive DELETE, and other covered external effects, the release-valid handoff protocol is:

1. create/reuse the immutable effect attempt and stable idempotency key;
2. persist `HANDOFF_ARMED` in the independent journal;
3. acquire the attempt's authoritative handoff serialization ownership;
4. while ownership is held, validate every **egress-stop** fence relevant to that effect;
5. without releasing that ownership, invoke the controlled transport and drive it to either:
   - a definitive pre-accept rejection/failure that proves no request can execute later; or
   - actual transport acceptance/enqueue into the non-cancellable path;
6. only after one of those outcomes may the serialization ownership be released;
7. if accepted, the already-existing journal obligation is conservatively `ACCEPTED_UNKNOWN` even if the process dies before recording a refinement;
8. reconcile to a terminal outcome using stable attempt/idempotency evidence.

The critical section is allowed to block cancellation/recovery while transport acceptance is undecided. Correctness is preferred over pretending a concurrent cancellation committed when the handoff owner had already won the serialization order.

If the worker/process dies while holding the handoff ownership, ownership loss does **not** imply no external effect. The surviving `HANDOFF_ARMED` attempt is ambiguous and requires reconciliation.

### Deterministic Round-13 fence-to-enqueue ordering

For every controlled transport:

1. `HANDOFF_ARMED` exists;
2. handoff ownership is acquired;
3. final egress-stop fence validation succeeds;
4. pause **after that validation but before transport enqueue/accept** while ownership is still held;
5. concurrently attempt recovery/cancellation/blocker commit through the same serialization domain;
6. prove the blocker cannot falsely commit as "won" while the handoff owner later sends from a stale decision;
7. release the barrier and force one authoritative outcome:
   - blocker/recovery acquired ownership first -> transport accepts zero requests;
   - handoff ownership acquired first -> transport acceptance or definitive no-accept result completes before the blocker can finish its conflicting transition.

Instrumentation only before/after transport acceptance is insufficient. The final validation-to-enqueue interval itself must be deterministically exercised.

## 4. Accepted does not mean executed; negative observation is never terminal proof

A transport may accept/enqueue a request and execute its external effect later. This applies symmetrically to social publication, billable AI work, queued provider operations, and destructive Object Storage requests.

Therefore an accepted request remains unresolved until there is **terminal attempt evidence**.

Forbidden negative reconciliation includes:

```text
provider lookup: post not visible right now -> conclude request never executed
object HEAD: bytes still present right now -> conclude accepted DELETE will never execute
no webhook yet -> conclude provider did nothing
worker died -> conclude send did not happen
```

All are transient observations.

A `TERMINAL_NO_EFFECT` disposition requires evidence that the exact immutable transport attempt can no longer produce a future effect, for example:

- transport/provider explicitly reports terminal rejection/cancellation for that attempt;
- an idempotency-status API proves the key completed with no mutation and cannot later execute;
- a controlled queue proves the accepted attempt was terminally cancelled before execution;
- another adapter-specific proof with equivalent finality.

If final non-execution cannot be proved, the state remains `ACCEPTED_UNKNOWN` / `RECOVERY_PENDING` and replay is blocked.

### Required delayed-execution provider case

The controlled provider transport must support:

1. accept/enqueue the provider request;
2. pause the accepted request before external provider mutation becomes visible;
3. kill/restart the originating worker;
4. run reconciliation while provider lookup still shows no publication;
5. prove reconciliation **cannot** clear the journal attempt from that absence;
6. then execute the already-accepted request;
7. late provider/callback evidence converges to the same operation/attempt and mutation count remains one.

### Required delayed-execution DELETE case

The controlled object transport must support:

1. accept/enqueue the DELETE;
2. pause the accepted DELETE before bytes are removed;
3. kill/restart the originating worker;
4. recovery observes that bytes are still present and may reconstruct a database reference;
5. prove object presence **cannot** clear the accepted destructive obligation or finish inventory as safe;
6. execute or terminally cancel the already-accepted DELETE;
7. only terminal evidence may resolve the destructive attempt;
8. if DELETE executes, the recovered reference enters explicit missing-bytes/data-loss recovery state rather than silently becoming valid.

This directly closes the Round-13 delayed-DELETE finding and preemptively applies the same rule to delayed provider execution.

## 5. Immutable target identity prevents ABA/reuse corruption

Every external attempt is pinned to an immutable target generation.

For provider mutation this includes the immutable logical operation and historical platform-account connection generation. Provider callbacks/evidence reconcile to that historical generation and never fall through to a newer current-owner mapping.

For destructive Object Storage work:

- the delete attempt binds the immutable `object_generation` and, where the storage system supports it, immutable object version/version-id or equivalent content identity;
- a mutable key/path must not be sufficient deletion authority if that key can later be reused for different bytes;
- old accepted DELETE work must not be capable of deleting a newly recreated/rebound object generation at the same logical path;
- version-specific delete, immutable content-addressed object identity, conditional deletion, or equivalent fencing is required.

This composes RT2-08 physical ownership with RT2-05 recovery fencing.

## 6. Hidden retries and duplicate workers are part of the handoff model

Generic SDK/client retries can recreate the same ambiguity below the application state machine. For every non-idempotent or billable external mutation:

- opaque automatic mutating retries are disabled **or** are proven to reuse the same stable external idempotency key and immutable attempt identity;
- timeout/connection reset after any possibly transmitted bytes is `UNKNOWN`, not an instruction to create a fresh attempt;
- redirects, proxy retries, library retries and failover transports cannot mint a second logical idempotency identity silently;
- two workers racing the same logical effect cannot both create independent active journal attempts. The journal requires uniqueness/CAS for `(operation_key/effect generation, effect_kind)` or equivalent;
- while an attempt is `HANDOFF_ARMED`, `ACCEPTED_UNKNOWN` or quarantined, no second logical attempt is permitted unless adapter-specific evidence proves retry is safe;
- a later permitted retry reuses the provider idempotency identity when that provider contract requires it.

RTV2 tests must include two workers attempting to arm the same logical provider effect and the same destructive object generation; at most one active external-effect attempt may win.

## 7. Egress-stop policy is strengthened and unified

The earlier documents distinguished several blocker boundaries. To remove check/commit/send asymmetry, the initial Architecture 1.0 baseline adopts the conservative rule:

**Every security, ownership, recovery, cancellation, or operational state that policy says can still stop the next irreversible egress remains effective until actual transport acceptance.**

The initial egress-stop registry therefore includes:

- recovery epoch/cutover and publishing kill switch;
- actor membership/permission revocation where current policy defines it as blocking;
- tenant suspension/deactivation;
- target/resource/content eligibility disable;
- platform-account disable;
- platform-account disconnect/reconnect / account-generation advance;
- user/workflow cancellation;
- deletion-request cancellation of future work;
- emergency kill switch;
- ownership-recovery quarantine;
- any future state registered as "stop the next irreversible effect".

These mutations contend with the same handoff serialization owner for the affected attempt. If the blocker obtains the serialization order first, transport acceptance is forbidden. If actual transport acceptance wins first, only then is that specific handed-off request too late and it becomes a reconciliation obligation.

**Commercial entitlement downgrade is intentionally different:** the already-defined just-in-time `reserve_usage(expected_entitlement_generation=...)` transaction remains the commercial admission boundary for that admitted unit. A later ordinary plan downgrade does not revoke an otherwise safe admitted unit, while security/ownership/recovery blockers above remain stronger until external acceptance.

Part 08 therefore supersedes earlier text that treated ordinary internal dispatch commitment alone as the final too-late boundary for security/ownership blockers.

### Required X8 matrix

X8 must parameterize every registered egress-stop blocker through:

1. live validation;
2. internal dispatch commitment;
3. `HANDOFF_ARMED`;
4. final fence validation under handoff ownership;
5. deterministic barrier after validation/before transport accept;
6. actual transport acceptance.

For each blocker, blocker-first means zero transport accepts. Acceptance-first is the only egress too-late outcome for that specific request.

## 8. PITR composition with the external-effect journal

RTV2-X5 must add a failure ordering in which:

1. business PostgreSQL snapshot is taken;
2. an external-effect attempt is armed/accepted after that restore point;
3. the journal/control-plane evidence survives independently;
4. PostgreSQL is restored to the older snapshot that contains no knowledge of that newer attempt and may show the logical operation as pending;
5. recovery discovers the newer journal attempt by stable operation/object identity;
6. restored outbox/Temporal work is blocked from creating another external mutation;
7. journal/provider/transport evidence is reconciled and rebound to the restored logical operation before resume.

A `HANDOFF_ARMED` implementation stored solely in the PITR-rewound PostgreSQL database **fails** this gate.

Recovery completion requires an explicit disposition for every affected journal attempt at or before the recovery inventory cut. `HANDOFF_ARMED`/`ACCEPTED_UNKNOWN` may remain quarantined and keep affected work blocked; recovery may not erase them to obtain a green cutover.

## 9. Usage accounting and AI inherit the same UNKNOWN discipline

### Usage / RT2-01

When a billable provider/model attempt reaches `HANDOFF_ARMED`, its usage reservation/settlement authority leaves generic expirable semantics. A sweeper cannot free the capacity while the external-effect attempt is ambiguous.

- terminal success -> settle usage once;
- terminal no-effect -> release/refund according to the metric policy;
- unknown -> retain settlement obligation/fail closed; generic TTL expiry is forbidden.

### AI / RT2-13

Billable AI/model calls use the same attempt journal and handoff rules when provider billing or result generation can survive a lost response:

- budget/quota admission first;
- stable attempt/idempotency identity where supported;
- no opaque generic SDK retry of ambiguous billable calls;
- timeout after possible transmission -> `UNKNOWN`;
- retry only with adapter-specific idempotency/terminal proof;
- usage settlement converges from terminal evidence.

This makes RT2-13 an explicit Architecture 1.0 contract instead of leaving AI to rediscover the provider-publication race later.

## 10. Callback/reconciliation monotonicity

External evidence can arrive after crashes, PITR and local reconciliation attempts.

For provider effects:

- callback/webhook evidence maps to immutable operation/attempt and historical account generation when safely attributable;
- callback confirmation can move `HANDOFF_ARMED`/`ACCEPTED_UNKNOWN` to terminal success;
- a later timeout/UNKNOWN writer cannot regress terminal confirmation;
- provider absence cannot override later/queued confirmation;
- uncorrelatable generation-less evidence remains quarantined per RT2-04/ownership-recovery rules.

For destructive effects:

- a terminal delete success cannot be overwritten by a stale "object was present" observation;
- a terminal proven no-effect may permit preservation only for the exact immutable object generation;
- ambiguous destructive attempts keep the object/reference in recovery quarantine.

This composes RTV2-X5 with X6 rather than allowing two independent state machines to disagree.

## 11. Full deterministic boundary matrix — mandatory evidence, not scheduler luck

For each covered external-effect transport (provider mutation and destructive DELETE are mandatory; billable AI when implemented), deterministic hooks must exercise all of these boundaries:

```text
A  before HANDOFF_ARMED persistence
B  after HANDOFF_ARMED persistence / before handoff ownership
C  after handoff ownership / before final fence validation
D  after final fence validation / before transport accept     <-- Round 13 gap
E  transport accept committed / before application return
F  accepted but external effect intentionally delayed
G  external terminal effect / before local business-state update
H  process restart + reconciliation
```

At each boundary test the applicable crash, cancellation/blocker, recovery and duplicate-worker interleavings.

PASS requires the invariant:

```text
no effect without surviving ambiguity evidence
no blocker-first external acceptance
no acceptance-first false cancellation
no negative observation used as terminal proof
no duplicate logical attempt while ambiguity exists
no PITR erasure of external-effect authority
```

A suite that covers only the two latest review examples is insufficient.

## 12. Thirteenth-review + systemic self-audit closure criteria

Before requesting another independent review, the specification is considered internally hardened only if all of the following are explicit:

- final fence validation and actual enqueue/accept have one authoritative serialization owner;
- a deterministic barrier exists after final validation and before enqueue;
- `HANDOFF_ARMED` survives the business PostgreSQL PITR domain;
- crash before/after transport acceptance cannot erase ambiguity;
- an accepted-but-delayed provider request cannot be cleared by current provider absence;
- an accepted-but-delayed DELETE cannot be cleared by current object presence;
- accepted attempts require terminal attempt evidence, not point-in-time negative observation;
- object deletion is pinned to immutable object/version generation and cannot hit a reused key generation;
- hidden transport/SDK retries preserve the same idempotency identity or are disabled;
- duplicate workers cannot arm two active logical attempts;
- security/ownership/recovery blockers remain effective through actual transport acceptance;
- ambiguous billable work cannot be released by generic UsageReservation expiry;
- billable AI calls inherit the same unknown-outcome/retry discipline;
- late callback/transport evidence converges monotonically;
- X5/X8 exercise the full A–H deterministic boundary matrix, not random concurrency.

Until executable evidence exists, the verdict remains:

```text
PoC A–E: PASS
Red-Team v2: FAIL / IN PROGRESS
Architecture 1.0: BLOCKED
```
