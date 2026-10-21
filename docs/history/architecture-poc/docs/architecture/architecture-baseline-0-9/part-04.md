## 50. CI/CD quality gates

Before merge:

```text
format/lint
type check
unit tests
architecture fitness tests
tenant isolation tests
migration checks
secret scanning
dependency/security checks
contract tests where affected
```

`main` is protected.

Changes are developed in short-lived branches and merged as small PRs.

Deployment and feature release are separate:

```text
code deployed
feature flag OFF
  ↓
internal
  ↓
beta
  ↓
selected tenants
  ↓
eligible plans
```

---

## 51. Architecture fitness suite

Automated checks should verify at least:

| Property | Example check |
|---|---|
| Platform isolation | no cross-platform internal imports |
| Tenant isolation | cross-tenant access tests |
| Credential safety | no secret serialization/logging |
| AI boundary | AI cannot call DB/secrets directly |
| Media boundary | untrusted URL cannot bypass downloader |
| State correctness | invalid publication transition rejected |
| Idempotency | duplicate execution does not duplicate effect where controllable |
| API stability | breaking contract detection |
| Migration safety | expand/contract compatibility |
| Supply chain | SBOM + scanners |
| UI accessibility | automated a11y checks |

---

## 52. Environments

Minimum:

```text
LOCAL
STAGING
PRODUCTION
```

Staging has separate:

- PostgreSQL;
- object storage;
- credentials;
- OAuth applications where practical;
- feature flags;
- Temporal namespace/environment.

No migration or destructive production experiment is first tested in production.

---

## 53. Backup and disaster recovery

PostgreSQL:

- managed backups;
- point-in-time recovery;
- periodic restore drills.

Object storage:

- versioning where appropriate;
- lifecycle policies.

Define and test RPO/RTO before public SaaS launch.

A backup is not considered operationally valid until restore has been tested.

---

## 54. Analytics architecture

Initial analytics remain in PostgreSQL where feasible.

Store raw provider semantics and normalized semantics separately:

```text
provider_metric_name
provider_raw_value
provider_schema_version

normalized_metric_name
normalized_value
normalization_version
```

Do not assume “views” or “impressions” mean the same thing across platforms.

ClickHouse or a warehouse is added only after observed analytical scale requires it.

---

## 55. Feedback loop

Long-term differentiator:

```text
Content
  ↓
AI decisions
  ↓
Platform variants
  ↓
Publish
  ↓
Analytics
  ↓
Performance attribution
  ↓
Brand/Profile knowledge
  ↓
Future ranking/planning
```

Initial implementation is versioned and explainable, not an opaque self-modifying agent.

---

## 56. Feature flags and kill switches

Support:

```text
global feature
platform feature
tenant feature
account feature
plan feature
```

Examples:

```text
publishing.enabled
instagram.enabled
ai.scene_ranker.enabled
tenant.123.auto_publish
```

Critical publishing components must be remotely disableable without redeploying the whole system.

---

## 57. Operational policy

Adding infrastructure requires evidence.

Process:

```text
problem
  ↓
measurement
  ↓
current architecture insufficient
  ↓
ADR
  ↓
new technology
```

Applies to:

- Kafka;
- Kubernetes;
- ClickHouse;
- OpenFGA;
- Elasticsearch;
- microservice extraction;
- database sharding;
- multi-region active-active.

---

## 58. Initial delivery sequence

### Phase A — architecture proof

1. Temporal crash/recovery PoC.
2. PostgreSQL tenant isolation PoC.
3. isolated media worker PoC.
4. mock async platform adapter PoC.

### Phase B — repository foundation

- repository;
- CI;
- module boundaries;
- migrations;
- observability foundation;
- architecture tests.

### Phase C — SaaS core

- User;
- Tenant;
- Membership;
- Role;
- Permission;
- Entitlement;
- Audit;
- Feature flags.

### Phase D — Content core

- ContentItem;
- ContentVersion;
- Asset;
- Provenance;
- PlatformVariant;
- RenderRecipe.

### Phase E — Publishing core

