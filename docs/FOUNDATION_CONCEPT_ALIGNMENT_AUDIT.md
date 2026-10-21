# ViMi Social — Production Foundation Concept Alignment Audit

**Date:** 2026-10-21  
**Scope:** production foundation PR #1 (`feat/production-foundation`, head `ea49ae3438f0b83fc67caf6bfa44fe4e3859ffe0`) versus the finalized `docs/PRODUCT_VISION.md`.

## Executive conclusion

The foundation is **not a throwaway**. Most architecture-level choices remain correct and should be preserved. The clarified product concept changes product-entry priorities and introduces missing domain concepts, but it does not invalidate Architecture 1.0.

The correct response is:

```text
KEEP validated backend foundations
+ CHANGE identity/customer-entry assumptions
+ ADD Telegram/source/international domain primitives
+ HARDEN DB/usage correctness
+ DEFER secondary/full-scope features
```

There is currently no justification for deleting the production repository or restarting architecture research.

## KEEP — correct and reusable

### Modular-monolith Python/FastAPI foundation

Keep. Backend application services/API boundaries remain useful for Telegram, workers and optional web surfaces.

### PostgreSQL + RLS direction

Keep. Tenant isolation remains a non-negotiable Architecture 1.0 contract.

### Transaction-local tenant helper

Keep. The fail-closed tenant transaction pattern is still the intended boundary.

### Stable `operation_key`

Keep. AI Search, Manual Upload and Source Feed all need stable logical operation identity and idempotency.

### Usage authority / reservation / append-only ledger model

Keep the model. It is required for Scout runs, AI/media work, Source Feed, publications and future billing. The current implementation needs concurrency hardening before it is production-complete.

### Temporal

Keep. Temporal is even more useful under the finalized concept because ViMi now has long-lived Scout/media/Source Feed/scheduling/publication/reconciliation workflows.

### Isolated media-worker boundary

Keep. AI-discovered and user-supplied media are both untrusted.

### Strict Ruff / Pyright / pytest CI

Keep and expand with PostgreSQL integration and bot/source tests.

### Next.js skeleton

Keep, but **demote**. It is cheap scaffolding and still useful for landing/OAuth/analytics/admin. Do not make it the main customer workflow or prioritize a large dashboard now.

## CHANGE NOW — concept mismatch or production correctness issue

### 1. Managed-IdP-only execution context assumption

Current branch documentation/code says `ExecutionContext` is produced only by the managed-IdP adapter and fails closed until an IdP resolver exists.

This no longer matches the product.

Required correction:

```text
TrustedIdentityAdapter
├── TelegramIdentityResolver   <- first customer path
└── ManagedIdPResolver         <- optional web/admin path
        ↓
ExecutionContext
```

`ExecutionContext` itself remains a good abstraction; only its producer assumption changes.

Telegram user/chat/update fields must never directly become arbitrary tenant authority. Resolve immutable Telegram identity server-side to ViMi user/membership/workspace.

### 2. Missing first-class Telegram bot process/ingress

PR #1 has API, worker, media-worker and web, but no Telegram bot application/process boundary.

Add a first-class bot/ingress process. Handlers remain thin interface code and call application services.

### 3. Missing three-source domain model

The current foundation has no explicit domain for:

- AI Search;
- Manual Upload;
- Source Feed.

Add typed source concepts so all three converge into one processing pipeline.

### 4. Missing Source Connector Registry

Scout must use source-specific connectors. Do not implement discovery as one generic `httpx`/browser search function spread through application code.

Add typed connector capabilities/normalized candidate records and one real connector first.

### 5. Missing Source Feed model

Add early domain/storage concepts for:

- source feed identity;
- Telegram channel/group/topic reference;
- source item identity;
- claim state/idempotency;
- last/next item behavior;
- cadence/automation policy;
- destination set;
- publication lineage.

Source Feed is an early production capability, not a distant optional feature.

### 6. Missing internationalization/timezone/currency primitives

Current customer-facing web shell hard-codes English, and the backend has no explicit timezone/locale/region/money types yet.

Required architecture direction now:

- UTC persisted event timestamps;
- IANA timezone for schedules;
- RU + EN localization resources from the first bot UI;
- separate UI locale / content language / search language / destination language;
- separate region/country;
- ISO-4217 currency-aware `Money`;
- future quiet-hours support.

