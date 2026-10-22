# ViMi Social — Project Status

**Updated:** 2026-10-22  
**Repository:** `Aragova/vimi-social`  
**Phase:** First real staging/VM deployment and end-to-end Telegram → X exercise

## Completed production slices

Architecture research/PoCs are historical and complete. Do not restart broad architecture work unless production evidence exposes a concrete contract defect.

Merged production milestones:

- PR #1 — production foundation;
- PR #2 — Telegram-first customer entrypoint;
- PR #4 — durable AI Search / Scout pipeline with official X source search;
- PR #5 — rights-gated secure media acquisition and MediaProbe;
- PR #6 — durable scene detection/ranking, destination preflight and VariantPlanner;
- PR #7 — sampled-frame visual moderation, RenderService, Telegram preview/approval and first real X publication path.

Current `main` after PR #7: `a5d693ab8ec38d14995f25b6cfe1f66c185d626f`.

The first real product path now exists in code:

```text
Telegram
-> AI Search
-> SourceTask / Scout
-> official X source connector
-> CandidateContent
-> rights/provenance gate
-> secure media acquisition
-> MediaProbe
-> scene detection + ranking
-> sampled-frame visual moderation
-> destination capability/compliance preflight
-> VariantPlanner
-> RenderService / PlatformVariant artifact
-> Telegram video preview
-> explicit publication approval
-> X v2 chunked media upload
-> POST /2/tweets
-> durable publication result / UNKNOWN / reconciliation
```

## Reliability/security state already implemented

- PostgreSQL RLS tenant isolation with normal app role non-owner/non-superuser/NOBYPASSRLS.
- Narrow privileged identity/source authority restoration rather than caller-selected tenant IDs.
- Atomic usage reservation and append-only usage ledger.
- Stable operation identity for externally visible work.
- External mutation fencing: ambiguous outcomes become `UNKNOWN`; no blind republish.
- Retry recovery after a worker crash performs zero duplicate X mutation when a prior dispatch attempt is already durably claimed.
- Remote media treated as untrusted with URL/DNS/redirect validation, bounded acquisition and isolated media work.
- Rights/provenance gate before media preparation.
- Explicit/sensitive or incomplete visual evidence does not authorize automatic publication.
- Telegram preview/approval is required before the current real X destination mutation.
- Destination credential values remain outside PostgreSQL; rows store secret references only.

## Current work — PR #8

Active PR: **`infra: deployable single-VM staging stack`** on branch `feat/staging-vm-deployment`.

Goal: stop extending the product blindly and exercise the existing end-to-end slice on a real VM.

PR #8 is responsible for:

- Python runtime image with ffmpeg/ffprobe;
- single-VM Docker Compose staging topology;
- PostgreSQL 17 with password-backed staging bootstrap and separate migrator/app roles;
- Temporal;
- Telegram bot;
- core Temporal worker;
- isolated media worker;
- isolated destination worker;
- internal API process;
- Caddy HTTPS ingress for Telegram webhook;
- persistent PostgreSQL/media/Caddy volumes;
- no public PostgreSQL or Temporal ports;
- one-shot Alembic migration service;
- staging env template with no committed secrets;
- operator helper for Telegram webhook registration;
- temporary operator helper for one X destination account until OAuth/account-management UX exists;
- deployment CI checks;
- `docs/STAGING_VM_RUNBOOK.md` with exact staging and smoke-test procedure.

## Definition of done for PR #8

- Existing backend/database/web CI stays green.
- Staging Compose model validates in CI.
- Caddy configuration validates in CI.
- Runtime Docker image builds in CI.
- Staging PostgreSQL bootstrap script passes syntax validation and uses passwords rather than trust auth.
- Alembic can use a staging migrator DSN without changing normal CI behavior.
- No secret values are committed.
- PR receives exact-head Codex review before merge.

After merge, PR #8 is **not complete as a product milestone until the stack is actually deployed to a VM and manually exercised**.

## Immediate post-merge staging exercise

Follow `docs/STAGING_VM_RUNBOOK.md`:

1. Prepare Linux VM + DNS + Docker.
2. Clone `main` and create `.env.staging` from the example.
3. Bring up the stack.
4. Verify public HTTPS `/health`.
5. Configure Telegram webhook.
6. Send `/start` through a dedicated staging bot.
7. Provision one staging X destination account by secret reference.
8. Run the real AI Search → preview → X publication path.
9. Confirm exactly one X post appears.
10. Run controlled worker-restart/failure drills and verify UNKNOWN/no-duplicate behavior.

Production evidence from this exercise should drive fixes before adding broad new features.

## Next product work after staging evidence

Assuming the staging path is healthy:

1. X OAuth / customer account connection and destination-account management.
2. Better caption generation/editing and destination selection UX.
3. Manual Upload through the same downstream pipeline.
4. Telegram Source Feed with durable cursors, concurrency-safe claiming and timezone-aware cadence.
5. Shared object storage before horizontal media-worker scaling.
6. Backups/restore automation, observability and deployment hardening before public multi-tenant production traffic.
7. Additional destination adapters only after the first X path is operationally understood.

## Fundamental source model

Three first-class modes remain canonical:

1. **AI Search** — automated discovery through source-specific connectors.
2. **Manual Upload** — user-provided content entering the common pipeline.
3. **Source Feed** — authorized Telegram source consumed as a persistent queue under automation policy.

Do not fork these into separate processing systems; they converge on the same analysis/adaptation/publication pipeline.

## International / regional guardrails

- Persist UTC instants.
- Use IANA timezone IDs for schedules/quiet hours.
- Initial UI locales: `ru`, `en`.
- UI locale != content language != search language != destination language.
- Telegram `language_code` is an initial hint only.
- Region/country is distinct from language.
- Money is amount + ISO 4217 currency.
- VM timezone is never customer schedule authority.

## Web scope

Next.js/web remains secondary: landing/marketing, OAuth callbacks, optional dashboards, analytics/admin. Do not prioritize a full customer dashboard ahead of Telegram workflows and account connection.

## Sources of truth

1. `docs/PRODUCT_VISION.md`
2. `docs/PROJECT_STATUS.md`
3. `docs/CONTEXT_FOR_AI.md`
4. `AGENTS.md`
5. `docs/STAGING_VM_RUNBOOK.md` for the current deployment exercise
6. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md` for historical foundation alignment
7. `docs/history/` for validated architecture/PoC rationale
