# PoC A — Temporal Durability & Publication Safety

## Goal

Prove the execution model required by ViMi Social before production implementation.

This PoC must demonstrate:

1. deterministic workflow identity;
2. duplicate outbox delivery does not create duplicate logical publication;
3. worker crash/restart resumes durable work;
4. workflow survives compatible code deployment/versioning;
5. external publish timeout can be classified as UNKNOWN;
6. UNKNOWN is never blindly retried;
7. reconciliation can resolve UNKNOWN into CONFIRMED or SAFE_RETRY;
8. irreversible external mutation is not automatically duplicated by SDK retry behavior.

## Required failure scenarios

The mock provider must support at least:

- normal success;
- provider accepts the post and response is lost;
- pending processing then success;
- transient 500 before mutation;
- rate limit before mutation;
- worker crash;
- duplicate workflow start request.

## PASS criteria

PoC A is PASS only if automated integration tests prove:

- zero duplicate logical publications;
- deterministic workflow identity rejects/deduplicates duplicate starts;
- a worker crash does not lose the workflow;
- UNKNOWN outcome never causes blind republish;
- reconciliation reaches the expected final state;
- a compatible worker release can continue a workflow started by the previous release.

## Non-goals

This is not a production publisher and must not call Telegram, X, Instagram, TikTok or any real user account.
