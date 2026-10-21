# 70. Updated domain entities

Core:

```text
User
Identity
Tenant
Membership
Role
Permission

Plan
PlanVersion
Entitlement
EntitlementDecision
Subscription

UsageReservation
UsageLedger

BrandProfile

PlatformDefinition
PlatformCapabilityVersion
PlatformComplianceVersion
PlatformAccount
PlatformAccountGrant?
CredentialVersion

ContentItem
ContentVersion
Asset
AssetLease
AssetProvenance
DistributionPolicy
PlatformVariant
RenderRecipe

ApprovalFlow
ApprovalStep
Approval

PublicationBatch
PublicationTarget
PublicationAttempt
ExternalPost
ReconciliationCase

OutboxEvent
WebhookInbox

AIRun
AIDecision
AIProcessingPolicy

AuditEvent
SupportSession
FeatureFlag
```

---

# 71. Critical invariants

These invariants are part of Architecture 0.10.

### Tenant

```text
Every tenant-owned operation has trusted TenantContext.
```

### Content

```text
Approved publication points to immutable ContentVersion.
```

### Asset

```text
Original asset is immutable.
```

### Platform account

```text
External platform account has one owning tenant by default.
```

### Publication

```text
UNKNOWN external mutation is never blindly retried.
```

### Workflow

```text
Same logical publication target maps to deterministic workflow identity.
```

### Usage

```text
Expensive work reserves quota atomically.
```

### Credential

```text
Concurrent token refresh cannot overwrite newer credentials.
```

### Webhook

```text
Webhook cannot choose authoritative tenant.
```

### AI

```text
Model cannot bypass Tool Gateway authorization/budget/data policy.
```

---

# 72. Five PoCs — executable acceptance plan

Architecture 0.10 must now be tested in code through five small prototypes.

## PoC A — Temporal durability, identity and versioning

Must prove:

- deterministic workflow ID;
- duplicate outbox delivery does not duplicate workflow;
- worker crash and restart;
- long sleep/timer survives;
- old workflow survives new worker release;
- unknown external mutation does not get blind retry;
- reconciliation resolves mocked unknown result.

Pass criteria:

```text
0 duplicate logical publications
0 replay nondeterminism errors
workflow resumes after crash/deploy
```

---

## PoC B — Tenant isolation + PostgreSQL RLS

Must prove:

- application role cannot read another tenant;
- missing application WHERE still blocked by RLS;
- connection reuse cannot leak tenant setting;
- Temporal activity respects tenant boundary;
- webhook path resolves tenant server-side;
- support/control-plane access is explicit and audited.

Pass criteria:

```text
all cross-tenant probes denied
no tenant context leakage between pooled connections
```

---

## PoC C — Secure media ingest

Must test:

- normal upload;
- normal remote URL;
- redirect to localhost;
- DNS rebinding;
- private IPv4;
- private/link-local IPv6;
- oversized streaming body;
- no Content-Length;
- redirect loop;
- malformed media;
- extreme resolution;
- worker CPU/RAM/time limit;
- asset lease prevents cleanup mid-job.

Pass criteria:

```text
malicious ingress fails safely
normal media reaches READY
worker exhaustion stays isolated
```

---

## PoC D — Async platform mock

Mock provider must simulate:

```text
success
accepted + lost response
pending
pending + completed
duplicate webhook
out-of-order webhook
429
500
auth expired
rotating refresh token
provider outage
```

Pass criteria:

```text
no duplicate external post
correct final state
correct credential version
state never regresses
```

---

## PoC E — Usage concurrency

Simulate:

```text
limited video quota
100 concurrent jobs
retries
failures
refund/release
duplicate completion
```

Pass criteria:

```text
reservations never exceed quota
no duplicate usage charge
failed jobs release quota correctly
```

---

# 73. PoC implementation rule

PoCs are disposable experiments, not the production repository.

They may live under:

```text
architecture-poc/
```

or separate temporary branches/repository.

Goal:

```text
prove assumptions
```

not:

```text
start product implementation early
```

Code from PoC may be rewritten for production.

---

# 74. Architecture 1.0 gate

Architecture can be frozen as 1.0 only after:

- all five PoCs pass;
- results are documented;
- failures update this baseline;
- Red-Team v2 attacks the corrected design;
- no Critical unresolved finding remains;
- High findings have either implementation or explicit accepted risk.

---

# 75. Updated delivery path after Architecture 1.0

Only after 1.0:

```text
Create production repository
        ↓
CI / architecture fitness
        ↓
Tenant/Auth core
        ↓
Content core
        ↓
Publishing core
        ↓
Telegram Adapter
        ↓
X Adapter
        ↓
Media Factory
        ↓
AI Layer
        ↓
Instagram/TikTok/YouTube
        ↓
Analytics Feedback
        ↓
Billing
        ↓
Pilot SaaS tenants
```

---

# 76. Decision status

## Confirmed

```text
Separate product/repository
Modular monolith
Managed PostgreSQL
Temporal Cloud
Object Storage
Managed IdP
FastAPI backend
Next.js frontend
Platform Adapter model
Content versioning
Unknown-outcome reconciliation
Usage reservation + ledger
AI Tool Gateway
Media isolation
Architecture fitness tests
```

## Deferred intentionally

```text
exact cloud provider
exact managed IdP vendor
exact PostgreSQL vendor
exact object storage vendor
exact observability vendor
exact payment provider
exact first Redis usage
exact public ID layout
exact production host
```

These choices are deferred because they do not need to be guessed before PoC evidence.

---

# 77. Next action

**Architecture Baseline 0.10 is ready for executable validation.**

The next stage is:

# Technical PoC Pack v1

Create five minimal executable proof-of-concepts:

1. Temporal durability/versioning
2. PostgreSQL tenant isolation/RLS
3. secure media ingress/worker isolation
4. async social platform lifecycle mock
5. concurrent usage reservation/ledger

Each PoC receives:

- objective;
- minimal architecture;
- runnable code;
- automated tests;
- failure injection;
- result report;
- PASS/FAIL verdict.

Only after those results do we perform Red-Team v2 and freeze Architecture 1.0.
