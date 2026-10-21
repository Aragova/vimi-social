# 27. Platform Capability Registry

Versioned runtime capability data:

```text
supports_video
supports_images
supports_carousel
supports_stories
async_publish
supports_status_poll
supports_webhook
max_video_duration
max_video_bytes
max_images
max_caption_length
supported_aspect_ratios
analytics_support
delete_support
comment_support
```

No distributed platform `if` logic outside adapter/registry boundaries.

---

# 28. Platform Compliance Registry

Separate from capabilities:

```text
technical_status
api_version
app_review_status
commercial_status
allowed_account_types
branding_policy
required_scopes
consent_requirements
policy_version
policy_reviewed_at
```

Product UI exposes only features whose technical and compliance states allow them.

---

# 29. Preflight

Before scheduling:

```text
Telegram     READY
X            READY
Instagram    READY
TikTok       REQUIRES_VARIANT
YouTube      TITLE_REQUIRED
Reddit       DESTINATION_REQUIRED
Bluesky      READY
```

Preflight validates known constraints.

It never claims guaranteed platform acceptance.

---

# 30. Publication domain model

```text
PublicationBatch
    ↓
PublicationTarget
    ↓
PublicationAttempt(s)
    ↓
ExternalPost
```

Targets are independent.

A batch may become:

```text
SUCCESS
PARTIAL_SUCCESS
FAILED
```

Successful external posts are never rolled back automatically merely because another target failed.

---

# 31. External mutation phase model

PublicationAttempt includes:

```text
CREATED
NOT_STARTED
STARTED
PROVIDER_ACCEPTED
PENDING
UNKNOWN
CONFIRMED
FAILED_SAFE
FAILED_PERMANENT
```

Important distinction:

- `FAILED_SAFE` means ViMi has evidence the provider did not perform the external side effect.
- `UNKNOWN` means the side effect may have occurred.

Blind retry from `UNKNOWN` is forbidden.

---

# 32. Idempotency and reconciliation

Each adapter defines:

```text
idempotency_strategy
reconciliation_strategy
safe_retry_conditions
```

Attempt stores:

```text
attempt_id
operation_key
dispatch_token
provider_request_id?
started_at
provider_accepted_at?
outcome_class
```

If provider supports idempotency keys, use them.

Otherwise:

```text
UNKNOWN
   ↓
reconcile provider
   ├── external found → CONFIRMED
   ├── proven absent  → SAFE_RETRY
   └── cannot prove   → NEEDS_REVIEW
```

Introduce optional:

```text
ReconciliationCase
```

for unresolved unknown outcomes.

---

# 33. Publication state machine

High-level target state:

```text
DRAFT
VALIDATING
READY
NEEDS_APPROVAL
APPROVED
SCHEDULED
PREPARING
DISPATCHING
PLATFORM_PROCESSING
PUBLISHED
```

Additional states:

```text
RETRY_WAIT
AUTH_REQUIRED
BLOCKED_ENTITLEMENT
REJECTED
FAILED_PERMANENT
UNKNOWN
CANCELLATION_REQUESTED
CANCELLED
EXPIRED
```

State transitions are centralized and tested.

---

# 34. Cancellation semantics

Cancel before external dispatch:

```text
CANCELLED
```

Cancel after side effect may have started:

```text
CANCELLATION_REQUESTED
       ↓
reconciliation
       ├── not sent  → CANCELLED
       └── accepted  → CANCEL_TOO_LATE / published resolution
```

UI never falsely promises immediate cancellation when external outcome is uncertain.

---

# 35. Deletion lifecycle

Deletion does not immediately remove in-flight domain objects.

```text
ACTIVE
  ↓
DELETE_REQUESTED
  ↓
cancel future work
  ↓
reconcile in-flight work
  ↓
optional external delete
  ↓
PURGE_PENDING
  ↓
PURGED
```

Tombstones remain until workflows are safely resolved.

---

# 36. Deterministic workflow identity

Every domain workflow receives deterministic ID.

Example:

```text
publication-target:{target_id}:v1
```

Outbox events have immutable:

```text
event_id
```

Outbox delivery is assumed at-least-once.

Duplicate relay attempts start the same logical workflow, not a second publication.

---

# 37. Transactional outbox

Atomic domain transaction:

```text
BEGIN
  update domain state
  insert OutboxEvent(event_id)
COMMIT
```

Outbox relay may crash/retry safely.

Do not depend on `delivered_at` for exactly-once semantics.

Deduplication exists at workflow/event consumer boundary.

---

# 38. Temporal responsibility

PostgreSQL:

```text
business truth
```

Temporal:

```text
execution truth
```

Temporal is used for:

- scheduled publication;
- async platform processing;
- multi-step AI/media flows;
- approval-to-publication orchestration;
- reconciliation;
- durable timers/retries.

Simple isolated work may use Temporal activities/standalone activities.

No competing full PostgreSQL job engine exists.

---

# 39. Temporal workflow evolution policy

Running workflows must survive application deployment.

Rules:

- workflow code is deterministic;
- no network/database I/O directly in workflow code;
- I/O occurs in activities;
- workflow types are versioned where necessary;
- Worker Versioning / compatible deployment mechanism is used;
- old workflow code is retained while old workflows require replay;
- long histories may use `continue-as-new`;
- secrets/media are never stored in workflow history;
- irreversible mutation activities do not receive blind SDK retry semantics.

Deployment test:

```text
start old workflow
deploy new worker
resume/replay
complete safely
```

must pass.

---

# 40. Provider quota coordination

Tenant fairness and provider quotas are separate concerns.

Add:

```text
PlatformQuotaCoordinator
```

Possible scopes:

```text
provider-global
provider-app
endpoint
platform-account
tenant
```

Adapters report provider rate-limit headers/events.

Scheduling requires both:

```text
resource capacity available
AND
provider quota available
```

After provider outage, backlog drains gradually with jitter and fairness rather than burst release.

---

# 41. Noisy-neighbor protection

Scheduling considers:

```text
global capacity
  ↓
work class
  ↓
provider/platform
  ↓
tenant fairness
  ↓
plan priority
  ↓
job priority
```

Expensive work has per-tenant concurrent limits.

Paid priority never means unlimited resource capture.

---

# 42. Webhook Inbox

Webhook request flow:

```text
receive
  ↓
verify signature
  ↓
freshness/replay check
  ↓
resolve trusted external account
  ↓
persist WebhookInbox
  ↓
dedupe provider event ID
  ↓
respond quickly
  ↓
async process
```

Fields:

```text
provider
provider_event_id
provider_timestamp?
provider_sequence?
payload_hash
received_at
processing_state
```

Tenant is derived from known server-side platform account mapping, never trusted from webhook payload.

---

# 43. Webhook ordering

External events may duplicate or arrive out of order.

Domain transitions are monotonic.

Forbidden regression:

```text
PUBLISHED → PROCESSING
```

Older provider events are stored for audit if useful but cannot regress domain state.

---

# 44. AI architecture

Deterministic:

```text
MediaProbe
SceneDetector
QualityMetrics
PlatformValidator
RenderService
RightsGate
Scheduler
Publisher execution
Authorization
Billing
```

Probabilistic/AI:

```text
Scout
Curator
SceneRanker
VariantPlanner
CaptionGenerator
AnalyticsInsight
```

No universal MegaAgent.

---

# 45. AI Tool Gateway

```text
Model
  ↓
Typed Tool Request
  ↓
AI Tool Gateway
  ├ tenant enforcement
  ├ authorization
  ├ entitlements
  ├ budget
  ├ argument validation
  ├ rate limit
  └ audit
  ↓
Application Service
```

AI cannot:

- run arbitrary shell;
- issue arbitrary SQL;
- fetch arbitrary secrets;
- choose authoritative tenant;
- bypass plan limits.

External content is treated as untrusted data, not instruction.

---

# 46. AI Processing Policy

Data classification controls model-provider eligibility.

Example:

```text
PUBLIC
→ approved public/commercial providers

CUSTOMER_CONTENT
→ providers with accepted retention/privacy terms

RESTRICTED
→ approved enterprise/local processing only

SECRET/CREDENTIAL
→ never sent to general-purpose model
```

Add:

```text
AIProcessingPolicy
```

Inputs:

```text
data_classification
tenant policy
task type
model/provider
region
retention guarantees
cost budget
```

Provider selection is policy-driven, not only cost-driven.

---

# 47. AI budgets and retry safety

Per-run budget:

```text
max_model_calls
max_tokens
max_images
max_video_frames
max_tool_calls
max_cost
deadline
```

Additional budgets:

```text
tenant/day
tenant/billing-period
global/provider
```

`AIRun` receives deterministic/unique:

```text
operation_key
```

to prevent accidental duplicate billing/work where feasible.

AI retry policy is provider and operation specific.

---

# 48. AI audit and evaluation

Store meaningful AI run metadata:

```text
ai_run_id
tenant_id
agent_type
provider
model
model_version
prompt_version
input_hash
output_hash
tool_calls
token_usage
media_usage
latency
estimated_cost
decision
confidence
human_override
created_at
```

Serious AI features require:

```text
golden dataset
offline evaluation
shadow/internal run
canary
production
```

---
