# ViMi Social — Context for AI / new chat

Read these first:

1. `docs/PRODUCT_VISION.md`
2. `docs/PROJECT_STATUS.md`
3. `docs/CONTEXT_FOR_AI.md`
4. `AGENTS.md`
5. `docs/STAGING_VM_RUNBOOK.md` while PR #8 / staging work is active
6. Historical architecture decisions only when their validated contract is being implemented.

## What this project is

ViMi Social is a production **Telegram-first, AI-first, automation-first** multi-tenant SaaS for discovering/receiving content, analyzing it, creating destination-specific variants, publishing safely and operating recurring content workflows.

Telegram is the primary customer interface. Web/Next.js is secondary.

Do not restart broad architecture research. The architecture laboratory is historical. New work should deliver a small production slice while preserving the validated reliability/security contracts.

## Repository reality

Production repository: `Aragova/vimi-social`.

Merged product path through PR #7 now covers:

```text
Telegram
-> AI Search
-> durable Scout / official X source connector
-> CandidateContent
-> rights/provenance gate
-> secure media acquisition + MediaProbe
-> scene detection/ranking
-> sampled-frame visual moderation
-> destination preflight
-> VariantPlanner
-> RenderService
-> Telegram preview
-> explicit approval
-> X v2 media upload / POST /2/tweets
-> durable result / UNKNOWN / reconciliation
```

PR #7 is merged into `main` at `a5d693ab8ec38d14995f25b6cfe1f66c185d626f`.

## Current active task

PR #8 on `feat/staging-vm-deployment` is the active slice.

Do **not** jump to OAuth, new destinations, dashboards or broad feature work before the first real staging exercise unless a deployment blocker requires a code change.

PR #8 builds a single-VM staging topology containing:

- Caddy HTTPS ingress;
- Telegram bot;
- core Temporal worker;
- media worker with ffmpeg/ffprobe;
- destination worker;
- internal API process;
- PostgreSQL 17;
- Temporal;
- persistent local media/PostgreSQL/Caddy volumes;
- one-shot Alembic migrations;
- staging secret template and operator helpers.

PostgreSQL and Temporal must not be exposed publicly. The dev/CI trust-auth PostgreSQL bootstrap must not be reused on the VM.

The deployment runbook is `docs/STAGING_VM_RUNBOOK.md`.

## Required staging evidence

After PR #8 is merged, deploy `main` to the staging VM and manually prove:

1. public HTTPS bot health;
2. Telegram webhook delivery;
3. `/start` identity/workspace provisioning;
4. AI Search through the official X source connector;
5. rights-gated media acquisition;
6. MediaProbe + scene analysis + visual moderation;
7. policy preflight + variant planning/rendering;
8. Telegram video preview and approval;
9. exactly one real X publication;
10. worker restart / ambiguous-publication failure drills without duplicate posts.

Operational defects discovered by this exercise take priority over feature expansion.

## Fundamental source model

Three first-class source modes remain canonical:

1. **AI Search** — primary automated path through source-specific connectors.
2. **Manual Upload** — user-supplied asset entering the common downstream pipeline.
3. **Source Feed** — persistent authorized Telegram source consumed under automation policy.

They converge into one downstream pipeline. Do not build three processing systems.

## Adult/18+ workload

Legal adult/18+ content, including explicit gay adult material, is an expected frequent workload. Adult classification, scene-level suitability, provenance/rights metadata and destination policy eligibility are normal pipeline concerns.

Destination decisions remain:

```text
DIRECT_ALLOWED
ADAPTATION_REQUIRED
MANUAL_REVIEW_REQUIRED
BLOCKED
```

Adaptation must produce a genuinely policy-compliant derivative. Never disguise prohibited content or attempt to bypass moderation/access controls.

Visual moderation is evidence about sampled frames; it is not proof of age, consent or redistribution rights.

## International / regional contract

- persisted event timestamps: UTC;
- schedules/quiet hours: IANA timezone IDs;
- initial UI locales: Russian + English;
- UI locale != content language != search language != destination/account language;
- Telegram `language_code` is only an initial hint;
- region/country is separate from language;
- money always has ISO 4217 currency;
- recurring schedules preserve local wall-clock intent across DST;
- VM/server timezone never defines customer schedule behavior.

## Workspace / brand / accounts

Do not assume one tenant equals one social account or brand.

Conceptual shape:

```text
User -> Membership -> Workspace/Tenant -> Brand/Project
                                      -> Sources/SourceFeeds
                                      -> Connected destination accounts
                                      -> Automation policies
```

User UI/notification preferences remain separate from workspace/brand publishing defaults.

## Architecture invariants

1. Stable `operation_key` identity for externally visible operations.
2. Ambiguous external mutations become `UNKNOWN`; never blind-retry.
3. PostgreSQL is the commercial-usage correctness authority.
4. Quota is reserved atomically before expensive work; ledger is append-only.
5. Tenant context is transaction-local; app DB roles are non-owner/non-superuser/NOBYPASSRLS.
6. Caller-controlled tenant IDs are never authority.
7. Telegram identity is resolved server-side into ViMi user/workspace authority.
8. Remote/discovered media is untrusted and goes through secure ingest/isolation.
9. AI has no unrestricted shell/DB/secrets/network authority.
10. Bot handlers, source connectors and provider adapters do not own core business rules.
11. Platform/content policies are versioned/testable, not scattered ad-hoc conditionals.
12. Privileged cross-tenant access must be narrow, explicit and auditable.
13. Destination secrets are referenced, not stored in plaintext in tenant tables.
14. A worker recovery attempt must not repeat an irreversible mutation merely because the prior attempt outcome is unknown.

## Work after staging succeeds

In priority order:

1. X OAuth / account connection and destination management.
2. Caption/editing and destination-selection UX.
3. Manual Upload through the common pipeline.
4. Telegram Source Feed with concurrency-safe claiming, durable cursors and timezone-aware cadence.
5. Shared object storage before horizontal media-worker scaling.
6. Backups/restore, observability and deployment hardening.
7. Additional destination adapters after the X path is operationally understood.

## Sources of truth

`docs/PRODUCT_VISION.md` is the canonical product concept. `docs/PROJECT_STATUS.md` is the live implementation status. `docs/STAGING_VM_RUNBOOK.md` is the current deployment procedure. Historical architecture under `docs/history/` remains authoritative for validated security/reliability contracts unless explicitly superseded.
