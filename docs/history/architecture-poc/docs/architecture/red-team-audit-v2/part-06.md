# Red-Team v2 — Part 06: eleventh-review external-handoff hardening

**Status:** NORMATIVE ADDENDUM — REVISED AFTER ELEVENTH INDEPENDENT REVIEW — EXECUTION PENDING

This part is a normative amendment to Parts 04–05 after the eleventh independent Codex review. Where Part 06 is stricter, **Part 06 wins**. It does not create new finding IDs; it strengthens executable closure requirements for **RT2-05**, **RT2-12**, and **RT2-16**.

## 1. A durable local `*_io_started` marker is not itself the irreversible boundary

Round 10 introduced durable provider/object-store I/O-start markers. Round 11 correctly identified one remaining ambiguity: a worker can commit such a local marker, pause before any external byte/request has escaped, then let recovery/cancellation win and still resume from the earlier local decision.

Architecture 1.0 therefore distinguishes:

```text
LOCAL_PREPARED / local marker
  -> EXTERNAL_HANDOFF_COMMITTED
  -> external outcome
```

The **too-late boundary is `EXTERNAL_HANDOFF_COMMITTED`, not a standalone database marker**.

`EXTERNAL_HANDOFF_COMMITTED` means the request has crossed into a transport/external side-effect mechanism such that cancellation can no longer prevent the first external request from escaping. The architecture may implement this in either of two ways:

1. **Atomic/non-cancellable handoff:** the sole egress owner serializes cancellation/recovery with the exact transport handoff in one authoritative critical section. The durable handoff record and the non-cancellable transfer are inseparable for the purposes of the state machine; there is no observable state where the record says handoff committed while cancellation can still prevent all external I/O.
2. **Cancellable prepared phase:** if the system cannot prove that inseparability, any earlier local `provider_io_started` / `delete_io_started` record is only `LOCAL_PREPARED`. Recovery, reference reconstruction and live-stop blockers remain effective until the actual non-cancellable transport handoff. The executable suite must pause after the local record but before the external call and prove that a winning blocker/recovery cancels the still-local operation with zero external calls.

A last-moment read, a database flag written before a later socket/object-store call, or an in-process boolean does **not** establish `EXTERNAL_HANDOFF_COMMITTED`.

## 2. X5 — provider recovery race must reach the actual provider handoff

The provider path is now:

```text
dispatch commitment
  -> gateway admission
  -> provider primitive acceptance
  -> local provider I/O preparation (optional)
  -> provider EXTERNAL_HANDOFF_COMMITTED
  -> provider outcome / UNKNOWN reconciliation
```

Required contract:

- recovery and provider external handoff have one authoritative ordering;
- if recovery/revocation wins while the request is still local/cancellable, the already-entered primitive is cancelled/fenced and **zero provider calls** may escape;
- if provider external handoff wins first, the operation becomes an external-side-effect obligation (`UNKNOWN` / equivalent) and recovery cannot complete until reconciliation;
- a local `provider_io_started` record written before the real handoff is treated only as preparation and cannot make recovery too late;
- if the implementation claims an atomic handoff, tests must prove there is no injectable post-record/pre-request window in which recovery can win yet provider I/O still escapes;
- otherwise the test must deliberately inject exactly that window and require recovery-first to prevent all provider I/O.

### Required X5 provider ordering E — post-marker / pre-request

If the implementation has any local I/O-start/preparation marker before the non-cancellable provider handoff:

1. provider primitive is accepted;
2. local I/O-start/preparation marker is durably recorded;
3. worker pauses before the first provider request/byte has escaped;
4. recovery revocation/cutover commits;
5. because external handoff has not yet happened, recovery must cancel/fence the request;
6. resume the worker;
7. assert **zero provider calls** and successful recovery completion;
8. the converse ordering races recovery against the actual non-cancellable provider handoff; handoff-first creates the typed `UNKNOWN`/reconciliation obligation.

