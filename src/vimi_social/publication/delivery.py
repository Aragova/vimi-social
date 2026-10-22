from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.international import UiLocale
from vimi_social.domain.publication import PublicationResult, PublicationWorkflowInput
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.telegram.menus import build_publication_result
from vimi_social.telegram.outgoing import (
    TelegramMessageRetryAfter,
    TelegramMessenger,
)


class PublicationDeliveryActivities:
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

    @activity.defn(name="deliver_publication_result")
    async def deliver_publication_result(
        self,
        workflow_input: PublicationWorkflowInput,
        result: PublicationResult,
    ) -> str:
        if self._messenger is None:
            raise ApplicationError(
                "Telegram delivery is not configured in the worker",
                non_retryable=True,
                type="TelegramPublicationDeliveryNotConfigured",
            )
        try:
            execution_token = UUID(workflow_input.source_task_execution_token)
        except ValueError:
            raise ApplicationError(
                "invalid publication delivery authority",
                non_retryable=True,
                type="PublicationDeliveryAuthorityInvalid",
            ) from None
        operation_key = OperationKey(workflow_input.source_task_operation_key)
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
                    "publication delivery source binding mismatch",
                    non_retryable=True,
                    type="PublicationDeliveryAuthorityMismatch",
                )
        if task.telegram_update_id is None or task.telegram_chat_id is None:
            raise ApplicationError(
                "source task has no Telegram delivery metadata",
                non_retryable=True,
                type="PublicationDeliveryMetadataMissing",
            )
        try:
            state = await self._messenger.send_message(
                task.telegram_update_id,
                f"publication-result:{result.publication_id}",
                task.telegram_chat_id,
                build_publication_result(UiLocale(task.locale), result),
            )
        except TelegramMessageRetryAfter as error:
            raise ApplicationError(
                "Telegram publication result delivery is rate limited",
                next_retry_delay=timedelta(seconds=error.retry_after_seconds),
                type="TelegramPublicationResultRateLimited",
            ) from None
        return state.value
