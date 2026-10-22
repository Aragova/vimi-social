from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.analysis import MediaAnalysisResult
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.international import UiLocale
from vimi_social.domain.media import MediaPreparationResult, MediaPreparationWorkflowInput
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.telegram.menus import build_media_preparation_result
from vimi_social.telegram.outgoing import (
    TelegramMessageRetryAfter,
    TelegramMessenger,
    TelegramOutgoingState,
)


class MediaPreparationDeliveryActivities:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        messenger: TelegramMessenger | None,
        *,
        source_repository: SourceTaskRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._messenger = messenger
        self._source_repository = source_repository or SourceTaskRepository()

    @activity.defn(name="deliver_media_preparation_result")
    async def deliver_media_preparation_result(
        self,
        workflow_input: MediaPreparationWorkflowInput,
        result: MediaPreparationResult,
        analysis_result: MediaAnalysisResult | None = None,
    ) -> str:
        if self._messenger is None:
            raise ApplicationError(
                "Telegram delivery is not configured in the worker",
                non_retryable=True,
                type="TelegramMediaDeliveryNotConfigured",
            )

        operation_key = OperationKey(workflow_input.source_task_operation_key)
        try:
            execution_token = UUID(workflow_input.source_task_execution_token)
        except ValueError:
            raise ApplicationError(
                "invalid source task execution authority",
                non_retryable=True,
                type="MediaDeliveryAuthorityInvalid",
            ) from None

        with self._session_factory() as session, session.begin():
            tenant_id = self._source_repository.resolve_tenant(
                session,
                operation_key=operation_key,
                execution_token=execution_token,
            )

        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            task = self._source_repository.get_by_operation_key(session, operation_key)
            if task is None or task.execution_token != execution_token:
                raise ApplicationError(
                    "source task authority binding mismatch",
                    non_retryable=True,
                    type="MediaDeliveryAuthorityMismatch",
                )

        if task.telegram_update_id is None or task.telegram_chat_id is None:
            raise ApplicationError(
                "source task has no Telegram delivery metadata",
                non_retryable=True,
                type="MediaDeliveryMetadataMissing",
            )

        message = build_media_preparation_result(
            UiLocale(task.locale),
            result,
            analysis_result,
        )
        try:
            state = await self._messenger.send_message(
                task.telegram_update_id,
                f"media-preparation-result:{result.preparation_id}",
                task.telegram_chat_id,
                message,
            )
        except TelegramMessageRetryAfter as error:
            raise ApplicationError(
                "Telegram media result delivery is rate limited",
                next_retry_delay=timedelta(seconds=error.retry_after_seconds),
                type="TelegramMediaResultRateLimited",
            ) from None

        if state is TelegramOutgoingState.UNKNOWN:
            return TelegramOutgoingState.UNKNOWN.value
        if state is TelegramOutgoingState.FAILED_SAFE:
            return TelegramOutgoingState.FAILED_SAFE.value
        return TelegramOutgoingState.CONFIRMED.value