If no such pause is architecturally possible because the marker and transport handoff are proven inseparable, the composition test must exercise the implementation's atomic handoff primitive directly and prove the two exclusive outcomes.

## 3. X5 — destructive delete recovery race must reach the actual object-store handoff

The destructive path is now:

```text
orphan classification
  -> delete admission
  -> delete-boundary consumption
  -> deletion primitive acceptance
  -> local DELETE preparation (optional)
  -> object-store DELETE EXTERNAL_HANDOFF_COMMITTED
  -> external delete outcome / UNKNOWN reconciliation
```

Required contract:

- a recovered valid object remains preservable until the **actual destructive external handoff**;
- if reference reconstruction/cancellation wins while DELETE is still local/cancellable, the delete must be fenced and bytes preserved, even if a local `delete_io_started` marker already exists;
- a local marker before the object-store request is not an irreversible boundary;
- if destructive external handoff wins first, the delete becomes typed `UNKNOWN` / irreversible external obligation and inventory completion remains blocked until reconciliation;
- recovery may never intentionally drain a still-cancellable delete after reconstructing a valid reference.

### Required X5 destructive ordering E — post-marker / pre-DELETE

If any local DELETE-start/preparation marker exists before the non-cancellable object-store handoff:

1. deletion primitive is accepted;
2. local DELETE-start/preparation marker is durably recorded;
3. worker pauses while no external DELETE request has escaped;
4. recovery reconstructs/rebinds a valid reference and commits cancellation;
5. because destructive handoff has not yet happened, cancellation must still win;
6. resume the worker;
7. assert **zero object-store DELETE calls** and object bytes remain present;
8. only the opposite race, where the actual non-cancellable object-store handoff wins first, may enter `UNKNOWN`/reconciliation semantics.

As with provider egress, an implementation claiming no such window must prove an atomic handoff primitive with mutually exclusive outcomes.

## 4. X8 — live-stop blockers remain effective until actual provider handoff

The live-stop blocker class remains:

- pre-dispatch user/workflow cancellation;
- deletion requests whose semantics cancel future work;
- emergency kill-switch activation preventing the next irreversible step.

For these blockers, the too-late boundary is the **actual non-cancellable provider handoff**, not dispatch commitment, gateway admission, primitive acceptance, or a standalone local `provider_io_started` marker.

Required parameterized race for every live-stop blocker:

1. dispatch commitment succeeds;
2. gateway admission and provider primitive acceptance succeed;
3. if present, local provider I/O-start/preparation marker also succeeds;
4. pause before the actual provider handoff while the request is still cancellable;
5. commit the live-stop blocker;
6. blocker-first must cancel/fence the request and produce **zero provider calls**;
7. separately race blocker commit against the actual non-cancellable transport handoff;
8. handoff-first is the only valid live-stop too-late outcome and creates a typed external `UNKNOWN`/reconciliation obligation;
9. CI must fail any implementation that treats a pre-handoff local marker as sufficient to ignore a later live-stop blocker.

## 5. Eleventh-review closure criteria

The eleventh-review findings are incorporated only when executable evidence proves both of these properties:

- **provider side:** no recovery or live-stop blocker that commits before the actual non-cancellable provider handoff can be followed by provider I/O from an already-entered worker; any local marker before handoff remains cancellable;
- **destructive side:** no recovered valid object can be deleted when reference reconstruction/cancellation commits before the actual non-cancellable object-store DELETE handoff, even if a local DELETE-start marker was already written.

Therefore the release-valid rule is:

```text
local marker != external handoff
external handoff is the only too-late boundary
```

unless the implementation proves the local durable transition and non-cancellable transport handoff are one inseparable primitive.

Until executable evidence exists, the verdict remains:

```text
PoC A–E: PASS
Red-Team v2: FAIL / IN PROGRESS
Architecture 1.0: BLOCKED
```
