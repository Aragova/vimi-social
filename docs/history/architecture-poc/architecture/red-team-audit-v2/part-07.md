# Red-Team v2 — Part 07: twelfth-review crash-safe transport handoff

**Status:** NORMATIVE ADDENDUM — REVISED AFTER TWELFTH INDEPENDENT REVIEW — EXECUTION PENDING

This part is a normative amendment to Parts 04–06 after the twelfth independent Codex review. Where Part 07 is stricter, **Part 07 wins**. It does not create new finding IDs; it strengthens executable closure requirements for **RT2-05**, **RT2-12**, and **RT2-16**.

## 1. External handoff must be crash-safe before transport acceptance

Part 06 correctly moved the too-late boundary from a local marker to the actual non-cancellable external handoff. Round 12 identified the remaining crash window: the transport can accept/enqueue the request and the worker can die before a post-handoff `UNKNOWN`/handoff record is durably written.

Therefore Architecture 1.0 must never depend on this unsafe ordering:

```text
transport accepts external request
  -> write durable UNKNOWN / handoff state
```

The durable ambiguity obligation must already exist **before the transport can accept the request**.

The required state model is:

```text
LOCAL_PREPARED
  -> HANDOFF_ARMED        # durable; external acceptance is now possible
  -> either REVOKED_BEFORE_ACCEPT
     or EXTERNAL_HANDOFF_ACCEPTED / UNKNOWN
  -> reconciled external outcome
```

`HANDOFF_ARMED` (name may differ in implementation) is a conservative durable obligation keyed by stable operation/object identity and recovery epoch. It means: **this request may still cross the external boundary; recovery must not assume absence merely because no post-accept state was recorded**.

Required rules:

- `HANDOFF_ARMED` is durable before invoking the provider/object-store transport;
- transport acceptance/enqueue and cancellation/recovery revocation have one authoritative serialization order at the actual transport boundary;
- if cancellation/recovery wins before transport acceptance, the armed obligation is durably revoked and the transport must not accept/send the request;
- if transport acceptance wins, the pre-existing armed obligation survives any immediate process crash and is treated conservatively as `UNKNOWN` / externally ambiguous until reconciled;
- recovery/inventory completion may not erase or reinterpret an armed obligation merely because the worker died before writing a later state;
- a provider/object lookup that currently shows absence does not prove an armed request was never accepted;
- stable idempotency/reconciliation identity must prevent a second logical mutation while the armed/unknown obligation is unresolved;
- post-accept durable state may refine the obligation, but correctness cannot depend on that write succeeding.

The same rule applies to both social-provider mutation and destructive object-store deletion.

## 2. X5 — crash immediately after provider transport acceptance

RTV2-X5 must include a transport-level crash hook for the provider path.

Required deterministic ordering:

1. dispatch commitment, gateway admission and provider primitive acceptance succeed;
2. durable provider `HANDOFF_ARMED(operation_key, epoch)` is committed;
3. the provider transport reaches its **actual enqueue/send acceptance boundary**;
4. the fake/controlled transport reports that the request has been accepted into the non-cancellable external path;
5. **kill the worker/process immediately at that boundary**, before any later local success/`UNKNOWN`/handoff-confirmation write can run;
6. restart the worker/recovery path;
7. prove the pre-existing armed obligation is still present and blocks recovery completion from treating the request as safely cancelled/local;
8. reconcile provider evidence by stable operation identity/idempotency key;
9. prove exactly one logical provider mutation/settlement obligation: no blind retry and no duplicate publication.

PASS requires that both externally observable outcomes are safe:

- if transport acceptance ultimately produced a provider mutation, recovery converges that mutation to the existing operation and mutation count remains one;
- if the accepted transport attempt ultimately produced no mutation and non-execution can be proven, the obligation may resolve without mutation;
- if neither outcome can be proven, the operation remains typed `UNKNOWN` / `RECOVERY_PENDING`; it must not be replayed blindly.

A test that kills only after the application has durably observed provider acceptance is insufficient for this gate.

## 3. X5 — crash immediately after object-store DELETE transport acceptance

The destructive path requires the symmetric failure injection.

Required deterministic ordering:

