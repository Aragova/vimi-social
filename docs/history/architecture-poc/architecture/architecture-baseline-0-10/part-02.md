# 10. Tenant isolation and RLS contract

Tenant-owned rows contain `tenant_id`.

Application repositories require a `TenantContext`.

RLS is applied selectively to sensitive tenant-owned tables.

Conceptual transaction pattern:

```text
BEGIN
SET LOCAL app.tenant_id = <trusted tenant>
...
COMMIT
```

Rules:

- tenant session setting is transaction-local;
- pooled connections must never retain previous tenant context;
- tests execute with production-like `vimi_app`, not only superuser;
- RLS is defense-in-depth, not replacement for application authorization;
- table ownership/RLS bypass semantics are tested explicitly.

Tenant isolation tests intentionally remove the application-level tenant WHERE filter and verify the DB still prevents cross-tenant reads.

---

# 11. Authentication and authorization

Authentication uses a managed identity provider.

ViMi does not implement password storage, MFA or passkey infrastructure.

Authorization belongs to ViMi.

Core contract:

```text
can(actor, action, resource, tenant_context)
    -> ALLOW / DENY
```

Initial authorization model:

```text
Membership
Role
Permission
Resource ownership
```

Future relationship-based authorization may replace policy storage without changing application contracts.

---

# 12. Roles, permissions and support access

Initial product-facing roles:

- SuperAdmin
- Admin
- User

Data model supports future roles:

- Owner
- Manager
- Editor
- Analyst
- Support
- Billing Manager

Roles and plans remain separate concepts.

## Support impersonation

Support session stores:

```text
support_session_id
privileged_actor_id
effective_actor_id
tenant_id
reason
scope
started_at
expires_at
```

Default:

```text
read-only
time-limited
visible UI banner
fully audited
```

Audit event must display:

```text
Admin X acting as User Y
```

---

# 13. Entitlements and execution-time policy

Entitlements define commercial capability.

```text
Plan
  ↓
PlanVersion
  ↓
Entitlements
```

Examples:

```text
max_connected_accounts
max_members
monthly_video_minutes
smart_clip
auto_publish
approval_workflows
analytics_retention_days
api_access
```

No distributed:

```python
if plan == "PRO":
```

in application logic.

## Execution-time entitlement

The architecture distinguishes:

```text
EntitlementDecision
```

from plan configuration.

A scheduled action records its entitlement policy decision.

Before irreversible execution, ViMi revalidates according to the product policy.

For premium work that consumes scarce quota, use reservation.

---

# 14. UsageLedger + UsageReservation

`UsageLedger` is append-only accounting history.

`UsageReservation` prevents concurrent overspending.

Reservation state:

```text
RESERVED
COMMITTED
RELEASED
EXPIRED
```

Flow:

```text
check entitlement
      ↓
atomic reservation
      ↓
expensive work
  ┌───┴────┐
  ↓        ↓
success   failure
  ↓        ↓
COMMIT    RELEASE
```

Fields include:

```text
reservation_id
tenant_id
metric
quantity
operation_key
expires_at
state
```

Usage events include globally unique/deterministic:

```text
usage_dedupe_key
```

Retries cannot double charge.

Adjustments are compensating ledger records, never silent historical rewrites.

---

# 15. Content model

```text
ContentItem
    ↓
ContentVersion
    ↓
Assets
    ↓
PlatformVariants
```

All approvals and publications point to a specific immutable `ContentVersion`.

"Current version" is never used as authority for an already scheduled target.

---

# 16. Approval concurrency

Approval stores:

```text
approval_id
content_version_id
approval_flow_id
step_id
actor_id
decision
created_at
```

PublicationTarget stores immutable:

```text
content_version_id
```

At publication creation/execution:

```text
approved_version_id
==
publication_target.content_version_id
```

must be verified.

Changing content creates a new version and invalidates previous approval for the new version.

Optimistic locking/version columns prevent concurrent editor race conditions.

