# Red-Team v2 — Part 10: fifteenth-review external-authority and anti-rollback closure

**Status:** NORMATIVE ADDENDUM — SYSTEMIC RESPONSE TO FIFTEENTH INDEPENDENT REVIEW — EXECUTION PENDING

This part is a normative amendment to Parts 04–09. Where Part 10 is stricter, **Part 10 wins**. It addresses all findings returned together by the fifteenth exhaustive Codex review of `2105725...` (**6 P1 + 2 P2**) and closes the remaining classes around raw transport authority, split-brain, retry lifetime, destructive-generation terminal semantics, bridge fencing, control-plane rollback, and replay after journal GC.

It strengthens executable closure requirements for **RT2-01, RT2-05, RT2-08, RT2-12, RT2-14, and RT2-16** and the Part-08/09 External Effect Handoff Protocol.

---

## 1. Non-bypassable means the raw transport capability is physically unavailable to legacy/application workers

Part 09 said ordinary workers do not own raw provider/destructive egress authority. Round 15 correctly requires this to be proven against a **genuinely legacy direct-dispatch process that never calls the gateway at all**.

Architecture 1.0 therefore distinguishes application protocol enforcement from raw transport enforcement.

After `HANDOFF_V2_REQUIRED`, the following invariant is mandatory:

> **Only the transport-owning egress plane may possess a capability that can cause a covered irreversible external effect. Application workers, including surviving pre-protocol binaries, cannot reach the effecting endpoint with usable authority even if they retain stale in-process SDK/client state.**

This must be enforced outside ordinary worker code by one or more release-valid mechanisms such as:

- provider/object-store credentials scoped exclusively to the egress-plane workload identity;
- short-lived workload identity / STS credentials that are never issued to application workers after cutover;
- network/IAM/service-account policy that denies worker identities raw mutating routes;
- an egress proxy/private endpoint reachable only from the transport-owning plane;
- provider-side source/workload allowlisting where available;
- credential/key rotation at cutover so cached legacy credentials cease to authorize future mutation.

A code convention such as “legacy workers should call the gateway” is not enforcement.

### Cutover proof

`LEGACY_DRAIN -> HANDOFF_V2_REQUIRED` is not complete until all raw legacy capabilities are either expired/revoked/rotated or externally denied. The cutover records an explicit **raw-egress capability inventory** covering at minimum:

```text
provider credentials / refresh-derived access credentials
object-store destructive credentials
AI/billable-provider credentials
SDK-specific credential caches
proxy/direct routes
failover routes
pre-cutover service-account or workload tokens
```

If any listed capability may still authorize a direct mutation, Handoff-v2 enforcement is not complete.

### Mandatory surviving-legacy test

RTV2-X5/X8 and RT2-14 must deterministically keep a legacy worker alive across cutover, with cached pre-cutover client state, then attempt **every registered raw/fallback mutation route** after `HANDOFF_V2_REQUIRED`:

1. direct provider client;
2. direct object-store destructive client;
3. direct AI/billable provider client where applicable;
4. cached proxy/direct URL;
5. failover endpoint;
6. cached/pre-cutover credential/token.

PASS requires rejection **outside the legacy process** with zero external mutation, including while the gateway itself is unavailable. Gateway outage must not restore a fallback direct-send path.

The raw-route registry is executable configuration. Adding a new direct/fallback route without a denial test fails the release gate.

---

## 2. Internal fencing is insufficient for a split-brain transport-owning gateway

Round 15 correctly identifies that a provider does not understand ViMi's internal fence token. If two gateway processes split-brain and both retain usable raw credentials, an old gateway can send after a newer leader advances the internal generation.

Architecture 1.0 therefore requires the **raw transport capability itself** to have one exclusive authority path. A release-valid deployment must implement one of these equivalent models.

### Model A — externally fenced capability lease

The right to obtain/use raw mutating credentials is tied to a monotonically fenced, short-lived capability lease issued by a consensus/control-plane authority. A gateway that loses leadership/lease cannot refresh or continue using a capability past the bounded handoff interval. Any cached credential whose validity outlives safe leadership loss makes this model fail unless the raw downstream route independently rejects the stale gateway identity.

### Model B — single raw sender behind consensus-backed acceptance

