from collections.abc import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.domain.media import MediaPreparationWorkflowInput
from vimi_social.domain.publication import (
    PublicationPreviewResult,
    PublicationPreviewState,
    RenderResult,
    VariantArtifactState,
)
from vimi_social.publication.repository import PublicationRepository
from vimi_social.source.repository import SourceTaskRepository


class PublicationPreviewActivities:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        repository: PublicationRepository | None = None,
        source_repository: SourceTaskRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or PublicationRepository()
        self._source_repository = source_repository or SourceTaskRepository()

    @activity.defn(name="prepare_publication_preview")
    def prepare_publication_preview(
        self,
        workflow_input: MediaPreparationWorkflowInput,
        render_result: RenderResult,
    ) -> PublicationPreviewResult:
        if (
            render_result.state is not VariantArtifactState.READY
            or render_result.artifact_id is None
        ):
            return PublicationPreviewResult(
                state=PublicationPreviewState.RENDER_FAILED,
                artifact_id=render_result.artifact_id,
                reason_code=render_result.failure_code or "VARIANT_RENDER_NOT_READY",
            )
        try:
            artifact_id = UUID(render_result.artifact_id)
        except ValueError:
            return PublicationPreviewResult(
                state=PublicationPreviewState.RENDER_FAILED,
                reason_code="VARIANT_ARTIFACT_ID_INVALID",
            )
        tenant_id = self._resolve_source_tenant(
            workflow_input.source_task_operation_key,
            workflow_input.source_task_execution_token,
        )
        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            if not self._artifact_matches_workflow(session, artifact_id, workflow_input):
                raise RuntimeError("publication preview artifact authority mismatch")
            return self._repository.prepare_preview(
                session,
                artifact_id=artifact_id,
                destination="x",
            )

    def _resolve_source_tenant(self, operation_key: str, execution_token: str) -> TenantId:
        try:
            token = UUID(execution_token)
        except ValueError:
            raise RuntimeError("invalid source execution token") from None
        with self._session_factory() as session, session.begin():
            return self._source_repository.resolve_tenant(
                session,
                operation_key=OperationKey(operation_key),
                execution_token=token,
            )

    def _artifact_matches_workflow(
        self,
        session: Session,
        artifact_id: UUID,
        workflow_input: MediaPreparationWorkflowInput,
    ) -> bool:
        return (
            session.execute(
                text(
                    """
                    SELECT 1
                    FROM variant_artifact AS artifact
                    JOIN variant_plan AS plan
                      ON plan.id = artifact.plan_id AND plan.tenant_id = artifact.tenant_id
                    JOIN media_analysis AS analysis
                      ON analysis.id = plan.analysis_id AND analysis.tenant_id = plan.tenant_id
                    JOIN media_preparation AS preparation
                      ON preparation.id = analysis.preparation_id
                     AND preparation.tenant_id = analysis.tenant_id
                    JOIN source_task_candidate AS candidate
                      ON candidate.id = preparation.candidate_id
                     AND candidate.tenant_id = preparation.tenant_id
                    JOIN source_task AS task
                      ON task.id = candidate.source_task_id
                     AND task.tenant_id = candidate.tenant_id
                    WHERE artifact.id = :artifact_id
                      AND preparation.id = :preparation_id
                      AND preparation.operation_key = :preparation_operation_key
                      AND task.operation_key = :source_operation_key
                      AND task.execution_token = :source_execution_token
                    """
                ),
                {
                    "artifact_id": str(artifact_id),
                    "preparation_id": workflow_input.preparation_id,
                    "preparation_operation_key": workflow_input.operation_key,
                    "source_operation_key": workflow_input.source_task_operation_key,
                    "source_execution_token": workflow_input.source_task_execution_token,
                },
            ).scalar_one_or_none()
            is not None
        )
