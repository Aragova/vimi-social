# 31. High finding RT-29 — Feature flag inconsistency during irreversible operations

## Scenario

Worker checks flag:

```text
instagram.new_flow = ON
```

Starts operation.

Flag is switched OFF mid-operation.

Another step uses old/new behavior inconsistently.

## Risk

**HIGH — malformed workflow or duplicated side effect.**

## Required policy

For long-running operation, record relevant:

```text
execution_policy_version
feature_decision
```

at workflow start where semantics must remain stable.

Kill switches are different: they may interrupt future irreversible steps deliberately.

Distinguish:

```text
experiment/config flag
vs
emergency kill switch
```

---

# 32. High finding RT-30 — Secrets leak through errors/URLs

## Scenario

Provider returns error containing signed media URL or access token.

Developer logs raw exception.

## Risk

**HIGH — credential/media exposure.**

## Required change

Central:

```text
SensitiveDataRedactor
```

Redact:

- bearer tokens;
- refresh tokens;
- API keys;
- signed URL query strings;
- cookies;
- auth headers.

Structured logs should prefer safe fields over raw exception bodies.

Security tests inject fake secrets and ensure they never appear in captured logs.

---

# 33. Medium finding RT-31 — Redis outage semantics undefined

## Scenario

Redis is used for rate limits/cache.

Redis unavailable.

Do we publish anyway?

## Risk

**MEDIUM — inconsistent availability/security behavior.**

## Required classification

Each Redis use case defines fail mode:

```text
UI cache            fail open
non-security cache  fail open
provider quota      conservative fallback
login abuse limit   fail closed/local fallback
expensive AI quota  DB-backed authority
```

Redis never owns canonical entitlement/billing state.

---

# 34. Medium finding RT-32 — Secret manager outage

## Scenario

Secrets manager temporarily unavailable.

Existing schedule needs token.

## Required design

Allow short-lived in-memory credential cache where appropriate, bounded by:

```text
TTL
credential_version
account state
```

Never persist decrypted tokens to local disk.

If no valid cached credential exists, fail safely to retry/auth state.

---

# 35. Medium finding RT-33 — Provider API response shape changes

## Scenario

Provider adds/removes fields or changes enum.

Adapter crashes on strict parsing.

## Required change

- schema-tolerant parsing for unknown additive fields;
- strict validation for fields required for safety;
- fixture/contract tests;
- provider API version recorded;
- canary account tests where feasible.

---

# 36. Medium finding RT-34 — Analytics metrics are revised retroactively

## Scenario

Provider initially reports 10,000 views, later corrects to 9,200.

If analytics are append-only deltas only, totals become wrong.

## Required change

Store provider snapshots/revisions with:

```text
observed_at
provider_period
provider_metric
raw_value
schema_version
```

Normalized analytics can be recomputed.

Do not assume metrics are monotonic.

---

# 37. Medium finding RT-35 — High-cardinality observability cost explosion

Baseline already warns against tenant IDs as metric labels, but traces/logs can still explode in retention/cost.

## Required controls

- sampling strategy;
- shorter retention for verbose traces;
- error/slow trace retention priority;
- PII redaction;
- tenant IDs in traces only where operationally needed;
- budget monitoring for observability backend.

---

# 38. Medium finding RT-36 — Correlation ID injection

## Scenario

Client sends enormous/malicious `X-Correlation-ID`.

It gets copied into logs and downstream systems.

## Required change

External request ID is treated as untrusted.

Generate canonical server `correlation_id`.

Optionally preserve sanitized:

```text
client_request_id
```

with strict length/character limits.

---

# 39. Medium finding RT-37 — User invitation / identity linking

## Scenario

Invitation goes to email address.

Different IdP identity claims same email or case/alias variant.

## Risk

Potential tenant takeover.

## Required change

- use IdP stable subject ID as identity key;
- invitations expire;
- invitations are single-use;
- invitation is bound to intended normalized address or explicit authenticated identity policy;
- never merge identities solely because emails match unless IdP guarantees it.