Multiple gateways/controllers may validate attempts, but **only one separately fenced raw sender** possesses the provider/object-store mutation capability. Gateways append a consensus-backed acceptance record; the raw sender consumes only committed records from the current control-plane generation. A partitioned stale gateway cannot bypass the acceptance log because it does not possess usable raw transport authority.

Equivalent designs are allowed only if they prove the same property:

```text
at most one current authority can cause raw transport acceptance
```

A database/advisory lock plus long-lived shared provider credentials is not sufficient.

### Mandatory split-brain gateway test

The executable suite must run two live gateway instances:

1. G1 is current and passes final validation for attempt A;
2. pause G1 after final validation but before raw enqueue;
3. partition G1 from the controller/consensus plane while keeping its process alive;
4. elect/activate G2 and advance the transport authority generation;
5. let recovery/cancellation or a newer handoff proceed through G2;
6. resume G1 and force it to attempt the **raw** provider/object-store call, not merely another gateway RPC;
7. prove G1 cannot cause transport acceptance.

The converse ordering is also tested: if G1's externally fenced raw acceptance legitimately wins before capability loss, the attempt remains the one authoritative ambiguous/terminal effect and G2 must not duplicate it.

---

## 3. Mode A dedupe horizon covers every outstanding delivery source, not only ViMi retry state

Part 09 allowed destination dedupe to be shorter than the application replay horizon when ViMi retained attempt state and forbade later replay. Round 15 correctly notes that this does not stop an **already accepted SDK/proxy/queue/failover retry** from being delivered after the destination forgets the key.

For **Mode A** the stronger rule is now mandatory:

> The destination deduplication window must cover the maximum lifetime of **every outstanding delivery source that can still deliver that same immutable attempt**, not merely the period during which ViMi might initiate a new retry.

Let:

```text
D = destination dedupe lifetime
R = maximum lifetime of application-initiated replay
Q = maximum lifetime of SDK/proxy/mesh/queue/failover pending delivery
DR = maximum recovery/restore period in which an already-created delivery may reappear
```

Mode A is release-valid only if either:

```text
D >= max(R, Q, DR)
```

or all delivery sources whose lifetime could exceed `D` have **positive terminal drain/cancellation proof** before `D` can expire.

Retaining a journal row is not a substitute for destination deduplication of an already in-flight duplicate.

If neither bound nor terminal drain proof exists, that adapter is **Mode B** for mutating operations.

### Mandatory beyond-dedupe delayed-delivery test

The controlled transport must accept a retry/delivery under key K, hold it without executing, advance simulated time beyond the destination's configured dedupe window, then attempt execution while an earlier K delivery already succeeded. PASS requires either:

- the adapter contract proves such a held delivery cannot outlive the dedupe horizon; or
- the destination still dedupes it under the validated horizon; or
- terminal queue/transport cancellation proof prevents the delayed delivery.

A second mutation/charge is always FAIL.

---

## 4. Mode B evidence is adapter-stack specific and registry complete

A representative non-idempotent fixture is not sufficient. Every concrete mutating adapter has its own SDK, redirect behavior, proxy/mesh route, failover configuration and credential path.

Architecture 1.0 therefore defines a canonical **MutatingAdapterRegistry**. Every entry includes at least:

```text
adapter_id
provider/effect kind
mode = A | B
SDK/client implementation + relevant retry configuration
redirect policy
proxy/service-mesh retry policy
failover policy
queue/async transport if any
destination idempotency evidence if Mode A
maximum outstanding-delivery horizon
raw-egress route/capability identity
```

CI derives retry/handoff tests from this registry. A new mutating adapter without a registry entry or without mode-specific executable evidence fails the gate.

### Mandatory Mode B per-adapter matrix

For **every Mode-B adapter using its actual client/proxy configuration**, inject independently:

- SDK retry trigger;
- redirect of a mutating request;
- proxy/service-mesh retry trigger;
- failover trigger;
- connection reset after possible transmission;
- ambiguous timeout;
- gateway process restart after possible transmission.

PASS requires no automatic second external mutation. Any case with possible transmission becomes the same immutable `UNKNOWN` obligation until terminal evidence exists.

This applies to provider publication, destructive storage calls, and billable AI/model adapters that are Mode B.

---

