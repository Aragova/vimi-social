## 27. Unknown outcome / reconciliation

External mutations can succeed remotely even when the local response is lost.

Example:

```text
DISPATCHING
   ↓
network timeout
   ↓
UNKNOWN
   ↓
reconciliation
   ├── remote post found     → PUBLISHED
   ├── proven not published  → safe retry
   └── indeterminate         → NEEDS_REVIEW
```

Blind retry after an unknown external mutation is forbidden.

---

## 28. Idempotency

Every externally visible side effect defines an idempotency strategy.

Examples:

- publication attempt;
- payment mutation;
- webhook processing;
- account connection;
- destructive admin action.

Where the external provider does not support idempotency, ViMi uses internal attempt identity plus reconciliation.

---

## 29. Retry policy

Retry behavior depends on error taxonomy.

Examples:

```text
transient provider 5xx       retry
rate limited                 provider-aware delayed retry
invalid media                never retry unchanged
expired access token         refresh / reauth path
unknown publish outcome      reconcile; do not blind retry
permission revoked           user action required
```

No universal “retry 3 times” policy.

---

## 30. Circuit breakers and bulkheads

Each external platform/provider receives independent failure isolation.

If Instagram is degraded:

```text
Instagram  DEGRADED
Telegram   HEALTHY
X          HEALTHY
TikTok     HEALTHY
```

Instagram failure must not consume all platform worker capacity.

Resource bulkheads also isolate:

- AI provider work;
- media rendering;
- analytics collection;
- tenant-heavy workloads.

---

## 31. Noisy-neighbor protection

Scheduling considers:

```text
global capacity
  ↓
work class
  ↓
platform/provider
  ↓
tenant fairness
  ↓
plan priority
  ↓
job priority
```

Paid plans may receive priority but cannot monopolize global resources.

Per-tenant quotas/concurrency are enforced for expensive work.

---

## 32. Temporal usage policy

PostgreSQL is **business truth**.

Temporal is **execution truth**.

### Use Temporal workflows for:

- scheduled multi-step publication;
- async platform processing;
- long-running AI/media flows;
- approval-to-publication orchestration;
- account reconciliation.

### Use Temporal Standalone Activities or simple activities for:

- media probe;
- thumbnail generation;
- analytics fetch;
- simple exports;
- isolated AI generation.

Do not maintain a competing full PostgreSQL job engine.

---

## 33. Transactional outbox

Critical domain changes and emitted work/events are recorded atomically.

```text
DB transaction
  ├── update domain state
  └── insert outbox event
COMMIT
      ↓
outbox relay
      ↓
Temporal/event consumer
```

This prevents state saying “ready” while its workflow was never started.

---

## 34. Webhook inbox

External webhooks follow:

```text
HTTP request
  ↓
verify signature
  ↓
replay/freshness check
  ↓
deduplicate event ID
  ↓
persist WebhookInbox
  ↓
respond quickly
  ↓
async processing
```

Webhook processing is idempotent.

---

## 35. Scheduling and timezones

No naive datetimes.

For user-facing schedules preserve:

```text
local wall-clock intent
timezone identifier
resolved UTC instant
```

Recurring schedules must survive DST/timezone rule changes.

---

## 36. Database rules

PostgreSQL is the canonical source of business state.

PostgreSQL does **not** store:

- large media blobs;
- cache-only state;
- workflow execution history as primary truth.

### Row-Level Security

RLS is used selectively for tenant-owned sensitive tables as a defense-in-depth layer.

Application authorization remains mandatory.

The application database role design must account for RLS owner/bypass semantics.

---

## 37. IDs

Public resource identifiers should not expose simple sequential tenant/user IDs.

UUIDv7 is a preferred candidate.

Final choice between:

- UUIDv7 primary keys;
- bigint internal PK + UUIDv7 public ID

will be made during physical schema review.

---

## 38. Credentials and secrets

Platform credentials are represented by references:

```text
credential_ref
expires_at
scopes
health
```

Plaintext secrets must not appear in:

- domain DTOs;
- logs;
- audit payloads;
- Temporal workflow state;
- analytics records;
- browser responses.

Secret access is scoped to the smallest component that needs it.

---

## 39. Account health

Connected accounts expose health states:

```text
HEALTHY
EXPIRING
REFRESHING
REAUTH_REQUIRED
DISABLED
PROVIDER_DEGRADED
```

UI surfaces account health before a scheduled publication fails.

---

## 40. Error taxonomy

Typed domain/platform errors include:

