# PoC B — Result Report

**Status:** PASS — CI VERIFIED; FINAL INDEPENDENT REVIEW CLEAN

## Hypothesis

PostgreSQL RLS plus trusted transaction-scoped tenant context can prevent cross-tenant reads even when application queries omit tenant predicates, pooled connections are reused, work runs in Temporal, webhook payloads provide conflicting tenant claims, or support access requires controlled cross-tenant visibility.

## Verified environment

Latest evidence: GitHub Actions run `38885958055` (`PoC B - Tenant Isolation`, run #26), executed against PR #3 head `3bce5fb9ab59bc92fe451fcac4d578deb02f52bb`.

- GitHub runner: Ubuntu 24.04.5 LTS
- Python: 3.12.15
- PostgreSQL: 18.6 (`postgres:18` service container)
- Temporal CLI: 1.9.1
- Temporal Server: 1.32.0, development server with in-memory persistence
- Temporal Python SDK: 1.34.0
- psycopg: 3.3.6
- Ruff: 0.17.1
- Pyright: 1.1.414
- pytest: 8.4.2

PoC A regression run `38885958178` (`PoC A - Temporal`, run #49) also completed successfully on the same head.

## Automated verification

All PoC B CI stages completed successfully:

- PostgreSQL service startup: PASS
- Temporal development server startup: PASS
- `ruff check poc_b_tenant_isolation`: PASS
- `pyright poc_b_tenant_isolation/src`: PASS (`0 errors, 0 warnings, 0 informations`)
- `pytest poc_b_tenant_isolation/tests`: PASS (`17 passed in 1.23s`)
- rollback-resistant support audit signal check: PASS

The CI log independently observed the expected PostgreSQL marker after a rollback scenario:

```text
VIMI_SUPPORT_AUDIT ... reason=rollback persistence sentinel 9001 observed_count=1
```

The test suite now verifies these architectural properties:

1. `vimi_app` is not a table owner, is not a superuser, and has `NOBYPASSRLS`.
2. Tenant A sees only tenant A rows and tenant B sees only tenant B rows.
3. A query that deliberately omits `WHERE tenant_id = ...` remains constrained by RLS.
4. Missing tenant context exposes zero tenant rows.
5. Cross-tenant inserts are rejected by PostgreSQL RLS.
6. Tenant-scoped helpers refuse to run inside an already-open transaction, preventing `SET LOCAL` state from being scoped only to a nested savepoint.
7. Transaction-local tenant state does not leak across reuse of the same physical pooled connection.
8. Temporal background work uses a signed execution envelope before reconstructing `ExecutionContext`.
9. A background command whose tenant is changed after signing is rejected instead of being promoted into trusted context.
10. Webhook tenant claims supplied by the payload are ignored; ownership is resolved from server-side platform-account mapping.
11. The webhook login role has no direct access to `platform_accounts`; it can use only the narrow resolver interface.
12. Privileged support reads require a meaningful reason and explicit target tenant.
13. The meaningful-reason requirement is enforced by the database function itself, not only by Python code.
14. A successful privileged read writes a structured audit row in the database transaction.
15. A direct privileged read followed by caller-controlled rollback still leaves a non-transactional PostgreSQL audit marker visible in server logs.
16. The control-plane login role has no direct access to tenant tables or the privileged audit table.
17. The normal application role cannot read the privileged audit log.

Expected-denial events were also visible in PostgreSQL logs during the successful run, including an RLS-rejected cross-tenant insert and permission-denied attempts against tenant/audit tables. These are expected test evidence, not CI failures.

## Findings discovered during implementation and review

The PoC changed materially after independent review rather than merely making the original implementation pass tests.

### 1. Nested transaction / savepoint tenant-context hazard

The initial helper could set transaction-local tenant context while a caller already owned an outer transaction. PostgreSQL would then preserve that `SET LOCAL` state beyond the inner savepoint. The final design requires tenant-scoped work to own the top-level transaction and rejects a non-idle connection before applying tenant context.

### 2. Privileged login role was too broad

The initial `vimi_control_plane` approach depended too much on application code voluntarily using an audited wrapper. The final design removes direct unrestricted tenant-table access from login roles.

Cross-tenant operations are encapsulated behind narrow `SECURITY DEFINER` database functions owned by a dedicated `NOLOGIN + BYPASSRLS` executor role. Application-facing login roles remain `NOBYPASSRLS` and receive only the specific `EXECUTE` privileges required for their task.

### 3. Webhook resolution needs its own narrow interface

Webhook routing cannot trust `tenant_id` from provider payloads. The final PoC uses a dedicated `vimi_webhook_resolver` login role that cannot directly read the global platform-account table and can only execute the server-side resolver function.

### 4. A database audit row alone is not rollback-resistant

The second independent review identified that a caller could invoke the privileged function inside an explicit transaction, receive the returned data, and then roll back the transaction, removing the structured audit row.

The PoC now emits a PostgreSQL `LOG` audit marker before returning data and verifies in CI that the marker remains visible after the caller rolls back. This is evidence for the architectural requirement, not the intended final production sink.

Architecture 1.0 must require privileged access to emit an audit event to an external append-only or otherwise caller-non-rollbackable sink before privileged results leave the trusted boundary.

### 5. Temporal propagation is not enough; execution context must be authenticated

The initial background command contained a tenant ID that any Temporal client able to start the workflow could supply. That proved propagation and RLS scoping, but not that the tenant context was trusted.

The PoC now signs tenant/actor/correlation/operation fields with an application-controlled HMAC key. The activity verifies the envelope before creating `ExecutionContext`, and a tampered tenant value is rejected. Production Architecture 1.0 may use a different trusted-envelope mechanism, but must preserve the same invariant: workers do not promote caller-controlled tenant identifiers directly into trusted execution context.

### 6. Documentation is part of the architecture contract

The second review also found that the README still described the removed `BYPASSRLS` login design. The README now matches the implemented boundary: application-facing roles use `NOBYPASSRLS`; the only `BYPASSRLS` role is `NOLOGIN` and exists behind narrow `SECURITY DEFINER` interfaces.

## Final independent review

The third Codex review completed against head `3bce5fb9ab59bc92fe451fcac4d578deb02f52bb` with:

- `has_any_findings=false`
- `has_unresolved_findings=false`
- status `completed`

No additional correctness findings were raised against the post-fix architecture.

## Architecture changes required for ViMi Social Architecture 1.0

The PoC evidence supports keeping PostgreSQL RLS as defense-in-depth, with these explicit contracts:

- tenant-scoped DB helpers must own the top-level transaction or fail closed;
- `SET LOCAL app.tenant_id` and related execution context must come only from trusted server-generated/authenticated context;
- pooled connections must return to the pool with no tenant-local state;
- application login roles must be non-owner, non-superuser, and `NOBYPASSRLS`;
- migration ownership, ordinary application access, webhook resolution, and privileged execution must be separate database roles;
- any `BYPASSRLS` role used for controlled cross-tenant work must be `NOLOGIN` by default;
- cross-tenant support/control operations must use narrow database interfaces rather than direct table grants to login roles;
- privileged reads must emit audit evidence to an external caller-non-rollbackable append-only sink before the result is released outside the trusted support boundary;
- Temporal/background workers must authenticate or derive tenant execution context rather than trusting a raw tenant identifier in workflow input;
- webhook tenant resolution must be server-side and must not trust tenant identity supplied by provider payloads;
- CI must test RLS with production-like restricted roles, not the migration owner or superuser.

## Limitations

This PoC demonstrates the isolation contract under PostgreSQL 18, psycopg pooling, and a real Temporal development server in CI. It does not prove every future production query, migration, support feature, or database extension is safe automatically. Architecture tests and tenant-isolation integration tests remain mandatory in the production repository.

The Temporal server used by this PoC has in-memory persistence because Temporal durability itself is covered separately by PoC A; PoC B uses Temporal to prove authenticated tenant-context propagation into background execution.

The PostgreSQL `LOG` marker is intentionally a PoC mechanism for demonstrating rollback-resistant evidence. It is not the final production audit architecture; Architecture 1.0 must specify an external append-only/non-rollbackable audit sink and its delivery semantics.

## Final verdict

**PASS — machine-verified acceptance criteria are satisfied and the final post-fix independent review is clean.**

PoC B is suitable as evidence for the Architecture 1.0 tenant-isolation contract and is ready to be closed after merge of PR #3.