## 5. DELETE success permanently tombstones the exact immutable object generation

Round 15 correctly identifies that “block the claimant until the destructive attempt is terminal” is outcome-insensitive. If DELETE succeeds, a waiting claimant must not then become a normal live reference to bytes that no longer exist.

The object-generation terminal state machine is strengthened:

```text
DELETE_ACCEPTED_UNKNOWN(g)
  -> DELETE_TERMINAL_SUCCESS(g)   => TOMBSTONED_MISSING(g)
  -> DELETE_TERMINAL_NO_EFFECT(g) => may reopen only as admission generation g+1

DELETE_REVOKED_BEFORE_ACCEPT(g)
  -> may reopen only as admission generation g+1
```

Rules:

1. `DELETE_TERMINAL_SUCCESS` permanently invalidates the exact immutable object generation targeted by that delete;
2. queued/waiting lease or reference claimants for that exact generation fail or enter explicit missing-bytes recovery; they do **not** become normally live after terminal success;
3. only `TERMINAL_NO_EFFECT` or proven pre-accept revocation may reopen the same underlying bytes, and reopening always advances the object-admission generation/fence;
4. recreating bytes later uses a **new immutable object generation/version identity**; it is never resurrection of the tombstoned generation;
5. a stale lease/reference token for the old generation cannot attach to replacement bytes.

### Mandatory X5/X7 terminal-outcome matrix

For the post-validation claimant race, execute both outcomes:

- DELETE wins and terminally succeeds -> object generation is tombstoned/missing; waiting claimant cannot become valid; zero false-live references;
- DELETE wins acceptance but terminally proves no effect -> object may reopen only under a new admission generation; stale delete/claimant tokens are rejected;
- claimant/revocation wins before accept -> zero DELETE accepts and new live generation/fence is authoritative.

---

## 6. UsageEffectBridge ownership is fenced across every phase, including sweeper resolution

Part 09 acquired bridge ownership at phase A but did not require B/C/D and sweeper resolution to atomically validate a monotonic bridge fence. Round 15 correctly exposes the live-process ownership-loss race.

Each `(reservation_id, attempt_id)` bridge has a monotonic **bridge_generation**. Every authoritative mutation carries and validates the expected generation:

```text
A acquire bridge ownership -> bridge_generation = b
B journal PREPARED(attempt_id, bridge_generation=b)
C PostgreSQL RESERVED -> EFFECT_BOUND(..., bridge_generation=b)
D journal PREPARED -> HANDOFF_ARMED(expected_bridge_generation=b)
E final egress admission references the same bound bridge generation
```

The following also require the same fenced generation:

- sweeper decision to expire/release a reservation;
- PREPARED cleanup to `TERMINAL_NO_EFFECT`;
- recovery rebinding after PostgreSQL PITR;
- settlement/refund transition that releases quota authority.

If bridge ownership/session/lease is lost, the control plane increments/invalidates the generation. A stale process may remain alive but **cannot** perform the next B/C/D/cleanup/egress mutation with generation `b`.

The PostgreSQL C transition validates the current bridge generation in the same transaction as the reservation state mutation. Journal B/D/Cleanup operations use conditional/CAS semantics against that generation. The sweeper cannot read a guard, lose ownership, then expire from a stale decision.

### Mandatory live ownership-loss matrix

Do not test only process death. Keep the process alive and drop bridge ownership at every inter-phase boundary:

```text
A -> B
B -> C
C -> D
D -> final handoff
PREPARED cleanup -> reservation expiry
terminal reconciliation -> quota release
```

At each boundary let a sweeper/recovery/new owner advance the bridge generation, then resume the stale process. PASS requires every stale mutation to fail and no effect to arm behind released quota.

PITR tests must also prove a restored PostgreSQL binding with an older bridge generation cannot overrule newer surviving journal/control-plane evidence.

---

## 7. Recovery/controller epochs are protected by a non-rollbackable monotonic witness

Part 09 assumed the independent controller/journal survives the business PostgreSQL PITR. Round 15 correctly asks what happens if the **controller itself** is restored/fails over from an older snapshot and makes epoch N appear current after N+1 was already used.

Architecture 1.0 therefore requires a **RecoveryFenceWitness** (name non-normative): a monotonic source whose accepted epoch/fence cannot roll backward merely because one controller/journal replica is restored.

