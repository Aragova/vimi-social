import math
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.media import MediaPreparation, MediaPreparationWorkflowInput
from vimi_social.media.repository import MediaPreparationRepository
from vimi_social.telegram.identity import TelegramPrincipal
from vimi_social.usage.models import ReservationRequest
from vimi_social.usage.repository import UsageRepository

_DEFAULT_UNKNOWN_DURATION_SECONDS = 60


class MediaPreparationService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        repository: MediaPreparationRepository | None = None,
        usage_repository: UsageRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or MediaPreparationRepository()
        self._usage_repository = usage_repository or UsageRepository()

    def select_candidate(
        self,
        principal: TelegramPrincipal,
        candidate_id: UUID,
    ) -> MediaPreparation | None:
        with (
            self._session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            return self._repository.select_candidate(
                session,
                candidate_id=candidate_id,
                actor_user_id=principal.user_id,
            )

    def confirm_rights(
        self,
        principal: TelegramPrincipal,
        preparation_id: UUID,
    ) -> MediaPreparationWorkflowInput | None:
        with (
            self._session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            preparation = self._repository.confirm_rights(
                session,
                preparation_id=preparation_id,
                actor_user_id=principal.user_id,
            )
            if preparation is None:
                return None
            candidate = self._repository.load_candidate(session, preparation.id)
            if candidate is None:
                raise RuntimeError("selected candidate disappeared from tenant context")
            quantity = _processing_seconds(candidate.duration_ms)
            self._usage_repository.reserve(
                session,
                ReservationRequest(
                    tenant_id=principal.context.tenant_id,
                    operation_key=OperationKey(preparation.operation_key),
                    metric="video_second_processed",
                    quantity=quantity,
                ),
            )
            return MediaPreparationWorkflowInput(
                preparation_id=str(preparation.id),
                operation_key=preparation.operation_key,
                source_task_operation_key=preparation.source_task_operation_key,
                source_task_execution_token=str(preparation.source_task_execution_token),
            )

    def decline_rights(
        self,
        principal: TelegramPrincipal,
        preparation_id: UUID,
    ) -> bool:
        with (
            self._session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            return self._repository.decline_rights(
                session,
                preparation_id=preparation_id,
                actor_user_id=principal.user_id,
            )


def _processing_seconds(duration_ms: int | None) -> int:
    if duration_ms is None or duration_ms <= 0:
        return _DEFAULT_UNKNOWN_DURATION_SECONDS
    return max(1, math.ceil(duration_ms / 1000))
