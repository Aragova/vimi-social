# ViMi Social — Product Vision

**Status:** Canonical live product direction  
**Updated:** 2026-10-21  
**Primary interface:** Telegram bot  
**Primary operating model:** AI-first automation  
**Core source model:** AI Search / Manual Upload / Source Feed

## 1. Product definition

ViMi Social is a **Telegram-first, AI-first content operating system** for discovering, receiving, analyzing, selecting, preparing, adapting, scheduling, publishing and measuring authorized social content across multiple platforms.

The user should primarily manage **goals, rules and approval level**, not routine technical work. ViMi should automate search, candidate selection, scene analysis, clipping, platform adaptation, captions/metadata, destination recommendation, scheduling, publication, reconciliation and analytics wherever it can do so safely and lawfully.

The Telegram bot is the primary product interface. Web/Next.js is secondary and may serve marketing, OAuth/provider callbacks, optional dashboards, analytics and administration.

## 2. Core product principles

- **Telegram-first** — normal customer use happens in the bot.
- **AI-first** — AI discovery and preparation is a primary product capability, not an add-on.
- **Automation-first** — the product is not merely cross-posting software.
- **Multi-source** — content may originate from search, direct user input, or persistent feeds.
- **Multi-platform** — one source asset may produce multiple destination-specific variants.
- **Adult-content aware** — legal adult/18+ content, including gay adult content, is an expected frequent workload.
- **Policy-aware** — destination eligibility is determined against versioned technical and content-policy constraints.
- **Human-controllable** — workflows range from per-item approval to configured autopilot.
- **International-ready** — timezone, locale, language, region and currency are first-class data from the beginning.
- **Reliability-first** — ambiguous external mutations become `UNKNOWN` and are reconciled rather than blindly repeated.

## 3. Telegram as the primary product surface

The bot should provide:

- `/start`, onboarding and product explanation;
- storefront, tariffs/subscriptions and usage;
- source selection;
- AI task intake;
- candidate previews and approvals;
- source-feed management;
- connected destinations/accounts;
- scheduling and automation policies;
- publication status and reconciliation;
- history and selected analytics;
- notifications, settings and support entry points.

The experience should feel like a premium application, not a command-line interface inside chat. Prefer buttons, inline keyboards, previews, concise status cards and guided flows.

## 4. Web scope

Web is secondary and must not become a prerequisite for normal MVP use. Appropriate roles include:

- public marketing/SEO/ad landing pages;
- OAuth/provider connection flows that require a browser;
- optional linked customer dashboard;
- richer analytics/media inspection;
- internal administration/support tools.

## 5. The three source modes

Before a content workflow starts, the user chooses where ViMi gets material.

Conceptual Telegram menu:

```text
Choose source:

[ AI Search ]
[ Add content ]
[ Channel / Group / Topic ]
```

These three modes are fundamental product concepts and must converge into the same downstream analysis/adaptation/publication pipeline.

### 5.1 AI Search — primary automated source

The user provides intent rather than a finished asset, for example:

> Find fresh high-quality videos about this topic, choose the best ones, prepare versions for my connected destinations and publish according to my schedule.

Flow:

```text
user intent/task
-> Scout
-> Source Router
-> source-specific connectors
-> normalized candidates
-> Curator
-> media/scene analysis
-> classification/policy preflight
-> VariantPlanner
-> preparation
-> approval or automation policy
-> publication
```

The user should not have to manually perform routine searching, downloading, scene selection, clipping, formatting or destination matching when ViMi can automate them safely.

### 5.2 Manual Upload — secondary direct source

The user may provide a specific item by uploading/forwarding video, photo, document, link, text or another supported asset.

It enters the same downstream pipeline:

```text
user-supplied asset
-> provenance/rights/policy checks
-> MediaProbe
-> SceneDetector
-> SceneRanker
-> content/adult classification
-> platform preflight
-> VariantPlanner
-> RenderService
-> publication
```

Manual upload is important, but it is not the dominant product model.

