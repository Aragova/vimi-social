# PoC B — PostgreSQL Tenant Isolation & RLS

## Hypothesis

ViMi Social can enforce tenant isolation at both the application and PostgreSQL layers so that a missing tenant filter, pooled connection reuse, background execution, webhook ingestion, or privileged support access cannot silently cross tenant boundaries.

## Must prove

1. `vimi_app` cannot read another tenant's rows.
2. An intentionally unsafe query with **no `WHERE tenant_id = ...`** is still constrained by PostgreSQL RLS.
3. Reusing the same pooled physical connection cannot leak a previous tenant context.
4. Background Temporal activities receive an authenticated execution envelope, reconstruct `ExecutionContext`, and remain tenant-isolated.
5. Webhook tenant resolution ignores any tenant supplied by the incoming payload and resolves ownership from server-side account mapping.
6. Privileged support/control-plane access is explicit, scoped to a target tenant, requires a reason, and produces both a structured audit row and a non-transactional audit signal.
7. Tests run with production-like non-owner application DB roles with `NOBYPASSRLS`.

## Database role model under test

```text
postgres                  bootstrap only in CI
vimi_migration_owner      NOLOGIN, owns schema/tables, NOBYPASSRLS
vimi_app                  LOGIN, normal application role, NOBYPASSRLS, not table owner
vimi_control_plane        LOGIN, support caller, NOBYPASSRLS, EXECUTE-only privileged interface
vimi_webhook_resolver     LOGIN, webhook routing role, NOBYPASSRLS, EXECUTE-only resolver interface
vimi_privileged_executor  NOLOGIN, BYPASSRLS, owns narrow SECURITY DEFINER functions
```

The PoC intentionally keeps all application-facing login roles separate from the table owner and from the `BYPASSRLS` executor. RLS is not considered proven if normal tenant tests execute as `postgres`, a superuser, the table-owning role, or a login role with `BYPASSRLS`.

## Tenant context contract

Inside every normal application transaction:

```sql
SELECT set_config('app.tenant_id', '<trusted tenant uuid>', true);
```

`true` means transaction-local. The value must disappear at commit/rollback before the connection returns to the pool. Tenant-scoped helpers must own the top-level transaction and fail closed if a transaction is already active.

The repository receives an immutable, server-generated `ExecutionContext`; callers do not pass a raw tenant ID into repository query methods.

For Temporal background execution, the server-side starter signs the tenant/actor/correlation/operation fields. The activity verifies that envelope before constructing `ExecutionContext`, so changing the tenant after signing is rejected.

## RLS policy shape

Tenant-sensitive tables use a policy equivalent to:

```sql
USING (
  tenant_id::text = current_setting('app.tenant_id', true)
)
WITH CHECK (
  tenant_id::text = current_setting('app.tenant_id', true)
)
```

Missing context therefore exposes zero tenant rows instead of falling back to unrestricted access.

## Privileged support audit contract

The support function writes a structured row to `audit_log` in the same transaction as the privileged read. Because a caller-controlled rollback can also roll back that row, the function additionally emits a PostgreSQL `LOG` audit marker before returning data. PostgreSQL log emission is non-transactional and CI verifies that the marker remains visible even when the caller rolls back the database transaction.

This log marker is a PoC stand-in for the Architecture 1.0 requirement: privileged access must emit to an external append-only audit sink before the result is released outside the trusted support boundary. The production sink/provider is intentionally deferred.

## Negative validation cases

- query all content rows without a tenant predicate;
- reuse one pooled physical connection across tenant A then tenant B;
- inspect connection state after transaction completion;
- submit a valid signed Temporal background command for each tenant;
- modify the tenant in a signed background command and verify rejection;
- send a webhook payload claiming the wrong tenant;
- attempt support access without a meaningful reason;
- roll back a direct privileged read and verify the non-transactional audit marker still exists;
- use normal application-facing credentials to read privileged tenant/audit tables directly.

## PASS criteria

```text
cross-tenant reads/writes remain constrained
no-WHERE query is still isolated by RLS
no tenant context survives transaction/pool reuse
Temporal background execution accepts authenticated context and rejects tampering
webhook tenant comes only from server-side platform-account mapping
privileged support access emits committed structured audit plus rollback-resistant audit signal
normal application-facing roles cannot use privileged tables directly
```

A green test suite and CI evidence are required. Code inspection alone is not sufficient for PASS.
