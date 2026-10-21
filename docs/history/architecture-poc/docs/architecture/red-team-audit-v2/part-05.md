# Red-Team v2 — Part 05: sixth–tenth-review normative hardening

**Status:** NORMATIVE ADDENDUM — REVISED AFTER TENTH INDEPENDENT REVIEW — EXECUTION PENDING

This part is a normative amendment to Part 04 after the sixth through tenth independent Codex reviews. Where Part 05 is stricter than Part 04, **Part 05 wins**. It does not create new finding IDs; it strengthens the executable closure requirements for **RT2-05**, **RT2-12**, and **RT2-16**.

## 1. X5 — provider egress must serialize all the way to external I/O start

A gateway-side read/check immediately before provider mutation is not a sufficient fence. The same is true of a primitive that validates an obligation, pauses, and later sends from that earlier decision.

The provider boundary therefore has four durable stages:

```text
dispatch commitment
  -> gateway admission
  -> provider-egress primitive acceptance
  -> provider I/O-start / UNKNOWN obligation
  -> provider outcome
```

`gateway admission`, primitive acceptance, and provider I/O-start are distinct states. No transient last-moment read is accepted as the release boundary.

Required contract:

- gateway admission is recorded under the same recovery-fence domain as recovery completion;
- provider-egress primitive acceptance is also represented as a durable in-flight obligation, not only an in-process decision;
- recovery start can stop new admissions and new primitive acceptances;
- recovery completion cannot pass any old-epoch admission or accepted primitive that can still begin provider I/O later;
- the transition to **provider I/O-start** is a durable serialization point, performed before the first external provider byte/request can be emitted;
- provider I/O-start and recovery revocation/completion have one authoritative serialization order;
- if recovery/revocation wins before provider I/O-start, the already-entered primitive must be durably fenced/cancelled and later resumption must not emit provider I/O;
- if provider I/O-start wins first, the operation immediately becomes an external-side-effect obligation (`UNKNOWN` / equivalent) and recovery cannot complete until that outcome is reconciled or otherwise proven safe;
- a provider lookup that currently returns no result is never proof that an admitted or accepted request cannot still send later;
- an implementation may instead keep recovery blocked until the provider primitive terminates, but it may not replace the serialized I/O-start boundary with another non-atomic read;
- if drain, durable cancellation, or reconciliation cannot be proven, the operation remains `UNKNOWN` / `RECOVERY_PENDING` and recovery remains blocked.

### Required X5 provider orderings

Exercise all of these deterministic barriers.

**A. After gateway admission, before primitive acceptance**

1. epoch-N dispatch commitment exists;
2. gateway admission succeeds;
3. worker pauses before provider-egress primitive acceptance;
4. recovery begins and attempts revocation/completion;
5. recovery must either revoke the admission before primitive acceptance or remain blocked;
6. resume the worker and prove no untracked provider mutation can occur after completed recovery.

**B. After primitive acceptance, before provider I/O-start**

1. gateway admission exists;
2. the actual provider-egress primitive durably accepts/consumes the obligation;
3. worker pauses inside that primitive before provider I/O-start;
4. recovery attempts to revoke and complete;
5. because no provider I/O has started, recovery may complete only after the accepted primitive is durably fenced/cancelled or otherwise proven unable to start I/O;
6. resume the already-entered primitive and assert **zero provider I/O calls** after recovery completion.

**C. Provider I/O-start races recovery**

1. provider primitive is accepted;
2. race durable `provider_io_started(operation_key, epoch)` against recovery revocation/cutover;
3. if recovery wins, I/O-start fails and provider mutation count stays zero;
4. if I/O-start wins, the operation is durably `UNKNOWN` / externally in-flight before any provider request can escape;
5. recovery must remain blocked until the external outcome is reconciled;
6. a later successful provider result must converge to exactly one logical publication/settlement obligation.

This is in addition to the existing barriers before validation, between validation and dispatch-permit consumption, and after dispatch commitment.

## 2. X5 — destructive GC/delete must serialize all the way to object-store I/O start

Disabling retention/GC at recovery start does not cancel destructive work already authorized before cutover. A final adapter-side read is also insufficient.

The destructive boundary is therefore:

```text
orphan classification
  -> delete admission
  -> delete-boundary consumption
  -> deletion-primitive acceptance
  -> object-store DELETE I/O-start / UNKNOWN obligation
  -> external delete outcome
```

Required contract:

