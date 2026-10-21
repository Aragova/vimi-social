# ViMi Social — Product Vision

**Status:** Canonical live product direction  
**Updated:** 2026-10-21  
**Primary interface:** Telegram bot

## 1. Product definition

ViMi Social is a Telegram-first AI-assisted content operating system for preparing, sourcing, adapting, scheduling, publishing, and analyzing authorized social content across multiple platforms.

The **Telegram bot is the primary product interface**. It is not merely a notification bot and Telegram is not merely one publication target. The bot acts as the user's storefront, onboarding flow, control panel, content inbox, workflow UI, subscription surface, status center, and day-to-day workspace.

A web application may exist, but it is secondary. Its expected roles are marketing/landing pages, optional account/dashboard views linked to Telegram, selected administrative tools, and flows that are materially better in a browser. The core product must remain usable from Telegram.

## 2. Intended user journey

A typical user should be able to:

1. Discover and open the ViMi Social Telegram bot.
2. Press Start and receive a polished welcome/onboarding experience.
3. Understand what the service does through bot-native menus, examples, demos, help, and plan comparison.
4. View tariffs/subscriptions and enter a purchase/subscription flow from the bot where platform/payment policy permits.
5. Start working without first visiting a website.
6. Provide content directly in Telegram by sending video, photo, text, document, link, or other supported media.
7. Alternatively create a task for ViMi agents to discover or prepare suitable content within configured authorization, provenance, safety, and platform-policy boundaries.
8. Choose what should happen to the content: transform/adapt it, prepare captions/metadata, choose destinations, select timing/schedule, and approve the result.
9. Publish to authorized social accounts/platforms.
10. Receive progress, confirmation, UNKNOWN/reconciliation states, failures, and actionable next steps in the Telegram conversation.
11. View usage, remaining quota, subscription state, connected accounts, publication history, and selected analytics from bot menus.

The interaction should feel like a premium product, not a terminal wrapped in chat commands. Prefer buttons, inline keyboards, guided steps, previews, concise status cards, and progressive disclosure over requiring users to memorize commands.

## 3. Interface priority

### Tier 1 — Telegram bot

Telegram owns the primary customer experience:

- `/start` and onboarding;
- main navigation/menu;
- product explanation and examples;
- tariffs/subscriptions/storefront;
- account and workspace setup;
- content upload/inbox;
- agent task creation;
- content preparation and approval;
- target/platform selection;
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

FastAPI, PostgreSQL, Temporal, media workers, storage, provider adapters, and other backend components remain core architecture. They serve the Telegram experience first and secondary web surfaces second.

## 4. Identity and tenancy direction

For Telegram-originated customer flows, Telegram identity is the first interaction identity. Incoming bot updates must be accepted only through the trusted Telegram integration boundary and mapped server-side from immutable Telegram identifiers to ViMi users/workspaces/tenants.

A client must never be able to choose an arbitrary tenant by sending a tenant ID. Existing Architecture 1.0 tenant-isolation and RLS rules remain unchanged.

A managed web identity provider may still be used for browser/admin experiences, but the MVP customer journey must not require a separate web login before the Telegram bot can be used.

## 5. Content acquisition modes

ViMi Social supports two primary modes:

### User-supplied content

The user sends content to the bot directly. ViMi stores the immutable original, creates versioned derivatives, performs required media validation/processing, and guides the user through preparation and publication.

### Agent-assisted content work

The user gives an intent/task rather than a ready asset. Controlled agents may research/discover candidate material or prepare content according to explicit product policy, authorization, provenance, licensing/copyright, source, and platform constraints. Agents do not receive unrestricted shell/database/secrets/network authority.

Candidate content should be presented for user review/approval when required by policy or workflow.

## 6. Publication model

Initial destination family remains multi-platform and can include Telegram, X, Instagram, TikTok, YouTube/Shorts, Reddit, Bluesky, and future adapters.

The validated reliability contract is unchanged:

```text
ambiguous external outcome
-> UNKNOWN
-> reconciliation
-> confirmed / pending / proved absent / still unknown
```

No blind duplicate publication is allowed after an ambiguous external mutation.

## 7. Commercial experience

The bot is the primary storefront. It should be able to present:

- free/trial capability if offered;
- plan comparison;
- current plan;
- usage and limits;
- upgrade/renewal entry points;
- purchase/subscription state;
- billing/help links where a browser or external payment flow is required.

The exact payment provider/mechanism is an implementation decision and must respect Telegram/platform/payment-store policy. Product architecture must keep subscription entitlements separate from identity and from provider API quotas.

## 8. Product architecture consequence

The existing modular-monolith architecture remains valid, but interface emphasis changes:

- add a first-class Telegram bot application/process boundary;
- treat Telegram update handling as a trusted ingress that still resolves tenant/workspace authority server-side;
- bot handlers must call domain/application services rather than contain business logic;
- backend API remains useful internally and for optional web surfaces;
- Next.js is secondary and should not consume MVP effort ahead of core bot workflows;
- Temporal remains the durable workflow engine;
- PostgreSQL remains the correctness authority;
- media processing remains isolated;
- provider adapters remain independent of Telegram UI code.

## 9. MVP vertical slice

The first real product slice is Telegram-native:

```text
Telegram /start
-> server-side Telegram identity/workspace resolution
-> onboarding/main menu
-> content upload
-> destination + publication options
-> tenant RLS transaction
-> atomic usage reservation
-> persisted publication operation keyed by operation_key
-> Temporal workflow
-> provider dispatch
-> bot status updates
-> UNKNOWN-safe reconciliation
-> final result shown in Telegram
```

The first staging/VM deployment should happen as soon as this path works for one real destination, rather than waiting for a complete web dashboard or every social platform.

## 10. Source-of-truth precedence

For current product intent, read in this order:

1. `docs/PRODUCT_VISION.md` — current product/UI direction.
2. `docs/PROJECT_STATUS.md` — current implementation stage.
3. `docs/CONTEXT_FOR_AI.md` — compact handoff context.
4. `AGENTS.md` — engineering constraints.
5. Historical architecture documents under `docs/history/` — validated contracts and rationale.

Historical documents that describe Next.js as the main customer frontend are superseded **only on product-interface priority**. Their reliability, security, tenancy, media, usage, workflow, and provider-lifecycle contracts remain authoritative unless explicitly revised by a later production decision.