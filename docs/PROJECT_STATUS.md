# ViMi Social — Project Status

**Updated:** 2026-10-21  
**Repository:** `Aragova/vimi-social`  
**Phase:** Production implementation — Telegram-first, AI-first foundation / vertical slice 1

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
- Product interface direction clarified: **Telegram bot is the primary customer interface**; web is secondary.
- Product source direction clarified: **AI-assisted discovery/automation is the primary content source**; manual upload is secondary.
- Adult/18+ content is treated as a normal high-frequency workload requiring content classification, policy-aware destination eligibility, scene selection and compliant variant generation.

## Current goal

Build the first real **Telegram-native, AI-first** production vertical slice, not another PoC, not a web-first dashboard, and not a manual-upload-first workflow.

```text
Telegram /start
-> trusted Telegram ingress + server-side Telegram identity/workspace resolution
-> onboarding / main bot menu
-> user describes desired content/task
-> Scout discovers candidate material from an authorized source
-> Curator ranks/filters candidates
-> MediaProbe + SceneDetector + SceneRanker
-> adult/content classification + platform compliance preflight
-> VariantPlanner produces/recommends a compliant variant for one destination
-> user preview/approval
-> tenant RLS transaction
-> atomic usage reservation
-> persisted operation
-> Temporal workflow start
-> provider dispatch
-> Telegram progress/status updates
-> UNKNOWN-safe reconciliation
-> final result in Telegram
```

The first staging/VM deployment should happen as soon as this path works end-to-end for one authorized source and one real publication destination.

## Immediate implementation sequence

1. Finish/merge production foundation PR #1 without changing its validated backend contracts.
2. Add first-class Telegram bot application/process boundary.
3. Implement trusted Telegram webhook/update ingress and server-side identity/workspace mapping. No client-supplied tenant authority.
4. Build `/start`, welcome/onboarding and polished main menu with inline keyboards.
5. Build bot-native product explanation, tariffs/subscription/storefront entry points and account/status menus.
6. Implement AI task intake as the default content-entry path: user describes desired content, automation level and target intent.
7. Implement controlled `Scout` discovery against one explicitly authorized source/provider boundary.
8. Persist candidate provenance/source metadata and apply rights/policy gates before reuse.
9. Add `Curator`, media probe/scene detection and `SceneRanker` contracts sufficient to select one candidate and usable segment(s).
10. Add adult/explicitness classification and destination-policy preflight as a first-class decision step.
11. Add `VariantPlanner` + render path for direct-use or a genuinely compliant derivative. If no compliant variant exists, block the target rather than disguise prohibited content.
12. Present candidate/variant preview and destination recommendation in Telegram for user approval where required.
13. In one tenant-scoped transaction, bind stable `operation_key`, reserve usage and persist the publication aggregate.
14. Start Temporal workflow and execute through a typed provider adapter.
15. Surface accepted/pending/confirmed/unknown/failed-safe states back into the Telegram conversation.
16. Implement reconciliation so UNKNOWN never produces a blind duplicate publish.
17. Add manual user upload as the secondary source path, reusing the same classification/adaptation/publication pipeline.
18. Add end-to-end tests for duplicate Telegram updates, duplicate operation starts, tenant isolation, quota concurrency, ambiguous provider outcomes and policy-blocked destinations.
19. Deploy this slice to staging/VM and test the actual bot from a real Telegram account.

## Definition of done for vertical slice 1

- A user can find the bot, press Start and receive the ViMi Social onboarding/main menu.
- Telegram identity is mapped server-side to a ViMi user/workspace/tenant; arbitrary tenant selection is impossible.
- The user can describe a desired content task without uploading a finished asset.
- ViMi can discover at least one candidate through an authorized source boundary and preserve provenance metadata.
- ViMi can rank/select a candidate and identify usable segment(s).
- Adult/explicitness classification is part of the normal pipeline.
- The system can decide whether one real destination allows the original, requires an adapted compliant derivative, or must be blocked.
- At least one adapted/direct variant can be previewed in Telegram and approved.
- The user can initiate publication to at least one real destination from the bot.
- Reusing the same `operation_key` with different binding data fails closed.
- Concurrent duplicate starts/updates do not double-reserve or double-dispatch.
- Cross-tenant reads/writes are blocked by both application context and RLS.
- Capacity is reserved before expensive/external work.
- Provider acceptance with lost response becomes UNKNOWN, not retry authorization.
- Reconciliation can move UNKNOWN forward only from typed provider evidence.
- Bot messages expose progress/result without leaking infrastructure complexity.
- Manual upload exists only as a secondary input and reuses the same downstream pipeline.
- Ruff, strict Pyright, pytest and bot-specific tests pass in CI.
- The slice is deployed to a VM/staging environment and manually exercised through Telegram.

## Adult-content adaptation rule

Adult/18+ content is expected. Destination handling follows this order:

```text
allowed as-is -> publish direct technical variant
not allowed as-is but a compliant derivative is possible -> cut/select/crop/censor/adapt -> preflight again -> publish only if compliant
no compliant derivative possible -> block destination and explain/suggest alternatives
```

Adaptation must produce a genuinely policy-compliant result; the system must not attempt to hide prohibited content or bypass moderation.

## Web scope

Next.js/web remains in the repository but is **secondary**. Near-term acceptable uses are:

- marketing/advertising landing page;
- optional linked personal account/dashboard;
- OAuth/provider callback flows that require a browser;
- richer analytics or administration where Telegram is materially worse.

Do not prioritize a full web customer dashboard ahead of the Telegram/AI MVP.

## What not to do

- Do not restart architecture discovery as the default next step.
- Do not turn the project back into web-first SaaS.
- Do not turn the project into manual-upload-first publishing software.
- Do not make normal MVP use depend on a website login/dashboard.
- Do not copy PoC implementation wholesale into production; port contracts and tests deliberately.
- Do not introduce temporary insecure tenant headers, blind retries, mutable billing history or unrestricted media/network access.
- Do not put core business logic directly in Telegram handlers.
- Do not treat adult/18+ content as an exceptional afterthought; it is a core classification/compliance workload.
- Do not adapt prohibited content merely to evade platform moderation; adaptation must satisfy the destination policy.

## Historical evidence

The complete copied architecture documentation lives under `docs/history/architecture-poc/`. PoC README/REPORT documents live under `docs/history/poc-*` and `docs/history/red-team-v2/`.

Historical documents remain authoritative for Architecture 1.0 reliability/security contracts. Where they imply that Next.js or manual upload is the main customer path, `docs/PRODUCT_VISION.md` supersedes them on product priority.