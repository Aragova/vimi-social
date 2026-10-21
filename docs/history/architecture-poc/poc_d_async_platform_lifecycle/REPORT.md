# PoC D — Result Report

**Status:** PASS — CI VERIFIED — INDEPENDENT RE-REVIEW CLEAN

## Hypothesis

A platform-neutral publication lifecycle can safely represent synchronous, asynchronous, and ambiguous provider outcomes without blind retrying an external mutation.

## Verified environment

GitHub Actions run `38902823437` (`PoC D - Async Platform Lifecycle`, run #5) completed successfully against reviewed head `e1ca8d524d46d70ae28424803896a049f15110fd`.

- GitHub runner: Ubuntu 24.04.5 LTS
- Python: 3.12.15
- Ruff: 0.17.1 — PASS
- Pyright: 1.1.414 — PASS (`0 errors, 0 warnings, 0 informations`)
- pytest: 8.4.2 — PASS (`21 passed`)
- PoC A regression run #82: PASS
- PoC B regression run #59: PASS
- PoC C regression run #32: PASS

The P1 finding from the first independent review was fixed in commit `663935c8c040b98deb23e740fd767391a57c7d8c`. A second independent Codex review completed on head `e1ca8d524d46d70ae28424803896a049f15110fd` with no findings and no unresolved findings. The original P1 review thread is resolved.

## Implemented contract

The PoC implements a typed provider boundary and an in-memory serialized operation owner keyed by `operation_key`.

Key rules:

- duplicate or concurrent `start()` calls for one operation key join the same lifecycle;
- an operation key cannot be rebound to a different target;
- external publish begins from `STARTED` and increments the attempt counter exactly once per dispatch;
- synchronous success becomes `CONFIRMED`;
- asynchronous acceptance becomes `PROVIDER_ACCEPTED` or `PENDING` and is advanced only by reconciliation/callback evidence;
- an ambiguous result, caller cancellation, or exception raised after publish dispatch begins becomes `UNKNOWN`;
- `UNKNOWN` never auto-retries and remains eligible for reconciliation;
- `INCONCLUSIVE` reconciliation preserves the current uncertain/pending state;
- only `PROVED_ABSENT` or a typed known-safe pre-mutation failure produces `FAILED_SAFE`;
- safe retry is explicit, reuses the same operation key, and is bounded;
- permanent failures are terminal;
- duplicate webhook event IDs are idempotent;
- late pending callbacks cannot regress `CONFIRMED`.

## Automated verification

The CI-verified suite contains 21 deterministic test cases covering:

- synchronous confirmation;
- repeated-start idempotency;
- ambiguous outcome handling;
- post-dispatch `TimeoutError` -> `UNKNOWN`, no republish, reconciliation allowed;
- post-dispatch `ConnectionError` -> `UNKNOWN`, no republish, reconciliation allowed;
- known-safe failure and explicit retry;
- permanent failure terminality;
- operation-key/target conflict;
- async accepted -> pending -> confirmed lifecycle;
- inconclusive reconciliation;
- proved-absent retry authorization;
- reconciliation discovery after ambiguous publish;
- pending-state preservation;
- safe-retry budget enforcement;
- concurrent-start serialization;
- cancellation during publish -> `UNKNOWN`;
- duplicate webhook idempotency;
- late callback monotonicity;
- webhook confirmation of `UNKNOWN`;
- reconcile/callback ordering;
- callback advancement from `UNKNOWN` to `PENDING`.

## Findings

### 1. `UNKNOWN` must be a persisted first-class state

An ambiguous network outcome cannot be represented as a generic failure because retry safety depends on later reconciliation evidence.

### 2. Retry authorization is different from retry execution

`PROVED_ABSENT` and known-safe pre-mutation failure only authorize a retry by moving the lifecycle to `FAILED_SAFE`. The second external mutation remains explicit and bounded.

### 3. Operation identity must outlive provider response identity

Reconciliation must work even when the initial provider response was lost and no external ID is available. The stable `operation_key` therefore remains the primary logical identity.

### 4. Callback processing must be monotonic

Provider callbacks can be duplicated or delayed. Terminal confirmation cannot be regressed by a later pending callback.

### 5. Caller cancellation after dispatch begins is ambiguous

Once an external publish call has started, cancellation of the local await cannot prove that the remote mutation did not happen. The lifecycle therefore records `UNKNOWN` before propagating cancellation.

### 6. Exceptions after dispatch begins are ambiguous

A timeout, connection failure, or other exception raised after the provider publish call has begun cannot prove that the remote mutation did not happen. The orchestrator records `UNKNOWN` before propagating the exception, so later calls cannot blind-republish and reconciliation remains possible.

## Architecture 1.0 implications

- platform adapters return typed mutation/reconciliation outcomes rather than leaking raw HTTP status/transport behavior into orchestration;
- durable orchestration owns one lifecycle per stable operation key;
- irreversible publish activities have no blind automatic retry after ambiguous completion;
- `UNKNOWN` is reconciled by operation identity and provider-specific evidence;
- retry is allowed only from `FAILED_SAFE`, with a configured bound;
- callback/webhook signals must be idempotent and monotonic;
- provider-specific logic is responsible for deciding when absence evidence is strong enough to emit `PROVED_ABSENT`.

## Limitations

This PoC uses deterministic provider mocks and an in-memory operation store. It validates lifecycle semantics, not provider-specific API behavior, webhook authentication, database durability, or Temporal worker recovery. PoC A supplies the separate durable-execution evidence; Architecture 1.0 must compose these contracts.

A generic HTTP 404 is **not** treated as proof of absence by this PoC. `PROVED_ABSENT` is an adapter semantic and must account for provider eventual consistency and lookup guarantees.

## Final verdict

**PASS.** The corrected implementation is CI-verified, the PoC A/B/C regressions are green, the original P1 finding is resolved, and the independent re-review completed with no findings.