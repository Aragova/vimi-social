# ViMi Social — Project Status

**Updated:** 2026-10-21  
**Repository:** `Aragova/vimi-social`  
**Phase:** Production implementation — foundation hardening before Telegram/AI-first vertical slice 1

## Completed

- Architecture Baseline 0.9/0.10, Red-Team v1, PoCs A–E, post-PoC decisions and Red-Team v2 completed.
- Architecture PR #8 merged at `6252c6f4e425006f927f7b5e5556c96ecb37d245`.
- Production repository created; historical architecture/PoC evidence preserved under `docs/history/`.
- Canonical product concept finalized in `docs/PRODUCT_VISION.md`:
  - Telegram-first;
  - AI-first / automation-first;
  - three source modes: AI Search, Manual Upload, Source Feed;
  - typed Source Connector Registry;
  - adult/18+ content as a first-class workload;
  - platform-policy-aware compliant variants;
  - UTC + IANA timezone model;
  - RU/EN localization architecture;
  - separate UI/content/search/destination languages;
  - region and currency-aware data model;
  - workspace/brand/multi-account readiness.
- Production foundation concept-alignment audit recorded in `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md`.
- Audit conclusion: **keep the foundation; do not restart**.
- PR #1 identity boundary corrected: `ExecutionContext` is now trusted/source-neutral; Telegram is the first customer identity adapter and managed IdP is optional for web/admin.
- Codex P1 Alembic logging blocker fixed.
- Codex P1 usage-reservation concurrent-first-seen race fixed by porting the verified PoC E reservation ordering.
- Both original Codex P1 review threads resolved.
- Current PR #1 head: `f158b1ba573d0f03d0283b226c39bbc03a068391`.
- CI run `39640557288` (#7) on that head: **SUCCESS** (backend + web).
- Fresh Codex review requested on the current head after the fixes.

## Current goal

Finish foundation hardening/review without expanding the wrong product surface, then merge PR #1 and begin the real Telegram/AI-first vertical slice.

The next remaining foundation correctness priority is PostgreSQL production-role/RLS integration evidence:

- separate migration owner and application role;
- application role non-owner/non-superuser/NOBYPASSRLS;
- explicit grants;
- CI PostgreSQL service + migrations;
- tests proving fail-closed no-tenant behavior, cross-tenant denial and transaction-local context non-leakage.

After that, the first real product path is:

```text
Telegram /start
-> trusted Telegram identity/workspace resolution
-> localized RU/EN-ready onboarding/menu
-> user chooses AI Search
-> user describes desired content/task
-> Scout routes to one authorized source connector
-> normalized candidates + Curator
-> MediaProbe + SceneDetector + SceneRanker
-> adult/content classification + destination policy preflight
-> VariantPlanner creates/recommends one compliant variant
-> Telegram preview/approval
-> tenant-scoped usage reservation + persisted operation
-> Temporal workflow
-> one real destination adapter
-> Telegram status
-> UNKNOWN-safe reconciliation
```

Deploy to staging/VM as soon as this works end-to-end for one authorized source and one real destination.

## Immediate implementation sequence

1. Finish fresh Codex review of PR #1 and address any new findings.
2. Add production-like PostgreSQL role/grant bootstrap and DB integration CI/RLS tests.
3. Merge PR #1 only when CI/review gates are clean.
4. Add first-class Telegram bot process/ingress with duplicate-update idempotency.
5. Add early international primitives: localization resources (`ru`, `en`), IANA timezone types/defaults, locale/region/content-language separation, currency-aware Money.
6. Add Telegram user/membership/workspace mapping compatible with future Brand/Project and multiple connected accounts.
7. Build `/start`, localized onboarding, source selection and main menu.
8. Add typed source domain with AI Search / Manual Upload / Source Feed.
9. Implement Source Connector Registry and one real authorized source connector for Scout.
10. Persist candidate/source provenance metadata and route discovered media through secure ingest.
11. Add Curator/media/scene-analysis contracts, adult classification and destination preflight.
12. Add VariantPlanner/render path and Telegram preview/approval.
13. Bind `operation_key`, reserve usage, persist operation and compose Temporal through the validated durable-authority pattern.
14. Dispatch through one real destination adapter; surface status and reconcile UNKNOWN safely.
15. Deploy to staging/VM and test through a real Telegram account.
16. Add Manual Upload through the same downstream pipeline.
17. Add Telegram Source Feed (channel/group/topic) with idempotent item claiming and timezone-aware cadence.

## Definition of done for vertical slice 1

- Telegram customer path does not require web login.
- RU/EN-ready bot onboarding/menu works.
- Telegram identity resolves server-side to ViMi workspace authority.
- User can choose AI Search and describe a task.
- One real source connector returns normalized candidates with provenance metadata.
- Curator selects/ranks candidate material.
- Media/scene analysis and adult/explicitness classification are normal pipeline stages.
- One real destination produces DIRECT / ADAPT / REVIEW / BLOCKED decision.
- One usable direct/compliant variant can be previewed in Telegram.
- Usage is atomically reserved before expensive/external work.
- Duplicate Telegram updates/operation starts do not double-reserve or double-dispatch.
- Cross-tenant access is blocked by production-like RLS roles.
- Ambiguous provider outcome becomes `UNKNOWN`, never blind retry.
- Persisted event timestamps are UTC; schedules use IANA timezones.
- Customer-facing strings are localization-key based rather than hard-coded through business logic.
- CI including DB/bot tests is green.
- Slice runs on staging/VM and is manually exercised through Telegram.

## Fundamental Source Feed follow-up

Source Feed is one of the three core source modes, not a distant optional feature:

```text
Telegram channel/group/topic
-> SourceFeed
-> claim next unprocessed item
-> common analysis/adaptation pipeline
-> automation policy
-> publish
-> record outcome
-> timezone-aware cadence
-> next item
```

Source-item identity and claiming must be concurrency-safe and idempotent.

## International / regional guardrails

- Persist UTC instants.
- Use IANA timezone IDs for schedules/quiet hours.
- Initial UI locales: `ru`, `en`.
- UI locale != content language != search language != destination language.
- Telegram `language_code` is an initial hint only.
- Region/country is distinct from language.
- Money is amount + ISO 4217 currency.
- Full translation catalogue, global tax engine and full KYC are not MVP blockers, but the model must not assume one timezone/language/currency.

## Web scope

Next.js/web remains secondary: landing/marketing, OAuth callbacks, optional dashboards, analytics/admin. Do not prioritize a full customer web dashboard ahead of Telegram/AI workflows.

## Sources of truth

1. `docs/PRODUCT_VISION.md`
2. `docs/PROJECT_STATUS.md`
3. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md`
4. `docs/CONTEXT_FOR_AI.md`
5. `AGENTS.md`
6. `docs/history/`