### 5.3 Source Feed — persistent channel/group/topic source

A user may connect an existing Telegram content library and let ViMi consume it over time.

Supported conceptual sources include:

- Telegram channel;
- Telegram group;
- forum-style group;
- a specific topic/thread inside a group;
- other supported persistent Telegram repositories the user is authorized to use.

Example:

```text
Source:
Content Library

Topic:
Muscle

Destinations:
X account
Telegram channel
Reddit account

Cadence:
one item every 6 hours
```

The connected source becomes a managed `SourceFeed`, not a one-time upload.

## 6. Source Feed behavior

ViMi must track, for every feed and source item:

- source/channel/group/topic identity;
- source message/item identity;
- whether the item is new, claimed, processed, skipped or blocked;
- whether it has already been published;
- derived variants;
- destination publications and outcomes;
- when the next item may be claimed.

Conceptual lifecycle:

```text
NEW
-> CLAIMED
-> ANALYZING
-> PREPARING
-> READY
-> SCHEDULED
-> PUBLISHING
-> PUBLISHED
```

Side states may include:

```text
SKIPPED
BLOCKED
NEEDS_REVIEW
FAILED_SAFE
UNKNOWN
```

A source item must not be accidentally claimed by multiple concurrent workflows or published twice because of retries.

## 7. Source Feed automation levels

### Manual approval

ViMi prepares the next item and asks:

```text
[ Publish ] [ Edit ] [ Skip ]
```

### Assisted automation

ViMi claims, analyzes, clips, adapts and prepares captions automatically. The user approves the final publication bundle.

### Autopilot

The user configures a policy once:

```text
source
selection rules
destinations
cadence/schedule
adaptation rules
language/style
stop conditions
```

ViMi then processes items continuously until an explicit stop condition or intervention state occurs.

Autopilot must pause/ask for action when required by low confidence, missing rights/provenance, policy ambiguity, source exhaustion, authorization failure, quota limits, `UNKNOWN`, or other configured safety/operational conditions.

## 8. Source is not Destination

ViMi separates:

- **Source** — where material comes from.
- **Destination** — where a prepared variant is published.

A platform can play both roles. X and Telegram may be both source and destination. Some adult sites or catalogues may be sources only.

## 9. Multi-source Scout / Source Connector Registry

Scout must not depend on one generic browser search. Content discovery is a first-class integration layer of source-specific connectors behind a typed registry.

```text
Scout
-> Source Router
   -> XSourceConnector
   -> TelegramSourceConnector
   -> AdultSiteSourceConnector(s)
   -> RedditSourceConnector
   -> WebsiteSourceConnector
   -> future connectors
   -> GenericWebSearchConnector as fallback/supplement
-> CandidateContent
-> Curator
```

Potential sources include X, Telegram, Reddit, adult-content platforms and catalogues, public sites and future permitted sources.

If the user explicitly names a source, Scout should route there first. If the request is broad, Scout may query multiple eligible connectors and rank normalized candidates together.

Generic web/browser search is a fallback or supplemental mechanism, not a substitute for a dedicated connector when one exists.

Connectors must use permitted access methods only. ViMi must not bypass authentication, paywalls, DRM, age gates, access controls, anti-bot protections or source restrictions.

## 10. Common source connector model

A connector should expose a common capability shape such as:

```text
search(query, filters, cursor)
get_candidate_metadata(candidate_id)
get_media_references(candidate_id)
get_source_context(candidate_id)
get_provenance_hints(candidate_id)
get_policy_availability_hints(candidate_id)
```

It also declares operational capabilities/restrictions, for example:

- official API/search availability;
- authentication requirements;
- pagination and rate limits;
- media metadata availability;
- adult/sensitive-content visibility behavior;
- permitted automation/download/reuse paths;
- regional/account/age restrictions;
- provenance/rights evidence availability;
- connector health/version/policy status.

## 11. Normalized candidate model

Different sources normalize into a common internal concept such as:

```text
CandidateContent
  source
  source_id
  source_url
  author/source context
  published_at
  media_type
  duration
  technical metadata
  caption/tags
  relevance_score
  quality_score
  adult_classification
  explicitness_score
  provenance/rights/consent metadata
  engagement metadata
  availability/policy hints
```

Downstream AI/media components should not need source-specific scraping/API knowledge.

## 12. AI component model

ViMi should use specialized components rather than one unrestricted MegaAgent.

- `Scout` — discovers candidate material.
- `Curator` — filters/ranks candidates and their context.
- `SceneRanker` — ranks scenes/segments for reuse.
- `VariantPlanner` — plans destination-specific variants.
- `CaptionGenerator` — prepares captions/title/description/tags/metadata.
- `AnalyticsInsight` — turns performance data into future recommendations.

Deterministic components remain authoritative for media probing, rendering, policy gates, authorization, usage/billing, scheduling and publication lifecycle.

AI acts through typed tools with tenant, entitlement, budget, validation and audit controls.

## 13. Common media pipeline

All source modes converge into one processing path:

```text
Original/Candidate Asset
-> MediaProbe
-> SceneDetector
-> Feature Extraction
-> SceneRanker
-> Content Classification
-> Platform Capability + Compliance Preflight
-> VariantPlanner
-> RenderRecipe
-> RenderService
-> Platform Variant
-> Caption/Metadata
-> Destination Recommendation
```

Do not build separate downstream systems for AI Search, Manual Upload and Source Feed.

## 14. Adult/18+ content as a first-class workload

Legal adult/18+ content, including explicit gay adult material, is an expected and frequent workload rather than an exceptional edge case.

For candidate and supplied assets ViMi should determine, as applicable:

- adult/explicitness classification and confidence;
- scene-level explicitness/suitability;
- provenance and usage basis;
- available rights/consent information;
- destination-specific eligibility;
- whether the original is allowed;
- whether a genuinely compliant derivative can be produced;
- whether the destination must be blocked.

The system must never assume that public availability implies permission to redistribute.

## 15. Platform policy decision model

For a content/destination combination, the result should be explicit, for example:

```text
DIRECT_ALLOWED
ADAPTATION_REQUIRED
MANUAL_REVIEW_REQUIRED
BLOCKED
```

### Original permitted

```text
original
-> technical variant if needed
-> publish
```

### Original not permitted, but a compliant derivative is possible

```text
original
-> scene analysis
-> select allowed/non-explicit segments
-> cut/crop/censor as genuinely required
-> adjust duration/framing/cover/caption/metadata
-> policy preflight again
-> publish only if compliant
```

### No compliant derivative is possible

```text
BLOCKED
-> do not publish there
-> explain reason
-> suggest eligible alternatives
```

Adaptation must produce genuinely compliant content. It must not disguise prohibited content or bypass moderation.

## 16. Platform Capability and Compliance registries

Technical capability and policy/compliance are separate concerns.

Capability examples:

```text
supports_video
supports_images
supports_carousel
supports_stories
max_video_duration
max_video_bytes
supported_aspect_ratios
caption_limit
async_publish
status_poll
webhook
analytics
delete
comments
```

Compliance examples:

```text
policy_version
adult_policy
allowed_account_types
required_scopes
region_restrictions
feature_restrictions
technical_status
commercial_status
reviewed_at
```

Eligibility must be versioned/data-driven rather than scattered hard-coded assumptions.

## 17. Destination recommendation

ViMi should recommend destinations and variants, not merely ask the user to choose blindly.

Example:

```text
Telegram   DIRECT_ALLOWED      original variant
X          DIRECT_ALLOWED      original/technical variant
Reddit     ADAPTATION_REQUIRED variant A
Platform Y MANUAL_REVIEW       safe variant candidate
Platform Z BLOCKED             no compliant variant
```

The user may confirm/change the recommendation, or an approved automation policy may act automatically.

## 18. Scheduling, timezones and calendars