Release-valid implementations include a consensus log/quorum sequence, append-only external witness, or equivalent durability with proven anti-rollback semantics. The witness is not the business PostgreSQL PITR domain and is not reconstructed by trusting the restored controller's local counter.

Every controller activation/failover/recovery must prove:

```text
local_epoch >= witnessed_high_watermark
```

before it may enter `RUNNING` or issue/accept any new handoff/bridge/object-admission fence.

If local state is older or evidence conflicts, the controller enters:

```text
CONTROL_PLANE_RECOVERY_PENDING
```

and all new irreversible egress fails closed while journal/gateway/PG/external evidence is reconciled forward. Epoch/fence numbers are never reused.

### Mandatory controller rollback test

1. establish witnessed epoch/fence N+1;
2. create newer PostgreSQL/journal/gateway/external-effect evidence under N+1;
3. restore/fail over the controller from snapshot N;
4. keep newer systems/evidence alive;
5. attempt stale PREPARED promotion, bridge mutation, object admission and raw gateway handoff using N-era authority;
6. prove controller/gateway remain fail closed until monotonic forward reconciliation reaches at least the witnessed high-watermark;
7. prove no N fence becomes current again and zero duplicate/raw mutation occurs.

The same rule applies if the journal storage itself is restored from an older snapshot: absence of a newer row cannot lower the witnessed effect/control generation.

---

## 8. Journal record GC leaves a replay-resistant uniqueness tombstone for the full supported restore horizon

Round 15 correctly identifies that deleting terminal journal evidence after a one-time scan can be invalidated by a later supported restore of an older outbox/Temporal/queue snapshot.

Architecture 1.0 therefore separates **full attempt payload retention** from **effect-identity tombstone retention**.

A terminal attempt's verbose journal data may eventually be compacted, but an independently durable tombstone containing at least:

```text
immutable effect identity / operation_key / object_generation
effect_kind
terminal disposition or terminal-generation marker
idempotency identity hash/reference
minimum replay-safe generation
```

must remain unavailable to ordinary replay GC until **all** supported sources capable of resurrecting that effect are provably beyond it.

Release-valid deletion of the uniqueness tombstone requires both:

1. every supported restore point/snapshot/backup older than the tombstone is expired or policy-forbidden from restore **or** restore tooling rehydrates the tombstone set before workflows can resume;
2. Temporal/outbox/queue/retry/rollback histories capable of replaying the operation are terminally expired/drained beyond that identity.

If the platform promises restore from snapshots older than the tombstone, then the tombstone must survive independently of those snapshots or be reconstructed from another authoritative append-only source before egress resumes.

A wall-clock age by itself is not proof.

### Mandatory GC -> oldest-supported-replay test

1. complete an external effect terminally;
2. compact/delete the full journal record according to the proposed retention policy while retaining whatever compact tombstone the design claims is sufficient;
3. restore/replay the **oldest still-supported** PostgreSQL/outbox/Temporal/queue state that would present the operation as pending/fresh;
4. start compatible N and N-1 workers;
5. prove the replay resolves against the retained/reconstructed terminal identity and cannot create a fresh external mutation;
6. external mutation count remains one.

Also test that restore is rejected/fail-closed if its age exceeds the retention evidence the architecture can safely reconstruct.

---

## 9. External-authority registry is the common source for gateway, retry, raw-route and rollout gates

To prevent future omissions from appearing as another series of adjacent findings, Architecture 1.0 requires one release-time **ExternalAuthorityRegistry** (logical concept; file/table format non-normative) that enumerates every covered irreversible/billable effect.

For each effect it records:

```text
effect_kind / adapter_id
raw transport endpoint(s)
workload identity/capability allowed to mutate
legacy/raw routes denied after cutover
gateway/raw-sender fencing model
Mode A or Mode B retry model
maximum outstanding delivery lifetime
destination dedupe horizon/proof if Mode A
journal/effect identity and tombstone retention rule
bridge requirement if billable
object-generation admission rule if destructive
minimum handoff protocol version
supported N/N-1 versions
```

CI validates registry completeness against all production mutating adapters/transports present in the production repository. A new irreversible transport with no registry entry, raw-route denial proof, retry-mode proof, or version gate is a release failure.

