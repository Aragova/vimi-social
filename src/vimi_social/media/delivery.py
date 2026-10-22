from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.analysis import MediaAnalysisResult
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.international import UiLocale
from vimi_social.domain.media import MediaPreparationResult, MediaPreparationWorkflowInput
from vimi_social.domain.publication import (
    PublicationPreviewResult,
    RenderResult,
    VariantArtifactState,
)
from vimi_social.media.render_repository import VariantRenderRepository
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.telegram.menus import build_media_preparation_result
from vimi_social.telegram.outgoing import (
    TelegramMessageRetryAfter,
    TelegramMessenger,
    TelegramOutgoingState,
)

_TELEGRAM_VIDEO_PREVIEW_MAX_BYTES = 49 * 1024 * 1024


class MediaPreparationDeliveryActivities:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        messenger: TelegramMessenger | None,
        *,
        media_root: Path | None = None,
        source_repository: SourceTaskRepository | None = None,
        render_repository: VariantRenderRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._messenger = messenger
        self._media_root = media_root.resolve() if media_root is not None else None
        self._source_repository = source_repository or SourceTaskRepository()
        self._render_repository = render_repository or VariantRenderRepository()

    @activity.defn(name="deliver_media_preparation_result")
    async def deliver_media_preparation_result(
        self,
        workflow_input: MediaPreparationWorkflowInput,
        result: MediaPreparationResult,
        analysis_result: MediaAnalysisResult | None = None,
        render_result: RenderResult | None = None,
        preview_result: PublicationPreviewResult | None = None,
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

        video_path: Path | None = None
        video_sha256: str | None = None
        oversized_video_preview = False
        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            task = self._source_repository.get_by_operation_key(session, operation_key)
            if task is None or task.execution_token != execution_token:
                raise ApplicationError(
                    "source task authority binding mismatch",
                    non_retryable=True,
                    type="MediaDeliveryAuthorityMismatch",
                )
            if (
                render_result is not None
                and render_result.state is VariantArtifactState.READY
                and render_result.artifact_id is not None
                and self._media_root is not None
            ):
                try:
                    artifact_id = UUID(render_result.artifact_id)
                except ValueError:
                    artifact_id = None
                if artifact_id is not None:
                    artifact = self._render_repository.get_by_id(session, artifact_id)
                    if (
                        artifact is not None
                        and artifact.storage_path is not None
                        and artifact.sha256 is not None
                    ):
                        candidate = (self._media_root / artifact.storage_path).resolve()
                        if candidate.is_relative_to(self._media_root) and candidate.is_file():
                            actual_size = candidate.stat().st_size
                            persisted_size = artifact.size_bytes or actual_size
                            if (
                                actual_size <= _TELEGRAM_VIDEO_PREVIEW_MAX_BYTES
                                and persisted_size <= _TELEGRAM_VIDEO_PREVIEW_MAX_BYTES
                            ):
                                video_path = candidate
                                video_sha256 = artifact.sha256
                            else:
                                oversized_video_preview = True

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
            render_result,
            preview_result,
            video_preview_available=not oversized_video_preview,
        )
        try:
            if video_path is not None and video_sha256 is not None:
                state = await self._messenger.send_video(
                    task.telegram_update_id,
                    f"media-preview:{result.preparation_id}",
                    task.telegram_chat_id,
                    video_path,
                    video_sha256,
                    message,
                )
            else:
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