---

# 17. Asset model and lifecycle

Original assets are immutable.

Lifecycle:

```text
PENDING_UPLOAD
UPLOADED
VERIFIED
READY
DELETE_REQUESTED
PURGE_PENDING
PURGED
FAILED
```

Publication only consumes `READY` assets.

Every asset stores:

```text
asset_id
tenant_id
storage_key
sha256
size_bytes
content_type
metadata
storage_version_id?
retention_class
retain_until
```

Storage key is immutable.

---

# 18. Asset leases and references

Retention cannot delete assets still needed by active work.

Introduce:

```text
AssetLease
────────────────
asset_id
owner_type
owner_id
expires_at
```

Examples:

```text
PublicationTarget lease
Temporal workflow lease
Render job lease
Provider ingestion lease
```

Cleanup requires:

```text
no active lease
AND retention expired
AND no legal/tenant hold
```

Reference counting may supplement, but lease/reconciliation is the primary mechanism for long-running jobs.

---

# 19. Asset provenance and distribution rights

Store:

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

Distribution policy may restrict allowed destinations.

Publishing requires rights/policy eligibility.

---

# 20. Secure media ingress

Media ingress is split into four components:

```text
UploadIngest
RemoteMediaFetcher
MediaVerifier
MediaWorker
```

## RemoteMediaFetcher

Must:

- allow only approved schemes;
- resolve DNS server-side;
- reject loopback/private/link-local/multicast/reserved networks;
- handle IPv4 and IPv6;
- revalidate every redirect;
- cap redirect count;
- restrict ports;
- enforce byte limit while streaming;
- enforce connect/read/total timeouts;
- not forward arbitrary user cookies/headers;
- have no route to cloud metadata/private control networks;
- write into quarantine/object storage;
- never invoke FFmpeg on a remote URL.

Protection must account for DNS rebinding and alternative IP encodings.

---

# 21. Media verification and resource-bomb protection

Before full processing validate:

```text
file size
container parse time
duration
resolution
pixel count
stream count
frame-rate sanity
codec/container policy
```

Media Worker runs:

```text
non-root
CPU limit
RAM limit
disk limit
wall-time limit
restricted network
isolated temp storage
```

A pathological media file cannot consume unlimited resources.

---

# 22. RenderRecipe

Derived assets are reproducible from versioned recipes:

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

Derived platform variants come from original/normalized master, not from another degraded platform render unless explicitly requested.

---

# 23. Platform account ownership

Default invariant:

```text
one external social account
→ one owning tenant
```

Globally unique:

```text
(provider, external_account_id)
```

If future agency sharing is required, model it explicitly:

```text
PlatformAccountGrant
```

Do not permit accidental duplicate connections across tenants.

---

# 24. Credential model and token refresh concurrency

Credential metadata:

```text
platform_account_id
credential_ref
credential_version
expires_at
scopes
health
updated_at
```

Plaintext tokens live only in approved secret storage / short-lived process memory.

## Refresh protocol

Use single-flight refresh + compare-and-swap:

```text
lock account refresh
      ↓
reload latest credential version
      ↓
already refreshed?
  yes → reuse
  no  → refresh provider
      ↓
store only if expected_version matches
      ↓
credential_version += 1
```

Publishing rechecks credential/account version before irreversible mutation.

Concurrent refresh tests are mandatory.

---

# 25. Account health

States:

```text
HEALTHY
EXPIRING
REFRESHING
REAUTH_REQUIRED
DISABLED
PROVIDER_DEGRADED
```

Account health is visible before scheduled publication time.

Disabled/revoked account blocks new irreversible dispatch.

---

# 26. Platform Adapter contract

Conceptual contract:

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

Adapters return typed outcomes; they do not arbitrarily update publication repositories.

Example typed outcomes:

```text
PublishStarted
PublishPending
PublishConfirmed
PublishRejected
PublishUnknown
```

PublishingService/Workflow owns state transitions.

---