- destructive retention work has a versioned delete obligation/admission bound to the live recovery epoch/inventory cut;
- recovery start stops new destructive admission;
- every already-admitted/consumed/accepted delete is enumerated before the inventory cut can complete;
- delete-boundary consumption is a durable serialized transition;
- deletion-primitive acceptance is a separate durable in-flight state after consumption and before object-store I/O;
- the transition to **object-store DELETE I/O-start** is durable and occurs before the first destructive external request can escape;
- delete admission, consumption, primitive acceptance, I/O-start, cancellation, reference reconstruction and inventory completion have an authoritative order in the same recovery/fencing domain;
- if recovery reconstructs/rebinds a valid reference for that exact object generation **before DELETE I/O-start**, every stale admitted/consumed/accepted delete must be durably fenced/cancelled and the object preserved;
- a valid recovered object may not be deliberately deleted merely because delete admission, consumption or primitive acceptance already happened;
- if object-store DELETE I/O-start wins before recovery can cancel, the delete immediately becomes an external `UNKNOWN` / irreversible obligation and inventory completion is blocked until reconciliation;
- drain/reconcile is permitted only after destructive external I/O has already crossed an irreversible or ambiguous boundary;
- retention/GC cannot resume while any pre-recovery delete remains capable of deleting a newly recovered valid object.

### Required X5 destructive orderings

**A. After delete admission, before delete-boundary consumption**

1. object is classified orphaned and delete authority is admitted under epoch N;
2. GC worker pauses before consumption;
3. PITR recovery reconstructs/rebinds a valid lost reference;
4. recovery revokes stale authority;
5. stale consumption fails;
6. zero object-store delete calls.

**B. After consumption, before deletion-primitive acceptance**

1. delete admission and durable consumption both succeed;
2. worker pauses before primitive acceptance;
3. recovery proves the object generation is valid;
4. consumed delete is fenced/cancelled;
5. primitive acceptance fails;
6. zero object-store delete calls and recovered object remains present.

**C. After deletion-primitive acceptance, before DELETE I/O-start**

1. admission and consumption succeed;
2. the actual deletion primitive durably accepts the destructive obligation;
3. worker pauses inside the primitive before external I/O-start;
4. recovery reconstructs/rebinds a valid reference;
5. because destructive I/O has not started, recovery must cancel/fence the already-entered primitive before finalizing inventory;
6. resume the primitive and assert **zero object-store DELETE calls**.

**D. DELETE I/O-start races recovery**

1. deletion primitive is accepted;
2. race durable `delete_io_started(object_generation, epoch)` against recovery cancellation/reference reconstruction/inventory cut;
3. if recovery wins first, I/O-start fails and bytes are preserved;
4. if I/O-start wins first, the delete becomes typed `UNKNOWN` / external destructive obligation before the request escapes;
5. recovery must not finalize inventory from local cancellation alone and remains blocked until the external outcome is reconciled;
6. missing bytes become explicit recovery/data-loss state if deletion ultimately succeeded.

A non-atomic "check cancelled immediately before DELETE" does not satisfy this gate.

## 3. X5 — account ownership generation must reconcile across PITR

Credential-version reconciliation is insufficient if PostgreSQL ownership itself is stale after PITR.

Required failure ordering:

1. at the PostgreSQL snapshot, external account generation N belongs to Tenant A;
2. after the restore point, N is disconnected/tombstoned;
3. generation N+1 reconnects the same provider account to Tenant B;
4. provider state, Secret Store and Temporal evidence retain N+1;
5. PostgreSQL is restored to the snapshot that still says N / Tenant A is current.

Required contract:

- restored current-owner mapping is not authority by itself after PITR;
- account ownership/connection generations are immutable historical identities and require independent durable recovery evidence;
- recovery reconciles PostgreSQL against surviving immutable ownership-generation evidence before credential rebinding, webhook tenant delivery or dispatch resumes;
- a credential belonging to N+1/Tenant B can never be rebound to restored N/Tenant A merely because the database pointer rolled back;
- if current ownership generation cannot be proven, the external account enters fail-closed `OWNERSHIP_RECOVERY_PENDING` / quarantine state;
- fresh Tenant A workflow execution cannot mutate the provider account while N+1 ownership evidence for Tenant B survives;
- webhook intake during `OWNERSHIP_RECOVERY_PENDING` may authenticate/dedupe/store raw quarantined evidence only; it must not resolve through the restored Tenant A current-owner mapping or create tenant-scoped delivery/side effects;
- correlatable and uncorrelatable generation-less webhooks remain quarantined until ownership-generation reconciliation is complete;
- after recovery proves N+1/Tenant B, only evidence safely attributable to N+1 may be delivered to Tenant B.

### Required X5 ownership/webhook ordering

During the restored-N / `OWNERSHIP_RECOVERY_PENDING` interval inject provider-realistic webhooks with **no internal ViMi generation field**:

1. a correlatable N+1 event/object webhook whose immutable surviving provider-object/history evidence belongs to Tenant B;
2. an uncorrelatable account-level webhook for the same external account.

Before reconciliation completes, prove zero tenant delivery/mutation to restored Tenant A and no fallback through `(provider, external_account_id) -> restored current owner`. After immutable evidence proves N+1/Tenant B, the correlatable event may route only to B; uncorrelatable evidence remains quarantined unless safe immutable attribution can be proven.

X5 must therefore prove **zero cross-tenant provider mutation, zero cross-tenant credential rebinding, and zero cross-tenant webhook delivery** in this PITR ordering.

## 4. X8 — canonical blocker registry with blocker-specific too-late boundaries

Part 04's requirement to test only sampled blocking states is superseded. Architecture 1.0 must expose a canonical registry of every committed state mutation that can block irreversible dispatch.

The initial registry includes at least:

- actor membership removal;
- actor permission revocation;
- tenant suspension/deactivation;
- target disable;
- target/resource/content eligibility becoming blocked;
- platform-account disable;
- platform-account disconnect/reconnect / account-generation advance;
- pre-dispatch user/workflow cancellation;
- resource/content deletion requests whose semantics cancel future work;
- emergency kill-switch activation that prevents the next irreversible step;
- any additional blocker later added to production dispatch policy.

For each blocker, one of two equivalent fencing designs is required:

1. it advances an authoritative shared `dispatch_policy_generation`; or
2. it owns a separate permit-bound generation participating in the same serialized boundary relevant to that blocker.

A blocker is not release-valid until the executable matrix covers it.

### Blocker classes and too-late boundaries

The architecture must not use one universal too-late boundary for every blocker.

**Dispatch-admission blockers** such as actor permission/membership, tenant/target/resource eligibility and account generation must at minimum serialize with dispatch commitment/permit consumption as defined in Part 04.

**Live-stop blockers** have stronger baseline semantics and remain effective until external provider I/O actually starts. The initial live-stop class includes:

- pre-dispatch user/workflow cancellation;
- deletion requests that cancel future work;
- emergency kill switch preventing the next irreversible step.

For live-stop blockers, internal dispatch commitment, gateway admission, or primitive acceptance is **not** yet too late. Their authoritative generation/state must participate in the durable provider I/O-start transition from §1.

### Required parameterized X8 matrix

For every registered blocker, run the validation-to-dispatch-commit race required by Part 04/earlier amendments.

Additionally, for every live-stop blocker:

1. internal dispatch commitment succeeds while the blocker is still inactive;
2. gateway admission and provider primitive acceptance may also succeed;
3. worker pauses before durable provider I/O-start;
4. concurrently commit the live-stop blocker;
5. race blocker commit against `provider_io_started(...)` in one authoritative serialization domain;
6. if blocker commits first, I/O-start fails, provider mock count remains zero, and the operation transitions to the appropriate blocked/cancelled state;
7. if provider I/O-start commits first, only then has the operation crossed the live-stop too-late boundary and it becomes an auditable `UNKNOWN` / reconciliation obligation;
8. no live-stop blocker may rely on a non-atomic read after primitive acceptance.

CI must parameterize over the complete blocker registry, including the blocker class/required boundary, so adding a new blocker without fence and race coverage fails the architecture gate.

## 5. Sixth–tenth-review closure criteria

The sixth-through-tenth-review findings are considered incorporated only when executable evidence proves all properties together:

- gateway admission cannot outlive recovery completion as a future provider mutation;
- provider-egress primitive acceptance cannot outlive recovery completion and later begin I/O;
- provider I/O-start is a durable `UNKNOWN`/external-obligation transition serialized with recovery and live-stop cancellation;
- pre-authorized destructive GC cannot outlive the inventory cut and delete a recovered valid object;
- delete consumption and deletion-primitive acceptance are serialized with recovery cancellation/reference reconstruction;
- object-store DELETE I/O-start is a durable destructive `UNKNOWN` transition serialized with inventory completion;
- a valid recovered object is fenced/preserved whenever recovery wins before destructive I/O-start;
- drain/reconcile for deletion is limited to already-started irreversible/ambiguous external outcomes;
- account ownership generation cannot roll back across PITR into cross-tenant dispatch, credential rebinding or webhook delivery;
- every registered dispatch blocker participates in the appropriate serialized permit/I/O-start matrix;
- user/workflow cancellation, deletion-request cancellation and emergency kill switch remain effective until provider I/O-start, not merely until internal dispatch commitment.

Until executable evidence exists, the verdict remains:

```text
PoC A–E: PASS
Red-Team v2: FAIL / IN PROGRESS
Architecture 1.0: BLOCKED
```
