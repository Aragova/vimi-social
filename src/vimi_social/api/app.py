from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status

from vimi_social.api.schemas import HealthResponse, PublicationCreateRequest, PublicationCreateResponse
from vimi_social.auth.context import ExecutionContext, require_execution_context
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.publication import PublicationCommand, PublicationState

app = FastAPI(title="ViMi Social API", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/v1/publications", response_model=PublicationCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_publication(
    body: PublicationCreateRequest,
    execution: Annotated[ExecutionContext, Depends(require_execution_context)],
) -> PublicationCreateResponse:
    """Create a tenant-scoped publication command from trusted execution context."""
    try:
        command = PublicationCommand(
            tenant_id=execution.tenant_id,
            operation_key=OperationKey(body.operation_key),
            target_id=body.target_id,
            metric=body.metric,
            quantity=body.quantity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return PublicationCreateResponse(operation_key=command.operation_key.value, state=PublicationState.REQUESTED)
