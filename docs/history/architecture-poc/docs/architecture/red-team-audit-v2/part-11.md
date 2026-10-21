# Red-Team v2 — Part 11: sixteenth-review authority-root anti-fork and anti-rollback closure

**Status:** NORMATIVE ADDENDUM — SYSTEMIC RESPONSE TO SIXTEENTH EXHAUSTIVE REVIEW — EXECUTION PENDING

This part is a normative amendment to Parts 04–10. Where Part 11 is stricter, **Part 11 wins**. It addresses the complete Round-16 package returned on `2b996184...` (**3 P1 + 1 P2**) and replaces several separately monotonic counters with one stronger authority-plane contract.

It strengthens executable closure requirements for **RT2-05, RT2-08, RT2-12, RT2-14, RT2-16**, the Handoff-v2 cutover, and the replay/tombstone rules.

---

## 1. Root correction: authority is a linearizable, append-only state — not a locally caught-up number

Round 16 exposed the common flaw behind all four findings: Part 10 allowed a restored component to compare a local number with a high-watermark and then continue. Numeric catch-up is insufficient when the state that originally occupied that generation may have been lost.

Architecture 1.0 therefore defines one logical **AuthorityRoot**. The storage technology is non-normative, but its semantics are mandatory.

AuthorityRoot is outside ordinary business PostgreSQL restore and records, at minimum:

```text
activation_epoch allocations
controller/witness commit index
raw-egress cutover generation + enforcement manifest digest
external transport-capability generation
terminal effect-identity/tombstone commitments
journal/recovery inventory checkpoint commitments
bridge/object-admission high-watermarks required for recovery activation
```

AuthorityRoot must have these properties:

1. **linearizable append/CAS allocation** for authority-changing records;
2. no two successfully issued activation certificates may reuse the same epoch/fence;
3. committed history cannot silently fork into two independently current branches;
4. a replica restored behind committed history cannot make an older generation current by locally incrementing a counter;
5. loss of current quorum/witness authority is fail-closed for new irreversible egress;
6. recovery may compact payloads, but commitments needed to reject stale/replayed authority survive for the full supported recovery horizon.

A single scalar stored in a normally restored database does not satisfy this contract.

---

## 2. Activation always allocates a fresh epoch strictly above every discovered high-watermark

Part 10 used:

```text
local_epoch >= witnessed_high_watermark
```

Round 16 correctly shows that a controller restored from N could merely set itself to the already-used N+1 and reuse authority whose original N+1 journal/bridge/object state was lost.

That rule is replaced.

Before a controller may enter `RUNNING`, it must:

1. read the current linearizable AuthorityRoot head;
2. reconcile forward every authority-relevant surviving source it can discover, including journal, bridge, object-admission, raw-egress enforcement and tombstone commitments;
3. compute `max_seen_generation` over the AuthorityRoot head and all positively discovered newer evidence;
4. if newer evidence exists beyond the current AuthorityRoot head, first commit/reconcile that evidence into the authoritative history or remain `CONTROL_PLANE_RECOVERY_PENDING`;
5. atomically allocate a **fresh activation epoch `E` where `E > max_seen_generation`** using AuthorityRoot CAS/quorum allocation;
6. publish an activation certificate bound to that exact AuthorityRoot commit;
7. only then enter `RUNNING(E)` and mint E-bound handoff/bridge/object-admission authority.

Equality is never sufficient after controller recovery/failover. Previously used epoch/fence numbers are never reactivated.

### Mandatory strict-greater-than test

RTV2-X5 must execute:

- original system used epoch N+1 and created authority-bearing state under N+1;
- controller/journal replica is restored to N while the AuthorityRoot still proves N+1 was committed;
- recovery reconstructs/reconciles surviving N+1 evidence;
- activation must allocate **N+2 or later**, never N+1;
- every stale N and original N+1 token is rejected for new authority;
- only the newly issued activation certificate may mint fresh egress authority.

If the state that originally used N+1 cannot be fully reconciled, recovery remains fail-closed; inventing a fresh local copy of N+1 is forbidden.

---

## 3. Witness/AuthorityRoot activation is linearizable under partition and quorum loss

Anti-rollback is not enough if two controllers can partition, observe the same high-watermark, and each choose the same next value.

Every activation epoch is therefore **allocated**, not calculated locally.

Conceptually:

```text
allocate_activation(after=max_seen, expected_root_commit=r)
  -> atomically append unique E where E > max_seen
  -> return signed/quorum-backed ActivationCertificate(E, root_commit=r+1, state_commitments...)
```

Required semantics:

- two competing controllers cannot both successfully allocate the same E;
- a stale `expected_root_commit` loses CAS and must reread/reconcile;
- if a linearizable quorum/current AuthorityRoot cannot be reached, neither side may enter RUNNING or mint new irreversible egress authority;
- an isolated replica cannot self-declare itself current from a cached witness value;
- after partition healing, conflicting uncommitted branches are discarded/reconciled; only the AuthorityRoot committed branch can issue authority;
- activation certificates bind the controller epoch to the exact AuthorityRoot commit and relevant state commitments, so a certificate cannot be transplanted onto an older journal/enforcement/tombstone snapshot.

### Mandatory witness fork/partition matrix

Run two live controller candidates C1/C2 against the same prior AuthorityRoot head:

1. both observe high-watermark H;
2. partition one candidate from quorum and attempt concurrent activation;
3. prove at most one linearizable allocation succeeds;
4. the partitioned/non-quorum candidate remains `CONTROL_PLANE_RECOVERY_PENDING` and cannot mint usable gateway/bridge/object authority;
5. explicitly lose quorum for **all** candidates and prove zero new egress activation occurs;
6. restore quorum and prove the next successful activation receives a unique epoch strictly greater than every previously committed epoch;
7. restore an older AuthorityRoot replica/branch and prove it cannot become current without forward synchronization to the committed quorum history.

Scheduler luck or local compare-and-increment is insufficient.

---

## 4. Raw-egress enforcement is itself generation-fenced and cannot be revived by deployment/DR rollback

Round 16 exposed that Handoff-v2 can be logically current while IAM, STS issuer, proxy allowlists, network policy, workload identity or provider-side allowlists are restored to a pre-cutover configuration that re-enables a legacy route.

Architecture 1.0 therefore makes external enforcement part of AuthorityRoot activation.

Each raw-egress mechanism in the `ExternalAuthorityRegistry` must expose or be represented by a durable **enforcement_generation / policy commitment**. At minimum:

```text
mechanism_id
cutover_generation
policy/config digest or provider-side policy version
credential/key generation
issuer generation
allowed transport workload identity
revoked legacy identities/keys
```

`HANDOFF_V2_REQUIRED` is valid only when AuthorityRoot contains the cutover commitment and every required enforcement mechanism is proven at that generation or later.

### Non-revivable authority rule

A local rollback must not be able to make old raw authority usable again.

Release-valid mechanisms therefore require at least one external/non-restored fence per raw path, for example:

- provider-side revocation/rotation of the old credential/key;
- current workload identity accepted only for the committed cutover generation;
- STS issuer that binds issued credentials to the current cutover generation and refuses issuance from stale issuer state;
- network/proxy/IAM policy whose current version is checked against AuthorityRoot before raw send;
- a consensus-backed raw sender whose current transport capability is not present in older deployment snapshots.

Merely restoring an old allowlist or service-account configuration must not resurrect a credential already revoked at the provider/object-store authority boundary.

If any required enforcement mechanism is behind, unreachable, or cannot prove its committed generation, new irreversible egress fails closed to `RAW_EGRESS_ENFORCEMENT_RECOVERY_PENDING`.

### Mandatory enforcement-plane rollback matrix

For **every registered raw-egress enforcement mechanism**:

1. complete Handoff-v2 cutover at generation C;
2. keep a pre-protocol legacy worker alive with cached clients/routes/tokens;
3. restore/fail over that enforcement mechanism to a pre-C snapshot/config while controller AuthorityRoot remains at C or later;
4. also test rollback while the gateway is unavailable, so no application fallback can hide the failure;
5. attempt direct provider, object-store destructive, AI/billable, proxy and failover routes applicable to that mechanism;
6. prove the mechanism either remains externally denied or the system detects the generation mismatch and fails closed before any usable new authority is issued;
7. zero external mutations are accepted from the legacy identity;
8. recovery of the enforcement plane must move **forward** to the committed cutover generation; it may not lower AuthorityRoot or re-enable the old key/identity.

The matrix includes IAM, workload identity/STS, proxy/network policy, provider-side credential/allowlist and any future mechanism added to the registry.

---

## 5. Tombstone uniqueness is committed per identity in append-only authority history

Round 16 exposed that a tombstone store can itself be restored from a backup taken before one terminal identity was written while the scalar recovery epoch remains unchanged. Epoch equality therefore cannot prove that every terminal identity survived.

A replay-safe terminal identity is now committed in an append-only **EffectIdentityManifest** that is either part of AuthorityRoot or has its checkpoint/digest committed by AuthorityRoot before journal payload compaction is allowed.

Each terminal commitment includes at least:

```text
immutable effect identity / operation_key / object_generation
effect_kind
terminal disposition / tombstone state
idempotency identity hash/reference
manifest sequence / commit index
minimum replay-safe generation
```

Rules:

1. terminal uniqueness is not considered durable merely because a mutable tombstone table row exists;
2. before a full journal record may be compacted, the identity's manifest entry must be committed in the append-only authority history and its checkpoint included in AuthorityRoot;
3. restoring/loss of the mutable tombstone cache below the committed manifest checkpoint enters `TOMBSTONE_RECOVERY_PENDING`;
4. no N/N-1 worker, Temporal/outbox replay or external egress may resume for affected identities until the missing tombstones are rehydrated from the append-only manifest;
5. if the authoritative manifest/checkpoint is unavailable or cannot prove continuity, replay remains fail-closed — absence in the restored cache is not freshness;
6. manifest retention covers the oldest supported restore/replay horizon, or restore tooling must reject snapshots older than reconstructable manifest history;
7. manifest history itself follows AuthorityRoot anti-fork/anti-rollback semantics; an older branch cannot become current solely because a replica was restored.

### Mandatory tombstone-store rollback/loss test

1. terminally complete effects A and B in the same controller epoch;
2. commit both identities to EffectIdentityManifest and compact their verbose journal records;
3. take/restore a tombstone-cache snapshot that contains A but predates B, while keeping the same scalar epoch;
4. replay old PostgreSQL/outbox/Temporal/queue work for B with compatible N and N-1 workers;
5. system must detect cache checkpoint < AuthorityRoot/manifest checkpoint, enter `TOMBSTONE_RECOVERY_PENDING`, and permit **zero** fresh mutation;
6. rehydrate B from the append-only manifest;
7. replay resolves to B's terminal identity and external mutation count remains one;
8. repeat with complete loss/unavailability of the mutable tombstone cache; recovery must reconstruct from manifest or remain fail-closed.

---

## 6. Activation certificate binds the whole authority plane, preventing cross-component rollback composition

To close adjacent rollback combinations rather than only the exact Round-16 examples, every successful controller activation produces an **ActivationCertificate** bound to one AuthorityRoot commit.

The certificate commits, at minimum, to:

```text
fresh activation_epoch E
AuthorityRoot commit/index
journal/recovery inventory checkpoint
raw-egress cutover/enforcement generation + manifest digest
transport-capability generation
EffectIdentityManifest checkpoint/digest
minimum accepted bridge_generation / recovered bridge high-watermarks
minimum object-admission recovery high-watermarks relevant to restored work
handoff protocol version
```

Before accepting new irreversible handoff, the gateway/controller validates that the live components satisfy the certificate commitments. A component restored below its committed checkpoint cannot be hidden by another component that still reports the correct epoch.

This creates one release-valid rule:

> **A recovered system resumes irreversible egress only after every authority-bearing subsystem has reconciled forward to one freshly allocated, linearizably committed activation certificate.**

There is no independent local "looks current enough" path.

### Mandatory combined authority-plane rollback scenario

RTV2-X5 must include one composed failure:

- business PostgreSQL/outbox restored;
- controller/journal replica restored behind current state;
- raw-egress enforcement mechanism restored pre-cutover;
- mutable tombstone cache restored before a terminal identity;
- newer external/provider/object effects remain alive;
- an old worker and an old gateway process remain alive.

PASS requires:

1. no component resumes irreversible egress from local counters/config;
2. AuthorityRoot/quorum history identifies all stale checkpoints;
3. journal/tombstones/enforcement/bridge/object-admission evidence is reconciled forward;
4. a **fresh unique epoch strictly greater than every discovered prior authority generation** is allocated;
5. stale workers/gateways/tokens and pre-cutover raw routes remain unusable;
6. restored pending work converges against surviving terminal/ambiguous evidence rather than duplicating it;
7. only after the new ActivationCertificate is committed may fresh irreversible work resume.

---

## 7. Sixteenth-review closure criteria

Round-16 feedback is incorporated only when specification **and executable evidence** require all of the following together:

1. **No epoch reuse:** recovered activation receives a fresh epoch strictly greater than every witnessed/discovered prior authority generation; equality is never activation proof.
2. **Linearizable allocation:** competing/partitioned controllers cannot fork or allocate the same next epoch; witness/quorum loss fails closed.
3. **Enforcement anti-rollback:** Handoff-v2 raw-egress denial has its own committed generation and external fence; rollback of IAM/STS/proxy/network/provider policy cannot resurrect legacy authority.
4. **Per-identity replay durability:** tombstone/cache rollback or loss is detected through an append-only EffectIdentityManifest checkpoint; missing terminal identities are reconstructed before workers/egress resume.
5. **Composed activation:** one ActivationCertificate binds controller epoch, journal inventory, raw enforcement, transport authority, tombstone manifest and relevant bridge/object high-watermarks.

Review-thread resolution means only that the architecture specification has incorporated feedback. Runtime Critical/High findings remain OPEN until RTV2-X1..X8 and the Part-11 matrices pass in CI.

Until executable evidence exists, the verdict remains:

```text
PoC A–E: PASS
Red-Team v2: FAIL / IN PROGRESS
Architecture 1.0: BLOCKED
```