1. delete admission, delete-boundary consumption and deletion-primitive acceptance succeed;
2. durable delete `HANDOFF_ARMED(object_generation, epoch)` is committed;
3. the object-store transport reaches its **actual DELETE enqueue/send acceptance boundary**;
4. the controlled transport accepts the destructive request into the non-cancellable path;
5. **kill the worker/process immediately at that boundary**, before any later local `UNKNOWN`/delete-confirmation write;
6. start recovery/inventory reconciliation;
7. prove the armed destructive obligation survives the crash and blocks inventory completion/GC resumption until the external outcome is reconciled;
8. if DELETE executed, missing bytes become an explicit destructive outcome/data-loss recovery state and must never be silently reconstructed from stale DB assumptions;
9. if DELETE provably did not execute, the armed obligation can be resolved and a recovered valid reference/object may be preserved;
10. if outcome is ambiguous, keep the object generation in typed `UNKNOWN` / recovery quarantine and do not issue a second destructive request blindly.

Recovery must never convert a pre-crash armed DELETE to `CANCELLED` solely because no post-accept local state exists.

## 4. Claimed atomic handoff must be proven at the actual transport boundary

An implementation cannot satisfy Parts 06–07 merely by placing `write state; call transport` inside one method and naming that method “atomic”.

Executable evidence must instrument the real adapter boundary where the transport accepts/enqueues the request.

For **both provider mutation and object-store DELETE**, the controlled adapter must expose deterministic barriers/hooks equivalent to:

```text
before_transport_accept
transport_accept_committed
after_transport_accept_before_application_return
```

The exact API names are not normative; the observable ordering is.

Required proof:

- pause at `before_transport_accept` and race cancellation/recovery against transport acceptance;
- if cancellation/recovery wins, the armed obligation is revoked and transport call count is zero;
- if transport acceptance wins, cancellation/recovery cannot later classify the operation as safely local/cancelled; the pre-existing armed obligation remains until reconciliation;
- inject process death at `after_transport_accept_before_application_return` and prove the same property after restart;
- the test must not rely on sleeps, scheduler luck, or merely observing both outcomes over many runs;
- the transport boundary and revocation attempt must be coordinated by deterministic barriers so the contested interleaving is exercised on demand.

If a production adapter/library does not expose an instrumentable acceptance point, the architecture must wrap it with a controlled handoff abstraction that can provide equivalent deterministic evidence. “The window is probably too small” is not accepted as proof.

## 5. X8 — live-stop blockers vs armed handoff

For user/workflow cancellation, deletion-request cancellation and emergency kill switch, `HANDOFF_ARMED` is **not** the too-late boundary.

These blockers remain effective until the actual provider transport acceptance/non-cancellable handoff.

The parameterized X8 race must therefore include:

1. provider path reaches durable `HANDOFF_ARMED`;
2. pause at the actual `before_transport_accept` hook;
3. race the live-stop blocker commit against transport acceptance;
4. blocker-first: revoke the armed obligation, zero provider transport accepts/calls, transition to blocked/cancelled state;
5. transport-first: the armed obligation becomes externally ambiguous/`UNKNOWN`; only this ordering is too late for that already-handed-off request;
6. kill immediately after transport acceptance before application return and prove the live durable obligation survives restart and forces reconciliation.

## 6. Twelfth-review closure criteria

The Round-12 findings are incorporated only when executable evidence proves all of the following together:

- external transport can never accept a provider request before a durable ambiguous obligation already exists;
- external transport can never accept an object-store DELETE before a durable destructive ambiguous obligation already exists;
- process death immediately after transport acceptance but before application observation cannot make either obligation disappear;
- recovery/inventory completion remains blocked or fail-closed while such an armed/unknown obligation is unresolved;
- provider and DELETE adapter tests instrument the actual enqueue/send acceptance boundary deterministically;
- cancellation/recovery winning before transport acceptance produces zero external calls;
- transport acceptance winning first survives process death as a reconciliation obligation rather than reverting to local/cancelled state;
- no claim of “atomic handoff” is accepted without deterministic boundary instrumentation.

Therefore the release-valid rule is:

```text
arm ambiguity before transport
race at the real transport-accept boundary
crash after accept must still leave durable ambiguity
```

Until executable evidence exists, the verdict remains:

```text
PoC A–E: PASS
Red-Team v2: FAIL / IN PROGRESS
Architecture 1.0: BLOCKED
```
