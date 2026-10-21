# 49. Scheduling and timezone correctness

Server owns scheduling truth.

Store:

```text
local_wall_time
iana_timezone
resolved_utc_instant
```

No naive datetimes.

Recurring schedules retain local intent across timezone/DST changes.

Browser clock is advisory only.

---

# 50. Membership and permission changes after scheduling

At creation:

- user must be authorized.

At execution:

- tenant must still be active;
- platform account must still belong to tenant;
- content/version must remain eligible;
- target must not be revoked;
- account/credential must remain valid;
- execution entitlement policy must pass.

Product decision on creator-role revocation is explicit and versioned.

Historic authorization decision is stored for audit, but stale permission snapshot does not become permanent authority.

---

# 51. Entitlement changes after scheduling

Architecture supports one explicit product policy:

```text
RESERVE_AT_SCHEDULE
REVALIDATE_AT_EXECUTION
GRACE_EXISTING_SCHEDULES
```

The chosen policy is recorded/versioned.

Blocked execution uses:

```text
BLOCKED_ENTITLEMENT
```

rather than generic failure.

---

# 52. Feature flags vs kill switches

Feature flag:

```text
controls rollout/configuration
```

Kill switch:

```text
stops unsafe future irreversible actions
```

Long-running workflows capture:

```text
execution_policy_version
```

for semantics that must remain stable.

Emergency kill switches remain live and may prevent the next irreversible step.

---

# 53. Redis policy

Redis is optional.

Every use declares failure semantics.

Examples:

```text
UI cache
→ fail open

non-security cache
→ fail open

provider quota
→ conservative fallback

expensive usage quota
→ PostgreSQL authority

security abuse throttle
→ fail closed or local conservative fallback
```

Redis never owns canonical entitlement, usage or billing data.

---

# 54. Secret manager outage

Optional short-lived in-memory token cache may exist.

Bound by:

```text
TTL
credential_version
account health
```

Never persist decrypted credentials to local disk.

If no valid credential is available:

```text
retry/auth-required
```

rather than unsafe fallback.

---

# 55. Sensitive-data redaction

Central:

```text
SensitiveDataRedactor
```

removes or masks:

- bearer tokens;
- refresh tokens;
- API keys;
- cookies;
- authorization headers;
- signed URL query strings;
- known secret patterns.

Logs prefer structured safe fields.

Security tests inject fake secrets and assert absence from log capture.

---

# 56. Observability

OpenTelemetry-compatible:

```text
traces
structured logs
low-cardinality metrics
```

Common context:

```text
request_id
server_correlation_id
trace_id
tenant_id
publication_id
content_id
platform
account_id
workflow_id
```

External client correlation IDs are untrusted and sanitized or stored separately.

Metrics do not use tenant/user/content IDs as routine labels.

Trace/log sampling and retention budgets are explicit.

---

# 57. Analytics model

Provider analytics are snapshots/revisions, not assumed monotonic counters.

Store:

```text
provider_metric_name
provider_raw_value
provider_schema_version
provider_period
observed_at

normalized_metric_name
normalized_value
normalization_version
```

Normalization can be recomputed when semantics change.

---

# 58. Data classification and retention

Data classes:

```text
PUBLIC
INTERNAL
CUSTOMER_CONTENT
PERSONAL_DATA
RESTRICTED
CREDENTIAL
SECRET
PAYMENT_REFERENCE
AUDIT
```

Retention policy applies to:

- temporary uploads;
- quarantine files;
- failed renders;
- AI intermediate frames;
- derived assets;
- originals;
- audit records;
- webhook payloads.

Retention job respects active AssetLease and deletion state.

---

# 59. API-first contract

Customer Web UI consumes the same application API used by future clients.

Initial contract:

```text
REST + OpenAPI
```

Domain entities are not serialized directly.

Versioned public DTOs/events:

```text
publication.created.v1
publication.published.v1
publication.failed.v1
account.reauth_required.v1
content.version_created.v1
```

---

# 60. Frontend baseline

Technology:

```text
Next.js
TypeScript strict
Design Tokens
Storybook/component documentation
```

UI requirements:

- WCAG 2.2 AA target;
- keyboard navigation;
- focus states;
- semantic HTML;
- responsive behavior;
- loading/empty/error states;
- account health;
- target-level publication status;
- partial-success UX;
- internationalization from first screen.

Initial locales:

```text
ru
en
```

---

# 61. Premium partial-success UX

Example:

```text
Publication batch

Telegram      Published
X             Published
Instagram     Auth required
TikTok        Unknown — checking
YouTube       Published
```

Overall:

```text
PARTIAL_SUCCESS
```

Never expose only "Failed" for mixed outcome.

"Retry all" must not repeat targets already externally confirmed.

---

# 62. CI/CD and architecture fitness

Merge gates:

```text
Ruff
Pyright
unit tests
integration tests
architecture tests
tenant isolation tests
workflow tests
migration checks
secret scanning
dependency scanning
contract tests
```

Architecture fitness functions verify:

- platform isolation;
- tenant context requirement;
- no direct AI secret/DB access;
- media URL boundary;
- state transition legality;
- usage dedupe;
- public contract compatibility;
- migration safety;
- secret redaction.

---

# 63. Migration policy

Production migrations use:

```text
expand
deploy compatible readers/writers
backfill
validate
contract later
```

Rules:

- lock timeout;
- statement timeout;
- concurrent index creation where available;
- no unbounded table rewrite in normal deploy;
- destructive cleanup separated from feature deployment;
- rehearse on production-scale dataset;
- old app version remains compatible during rollback window.

---

# 64. Deployment compatibility

Every release defines:

```text
schema compatibility
workflow compatibility
rollback compatibility
```

New code must tolerate the immediately previous compatible schema/state during rolling deployment.

Old workflow code required for replay is not removed prematurely.

Production image is immutable and identified by digest.

---

# 65. Supply-chain baseline

```text
Git commit
  ↓
CI
  ↓
tests/scanners
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

No mutable `latest` deployment as source of truth.

No manual `git pull && pip install` on production.

---

# 66. Disaster recovery model

Systems involved:

```text
PostgreSQL
Temporal
Object Storage
External Social Platforms
Secret Store
```

PostgreSQL remains canonical business state, but external side effects may have occurred after a DB restore point.

Recovery runbook:

```text
1. Global publishing kill switch ON
2. Restore PostgreSQL
3. Verify object storage consistency
4. Isolate/pause affected workflow execution
5. Determine uncertainty time window
6. Reconcile external platform state
7. Recreate/restart workflows from canonical state/outbox
8. Validate no duplicate external side effects
9. Resume publishing gradually
```

DR drills must test PostgreSQL/Temporal disagreement.

---

# 67. Backup policy

PostgreSQL:

- managed backups;
- PITR;
- restore drills.

Object storage:

- versioning where appropriate;
- lifecycle policy;
- restore/consistency check.

Before public launch define target:

```text
RPO
RTO
```

and measure recovery against them.

---

# 68. Technology baseline

| Layer | Baseline |
|---|---|
| Backend | Python 3.12/3.13 after compatibility validation |
| HTTP | FastAPI |
| Validation | Pydantic v2 |
| ORM | SQLAlchemy 2 |
| DB driver | psycopg 3 |
| Database | Managed PostgreSQL |
| Workflow | Temporal Cloud |
| Cache/ephemeral limits | Redis only if justified |
| Object storage | S3-compatible |
| Video | FFmpeg/ffprobe isolated worker |
| Frontend | Next.js + TypeScript strict |
| Authn | Managed IdP |
| Authz | ViMi AuthorizationService |
| Secrets | Managed Secret Store/KMS |
| Observability | OpenTelemetry |
| Migrations | Alembic |
| Python quality | Ruff + Pyright |
| Testing | pytest + Playwright |
| CI/CD | GitHub Actions |
| Packaging | Immutable Docker |
| Supply chain | SBOM + scanning + provenance |
| IaC | Terraform/OpenTofu when staging is formalized |

---

# 69. Explicit non-goals before measured need

Do not add merely for prestige:

```text
Kafka
Kubernetes
ClickHouse
OpenFGA
Elasticsearch cluster
database sharding
multi-region active-active
dozens of microservices
custom authentication stack
full event sourcing
```

Any addition requires measurement + ADR.

---
