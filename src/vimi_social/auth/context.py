from dataclasses import dataclass

from fastapi import HTTPException, status

from vimi_social.domain.identity import TenantId


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Trusted identity envelope produced only by the managed-IdP adapter."""

    tenant_id: TenantId
    actor_subject: str


def require_execution_context() -> ExecutionContext:
    """Fail closed until the managed IdP verifier + tenant membership resolver is wired.

    Production code must never construct tenant context from a raw caller-controlled tenant ID.
    The first auth slice will replace this stub with verified-token -> server-side membership
    resolution while keeping the same dependency boundary.
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="managed IdP execution-context resolver is not configured",
    )
