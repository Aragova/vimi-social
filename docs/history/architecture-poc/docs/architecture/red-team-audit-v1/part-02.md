# 7. Critical finding RT-05 — External publish timeout can create duplicates

## Scenario

ViMi sends:

```text
POST publish
```

Provider creates the post.

Network response is lost.

ViMi sees timeout.

Retrying could publish a duplicate.

## Risk

**CRITICAL — one of the most dangerous failure modes of the product.**

## Required change

Expand publication attempts to include external mutation phase:

```text
CREATED
NOT_STARTED
STARTED
PROVIDER_ACCEPTED
UNKNOWN
CONFIRMED
FAILED_SAFE
FAILED_PERMANENT
```

`UNKNOWN` is not ordinary failure.

Each adapter defines:

```text
idempotency_strategy
reconciliation_strategy
safe_retry_conditions
```

If provider supports idempotency keys: use them.

If provider exposes lookup/status APIs: reconcile.

If neither is possible: stop automatic retry and surface manual review.

Store:

```text
attempt_id
dispatch_token
provider_request_id if known
started_at
provider_accepted_at if known
outcome_class
```

## Acceptance test

Simulate provider accepting request and cutting TCP connection before response.

System must not automatically create a second post.

---

# 8. Critical finding RT-06 — OAuth refresh race and refresh-token rotation

## Scenario

Multiple publication workers simultaneously discover that an access token expired.

Both call refresh.

Provider rotates refresh tokens.

Worker A stores new token.

Worker B completes slightly later using old refresh token and overwrites credentials with an invalid/older state.

## Risk

**CRITICAL — account credentials become corrupted and scheduled publications fail.**

## Required change

Credential record needs:

```text
credential_version
access_token_ref
refresh_token_ref
expires_at
updated_at
```

Refresh uses **single-flight / lock + compare-and-swap**.

Conceptually:

```text
lock platform-account credential
reload latest version
if already refreshed -> reuse
else refresh
store only if expected_version matches
increment version
```

Publishing activity verifies account/credential version before irreversible mutation.

## Acceptance test

Run 20 simultaneous refresh attempts against a provider mock that rotates refresh tokens. Exactly one refresh sequence must win; all callers receive valid latest credentials.

---

# 9. Critical finding RT-07 — UsageLedger alone does not prevent over-consumption

## Scenario

Tenant has 100 video minutes remaining.

Ten concurrent 30-minute processing jobs start at the same time.

Each checks:

```text
remaining = 100
```

All pass.

300 minutes are consumed.

## Risk

**CRITICAL — direct financial loss and broken plan enforcement.**

## Required change

Add:

```text
UsageReservation
```

or equivalent atomic quota reservation.

Lifecycle:

```text
AVAILABLE
  ↓ reserve atomically
RESERVED
  ↓ work succeeds
COMMITTED

or

RESERVED
  ↓ work fails/cancelled
RELEASED
```

UsageLedger remains append-only accounting history.

A unique operation key prevents double charging after retries.

## Acceptance test

100 concurrent jobs compete for limited quota. Sum of active reservations must never exceed entitlement.

---

# 10. Critical finding RT-08 — Usage retries can double-bill

## Scenario

Video processing succeeds.

Usage event is written.

Worker crashes before recording job completion.

Retry writes same usage again.

## Risk

**CRITICAL — users charged twice and financial reconciliation becomes unreliable.**

## Required change

Every usage event has unique:

```text
usage_dedupe_key
```

derived from immutable source operation identity.

Database UNIQUE constraint enforces idempotency.

Corrections are new ledger entries:

```text
+300 seconds
-300 seconds adjustment
```

Never silently UPDATE historical usage.

## Acceptance test

Retry same successful workflow/activity 10 times. Ledger must contain one billable charge.

---

# 11. Critical finding RT-09 — Remote media fetch SSRF / DNS rebinding

## Scenario

User supplies:

```text
https://attacker.example/video.mp4
```

Initial DNS resolves to public IP.

After validation, DNS rebinds to:

```text
169.254.169.254
127.0.0.1
10.0.0.1
::1
```

or redirect leads to private address.

## Risk

**CRITICAL — cloud credential theft/internal network access.**

## Required change

Create dedicated:

```text
RemoteMediaFetcher
```

It must:

- allow only approved schemes;
- resolve DNS server-side;
- reject loopback/private/link-local/multicast/reserved ranges;
- validate IPv4 and IPv6;
- revalidate every redirect;
- cap redirect count;
- cap bytes while streaming even without `Content-Length`;
- use connect/read/total timeouts;
- restrict ports;
- not forward arbitrary user headers/cookies;
- run with no access to cloud metadata/private control networks;
- write to quarantine/object storage;
- validate media before processing.

FFmpeg never fetches arbitrary remote URLs directly.

## Acceptance test

Test:
- redirects to localhost;
- DNS rebinding;
- IPv6 loopback;
- decimal/octal IP encodings;
- huge chunked response;
- missing `Content-Length`;
- infinite redirect chain.

All must fail safely.

---

# 12. High finding RT-10 — Object retention can delete media still in use

## Scenario

Temporary derived asset expires after 24 hours.

A publication workflow is delayed by provider outage for 26 hours.

Retention worker deletes asset while workflow is still waiting.

## Risk

**HIGH — delayed scheduled posts fail unexpectedly.**

## Required change

Objects need explicit lifecycle references:

```text
asset state
retention_class
retain_until
active_reference_count or lease
```

Before destructive cleanup verify no:

- active publication target;
- active Temporal workflow;
- unresolved external upload;
- legal/tenant retention hold.

Never overwrite storage keys; assets are immutable.

---

# 13. High finding RT-11 — Deleting content while publish is in flight

## Scenario

User clicks Delete while Instagram upload is already underway.

The app removes DB row/object immediately.

Provider may still publish it.

## Risk

**HIGH — invisible external posts / impossible reconciliation.**

## Required change

Deletion is a lifecycle:

```text
ACTIVE
  ↓
DELETE_REQUESTED
  ↓
cancel future work
  ↓
reconcile in-flight work
  ↓
delete external posts if requested/possible
  ↓
PURGE_PENDING
  ↓
PURGED
```

Use tombstones until workflows are safely resolved.

---

# 14. High finding RT-12 — User cancels scheduled post during DISPATCHING

## Scenario

User presses Cancel at the exact moment provider request has started.

UI immediately says “Cancelled”.

Provider actually publishes.

## Risk

**HIGH — misleading premium UX and orphan publication.**

## Required change

State distinguishes:

```text
CANCELLATION_REQUESTED
CANCELLED_BEFORE_DISPATCH
CANCEL_TOO_LATE
```

If external side effect may have started, cancellation becomes reconciliation, not immediate success.

UI must explain:

> Cancellation requested; checking whether the platform already accepted the post.

---

# 15. High finding RT-13 — Webhooks arrive duplicated or out of order

## Scenario

Provider sends:

```text
PUBLISHED
```

then delayed older event:

```text
PROCESSING
```

or sends same event 5 times.

## Risk

**HIGH — state regression or repeated side effects.**

## Required change

Webhook Inbox stores:

```text
provider_event_id
provider_timestamp/sequence if available
received_at
payload_hash
processing_state
```

Transitions are monotonic according to domain state machine.

Never allow old webhook to regress:

```text
PUBLISHED → PROCESSING
```

Deduplicate with DB uniqueness.

---

# 16. High finding RT-14 — Webhook tenant confusion

## Scenario

Webhook contains external account/post identifiers controlled or spoofed by attacker.

Handler trusts tenant ID/provider metadata in payload.

## Risk

**HIGH — cross-tenant mutation.**

## Required change

Resolve tenant only through server-side mapping:

```text
provider
+ provider_app/account identity
+ known external object mapping
→ PlatformAccount
→ tenant
```

Never trust tenant identifier from webhook body.

---

# 17. High finding RT-15 — Shared provider quotas are different from tenant fairness

## Scenario

Temporal fairness prevents Tenant A from using all workers.

But all tenants share one platform app quota.

Concurrent workers collectively exceed Instagram/TikTok/X API quotas.

## Risk

**HIGH — platform-wide throttling affecting every customer.**

## Required change

Add:

```text
PlatformQuotaCoordinator
```

Scopes may include:

```text
provider-global
provider-app
platform-account
endpoint
tenant
```

Adapter reports rate-limit metadata to coordinator.

Scheduling consults both:

```text
resource fairness
+
provider quota budget
```

---
