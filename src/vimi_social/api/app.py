from collections.abc import Generator

from fastapi import Depends, FastAPI, status
from sqlalchemy.orm import Session

from vimi_social.api.schemas import PublicationRequest, PublicationResponse
from vimi_social.auth.context import require_execution_context
from vimi_social.db.base import SessionFactory
from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import ExecutionContext, OperationKey
from vimi_social.usage.models import ReservationRequest
from vimi_social.usage.repository import UsageRepository

app = FastAPI(title="ViMi Social API", version="0.1.0")
usage_repository = UsageRepository()


def get_session() -> Generator[Session, None, None]:
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/publications",
    response_model=PublicationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_publication(
    request: PublicationRequest,
    context: ExecutionContext = Depends(require_execution_context),
    session: Session = Depends(get_session),
) -> PublicationResponse:
    operation_key = OperationKey(request.operation_key)
    with tenant_transaction(session, context.tenant_id):
        reservation = usage_repository.reserve(
            session,
            ReservationRequest(
                tenant_id=context.tenant_id,
                operation_key=operation_key,
                metric="publication",
                quantity=1,
            ),
        )

    return PublicationResponse(
        operation_key=operation_key.value,
        state="RESERVED",
        joined_existing_reservation=reservation.joined_existing,
    )
