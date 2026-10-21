# ViMi Social — Project Status

**Updated:** 2026-10-21  
**Repository:** `Aragova/vimi-social`  
**Phase:** Production implementation — concept alignment + Telegram/AI-first vertical slice 1

## Completed

- Architecture Baseline 0.9 and 0.10 produced.
- Red-Team v1 completed.
- Executable PoCs A–E completed and passed.
- Post-PoC decisions captured.
- Red-Team v2 composition audit completed and release-blocking findings remediated.
- Architecture PR #8 merged to `Aragova/vimi-social-architecture-poc` main at `6252c6f4e425006f927f7b5e5556c96ecb37d245`.
- Production repository `Aragova/vimi-social` created.
- Historical architecture/PoC evidence copied under `docs/history/`.
- Production foundation PR #1 created; latest verified CI on head `ea49ae3438f0b83fc67caf6bfa44fe4e3859ffe0` passed backend and web jobs.
- Canonical product direction finalized in `docs/PRODUCT_VISION.md`:
  - Telegram-first customer interface;
  - AI-first/automation-first operation;
  - three fundamental source modes: AI Search, Manual Upload, Source Feed;
  - Source Feed may consume a Telegram channel/group/topic as a persistent queue;
  - source-specific connector registry rather than generic web search only;
  - adult/18+ content is a first-class frequent workload;
  - platform-policy-aware compliant variants, never moderation evasion;
  - international-ready from the beginning: UTC + IANA timezones, RU/EN localization architecture, region, language separation and currency-aware money;
  - workspace/brand/multi-account readiness.

## Current goal

Before extending PR #1 blindly, align the existing foundation with the finalized product concept and preserve only the parts that remain correct.

Then build the first real **Telegram-native, AI-first** production vertical slice:

```text
Telegram /start
-> trusted Telegram ingress + server-side identity/workspace resolution
-> localized onboarding/main menu
-> user chooses AI Search
-> user describes desired content/task
-> Scout routes to one authorized real source connector
-> candidates normalized + Curator ranking
-> MediaProbe + SceneDetector + SceneRanker
-> adult/content classification + destination policy preflight
-> VariantPlanner creates/recommends one compliant variant
-> Telegram preview/approval
-> tenant-scoped usage reservation + persisted operation
-> Temporal workflow
-> one real provider adapter
-> Telegram status
-> UNKNOWN-safe reconciliation
```

The first staging/VM deployment should happen as soon as this path works end-to-end for one authorized source and one real destination.

## Immediate implementation sequence

1. Complete and record the production-foundation concept-alignment audit.
2. Keep the validated modular-monolith, PostgreSQL/RLS, Temporal, usage, operation identity, media-worker and CI foundations.
3. Correct the identity boundary: `ExecutionContext` must be source-neutral/trusted; Telegram identity resolution is the first customer path, while managed IdP becomes a web/admin adapter rather than the mandatory customer gate.
4. Harden PostgreSQL production roles/grants and add integration CI using the real non-owner/NOBYPASSRLS application role.
5. Fix usage reservation concurrency so concurrent first-seen identical operation keys cannot double-increment reserved capacity.
6. Add first-class Telegram bot process/ingress and duplicate-update idempotency.
7. Add internationalization primitives early: localization keys/resources, RU + EN, IANA timezone types/defaults, locale/region/content-language separation, currency-aware money types.
8. Add user/workspace/brand/account identity model sufficient for Telegram-first operation and future multi-brand/multi-account use.
9. Build `/start`, localized onboarding, source selection and main menu.
10. Implement the three source concepts in the domain contract:
    - AI Search (first executable source),
    - Manual Upload (secondary),
    - Source Feed (persistent channel/group/topic queue; early production follow-up).
