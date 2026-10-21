## 9. Identity and tenancy

### 9.1 Core model

```text
User
  ↓
Membership
  ↓
Tenant / Workspace
  ↓
Brand / Resources
```

A user may belong to multiple tenants.

`tenant_id` from user input is never trusted as an authorization source. Active tenant context is resolved server-side from authenticated membership.

### 9.2 Authentication

Authentication is delegated to a managed identity provider.

ViMi does not implement its own:

- password hashing stack;
- password reset infrastructure;
- MFA engine;
- passkeys;
- enterprise SSO protocols.

### 9.3 Authorization

Authorization remains ViMi-owned.

Conceptual contract:

```text
can(actor, action, resource, tenant_context) -> allow/deny
```

Initial model: RBAC + explicit permissions.

Future relationship-based authorization engine may replace storage implementation without changing application contracts.

---

## 10. Roles, permissions and privileged access

Initial product roles:

- SuperAdmin
- Admin
- User

Domain model must support future roles such as:

- Owner
- Manager
- Editor
- Analyst
- Support
- Billing Manager

Roles are collections of permissions.

Plans and entitlements are **not** roles.

### Privileged actions

High-risk operations require:

- explicit authorization;
- audit event;
- reason where appropriate;
- step-up authentication where supported.

Examples:

- support impersonation;
- reading protected tenant content;
- changing subscription;
- disabling tenant;
- rotating credentials;
- assigning admin roles.

Support access should be temporary, scoped and read-only by default.

---

## 11. Entitlements and SaaS plans

Commercial plan names must not be spread through business logic.

Forbidden pattern:

```python
if tenant.plan == "PRO":
    ...
```

Required model:

```text
Plan
  ↓
PlanVersion
  ↓
Entitlements
```

Example entitlement values:

```text
max_connected_accounts
max_members
monthly_video_minutes
analytics_retention_days
auto_publish
smart_clip
approval_workflows
api_access
```

Plan versions are immutable once customers are assigned, allowing grandfathered pricing/features.

---

## 12. Usage metering

Usage metering is implemented **before billing integration**.

Append-only `UsageLedger` examples:

```text
published_post
scheduled_post
video_second_processed
ai_token
vision_frame
storage_byte_hour
egress_byte
connected_account
workspace_member
scout_run
```

Every usage record includes:

```text
tenant_id
metric
quantity
unit
source_id
correlation_id
occurred_at
```

Usage serves both billing and internal unit-economics analysis.

---

## 13. Content model

### 13.1 Core graph

```text
ContentItem
    ↓
ContentVersion
    ↓
Assets
    ↓
PlatformVariants
```

### 13.2 Immutable originals

Original assets are immutable.

```text
OriginalAsset
   ├── DerivedAsset A
   ├── DerivedAsset B
   └── DerivedAsset C
```

Never overwrite the original with an enhanced/rendered version.

### 13.3 Content versioning

Approvals, variants and publications bind to a **specific ContentVersion**.

If content is changed after approval, a new version is created and previous approval does not automatically carry forward.

---

## 14. Asset lineage and provenance

Every asset may store:

```text
source_type
source_url
original_hash
owner_reference
usage_basis
license_reference
consent_reference
imported_by
imported_at
```

A distribution policy may define permitted platform targets.

The publishing system only operates on content the tenant is authorized to distribute.

---

## 15. Media storage

Permanent media identity is an asset/storage key, not a local path.

Domain data stores:

```text
asset_id
storage_key
checksum
media_type
metadata
```

Object storage stores bytes.

Signed URLs are short-lived and generated only when needed by clients or platform ingestion.

Temporary local media is disposable.

---

## 16. Media processing architecture

```text
Original
   ↓
MediaProbe
   ↓
SceneDetector
   ↓
FeatureExtractor
   ↓
SceneRanker
   ↓
VariantPlanner
   ↓
RenderRecipe
   ↓
RenderService
   ↓
DerivedAsset / PlatformVariant
```

