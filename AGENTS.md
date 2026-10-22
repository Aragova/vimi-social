# AGENTS.md — ViMi Social production repository

## Purpose

This is the production ViMi Social SaaS repository. It is not an architecture laboratory. New work must deliver product capability while preserving the validated Architecture 1.0 contracts and the finalized product concept.

## Mandatory reading order

Before changing code, read:

1. `docs/PRODUCT_VISION.md`
2. `docs/PROJECT_STATUS.md`
3. `docs/CONTEXT_FOR_AI.md`
4. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md` for historical alignment context
5. `docs/history/architecture-poc/architecture/POST_POC_DECISIONS.md` when implementing a validated durability/security contract
6. `docs/history/architecture-poc/architecture/RED_TEAM_AUDIT_V2.md` when relevant
7. Relevant detailed historical parts only when implementing their contract.

Do not start a new broad architecture audit or PoC unless a concrete production problem requires one.

## Product contract

- ViMi Social is **Telegram-first, AI-first and automation-first**.
- Telegram bot is the primary customer surface; web is secondary.
- Three source modes are fundamental: **AI Search**, **Manual Upload**, **Source Feed**.
- AI Search is the primary automated source path.
- Manual Upload is secondary and reuses the same downstream pipeline.
- Source Feed turns an authorized Telegram channel/group/topic into a persistent content queue consumed according to automation policy.
- Scout uses a typed Source Connector Registry; generic web search is fallback/supplement, not the universal source implementation.
- Source and Destination are separate concepts. A platform may be one, the other, or both.
- Do not design the MVP around `upload file -> choose destination` as the normal workflow.
- Specialized AI components remain behind typed application contracts; no unrestricted MegaAgent.
- Legal adult/18+ content, including explicit gay adult material, is a first-class frequent workload.
- Platform adaptation must produce genuinely compliant derivatives; never disguise prohibited content or bypass moderation/access controls.
- Bot/source/provider handlers are interface/adapter code only. Core business policy belongs in application/domain services and durable workflows.

## Internationalization / regionalization contract

- Persist event timestamps as UTC instants.
- Customer recurring schedules and quiet hours use IANA timezone IDs, not VM timezone or fixed offsets as authority.
- Initial customer UI locales: `ru` and `en`.
- Use localization resources/keys; do not scatter hard-coded customer-facing strings through business code.
- UI locale, content language, Scout/search languages and destination/account content language are separate concepts.
- Telegram `language_code` is only an initial hint; user preference is server-side and overrideable.
- Region/country is separate from language and may affect platform/adult/payment policy.
- Money is modeled with amount + ISO 4217 currency.
- Do not block MVP on many languages/taxes/full KYC, but do not create models that assume one language, timezone or currency.

## Workspace / multi-account contract

Do not assume one tenant equals one brand or one social account.

Architecture must remain compatible with:

```text
User -> Membership -> Workspace/Tenant -> Brand/Project
                                      -> Sources/SourceFeeds
                                      -> Destination accounts
                                      -> Automation policies
```

User UI/notification preferences and workspace/brand publishing defaults are distinct.

## Identity contract

- `ExecutionContext` is a trusted, source-neutral application envelope.
- Telegram identity resolver is the first customer identity adapter.
- Managed IdP may be another adapter for web/admin flows; it is not a prerequisite for Telegram MVP use.
- Never trust caller-controlled tenant IDs.
- Telegram/provider/webhook claims never authorize arbitrary tenant selection; resolve ownership server-side.
- Durable background work must restore tenant authority from trusted persisted bindings, not accept an arbitrary tenant ID from an external caller.

## Non-negotiable Architecture 1.0 contracts

- PostgreSQL RLS is defense-in-depth tenant isolation; normal app roles are non-owner, non-superuser and NOBYPASSRLS.
- Any BYPASSRLS capability must be isolated to a narrowly privileged NOLOGIN executor/function with explicit grants; never give it to `vimi_app`.
- External side effects use stable `operation_key` identity and explicit idempotency/unknown-outcome handling.
- Ambiguous external mutations become `UNKNOWN`; UNKNOWN never authorizes blind retry.
- Expensive tenant work reserves quota atomically before execution; PostgreSQL is commercial-usage correctness authority.
- Usage ledger is append-only; corrections/refunds are compensating adjustments.
- Remote and AI-discovered media is untrusted; preserve SSRF/DNS pinning, redirect revalidation, bounded streaming and isolated processing.
- Privileged cross-tenant access requires the validated narrow authority/audit contracts appropriate to the operation.
- Raw external I/O must not bypass durable authority/fencing contracts.
- No plaintext secrets or production credentials in source, fixtures, logs or docs.

## Engineering workflow

- Work in small vertical slices ending in executable behavior and tests.
- Prefer deterministic tests and explicit failure injection for durability/concurrency behavior.
- Ruff and strict Pyright must remain green.
- Do not weaken tests to make CI pass.
- Do not add test-only runtime/security bypasses.
- Keep domain types explicit; avoid unstructured dictionaries for important state.
- Avoid broad `except Exception` as normal control flow.
- Every irreversible external mutation must define retry/idempotency/reconciliation semantics before implementation.
- Platform/source capability and compliance rules must be versioned/testable, not scattered conditionals in handlers.
- Source Feed item claiming must be idempotent/concurrency-safe.
- Do not implement generic unrestricted scraping when a source-specific permitted connector contract is required.
- Publicly discoverable content must not be treated as automatically reusable; preserve provenance/rights state through the pipeline.

## Deployment / staging contract

- The current priority is real staging evidence, not another broad feature wave.
- Keep PostgreSQL and Temporal private to the Docker network; only intentional ingress is public.
- Staging secrets live outside Git and must never be copied into docs, logs, fixtures or database credential fields.
- Preserve separate PostgreSQL app and migrator roles; do not use the dev/CI trust-auth bootstrap on the VM.
- Media paths are persistent single-node staging state for now. Do not pretend they are horizontally scalable object storage.
- Migrations are a one-shot deployment step and must complete before application services start.
- The first VM exercise must include controlled worker restarts around media processing and X publication.
- A crash around an irreversible destination mutation must still converge through fencing/UNKNOWN/reconciliation without duplicate publication.
- Operational defects found on staging take priority over OAuth, additional destinations, dashboards or feature expansion.

## Current production state

- PR #1 production foundation is merged.
- PR #2 Telegram-first entrypoint is merged.
- PR #4 durable AI Search / Scout is merged.
- PR #5 rights-gated secure media acquisition / MediaProbe is merged.
- PR #6 scene analysis, preflight and VariantPlanner is merged.
- PR #7 visual moderation, RenderService, Telegram preview/approval and real X publication path is merged at `a5d693ab8ec38d14995f25b6cfe1f66c185d626f`.
- The active slice is PR #8 on `feat/staging-vm-deployment`: deploy the existing end-to-end Telegram → X path to a real single-VM staging environment and exercise it manually.
- Read `docs/STAGING_VM_RUNBOOK.md` before changing deployment behavior.
- After successful staging evidence, continue with X OAuth/account management, Manual Upload and Source Feed. Do not skip the staging exercise to add more product surface.

## Sources of truth

`docs/PRODUCT_VISION.md` is the canonical product source of truth. `docs/PROJECT_STATUS.md` is the live phase/status source. `docs/STAGING_VM_RUNBOOK.md` is the current deployment exercise. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md` is historical alignment evidence, not the current implementation status. Historical PoC documents explain validated contracts and rationale.
