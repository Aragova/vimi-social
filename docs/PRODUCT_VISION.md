# ViMi Social — Product Vision

**Status:** Canonical live product direction  
**Updated:** 2026-10-21  
**Primary interface:** Telegram bot  
**Primary content source:** AI-assisted discovery/automation

## 1. Product definition

ViMi Social is a Telegram-first, AI-first content operating system for discovering, selecting, preparing, adapting, scheduling, publishing, and analyzing authorized social content across multiple platforms.

The **Telegram bot is the primary product interface**. It is the user's storefront, onboarding flow, control panel, task entry point, approval UI, subscription surface, status center, and day-to-day workspace.

The primary workflow is **not** "user uploads a finished file and ViMi posts it". The normal workflow starts with the user describing the desired content/task. ViMi's controlled AI components discover candidate material, rank and curate it, analyze scenes, plan platform variants, prepare compliant derivatives, recommend eligible destinations, and orchestrate publication. Manual upload remains an important secondary input path.

A web application may exist, but it is secondary. Its expected roles are marketing/landing pages, optional account/dashboard views linked to Telegram, selected administrative tools, richer analytics, and browser-required integration flows. The core product must remain usable from Telegram.

## 2. Intended user journey

A typical user should be able to:

1. Discover and open the ViMi Social Telegram bot.
2. Press Start and receive a polished welcome/onboarding experience.
3. Understand the service through bot-native menus, examples, demos, help, and plan comparison.
4. View tariffs/subscriptions and enter a purchase/subscription flow from the bot where platform/payment policy permits.
5. Start working without first visiting a website.
6. Describe the desired content/task in natural language: topic, style, audience, destination preferences, schedule, and automation level.
7. Let ViMi agents discover candidate source material from authorized sources and return ranked options with provenance/policy metadata.
8. Let ViMi analyze scenes, choose the strongest usable segments, create cuts/derivatives, generate captions/metadata, and prepare platform-specific variants.
9. Receive an eligibility/preflight result for each destination: direct publish, adapted variant required, manual review required, or blocked.
10. Review/approve the proposed content and destinations when the configured workflow requires approval.
11. Publish to authorized social accounts/platforms and receive progress, confirmation, UNKNOWN/reconciliation states, failures, and actionable next steps in Telegram.
12. View usage, remaining quota, subscription state, connected accounts, publication history, and selected analytics from bot menus.
13. As a secondary path, send a ready video/photo/link/document to the bot and run the same analysis/adaptation/publication pipeline.

The interaction should feel like a premium autonomous service, not a terminal wrapped in chat commands. Prefer buttons, inline keyboards, guided steps, previews, concise status cards, and progressive disclosure over requiring users to memorize commands.

## 3. Automation-first content pipeline

The default product flow is:

```text
user intent/task
-> Scout: discover candidate content from authorized sources
-> Curator: filter/rank candidates and verify provenance/policy metadata
-> MediaProbe / SceneDetector
-> SceneRanker: identify useful scenes/segments
-> Content classification + platform policy preflight
-> VariantPlanner: decide direct-use vs adapted derivatives per platform
-> RenderRecipe / RenderService
-> CaptionGenerator / metadata preparation
-> destination recommendation
-> approval when required
-> scheduling/publication
-> reconciliation/status/analytics
```

The user should not need to manually perform routine searching, downloading, scene selection, clipping, formatting, or destination matching when ViMi can safely automate them.

Manual content upload is the secondary source path:

```text
user-supplied asset
-> provenance/rights/policy checks
-> same analysis, adaptation and publication pipeline
```

## 4. Multi-source Scout / Source Connector Registry

Scout must not depend on one generic web search. Content discovery is a first-class integration layer built from **source-specific connectors** behind one typed contract and registry.

Conceptual flow:

```text
user task
-> Scout
-> Source Router
   -> XSourceConnector
   -> TelegramSourceConnector
   -> AdultSiteSourceConnector(s)
   -> RedditSourceConnector
   -> other platform/site connectors
   -> GenericWebSearchConnector as fallback/supplement
-> normalized CandidateContent records
-> Curator / downstream pipeline
```

Potential sources include X, Telegram, adult-content platforms and sites (including gay/adult catalogues), Reddit, public websites, and future sources that satisfy product, legal, authorization and technical requirements.

Each connector should expose a common capability model such as:

```text
search(query, filters, cursor)
get_candidate_metadata(candidate_id)
get_media_references(candidate_id)
get_author/source_context(candidate_id)
get_provenance_hints(candidate_id)
get_policy/availability_hints(candidate_id)
```

Each source adapter must also declare its operational capabilities and restrictions, including:

- official API/search availability;
- authenticated-access requirements;
- whether public web access is supported;
- pagination/rate limits;
- video/image/media metadata availability;
- sensitive/adult-content visibility behavior;
- allowed automation/download/reuse paths;
- regional/account/age restrictions where relevant;
- provenance/rights evidence that can be collected;
- connector health/version/policy status.

If the user explicitly names a source (for example, "find this on X"), Scout should route to that source connector first rather than silently replacing the request with a generic browser search. If the user asks broadly, Scout may query several eligible connectors in parallel and rank the normalized candidates together.

Generic browser/web search is a fallback or supplemental discovery tool, not a substitute for source-native integration when a dedicated connector exists.

Connectors must use permitted access methods only. ViMi must not bypass authentication, paywalls, DRM, age gates, access controls, anti-bot protections, or platform restrictions. Where an official API or permitted authenticated integration exists, prefer it over brittle scraping.

## 5. Adult/18+ content as a first-class workload

Adult/18+ content is an expected and frequent product workload, including explicit adult material. The architecture must therefore treat adult-content classification and destination eligibility as normal product behavior, not as an exceptional edge case.

For every candidate or supplied asset, ViMi should determine at minimum:

- adult/explicitness classification and confidence;
- provenance/usage basis and any required consent/rights metadata;
- scene-level suitability where useful;
- destination-specific policy eligibility;
- whether the original can be published directly;
- whether a genuinely policy-compliant derivative can be created;
- whether the target must be blocked.

The intended decision model is:

```text
platform permits this content as-is
-> prepare technical variant if needed
-> publish directly

platform does not permit the original explicit form,
but a genuinely compliant derivative can be created
-> select allowed/non-explicit scenes
-> remove/crop/censor prohibited elements as required
-> adjust cut, duration, framing, cover, caption and metadata
-> run platform preflight again
-> publish only if the resulting variant is compliant

no compliant variant can be produced
-> block that destination
-> explain why and suggest eligible alternatives
```

Adaptation must make the resulting asset actually compliant with the destination's rules; ViMi must not attempt to disguise prohibited content or bypass moderation.

Because policies differ by platform, account type, region, feature and policy version, eligibility must be versioned and data-driven through the Platform Capability/Compliance registries rather than hard-coded assumptions.

## 6. Interface priority

### Tier 1 — Telegram bot

Telegram owns the primary customer experience:

- `/start` and onboarding;
- main navigation/menu;
- product explanation and examples;
- tariffs/subscriptions/storefront;
- account and workspace setup;
- AI task creation as the primary content source;
- candidate discovery/results/review;
- optional manual content upload/inbox;
- content preparation and approval;
- target/platform recommendation and selection;
- scheduling;
- publication progress and reconciliation;
- history and status;
- usage/quota/subscription information;
- notifications and support entry points.

### Tier 2 — Web

Web is optional/secondary and must not become a prerequisite for normal MVP use. Suitable roles include:

- public marketing landing page and SEO/ad destination;
- optional linked personal account/dashboard;
- richer analytics or media inspection where a browser genuinely helps;
- selected administrative/support functions;
- OAuth/provider connection callbacks or other browser-required integrations.

### Tier 3 — Internal APIs/workers

FastAPI, PostgreSQL, Temporal, media workers, storage, AI Tool Gateway, provider adapters, source connectors, and other backend components remain core architecture. They serve the Telegram experience first and secondary web surfaces second.

## 7. Identity and tenancy direction

For Telegram-originated customer flows, Telegram identity is the first interaction identity. Incoming bot updates must be accepted only through the trusted Telegram integration boundary and mapped server-side from immutable Telegram identifiers to ViMi users/workspaces/tenants.

A client must never be able to choose an arbitrary tenant by sending a tenant ID. Existing Architecture 1.0 tenant-isolation and RLS rules remain unchanged.

A managed web identity provider may still be used for browser/admin experiences, but the MVP customer journey must not require a separate web login before the Telegram bot can be used.

## 8. AI component model