- PublicationBatch;
- PublicationTarget;
- PublicationAttempt;
- ExternalPost;
- state machine;
- Temporal orchestration;
- preflight.

### Phase F — first live adapters

1. Telegram
2. X

### Phase G — media factory

- probing;
- scene detection;
- feature extraction;
- rendering;
- variant creation.

### Phase H — AI

- SceneRanker;
- CaptionGenerator;
- Curator;
- Scout;
- analytics insight.

### Phase I — remaining platforms

1. Instagram
2. TikTok
3. YouTube
4. Reddit
5. Bluesky

### Phase J — analytics feedback

- provider metrics;
- normalization;
- brand insights.

### Phase K — billing

- subscription provider;
- entitlements;
- invoices;
- usage-based dimensions where chosen.

### Phase L — beta

- internal tenant;
- 2–5 pilot tenants;
- 20;
- 100;
- public signup.

---

## 59. First end-to-end milestone

The first complete vertical slice is:

```text
User
  ↓
Tenant
  ↓
Upload authorized video
  ↓
ContentVersion
  ↓
Telegram/X variants
  ↓
Preflight
  ↓
Approval
  ↓
Schedule
  ↓
Temporal
  ↓
TelegramAdapter + XAdapter
  ↓
PublicationAttempts
  ↓
ExternalPosts
  ↓
Basic analytics
```

This path must be reliable before broad platform and AI expansion.

---

## 60. ADR registry — baseline

Initial ADRs to write:

1. Modular monolith
2. Separate ViMi Social repository
3. PostgreSQL as canonical business state
4. Managed identity provider
5. Multi-tenant isolation model
6. Authorization service boundary
7. Temporal execution model
8. Transactional outbox
9. Platform adapter lifecycle contract
10. Publication state machine
11. Unknown-outcome reconciliation
12. Object storage
13. Media worker isolation
14. Content versioning
15. Asset provenance/rights
16. Usage ledger
17. AI Tool Gateway
18. AI evaluation policy
19. OpenTelemetry observability
20. API-first/OpenAPI
21. Design system/i18n/accessibility
22. Supply-chain security
23. Feature flags and kill switches
24. Backup/DR policy
25. No infrastructure without evidence

---

## 61. Open decisions before Architecture 1.0

The following remain intentionally undecided and require targeted comparison/PoC:

- managed PostgreSQL provider;
- managed identity provider;
- object storage provider;
- Temporal Cloud region/plan;
- secret manager/KMS provider;
- exact public ID strategy;
- Redis introduction threshold;
- frontend component primitives/library;
- production hosting platform;
- payment provider(s);
- observability backend;
- exact first X/Telegram API implementation details;
- data retention defaults;
- initial SLO targets.

These are not architecture failures; they are explicit decision gates.

---

## 62. Architecture 0.9 acceptance criteria

Baseline can move to architecture red-team review when:

- system boundaries are unambiguous;
- no runtime dependency on legacy ViMi exists;
- tenant isolation model is defined;
- content/version/asset model is defined;
- publication state machine includes `UNKNOWN`;
- platform lifecycle adapter is defined;
- Temporal/PostgreSQL responsibilities are separated;
- AI/tool boundaries are defined;
- security boundaries for media/secrets are defined;
- metering and entitlements are separate from roles;
- architecture fitness tests are specified;
- unnecessary infrastructure is explicitly excluded.

---

## 63. Next step

**Do not create the production repository yet.**

Next phase:

### Architecture Red-Team v1

Attempt to break Architecture 0.9 using:

- cross-tenant access;
- duplicate external publication;
- unknown network outcome;
- OAuth revocation;
- provider outage/rate limit;
- large/malformed media;
- SSRF attempts;
- media worker crash;
- Temporal worker crash;
- PostgreSQL outage;
- AI cost loop;
- noisy tenant;
- approval/version race;
- DB migration rollback;
- webhook replay;
- admin abuse;
- secret leakage;
- object-storage inconsistency;
- partial multi-platform success.

Red-team findings modify this document before **Architecture 1.0** is frozen.

---

# Status

**Architecture Baseline 0.9 created.**  
**Next gate:** Red-Team Architecture Audit v1.