---

# 40. Medium finding RT-38 — Support impersonation becomes invisible privilege escalation

## Scenario

Admin impersonates user and makes publication.

Audit shows action as user.

## Required change

Every request carries two identities where applicable:

```text
effective_actor
privileged_actor
```

Audit must show:

```text
Admin X acting as User Y
```

Support session:

- reason;
- expiry;
- scope;
- banner in UI;
- read-only default.

---

# 41. Medium finding RT-39 — Plan/permission cache becomes stale

## Scenario

Admin revokes permission.

Worker/API continues using cached decision for 30 minutes.

## Required change

Cache keys include:

```text
membership_version
entitlement_version
```

Critical actions may always revalidate from authoritative store.

Revocation must have bounded propagation time.

---

# 42. Medium finding RT-40 — Platform text limits are not simple Python length

Different platforms may count links, Unicode, grapheme clusters or media-specific limits differently.

## Required change

Platform validation belongs to adapter/capability layer.

Do not globally enforce:

```python
len(caption)
```

as universal policy.

Preflight uses provider-specific validator and versioned rule set.

---

# 43. Medium finding RT-41 — Scheduler clock and client clock differ

User browser clock may be wrong.

## Required change

Server owns scheduling truth.

Store:

```text
local wall time
IANA timezone
resolved UTC instant
tzdata/version if needed for audit
```

UI displays server-confirmed schedule.

---

# 44. Medium finding RT-42 — Provider outage creates enormous catch-up burst

## Scenario

Instagram unavailable for 3 hours.

100,000 scheduled targets become ready simultaneously after recovery.

## Risk

Recovery itself triggers new rate-limit incident.

## Required change

Backlog drain policy:

```text
rate-limited catch-up
jitter
priority by lateness/plan
tenant fairness
provider quota
```

Never release entire backlog at once.

---

# 45. Medium finding RT-43 — Object storage/database write split

## Scenario

File uploaded to object storage.

DB transaction creating Asset fails.

Or DB Asset exists but object upload failed.

## Required design

Use explicit asset ingest state:

```text
PENDING_UPLOAD
UPLOADED
VERIFIED
READY
FAILED
```

Garbage collector removes orphan objects after grace period.

Publication only accepts `READY` assets.

---

# 46. Medium finding RT-44 — Checksum mismatch / object mutation

Some S3-compatible systems or operational mistakes can replace object at same key.

## Required rule

Asset storage keys are immutable.

Record:

```text
sha256
size
content_type
storage_version_id if available
```

Media worker verifies expected hash where practical before processing.

---

# 47. Medium finding RT-45 — Partial batch UX

Batch has 7 targets:

```text
5 published
1 auth required
1 unknown
```

If UI shows simply “Failed”, user may repost all 7 manually.

## Required UX

Batch status:

```text
PARTIAL_SUCCESS
```

with independent target states and explicit action per target.

Never offer one-click “retry all” when successful external side effects already exist unless retry selection excludes them.

---

# 48. Low finding RT-46 — Audit log tamper resistance

Append-only at application level does not stop a database superuser.

## Future hardening

For larger/regulated deployments:

- restricted DB role;
- periodic signed audit batches;
- export to immutable/WORM storage;
- hash-chain audit records.

Not required for internal alpha but architecture should not prevent it.

---

# 49. Low finding RT-47 — Enterprise data residency

Future enterprise customers may demand regional storage/processing.

## Recommendation

Do not build multi-region now.

But store optional:

```text
tenant_data_region
```

behind a future policy boundary rather than hard-coding one region into domain semantics.

---

# 50. Low finding RT-48 — API abuse / spam reputation

Public SaaS can be used for platform spam.

## Before public signup

Add:

- account/tenant abuse limits;
- signup risk controls;
- publication velocity limits;
- complaint/takedown path;
- tenant suspension;
- platform policy enforcement.

This is a product/compliance requirement before open public growth, not before internal development.

---