The historical Architecture 1.0 specialization remains the intended direction:

- `Scout` — discovers candidate source material;
- `Curator` — evaluates/ranks candidate material and context;
- `SceneRanker` — ranks scenes/segments for reuse;
- `VariantPlanner` — plans destination-specific variants;
- `CaptionGenerator` — prepares text/metadata;
- `AnalyticsInsight` — turns performance data into recommendations.

Deterministic components remain authoritative for media probing, platform validation, rendering, rights/policy gates, authorization, billing/usage, scheduling, and publication lifecycle execution.

There is no unrestricted universal MegaAgent. AI acts through typed tools, tenant/entitlement/budget controls, and auditable application services.

## 9. Publication model

Initial destination family remains multi-platform and can include Telegram, X, Instagram, TikTok, YouTube/Shorts, Reddit, Bluesky, and future adapters.

Platform recommendation must combine:

- technical capability;
- content-policy/compliance eligibility;
- account/feature restrictions;
- media-format requirements;
- availability of a compliant derivative;
- user preferences and connected accounts.

The validated reliability contract is unchanged:

```text
ambiguous external outcome
-> UNKNOWN
-> reconciliation
-> confirmed / pending / proved absent / still unknown
```

No blind duplicate publication is allowed after an ambiguous external mutation.

## 10. Commercial experience

The bot is the primary storefront. It should be able to present:

- free/trial capability if offered;
- plan comparison;
- current plan;
- usage and limits;
- AI/scout/media-processing consumption where relevant;
- upgrade/renewal entry points;
- purchase/subscription state;
- billing/help links where a browser or external payment flow is required.

The exact payment provider/mechanism is an implementation decision and must respect Telegram/platform/payment-store policy. Product architecture must keep subscription entitlements separate from identity and from provider API quotas.

## 11. Product architecture consequence

The existing modular-monolith architecture remains valid, but product priorities are:

- first-class Telegram bot application/process boundary;
- AI-first task intake and automated content discovery/preparation;
- Source Connector Registry with typed source adapters and routing;
- first-class adult-content classification and platform eligibility/preflight;
- scene-level analysis and variant generation before publication;
- trusted Telegram update handling with server-side tenant/workspace resolution;
- bot handlers call domain/application services rather than contain business logic;
- backend API remains useful internally and for optional web surfaces;
- Next.js is secondary and must not consume MVP effort ahead of core bot/AI workflows;
- Temporal remains the durable workflow engine for scouting, media preparation, approvals, scheduling, publication and reconciliation;
- PostgreSQL remains the correctness authority;
- media processing remains isolated;
- source connectors and provider adapters remain independent of Telegram UI code.

## 12. MVP vertical slice

The first real product slice is Telegram-native and AI-first:

```text
Telegram /start
-> server-side Telegram identity/workspace resolution
-> onboarding/main menu
-> user describes desired content/task
-> Scout routes to one authorized source connector
-> source connector discovers candidate material
-> Curator ranks/filters candidates
-> MediaProbe + SceneDetector + SceneRanker
-> adult/content classification + platform policy preflight
-> VariantPlanner proposes one usable platform variant
-> user preview/approval
-> tenant RLS transaction
-> atomic usage reservation
-> persisted operation keyed by operation_key
-> Temporal workflow
-> one real provider dispatch
-> bot status updates
-> UNKNOWN-safe reconciliation
-> final result shown in Telegram
```

Manual upload must reuse the same downstream pipeline but is not the primary MVP source path.

The first staging/VM deployment should happen as soon as this AI-first path works end-to-end for one authorized content source and one real destination. Additional source connectors should then be added incrementally behind the same typed contract rather than as ad-hoc search code.

## 13. Source-of-truth precedence

For current product intent, read in this order:

1. `docs/PRODUCT_VISION.md` — current product/UI/automation direction.
2. `docs/PROJECT_STATUS.md` — current implementation stage.
3. `docs/CONTEXT_FOR_AI.md` — compact handoff context.
4. `AGENTS.md` — engineering constraints.
5. Historical architecture documents under `docs/history/` — validated contracts and rationale.

Historical documents that imply manual upload or Next.js is the dominant customer path are superseded on product priority by this document. Their reliability, security, tenancy, media, usage, workflow, AI-boundary and provider-lifecycle contracts remain authoritative unless explicitly revised by a later production decision.