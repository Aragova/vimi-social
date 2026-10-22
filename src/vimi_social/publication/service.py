from collections.abc import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.publication import PublicationWorkflowInput
from vimi_social.publication.repository import PublicationRepository
from vimi_social.telegram.identity import TelegramPrincipal
from vimi_social.usage.models import ReservationRequest
from vimi_social.usage.repository import UsageRepository


class PublicationService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        repository: PublicationRepository | None = None,
        usage_repository: UsageRepository | None = None,
        destination_task_queue: str = "vimi-social-destination",
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or PublicationRepository()
        self._usage_repository = usage_repository or UsageRepository()
        self._destination_task_queue = destination_task_queue

    def approve(
        self,
        principal: TelegramPrincipal,
        publication_id: UUID,
    ) -> PublicationWorkflowInput | None:
        with self._session_factory() as session, tenant_transaction(
            session,
            principal.context.tenant_id,
        ):
            approved = self._repository.approve(
                session,
                publication_id=publication_id,
                actor_user_id=principal.user_id,
            )
            if approved is None:
                return None
            self._usage_repository.reserve(
                session,
                ReservationRequest(
                    tenant_id=principal.context.tenant_id,
                    operation_key=OperationKey(approved.operation_key),
                    metric="published_post",
                    quantity=1,
                ),
            )
            authority = session.execute(
                text(
                    """
                    SELECT task.operation_key, task.execution_token::text
                    FROM publication_operation AS publication
                    JOIN variant_artifact AS artifact
                      ON artifact.id = publication.artifact_id
                     AND artifact.tenant_id = publication.tenant_id
                    JOIN variant_plan AS plan
                      ON plan.id = artifact.plan_id
                     AND plan.tenant_id = artifact.tenant_id
                    JOIN media_analysis AS analysis
                      ON analysis.id = plan.analysis_id
                     AND analysis.tenant_id = plan.tenant_id
                    JOIN media_asset AS asset
                      ON asset.id = analysis.asset_id
                     AND asset.tenant_id = analysis.tenant_id
                    JOIN source_task_candidate AS candidate
                      ON candidate.id = asset.candidate_id
                     AND candidate.tenant_id = asset.tenant_id
                    JOIN source_task AS task
                      ON task.id = candidate.source_task_id
                     AND task.tenant_id = candidate.tenant_id
                    WHERE publication.id = :publication_id
                      AND task.actor_user_id = :actor_user_id
                    """
                ),
                {
                    "publication_id": str(publication_id),
                    "actor_user_id": str(principal.user_id),
                },
            ).one_or_none()
            if authority is None:
                raise RuntimeError("publication source authority could not be restored")
            return PublicationWorkflowInput(
                publication_id=str(approved.id),
                operation_key=approved.operation_key,
                source_task_operation_key=str(authority.operation_key),
                source_task_execution_token=str(authority.execution_token),
                destination_task_queue=self._destination_task_queue,
            )
