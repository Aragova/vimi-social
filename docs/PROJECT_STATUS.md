# ViMi Social — Project Status

**Updated:** 2026-10-21  
**Repository:** `Aragova/vimi-social`  
**Phase:** Production implementation — Telegram-first foundation / vertical slice 1

## Completed

- Architecture Baseline 0.9 and 0.10 produced.
- Red-Team v1 completed.
- Executable PoCs A–E completed and passed:
  - A: Temporal durability, identity, workflow evolution and UNKNOWN handling.
  - B: PostgreSQL tenant isolation / RLS.
  - C: secure media ingest.
  - D: async platform lifecycle / reconciliation.
  - E: usage concurrency / reservations / ledger.
- Post-PoC decisions captured.
- Red-Team v2 composition audit completed, release-blocking findings remediated, final exact-head CI passed.
- PR #8 in `Aragova/vimi-social-architecture-poc` merged to `main` on 2026-10-21. Merge commit: `6252c6f4e425006f927f7b5e5556c96ecb37d245`.
- Production repository `Aragova/vimi-social` created.
- Historical architecture/PoC documentation copied into this repository so future AI sessions do not depend on the laboratory repository.
- Production foundation PR #1 created with FastAPI/PostgreSQL/Temporal/Next.js/bootstrap CI; latest verified CI run on head `ea49ae3438f0b83fc67caf6bfa44fe4e3859ffe0` passed backend and web jobs.
- Product interface direction clarified: **Telegram bot is the primary customer interface**; web is secondary. Canonical direction is in `docs/PRODUCT_VISION.md`.

## Current goal

Build the first real **Telegram-native** production vertical slice, not another PoC and not a web-first dashboard.

```text
Telegram /start
-> trusted Telegram ingress + server-side Telegram identity/workspace resolution
-> onboarding / main bot menu
-> direct content upload
-> destination + publication options
-> tenant RLS transaction
-> atomic usage reservation
-> persisted publication operation
-> Temporal workflow start
-> provider dispatch
-> Telegram progress/status updates
-> UNKNOWN-safe reconciliation
-> final result in Telegram
```

The first staging/VM deployment should happen as soon as this path works end-to-end for one real publication destination.

## Immediate implementation sequence

1. Finish/merge production foundation PR #1 without changing its validated backend contracts.
2. Add first-class Telegram bot application/process boundary.
3. Implement trusted Telegram webhook/update ingress and server-side identity/workspace mapping. No client-supplied tenant authority.
4. Build `/start`, welcome/onboarding and polished main menu with inline keyboards.
5. Build bot-native product explanation, tariffs/subscription/storefront entry points and account/status menus.
6. Accept one real content type through Telegram first (video is preferred if media pipeline readiness permits; otherwise start with the smallest representative supported asset and expand immediately).
7. Persist immutable incoming asset metadata and pass media through the validated secure-ingest boundary.
8. Let the user select one real publication destination/account and publication options in Telegram.
9. In one tenant-scoped transaction, bind stable `operation_key`, reserve usage and persist the publication aggregate.
10. Start Temporal workflow and execute through a typed provider adapter.
11. Surface accepted/pending/confirmed/unknown/failed-safe states back into the Telegram conversation.
12. Implement reconciliation so UNKNOWN never produces a blind duplicate publish.
13. Add end-to-end tests for duplicate Telegram updates, duplicate operation starts, tenant isolation, quota concurrency and ambiguous provider outcomes.
14. Deploy this slice to staging/VM and test the actual bot from a real Telegram account.

## Definition of done for vertical slice 1

- A user can find the bot, press Start and receive the ViMi Social onboarding/main menu.
- Telegram identity is mapped server-side to a ViMi user/workspace/tenant; arbitrary tenant selection is impossible.
- The user can submit content in Telegram and see an understandable preview/state.
- The user can choose at least one real destination and initiate publication from the bot.
- Reusing the same `operation_key` with different binding data fails closed.
- Concurrent duplicate starts/updates do not double-reserve or double-dispatch.
- Cross-tenant reads/writes are blocked by both application context and RLS.
- Capacity is reserved before expensive/external work.
- Provider acceptance with lost response becomes UNKNOWN, not retry authorization.
- Reconciliation can move UNKNOWN forward only from typed provider evidence.
- Bot messages expose progress/result without leaking infrastructure complexity.
- Ruff, strict Pyright, pytest and bot-specific tests pass in CI.
- The slice is deployed to a VM/staging environment and manually exercised through Telegram.

## Web scope

Next.js/web remains in the repository but is **secondary**. Near-term acceptable uses are:

- marketing/advertising landing page;
- optional linked personal account/dashboard;
- OAuth/provider callback flows that require a browser;
- richer analytics or administration where Telegram is materially worse.

Do not prioritize a full web customer dashboard ahead of the Telegram bot MVP.

## What not to do

- Do not restart architecture discovery as the default next step.
- Do not turn the project back into web-first SaaS.
- Do not make normal MVP use depend on a website login/dashboard.
- Do not copy PoC implementation wholesale into production; port contracts and tests deliberately.
- Do not introduce temporary insecure tenant headers, blind retries, mutable billing history or unrestricted media/network access.
- Do not put core business logic directly in Telegram handlers.

## Historical evidence

The complete copied architecture documentation lives under `docs/history/architecture-poc/`. PoC README/REPORT documents live under `docs/history/poc-*` and `docs/history/red-team-v2/`.

Historical documents remain authoritative for Architecture 1.0 reliability/security contracts. Where they imply that Next.js is the main customer UI, `docs/PRODUCT_VISION.md` supersedes them on interface priority.