11. Implement typed Source Connector Registry and one real authorized source connector for Scout.
12. Persist candidate/source provenance metadata and pass all remote/discovered media through secure ingest.
13. Add Curator/media/scene-analysis contracts and first usable candidate selection path.
14. Add adult/explicitness classification and destination policy preflight.
15. Add VariantPlanner/render path and Telegram preview/approval.
16. Bind `operation_key`, reserve usage, persist publication authority and start Temporal through the validated durable composition pattern.
17. Dispatch to one real destination adapter, surface status in Telegram and reconcile UNKNOWN safely.
18. Deploy the working slice to staging/VM and test it from a real Telegram account.
19. Add Manual Upload through the same downstream pipeline.
20. Add Telegram Source Feed with timezone-aware cadence and item claiming/idempotency.

## Definition of done for vertical slice 1

- User opens the Telegram bot and receives RU/EN-ready onboarding/menu.
- Telegram identity is resolved server-side to ViMi user/workspace authority; arbitrary tenant selection is impossible.
- The user can choose AI Search and describe a task without uploading a finished asset.
- Scout can query one real authorized source connector and preserve source/provenance metadata.
- Curator can rank/select candidate material.
- Media/scene analysis and adult/explicitness classification are normal pipeline steps.
- One real destination can be classified as direct/adaptation/review/blocked.
- At least one direct or genuinely compliant adapted variant can be previewed in Telegram.
- Usage is atomically reserved before expensive/external work.
- Duplicate Telegram updates/operation starts do not double-reserve or double-dispatch.
- Cross-tenant access is blocked by application context and production-like PostgreSQL RLS roles.
- Lost/ambiguous provider responses become `UNKNOWN`, not blind retry authorization.
- Reconciliation advances state only from typed provider evidence.
- All persisted timestamps are UTC; customer schedules are expressed in IANA timezones.
- UI localization architecture supports RU and EN without hard-coded business-layer strings.
- Ruff, strict Pyright, pytest and DB/bot integration tests pass.
- The slice runs on staging/VM and is manually exercised through Telegram.

## Early follow-up: Source Feed

Source Feed is one of the three fundamental source modes and must not be treated as a distant optional feature.

Early production behavior:

```text
Telegram channel/group/topic
-> persistent SourceFeed
-> claim next unprocessed item
-> common analysis/adaptation pipeline
-> publish according to automation policy
-> mark item outcome
-> wait timezone-aware cadence
-> next item
```

The system must track source item identity and prevent duplicate/concurrent claiming.

## Internationalization / regionalization contract

- Persist event timestamps as UTC instants.
- Use IANA timezone identifiers for schedules and quiet hours.
- Do not use VM/server timezone as customer behavior.
- Initial UI locales: `ru`, `en`.
- UI locale, content language, search language and destination/account language are separate concepts.
- Region/country is separate from language and may affect platform/adult/payment policy.
- Money is always `(amount, ISO 4217 currency)` rather than a bare number.
- Telegram `language_code` is only an initial locale hint; users can override it.
- Full global translations, tax engines and age/KYC systems are not MVP blockers, but the data model must not prevent them.

## Web scope

Next.js/web remains in the repository but is secondary. Near-term roles:

- marketing/landing page;
- OAuth/provider callbacks;
- optional linked dashboard;
- richer analytics/admin tools.

Do not prioritize a full web customer dashboard ahead of the Telegram/AI workflow.

## What not to do

- Do not restart architecture discovery as the default next step.
- Do not throw away validated Architecture 1.0 contracts because product UX/source priority changed.
- Do not turn the product back into web-first or manual-upload-first software.
- Do not make managed web IdP a prerequisite for Telegram customer use.
- Do not hard-code customer-facing strings, one timezone or one currency throughout business logic.
- Do not model one tenant as exactly one brand/account.
- Do not put business logic directly in Telegram handlers or source connectors.
- Do not bypass source/platform access controls or moderation.
- Do not publish a prohibited asset by disguising it; adaptation must actually satisfy the destination policy.

## Sources of truth

1. `docs/PRODUCT_VISION.md` — canonical product concept.
2. `docs/PROJECT_STATUS.md` — live implementation status.
3. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md` — current foundation review and remediation decisions.
4. `docs/CONTEXT_FOR_AI.md` — compact handoff.
5. `AGENTS.md` — engineering constraints.
6. `docs/history/` — validated historical architecture evidence.