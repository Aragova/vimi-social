# PoC A — Result Report

**Status:** PASS

## Hypothesis

Temporal can provide durable execution for ViMi Social publication workflows without blindly duplicating irreversible external publication when workers crash, workflows restart, duplicate start requests occur, or a provider accepts a request but the response is lost.

## Environment

Latest verified CI run for tested code head `d774c1c`:

- GitHub-hosted Ubuntu 24.04 runner;
- Python 3.12;
- `temporalio==1.34.0`;
- Temporal development server started with the official `temporalio/setup-temporal` action;
- Ruff, Pyright strict mode, and pytest executed in CI.

The documentation-only head `ba8220d` was also verified by CI and received a final Codex review with no findings.

## Automated tests

Latest code-evidence result: **12 passed in 21.82s**.

| Test | Result |
|---|---|
| Deterministic workflow identity from `operation_key` | PASS |
| Duplicate start protection | PASS |
| Same operation key + inconsistent target ID cannot create a second workflow | PASS |
| Worker subprocess SIGKILL + durable resume | PASS |
| Compatible V2 worker continues V1 workflow history | PASS |
| Provider accepted + lost response | PASS |
| Real activity timeout after external mutation → UNKNOWN/reconciliation | PASS |
| Inconclusive/eventually-consistent lookup remains UNKNOWN until conclusive | PASS |
| Reconciliation → CONFIRMED | PASS |
| Conclusive absence → SAFE_RETRY | PASS |
| Transient 500 before mutation is deliberately retried without duplicate mutation | PASS |
| Rate limit before mutation is deliberately retried without duplicate mutation | PASS |
| Worker startup timeout terminates the stuck child and returns bounded failure | PASS |
| Unexpected readiness output terminates the child and returns bounded failure | PASS |

## Unexpected findings

The review/test loop found several assumptions that the first implementation did not actually prove:

1. A real Temporal activity timeout is not the same failure shape as a synthetic provider-response-lost error.
2. A missing lookup result is not sufficient evidence for SAFE_RETRY when provider state may be eventually consistent.
3. Graceful worker shutdown does not prove crash recovery; an actual process kill after a persisted workflow checkpoint is required.
4. Reusing the same workflow implementation does not prove compatible deployment behavior; the recovery path now uses a distinct V2 workflow implementation.
5. Workflow identity must be tied to the external idempotency/operation key, not merely a caller-supplied target ID.
6. Safe pre-mutation failures such as a known 500 or rate limit need a separate retry path from UNKNOWN outcomes.
7. A subprocess startup timeout must terminate the child before draining stderr, otherwise the test helper itself can hang.
8. A result report must distinguish code-review confidence from directly exercised runtime evidence; the worker-startup failure paths are now covered by explicit failure-injection tests.

## Architecture changes required

The PoC produced the following rules for ViMi Social Architecture 1.0:

- publication workflow identity is derived from the deterministic external `operation_key`;
- unknown external mutation state and proven pre-mutation failure are different domain states and must have different retry semantics;
- Temporal activity retries for irreversible publish calls remain disabled by default (`maximum_attempts=1`);
- only failures positively classified as pre-mutation-safe may enter an explicit bounded publish retry loop;
- timeout/lost-response paths enter reconciliation instead of automatic republish;
- reconciliation may return SAFE_RETRY only from conclusive provider evidence;
- deployment/crash tests must use persisted checkpoints and real process failure, not timing sleeps plus graceful shutdown;
- worker/test process cleanup must itself be bounded and failure-injected in tests.

## Final verdict

**PASS**

Evidence supporting this verdict:

- the tested code head `d774c1c` passed Ruff, strict Pyright, and all 12 integration tests against a real Temporal development server;
- the documentation-only head `ba8220d` also passed CI;
- the fourth/final Codex review on `ba8220d` completed with `has_any_findings=false` and `has_unresolved_findings=false`;
- earlier review findings were converted into explicit implementation changes and/or failure-injection tests rather than waived.

PoC A therefore validates the current Architecture 0.10 assumptions for Temporal durability, deterministic workflow identity, controlled retry semantics, UNKNOWN-outcome reconciliation, crash recovery, and compatible worker evolution within the scope of this PoC.
