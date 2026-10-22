# ViMi Social — Project Status

**Updated:** 2026-10-21  
**Repository:** `Aragova/vimi-social`  
**Phase:** Production implementation — durable AI Search / Scout slice

## Completed baseline

- Architecture Baseline 0.9/0.10, Red-Team v1/v2, PoCs A–E and post-PoC decisions are complete and preserved under `docs/history/`.
- The finalized product concept is canonical in `docs/PRODUCT_VISION.md`: Telegram-first, AI-first, automation-first, with AI Search / Manual Upload / Source Feed as the three first-class source modes.
- Production foundation PR #1 is merged. Merge commit: `7811892d02f8d454a968c3877b53f1b7ad7b6a18`.
- Telegram-first entrypoint PR #2 is merged. Merge commit/current base for the Scout slice: `6b7ec905e7f7d6f7b4f37a7bbdef9982259ad4db`.
- Foundation correctness work is complete enough to build product slices without restarting architecture research:
  - PostgreSQL RLS with production-like non-owner, non-superuser, NOBYPASSRLS application role;
  - explicit DB grants and PostgreSQL integration CI;
  - fail-closed tenant context and cross-tenant denial tests;
  - atomic usage reservation with duplicate-operation joining;
  - append-only usage ledger;
  - stable operation identity and UNKNOWN/no-blind-retry semantics for external mutation shells.
- Telegram entrypoint now provides:
  - separate bot process and verified webhook secret;
  - server-side Telegram identity -> app user -> membership -> workspace resolution;
  - personal workspace provisioning on first `/start`;
  - RU/EN localization primitives and international domain primitives;
  - localized main menu and source selection;
  - AI Search / Manual Upload / Source Feed entry choices;
  - durable incoming-update idempotency;
  - stable outgoing Telegram operation identity;
  - UNKNOWN handling and Telegram 429 delayed retry semantics.

## Current work — PR #4

Active PR: **`feat: durable AI Search Scout pipeline`** on branch `feat/source-task-scout`.

The slice moves the product from a Telegram menu to a real durable AI Search workflow:

```text
Telegram
-> choose AI Search
-> durable conversation state
-> user intent
-> tenant-bound SourceTask + scout_run reservation
-> Temporal ScoutWorkflow
-> SourceConnectorRegistry
-> real authorized source connector
-> normalized CandidateContent
-> persisted candidates
-> Telegram results / selection
```

Implemented in the active PR:

- durable `SourceTask` with stable operation key and actor/workspace binding;
- durable Telegram `AWAITING_AI_SEARCH_INTENT` conversation state;
- `scout_run` usage reservation bound to the source-task operation key;
- usage commit when connector work starts and release when work is proven not to have started;
- Temporal `ScoutWorkflow` rather than FastAPI background tasks;
- typed `SourceConnector` + registry/router;
- first real connector through the official X API v2 Recent Search endpoint;
- no generic scraping and no assumption that public availability grants redistribution rights;
- normalized `CandidateContent` persistence with provenance/availability hints;
- RLS protection for source tasks, conversation state and candidates;
- narrow background authority restoration via stable operation key + random execution token;
- dedicated NOLOGIN resolver role for the narrow cross-tenant lookup while `vimi_app` remains NOBYPASSRLS;
- localized Telegram result cards with View / Select / Search more;
- unit and PostgreSQL integration coverage for routing, X normalization, usage idempotency and tenant isolation.

The X connector in this slice is discovery/metadata-only. It does **not** download discovered media and does **not** establish reuse rights.

## Immediate next step after PR #4

Build the next vertical slice around the selected candidate:

```text
selected CandidateContent
-> Curator/ranking boundary
-> permitted media acquisition
-> provenance / rights gate
-> secure ingest of untrusted media
-> MediaProbe
-> base content + adult classification
-> persisted asset lineage
-> Telegram status/preview
```

Do not jump directly to broad rendering or many destinations before this acquisition/probe boundary is reliable.

After that:

1. SceneDetector + feature extraction + SceneRanker + scene-level explicitness.
2. Platform Capability/Compliance preflight + VariantPlanner.
3. One real Destination Adapter with stable operation identity, typed outcomes, UNKNOWN and reconciliation.
4. Early staging/VM deployment and manual exercise through a real Telegram account.
5. Manual Upload through the same downstream pipeline.
6. Telegram Source Feed with concurrency-safe claiming, durable cursors and timezone-aware cadence.

## Definition of done for vertical slice 1

- Telegram customer path does not require web login.
- RU/EN-ready bot onboarding/menu works.
- Telegram identity resolves server-side to ViMi workspace authority.
- User can choose AI Search and describe a task.
- One real source connector returns normalized candidates with provenance metadata.
- Candidate selection feeds the common downstream pipeline.
- Media/scene analysis and adult/explicitness classification are normal pipeline stages.
- One real destination produces DIRECT / ADAPT / REVIEW / BLOCKED decision.
- One usable direct/compliant variant can be previewed in Telegram.
- Usage is atomically reserved before expensive work.
- Duplicate Telegram updates/operation starts do not double-reserve or double-dispatch.
- Cross-tenant access is blocked by production-like RLS roles.
- Ambiguous external mutation outcome becomes `UNKNOWN`, never blind retry.
- Persisted event timestamps are UTC; schedules use IANA timezones.
- Customer-facing strings are localization-key based rather than hard-coded through business logic.
- CI including DB/bot tests is green.
- Slice runs on staging/VM and is manually exercised through Telegram.

## Fundamental Source Feed follow-up

Source Feed remains one of the three core source modes, not a distant optional feature:

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
3. `docs/CONTEXT_FOR_AI.md`
4. `AGENTS.md`
5. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md` for the historical foundation alignment decision
6. `docs/history/` for validated architecture rationale and PoC evidence