Do not build many translations now; build the model correctly now.

### 7. Workspace/Brand/multi-account readiness

Current bootstrap only has a minimal `tenant` table. That is acceptable as bootstrap, but do not evolve it assuming one tenant == one brand == one social account.

Target conceptual model:

```text
User -> Membership -> Workspace/Tenant -> Brand/Project
                                      -> Sources/Feeds
                                      -> Destination accounts
                                      -> Automation policies
```

### 8. PostgreSQL production role/grant gap

The migration enables/forces RLS, but does not create/configure production-like migration/app roles or grants. Local Docker creates `vimi_migrator`, while application config expects `vimi_app`.

Required correction before claiming DB isolation is production-ready:

- migration owner separated from application role;
- app role non-owner, non-superuser, NOBYPASSRLS;
- explicit grants;
- CI PostgreSQL service;
- Alembic migrations in CI;
- RLS tests executed as the production-like app role;
- fail closed without tenant context;
- cross-tenant access blocked;
- transaction-local context proven not to leak through pool reuse.

### 9. Usage reservation concurrent-first-seen race

Current `UsageRepository.reserve()` reads an existing reservation, increments capacity, then inserts the unique reservation. Two concurrent first-seen requests for the same operation key can both increment capacity before one unique insert loses.

This is a known correctness blocker. Port the stronger PoC E semantics deliberately and add synchronized concurrency tests.

### 10. API publication endpoint is not the main UX

`POST /v1/publications` can remain as an application/API boundary, but it must not define the product flow. Telegram/Scout/Source Feed workflows should call the same underlying application/domain services rather than being forced through a web-centric request model.

### 11. Publication workflow shell is only a placeholder

Keep the Temporal worker/workflow boundary, but do not mistake the 1 ms placeholder for the final composition. The real workflow must follow the validated durable authority/outbox/fencing/UNKNOWN contracts before external mutation.

## ADD EARLY — product-defining capabilities

1. Telegram bot + trusted ingress.
2. Localization resources (`ru`, `en`) and locale/timezone primitives.
3. User/membership/workspace identity mapping from Telegram.
4. Source selection UI: AI Search / Add Content / Channel-Group-Topic.
5. Source domain + normalized `CandidateContent`.
6. Source Connector Registry + first real connector.
7. Adult/content classification + Platform Capability/Compliance preflight.
8. VariantPlanner/render contract.
9. Telegram preview/approval.
10. Source Feed persistent queue after initial AI Search end-to-end slice.
11. Multi-brand/multi-account-ready ownership model before large-scale account integration.

## DEFER — do not block first VM deployment

- full customer web dashboard;
- 10–20 UI languages (start RU + EN);
- global tax engine;
- broad currency catalogue (be currency-aware now, expose few initially);
- full KYC/age-verification platform (model eligibility state now);
- every Source Connector;
- every destination platform;
- advanced analytics-driven optimal-post-time scheduler;
- sophisticated cross-brand enterprise RBAC beyond the architecture-ready model.

## REMOVE

**No major component needs to be deleted at this stage.**

Do not remove Next.js merely because Telegram became primary. Do not delete FastAPI because the bot is primary. Do not replace PostgreSQL/Temporal/RLS. The problem was product priority, not the validated backend contracts.

Only remove code later if it proves unused or harmful after the aligned product slices are running.

## PR #1 disposition

PR #1 should be treated as **foundation that requires alignment/hardening before merge**, not as the final vertical slice and not as discarded work.

Recommended path:

1. keep PR #1 open;
2. patch the trusted identity wording/boundary to be source-neutral and Telegram-ready;
3. add/repair production-like DB role + integration-test foundation;
4. fix usage reservation concurrency or explicitly move it into the immediate next PR with a blocking tracked requirement;
5. keep web scaffold clearly secondary;
6. re-run CI and review;
7. merge foundation;
8. create the Telegram/source vertical-slice PR.

## Guardrail for future implementation

Before adding a feature, verify which layer it belongs to:

```text
Telegram/Web UI
-> application service
-> domain authority
-> durable workflow
-> source/provider/media adapter
```

Do not place product policy directly in Telegram handlers, source scrapers/connectors or provider SDK wrappers.

The current canonical product direction is `docs/PRODUCT_VISION.md`; this audit exists to prevent old bootstrap assumptions from silently steering implementation.