This registry is intentionally cross-cutting: adapter code cannot silently add a route or retry layer that the Red-Team matrix never sees.

---

## 10. Fifteenth-review deterministic evidence matrix

The Part-08 A–H and Part-09 dimensions remain mandatory. Add these Round-15 orderings explicitly.

### Raw bypass / migration

- surviving pre-protocol worker with cached provider credential after `HANDOFF_V2_REQUIRED`;
- cached object-store destructive capability;
- cached AI/billable credential;
- direct route, proxy fallback, failover route;
- same cases while gateway is unavailable.

Expected: all raw paths externally denied, zero mutation.

### Gateway split-brain

- two live gateways, G1 partitioned after final validation;
- G2 advances authority generation;
- G1 attempts raw enqueue with stale external capability;
- converse acceptance-first ordering.

Expected: stale raw capability cannot mutate; acceptance-first remains one ambiguity obligation.

### Retry lifetime

- accepted retry held past destination dedupe expiry;
- delayed queue/proxy/failover delivery past expiry;
- terminal drain/cancel proof before dedupe expiry where used.

Expected: no second mutation; otherwise adapter cannot be Mode A.

### Mode B registry completeness

Parameterize SDK/redirect/proxy/failover/reset/restart triggers over **every registered Mode-B adapter using its real configuration**.

### Object terminal semantics

- claimant waits behind accepted DELETE -> terminal success -> tombstoned/missing, claimant rejected;
- accepted DELETE -> terminal no-effect -> reopen only under next generation;
- pre-accept claimant/revocation wins -> zero DELETE accepts.

### Usage bridge fencing

At every A/B/C/D/E inter-phase boundary, lose ownership while stale process remains alive, advance bridge generation, then resume stale mutation. Repeat around sweeper cleanup/expiry and terminal quota release.

### Controller anti-rollback

- controller snapshot N restored after witness N+1;
- journal snapshot rollback after N+1 evidence;
- newer PostgreSQL/gateway/provider/object evidence survives;
- old fence attempts across PREPARED, bridge, object admission and gateway.

Expected: `CONTROL_PLANE_RECOVERY_PENDING`, no fence reuse, zero stale egress.

### Terminal journal GC/replay

- compact terminal record;
- restore oldest supported DB/outbox/Temporal/queue snapshot;
- N/N-1 replay attempt;
- tombstone/reconstructed identity blocks fresh mutation.

---

## 11. Fifteenth-review closure criteria

The eight Round-15 findings are considered incorporated only when the architecture and executable evidence require all of the following together:

1. **Legacy direct-send is physically denied.** A process that never calls the gateway still cannot mutate after Handoff-v2 cutover, including with cached credentials/routes and during gateway outage.
2. **Split-brain gateway cannot raw-send stale authority.** Internal fence numbers are backed by exclusive external transport capability or a single consensus-backed raw sender.
3. **Mode-A dedupe covers outstanding delivery lifetime.** Application journal retention cannot substitute for destination dedupe of already in-flight delayed deliveries.
4. **Mode-B tests are adapter-specific and registry complete.** Every concrete adapter stack is exercised with its actual retry/proxy/failover configuration.
5. **DELETE terminal success tombstones the exact generation.** Waiting claimants never become false-live references to deleted bytes; no-effect/revocation reopens only under a new generation.
6. **UsageEffectBridge is fenced end-to-end.** B/C/D, sweeper, cleanup and settlement all atomically validate one monotonic bridge generation, including live ownership-loss tests.
7. **Control-plane generations cannot roll backward.** Controller/journal restore is checked against an independent monotonic witness and fails closed on regression/conflict.
8. **Journal GC cannot erase replay uniqueness.** Compact terminal tombstones survive or are reconstructed for the entire supported restore/replay horizon, with oldest-supported-restore evidence.

Additionally, every covered effect must appear in the common ExternalAuthorityRegistry so raw routes, gateway authority, retry mode, retention, bridge/object admission and N/N-1 gates cannot diverge silently.

Until executable evidence passes, the verdict remains:

```text
PoC A–E: PASS
Red-Team v2: FAIL / IN PROGRESS
Architecture 1.0: BLOCKED
```