### Media worker isolation

Media workers run:

- non-root;
- with CPU/RAM/disk/time limits;
- with isolated temporary storage;
- with restricted outbound network access;
- without cloud metadata access;
- without direct access to SaaS secrets not required for media processing.

Arbitrary user URLs never flow directly to FFmpeg.

---

## 17. RenderRecipe

Every nontrivial rendered asset should be reproducible from a versioned recipe.

Example fields:

```text
recipe_version
source_asset_id
source_hash

clip_start_ms
clip_end_ms

target_width
target_height
crop_strategy

video_codec
audio_codec
crf
fps

branding_policy_version
renderer_version
model_versions

output_hash
```

Platform variants are rendered from an original or normalized master, never recursively from another lower-quality platform render unless explicitly intended.

---

## 18. AI architecture

AI is used only where probabilistic reasoning adds value.

### Deterministic components

- MediaProbe
- SceneDetector
- Quality metrics
- PlatformValidator
- RenderService
- RightsGate
- Scheduler
- Authorization
- Billing
- Publisher lifecycle execution

### AI/ML components

- Scout
- Curator
- SceneRanker
- VariantPlanner
- CaptionGenerator
- AnalyticsInsight

There is no universal “MegaAgent”.

### AI Tool Gateway

```text
Model
  ↓
Tool Request
  ↓
AI Tool Gateway
  ↓
Authorization
Tenant Context
Entitlement
Budget
Validation
Audit
  ↓
Application Service
```

Models never receive direct shell, unrestricted DB or secret-store access.

---

## 19. AI budgets and auditability

Every AI run can define:

```text
max_model_calls
max_tokens
max_images
max_video_frames
max_tool_calls
max_cost
deadline
```

Store significant AI runs with:

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

Avoid storing unnecessary sensitive raw prompts/media.

---

## 20. AI evaluation

Serious AI features require an evaluation path:

```text
candidate model/prompt
        ↓
golden evaluation set
        ↓
offline score
        ↓
shadow/internal tenant
        ↓
canary
        ↓
production
```

Scene selection, captioning and other subjective components should use human-reviewed benchmark sets.

Model/provider replacement occurs behind typed contracts.

---

## 21. Platform adapter contract

A platform is not represented by a single `publish()` method.

Conceptual lifecycle contract:

```text
get_capabilities()
connect()
refresh_credentials()

validate()
prepare()

start_publish()
get_publish_status()
handle_webhook()
reconcile_unknown()

fetch_external()
delete_external()
fetch_metrics()
```

Adapters implement only supported capabilities.

---

## 22. Platform Capability Registry

Capabilities are runtime/versioned data.

Examples:

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

Business logic queries the capability registry rather than scattering `if platform == ...` across the project.

---

## 23. Platform Compliance Registry

Separate from technical capabilities.

Stores operational/commercial policy state:

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

This prevents exposing a technically possible feature that is not yet commercially or policy-compliant.

---

## 24. Preflight validation

Before scheduling/publishing:

```text
Telegram     READY
X            READY
Instagram    READY
TikTok       REQUIRES_VARIANT
YouTube      TITLE_REQUIRED
Reddit       DESTINATION_REQUIRED
Bluesky      READY
```

Preflight validates known ViMi and platform constraints but never guarantees external platform acceptance.

---

## 25. Publication model

Do not store all publication state in one generic `posts` row.

Core model:

```text
PublicationBatch
    ↓
PublicationTarget
    ↓
PublicationAttempt(s)
    ↓
ExternalPost
```

A batch may partially succeed.

Failure on one target never triggers destructive rollback of already published posts on other platforms.

---

## 26. Publication state machine

Canonical states:

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

Failure/side states:

```text
RETRY_WAIT
AUTH_REQUIRED
REJECTED
FAILED_PERMANENT
UNKNOWN
CANCELLED
EXPIRED
```

Only the publishing/application domain owns state transitions.

Platform clients return outcomes; they do not directly mutate arbitrary domain state.

---
