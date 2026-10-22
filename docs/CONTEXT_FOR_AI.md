# ViMi Social — Context for AI / new chat

Read these first:

1. `docs/PRODUCT_VISION.md`
2. `docs/PROJECT_STATUS.md`
3. `docs/CONTEXT_FOR_AI.md`
4. `AGENTS.md`
5. Relevant historical architecture decisions only when their contract is being implemented.

## What this project is

ViMi Social is a production **Telegram-first, AI-first, automation-first** multi-tenant SaaS for discovering/receiving content, analyzing it, creating destination-specific variants, publishing safely and operating recurring content workflows.

Telegram is the primary customer interface. Web/Next.js is secondary.

Do not restart broad architecture research. The architecture laboratory is historical. New work should deliver a small production slice while preserving the validated reliability/security contracts.

## Repository reality

Production repository: `Aragova/vimi-social`.

Merged production milestones:

- PR #1 — production foundation, merge commit `7811892d02f8d454a968c3877b53f1b7ad7b6a18`;
- PR #2 — Telegram-first customer entrypoint, merge commit `6b7ec905e7f7d6f7b4f37a7bbdef9982259ad4db`.

The active next slice is PR #4 on `feat/source-task-scout`: durable AI Search SourceTask + Scout foundation + first real source connector.

## Fundamental source model

There are exactly three first-class source modes in the current product concept:

1. **AI Search** — primary automated path. User describes the task; Scout searches authorized source connectors.
2. **Manual Upload** — user supplies/forwards a specific asset; it enters the same downstream pipeline.
3. **Source Feed** — a persistent Telegram channel/group/topic becomes a managed queue consumed over time according to an automation policy.

These modes converge into one downstream pipeline. Do not build three separate processing systems.

## Current AI Search / Scout implementation direction

The current production slice is:

```text
Telegram AI Search selection
-> durable conversation state
-> user intent
-> tenant-bound SourceTask
-> scout_run usage reservation
-> Temporal ScoutWorkflow
-> SourceConnectorRegistry
-> source-specific connector(s)
-> CandidateContent
-> persisted candidates
-> Telegram results / selection
```

The first real connector uses the **official X API v2 Recent Search**. Do not replace it with scraping. Generic web search remains fallback/supplement only and is not the basis of Scout.

The connector currently discovers metadata only. Public availability is not treated as reuse permission. Media acquisition, provenance/rights gate, secure ingest and MediaProbe are the next production slice.

If the user explicitly asks for a source for which no configured connector exists, fail closed rather than silently searching a different platform.

UI locale must not automatically become search language. UI language, content language, search language and destination/account language remain separate concepts.

## Adult/18+ workload

Legal adult/18+ content, including explicit gay adult material, is an expected frequent workload. Adult classification, scene-level suitability, provenance/rights metadata and destination policy eligibility are normal pipeline concerns.

Destination decision examples:

```text
DIRECT_ALLOWED
ADAPTATION_REQUIRED
MANUAL_REVIEW_REQUIRED
BLOCKED
```

Adaptation must create a genuinely policy-compliant derivative. Never disguise prohibited content or attempt to bypass moderation/access controls.

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
12. Privileged cross-tenant access must be narrow, explicit and auditable; never broaden the normal app role to BYPASSRLS.

## Current task after the Scout slice

Once PR #4 is green and reviewed, the next production slice should continue from selected `CandidateContent`:

```text
selected candidate
-> Curator/ranking boundary
-> permitted media acquisition
-> provenance / rights gate
-> secure ingest
-> MediaProbe
-> base content/adult classification
-> persisted asset lineage
```

Then continue into SceneDetector / SceneRanker / policy preflight / VariantPlanner and one real destination adapter with UNKNOWN-safe reconciliation.

Deploy to staging/VM as soon as one source-to-destination path works end-to-end through Telegram. Manual Upload and Telegram Source Feed are early follow-ups through the same downstream pipeline.

## Sources of truth

`docs/PRODUCT_VISION.md` is the canonical product concept. `docs/PROJECT_STATUS.md` is the live implementation status. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md` is historical evidence explaining the initial foundation alignment and must not be mistaken for current live status. Historical architecture under `docs/history/` remains authoritative for validated security/reliability contracts unless explicitly superseded.
