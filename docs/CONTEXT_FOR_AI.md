# ViMi Social — Context for AI / new chat

Read these first:

1. `docs/PRODUCT_VISION.md`
2. `docs/PROJECT_STATUS.md`
3. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md`
4. `AGENTS.md`

## What this project is

ViMi Social is a production **Telegram-first, AI-first, automation-first** multi-tenant SaaS for discovering/receiving content, analyzing it, creating destination-specific variants, publishing safely and operating recurring content workflows.

The Telegram bot is the primary customer interface. Web/Next.js is secondary.

## Fundamental source model

There are exactly three first-class source modes in the current product concept:

1. **AI Search** — primary automated path. User describes the task; Scout searches authorized source connectors.
2. **Manual Upload** — user supplies/forwards a specific asset; it enters the same downstream pipeline.
3. **Source Feed** — a persistent Telegram channel/group/topic becomes a managed queue consumed over time according to an automation policy.

These modes converge into one downstream pipeline. Do not build three separate processing systems.

## Scout / source integrations

Scout is not generic web search. It routes through a typed Source Connector Registry, e.g. X, Telegram, Reddit, adult-content source adapters and future permitted sources. Generic web search is fallback/supplement only.

Connectors may only use permitted access methods and must not bypass auth, paywalls, DRM, age gates, anti-bot protections or source restrictions.

## Adult/18+ workload

Legal adult/18+ content, including explicit gay adult material, is an expected frequent workload. Adult classification, scene-level suitability, provenance/rights metadata and destination policy eligibility are normal pipeline concerns.

Destination decision examples:

```text
DIRECT_ALLOWED
ADAPTATION_REQUIRED
MANUAL_REVIEW_REQUIRED
BLOCKED
```

Adaptation must create a genuinely policy-compliant derivative. Never disguise prohibited content or attempt to bypass moderation.

## International / regional contract

Design international-ready from the first slices:

- persisted event timestamps: UTC;
- schedules/quiet hours: IANA timezone IDs;
- initial UI locales: Russian + English;
- UI locale != content language != search language != destination/account language;
- Telegram `language_code` is only an initial hint;
- region/country is separate from language;
- money always has ISO 4217 currency;
- recurring schedules must preserve local wall-clock intent across DST;
- VM/server timezone never defines customer schedule behavior.

Do not block MVP on many translations, global taxes or full age/KYC, but do not design data models that make them expensive to add.

## Workspace / brand / accounts

Do not assume one tenant equals one social account/brand.

Conceptual shape:

```text
User -> Membership -> Workspace/Tenant -> Brand/Project
                                      -> Sources/SourceFeeds
                                      -> Connected destination accounts
                                      -> Automation policies
```

User UI/notification preferences remain separate from workspace/brand publishing defaults.

## Production architecture that remains valid

- modular monolith initially;
- Python 3.12+, FastAPI/application services;
- PostgreSQL + RLS, SQLAlchemy/psycopg/Alembic;
- Temporal durable workflows;
- isolated media worker;
- S3-compatible object storage;
- specialized AI components behind typed tools;
- source connectors separate from destination/provider adapters;
- Next.js secondary web surface;
- GitHub Actions, Ruff, strict Pyright, pytest, OpenTelemetry.

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
12. Privileged cross-tenant access requires durable audit evidence.

## Current reality / correction to the initial foundation

Production foundation PR #1 was created before the final product concept was fully clarified. It is mostly reusable, but it must not be merged/extended blindly as if the product were web-first or managed-IdP-first.

Important corrections:

- `ExecutionContext` must be a source-neutral trusted envelope. Telegram is the first customer identity adapter; managed IdP remains optional for web/admin.
- Next.js stays but is secondary.
- PostgreSQL roles/RLS integration tests still need production-like hardening.
- Usage reservation has a known concurrent-first-seen operation race and is not production-complete.
- Telegram bot/source models, Source Feed, source connectors and internationalization primitives have not yet been implemented.

See `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md` for the explicit KEEP / CHANGE / DEFER decisions.

## Current task

Align the foundation first, then implement vertical slice 1:

```text
Telegram /start
-> trusted Telegram identity/workspace resolution
-> localized RU/EN-ready menu
-> AI Search task
-> one real authorized source connector
-> normalized candidates + Curator
-> media/scene analysis
-> adult classification + platform preflight
-> one direct/compliant variant
-> Telegram preview/approval
-> usage reservation + persisted operation
-> Temporal
-> one real destination adapter
-> publication/status/reconciliation
```

Deploy to staging/VM as soon as this works end-to-end. Manual Upload and Telegram Source Feed are early follow-ups through the same pipeline.

## Sources of truth

`docs/PRODUCT_VISION.md` is the canonical product concept. `docs/PROJECT_STATUS.md` is the live implementation status. Historical architecture under `docs/history/` remains authoritative for validated security/reliability contracts unless explicitly superseded.