```text
AUTH_REVOKED
AUTH_SCOPE_MISSING
RATE_LIMITED
PLATFORM_UNAVAILABLE
MEDIA_INVALID
MEDIA_TOO_LARGE
PLATFORM_REJECTED
PLATFORM_PROCESSING_FAILED
OUTCOME_UNKNOWN
TENANT_LIMIT_EXCEEDED
PLAN_FEATURE_UNAVAILABLE
CONTENT_NOT_APPROVED
RIGHTS_NOT_CONFIRMED
```

Each error may define:

```text
retryable
severity
user_action
user_message
admin_context
provider_code
```

Customer UI receives actionable messages; control plane receives diagnostic context.

---

## 41. Approval workflows

Approval model:

```text
ApprovalFlow
  ↓
ApprovalStep 1
  ↓
ApprovalStep 2
  ↓
...
```

Steps may target:

- role;
- specific user;
- manager;
- client approver.

Approval is always bound to a specific ContentVersion.

---

## 42. Control plane

Customer plane and control plane are distinct authorization/product concepts.

### Customer plane

- Content
- Calendar
- Accounts
- AI Studio
- Approvals
- Analytics
- Team
- Billing

### ViMi control plane

- Tenants
- Users
- Subscriptions
- Entitlements
- Usage
- Costs
- Platform health
- OAuth health
- Workflow health
- AI health
- Feature flags
- Audit
- Support access
- System configuration

They may initially live in one application but keep separate boundaries and permissions.

---

## 43. Observability

Use OpenTelemetry-compatible:

- traces;
- structured logs;
- low-cardinality metrics.

Common context:

```text
request_id
correlation_id
trace_id
tenant_id
publication_id
content_id
platform
account_id
workflow_id
```

High-cardinality resource IDs belong in traces/logs, not default Prometheus labels.

Metrics favor dimensions such as:

```text
platform
operation
outcome
worker_type
```

Measure p50/p95/p99 where relevant, not only averages.

---

## 44. Audit

Audit log is append-only and distinct from application logs.

Example fields:

```text
actor_user_id
actor_role
tenant_id
action
target_type
target_id
before_hash
after_hash
reason
ip
user_agent
request_id
created_at
```

Admin/support activity is always auditable.

---

## 45. Data classification and retention

Data classes:

```text
PUBLIC
INTERNAL
CUSTOMER_CONTENT
PERSONAL_DATA
CREDENTIAL
SECRET
PAYMENT_REFERENCE
AUDIT
```

Classification influences:

- encryption;
- logging;
- support visibility;
- retention;
- AI-provider eligibility;
- backup handling.

Retention policies exist for:

- temporary uploads;
- failed render artifacts;
- AI intermediate frames;
- published derivatives;
- originals;
- audit events.

---

## 46. API-first design

Web UI consumes the same application API layer used by future:

- mobile app;
- public developer API;
- MCP integration;
- automation clients;
- browser extensions.

REST/OpenAPI is the initial public contract.

Domain models are not exposed directly as API DTOs.

Public API/event contracts are versioned.

Example events:

```text
publication.created.v1
publication.published.v1
publication.failed.v1
account.reauth_required.v1
content.version_created.v1
```

---

## 47. Frontend and design system

Premium UI is built from:

```text
Design Tokens
  ↓
Primitives
  ↓
Components
  ↓
Patterns
  ↓
Screens
```

Baseline requirements:

- TypeScript strict;
- accessibility target WCAG 2.2 AA;
- keyboard navigation;
- focus states;
- semantic HTML;
- reduced-motion support;
- responsive design;
- dark/light support if product design requires;
- loading/empty/error states;
- platform/account health states;
- consistent typography/spacing/status language.

Internationalization is used from the first UI text.

Initial locales: Russian and English.

---

## 48. Security baseline

Security controls include:

- deny-by-default authorization;
- tenant isolation tests;
- secret scanning;
- dependency scanning;
- SSRF defenses;
- upload validation;
- webhook verification;
- media sandboxing;
- least-privilege cloud identities;
- immutable build artifacts;
- privileged action audit;
- short-lived signed media URLs;
- security headers and secure cookie/session configuration;
- CSRF protection where applicable.

---

## 49. Supply-chain security

Production artifact flow:

```text
Git commit
  ↓
CI
  ↓
lint/types/tests/security
  ↓
container build
  ↓
SBOM
  ↓
artifact digest
  ↓
provenance/attestation
  ↓
staging
  ↓
same digest
  ↓
production
```

No `git pull && pip install` production deployment.

---