Timezone correctness is a core requirement from day one.

Rules:

- all persisted event timestamps are stored as UTC instants (`timestamptz` where applicable);
- user/workspace schedules use an **IANA timezone** such as `Europe/Moscow` or `Asia/Bangkok`, never a fixed numeric offset as the source of truth;
- recurring schedules preserve the intended local wall-clock time across DST transitions;
- VM/server timezone must not define customer schedule behavior;
- analytics and bot displays render time in the relevant user/workspace timezone;
- Source Feed cadence and quiet hours are timezone-aware.

Future scheduling may also support analytics-driven posting windows instead of only fixed times.

## 19. Internationalization and language model

The system is international-ready from the first production slices without requiring many translations immediately.

Initial UI languages should be:

- Russian (`ru`);
- English (`en`).

UI strings must use localization keys/resources rather than hard-coded customer-facing prose throughout business code.

The following concepts are distinct:

```text
user interface locale
workspace default locale
content language
source/search languages
destination/account content language
```

A Russian UI user may publish English content to X and Russian content to Telegram. Scout may expand/search across languages independently of the interface language.

Telegram `language_code` may be used as an initial hint but must not be treated as permanent authoritative preference; the user can override it.

## 20. Region and adult eligibility readiness

Region is distinct from language and may affect platform policy, payment availability, legal/commercial behavior and adult-content eligibility.

Data models should be ready to represent at least:

```text
locale
timezone
region/country
preferred_content_languages
```

Adult-facing product flows should also be able to represent an eligibility state without forcing a full KYC implementation in the MVP, for example:

```text
UNKNOWN
DECLARED_18_PLUS
VERIFIED_18_PLUS
RESTRICTED
```

The exact verification mechanism is a later implementation/compliance decision.

## 21. Currency and money

Money must never be modeled as a bare number or as a hard-coded single currency.

Conceptually:

```text
Money
  amount
  currency (ISO 4217)
```

Examples: RUB, USD, EUR.

The MVP may expose only a small number of currencies/payment options, but pricing, billing records and UI formatting must be currency-aware from the beginning.

## 22. Locale-aware formatting and notifications

Customer-facing formatting should respect locale for dates, time, numbers and money.

Notification preferences should support local-time behavior, including future quiet-hours controls such as:

```text
quiet hours: 23:00-08:00 in user timezone
normal notifications
important-only notifications
critical override policy
```

## 23. Workspace, Brand and multi-account model

The product must not assume one customer equals one social account or one content identity.

Conceptual hierarchy:

```text
User
-> Membership
-> Workspace/Tenant
   -> Brand/Project
      -> Sources
      -> Source Feeds
      -> Connected Destination Accounts
      -> Automation Policies
      -> Content Language/Style defaults
```

A workspace may operate multiple brands/projects. A brand may have several Telegram channels, X accounts, Reddit identities or other destination accounts with different languages, schedules and policies.

User preferences (for example UI language/notification timezone) and workspace/brand publishing defaults must remain distinct.

## 24. Commercial experience

The Telegram bot is the primary storefront and should expose:

- free/trial capability if offered;
- plan comparison and current plan;
- usage/remaining limits;
- AI/Scout/media-processing consumption where relevant;
- connected account/source limits;
- Source Feed/automation limits;
- upgrade/renewal/subscription state;
- billing/help links where external/browser flows are required.

Plans/entitlements remain separate from identity and external provider API quotas.

## 25. Usage model

Useful metering dimensions may include:

```text
scout_run
ai_token
vision_frame
video_second_processed
rendered_video_minute
published_post
scheduled_post
storage_byte_hour
egress_byte
connected_account
source_feed
workspace_member
```

PostgreSQL remains the correctness authority for commercial usage. Expensive work reserves quota before execution and the ledger is append-only.

## 26. Identity and tenancy

For Telegram-originated flows, Telegram identity is the first interaction identity.

