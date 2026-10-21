from dataclasses import dataclass

from fastapi import HTTPException, status

from vimi_social.domain.identity import TenantId


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Trusted application identity envelope produced by a verified identity adapter.

    Telegram is the first customer identity path. A managed IdP may produce the same
    envelope for secondary web/admin flows. No adapter may derive tenant authority from
    a caller-controlled tenant ID.
    """

    tenant_id: TenantId
    actor_subject: str


def require_execution_context() -> ExecutionContext:
    """Fail closed until a trusted identity resolver is wired for this API surface.

    The Telegram bot/ingress will resolve immutable Telegram identity server-side into
    ViMi membership/workspace authority before constructing ExecutionContext. Web/admin
    surfaces may use a managed-IdP adapter behind the same trusted boundary.
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="trusted execution-context resolver is not configured",
    )