Incoming Telegram updates must be accepted only through a trusted integration boundary and mapped server-side from immutable Telegram identifiers to ViMi user/workspace/tenant authority.

A caller must never choose an arbitrary tenant by supplying a tenant ID.

A managed IdP may still be used for web/admin experiences, but normal Telegram MVP use must not depend on a separate web login.

## 27. Reliability and publication lifecycle

External publication is an irreversible distributed side effect.

The central rule remains:

```text
ambiguous external outcome
-> UNKNOWN
-> reconciliation
-> confirmed / pending / proved absent / still unknown
```

No blind second publication occurs after a lost response, timeout or cancellation after dispatch may have begun.

Stable `operation_key` identity, typed outcomes, bounded safe retry and reconciliation remain Architecture 1.0 contracts.

## 28. Security boundaries

- PostgreSQL RLS remains defense-in-depth tenant isolation.
- Application roles are non-owner/non-superuser/NOBYPASSRLS.
- Remote and AI-discovered media are untrusted input.
- Media processing remains isolated and bounded.
- AI has no unrestricted shell, SQL, secrets or arbitrary authority.
- Source connectors and provider adapters operate through controlled credentials/policies.
- Privileged cross-tenant access requires durable audit evidence.
- No plaintext production secrets in source/docs/logs.

## 29. MVP / first real product slice

The first production slice should prove the defining product idea rather than only file upload.

```text
Telegram /start
-> trusted Telegram identity/workspace resolution
-> localized onboarding/menu (RU/EN-ready)
-> user chooses AI Search
-> user describes desired content/task
-> Scout routes to one authorized real source connector
-> candidates normalized
-> Curator selects/ranks candidate(s)
-> MediaProbe + SceneDetector + SceneRanker
-> adult/content classification
-> platform capability/compliance preflight
-> VariantPlanner creates/recommends one usable variant
-> preview/approval in Telegram
-> tenant-scoped usage reservation + persisted operation
-> Temporal workflow
-> one real destination adapter
-> publication
-> bot status
-> UNKNOWN-safe reconciliation
```

Immediately after that, early production expansion must add:

1. Manual Upload through the same downstream pipeline.
2. Telegram Source Feed using a channel/group/topic as a persistent queue.
3. Automation cadence/scheduling with timezone correctness.
4. Additional source connectors behind the same registry contract.
5. Additional destination adapters.

The first staging/VM deployment should happen as soon as the initial AI-first slice works end-to-end for one authorized source and one real destination.

## 30. Product UX summary

The desired user experience is:

> I tell ViMi what content I need and how I want my accounts operated. ViMi finds or receives the material, analyzes it, selects the useful parts, prepares compliant destination-specific versions, shows me what needs approval, publishes according to my rules, tracks the result and continues the automation.

Customer-facing statuses should remain understandable, for example:

```text
Searching
Selecting candidates
Analyzing video
Preparing clips
Checking destinations
Creating variants
Ready for review
Scheduled
Publishing
Provider processing
Published
Needs decision
Destination blocked
```

Infrastructure complexity such as PostgreSQL, Temporal, workers and reconciliation internals should remain hidden from ordinary customers.

## 31. Source-of-truth precedence

For current product intent, read in this order:

1. `docs/PRODUCT_VISION.md` — canonical product/interface/source/automation/internationalization direction.
2. `docs/PROJECT_STATUS.md` — live implementation stage and immediate work.
3. `docs/CONTEXT_FOR_AI.md` — compact handoff context.
4. `AGENTS.md` — engineering constraints.
5. `docs/FOUNDATION_CONCEPT_ALIGNMENT_AUDIT.md` — review of existing foundation against the clarified concept.
6. Historical architecture documents under `docs/history/` — validated security/reliability contracts and rationale.

Historical documents that imply web-first or manual-upload-first product priority are superseded on product priority by this document. Their validated reliability, security, tenancy, media, usage, workflow, AI-boundary and provider-lifecycle contracts remain authoritative unless explicitly revised by a later production decision.