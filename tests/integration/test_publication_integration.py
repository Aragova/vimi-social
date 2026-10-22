import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.publication import (
    ProviderMutationResult,
    PublicationPreviewState,
    PublicationState,
    ReconciliationKind,
    ReconciliationResult,
)
from vimi_social.publication.activities import PublicationActivities
from vimi_social.publication.repository import PublicationRepository
from vimi_social.publication.service import PublicationService
from vimi_social.publication.x_adapter import XDestinationAdapter
from vimi_social.source.service import SourceTaskService
from vimi_social.telegram.identity import TelegramIdentityResolver, TelegramUpdateGuard
from vimi_social.telegram.models import TelegramUser


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


class NoCallXAdapter(XDestinationAdapter):
    def __init__(self) -> None:
        self.calls = 0

    async def publish_video(
        self,
        *,
        access_token: str,
        video_path: Path,
        caption: str,
        checkpoint_media: Callable[[str], Awaitable[bool]],
    ) -> ProviderMutationResult:
        del access_token, video_path, caption, checkpoint_media
        self.calls += 1
        raise AssertionError("retry must not issue a second X mutation")

    async def reconcile(
        self,
        *,
        access_token: str,
        remote_post_id: str | None,
    ) -> ReconciliationResult:
        del access_token, remote_post_id
        return ReconciliationResult(kind=ReconciliationKind.INCONCLUSIVE)

    async def aclose(self) -> None:
        return None


def _seed_ready_variant(
    session: Session,
    *,
    tenant_id: UUID,
    source_task_id: UUID,
    suffix: str,
    storage_path: str,
) -> UUID:
    candidate_id = uuid4()
    preparation_id = uuid4()
    asset_id = uuid4()
    analysis_id = uuid4()
    plan_id = uuid4()
    artifact_id = uuid4()
    session.execute(
        text(
            """
            INSERT INTO source_task_candidate (
                id, tenant_id, source_task_id, source, source_id, source_url,
                author, media_type, duration_ms, width, height, title, caption,
                tags, engagement, adult_classification, explicitness_score,
                provenance_hint, availability, connector_metadata
            ) VALUES (
                :candidate_id, :tenant_id, :source_task_id, 'x', :source_id,
                :source_url, '42', 'video', 20000, 1080, 1920,
                'Publish integration', 'training clip', '{}', '{}'::jsonb,
                'NO_ADULT_SIGNAL_DETECTED', NULL,
                'USER_CONFIRMED_REUSE_RIGHTS', 'READY', '{}'::jsonb
            )
            """
        ),
        {
            "candidate_id": str(candidate_id),
            "tenant_id": str(tenant_id),
            "source_task_id": str(source_task_id),
            "source_id": f"publish-{suffix}",
            "source_url": f"https://x.com/i/web/status/publish-{suffix}",
        },
    )
    session.execute(
        text(
            """
            INSERT INTO media_preparation (
                id, tenant_id, candidate_id, operation_key, rights_basis, state
            ) VALUES (
                :id, :tenant_id, :candidate_id, :operation_key,
                'USER_CONFIRMED', 'READY'
            )
            """
        ),
        {
            "id": str(preparation_id),
            "tenant_id": str(tenant_id),
            "candidate_id": str(candidate_id),
            "operation_key": f"media-prep:{candidate_id}",
        },
    )
    session.execute(
        text(
            """
            INSERT INTO media_asset (
                id, tenant_id, candidate_id, preparation_id, sha256, storage_path,
                size_bytes, media_format, content_type, final_url,
                duration_ms, width, height, video_codec, audio_codec, container,
                frame_rate, has_audio, adult_classification, explicitness_score,
                classifier_version, classification_signals
            ) VALUES (
                :id, :tenant_id, :candidate_id, :preparation_id, :sha256,
                :storage_path, 1000, 'mp4', 'video/mp4', 'https://video.example/file.mp4',
                20000, 1080, 1920, 'h264', 'aac', 'mp4', 30.0, true,
                'NO_ADULT_SIGNAL_DETECTED', 0.01, 'visual-moderation-v1',
                ARRAY['visual_moderation_sampled_frame']
            )
            """
        ),
        {
            "id": str(asset_id),
            "tenant_id": str(tenant_id),
            "candidate_id": str(candidate_id),
            "preparation_id": str(preparation_id),
            "sha256": "a" * 64,
            "storage_path": storage_path,
        },
    )
    session.execute(
        text(
            """
            INSERT INTO media_analysis (
                id, tenant_id, asset_id, preparation_id, operation_key,
                state, detector_version, ranker_version
            ) VALUES (
                :id, :tenant_id, :asset_id, :preparation_id, :operation_key,
                'READY', 'ffmpeg-scene-v1', 'deterministic-duration-position-v1'
            )
            """
        ),
        {
            "id": str(analysis_id),
            "tenant_id": str(tenant_id),
            "asset_id": str(asset_id),
            "preparation_id": str(preparation_id),
            "operation_key": f"scene-analysis:{asset_id}",
        },
    )
    session.execute(
        text(
            """
            INSERT INTO variant_plan (
                id, tenant_id, analysis_id, asset_id, destination, decision,
                capability_version, policy_version, planner_version,
                render_strategy, expected_duration_ms, requires_sensitive_label,
                reason_codes
            ) VALUES (
                :id, :tenant_id, :analysis_id, :asset_id, 'x', 'DIRECT_ALLOWED',
                'x-organic-video-v1', 'x-policy-test-v1', 'variant-planner-v1',
                'PASSTHROUGH', 20000, false, ARRAY['VIDEO_DIRECTLY_ELIGIBLE']
            )
            """
        ),
        {
            "id": str(plan_id),
            "tenant_id": str(tenant_id),
            "analysis_id": str(analysis_id),
            "asset_id": str(asset_id),
        },
    )
    session.execute(
        text(
            """
            INSERT INTO variant_artifact (
                id, tenant_id, plan_id, asset_id, operation_key, state,
                sha256, storage_path, size_bytes, duration_ms
            ) VALUES (
                :id, :tenant_id, :plan_id, :asset_id, :operation_key, 'READY',
                :sha256, :storage_path, 1000, 20000
            )
            """
        ),
        {
            "id": str(artifact_id),
            "tenant_id": str(tenant_id),
            "plan_id": str(plan_id),
            "asset_id": str(asset_id),
            "operation_key": f"render:{plan_id}",
            "sha256": "b" * 64,
            "storage_path": storage_path,
        },
    )
    return artifact_id


@pytest.mark.asyncio
async def test_publication_retry_becomes_unknown_without_second_x_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](bind=engine, expire_on_commit=False, autoflush=False)
    first_user = TelegramUser(
        id=950000001,
        first_name="PublishOne",
        username="publish_one",
        language_code="en",
    )
    second_user = TelegramUser(
        id=950000002,
        first_name="PublishTwo",
        username="publish_two",
        language_code="en",
    )
    update_id = 850000001

    try:
        resolver = TelegramIdentityResolver(session_factory)
        first = resolver.resolve(first_user)
        second = resolver.resolve(second_user)
        guard = TelegramUpdateGuard(session_factory)
        assert guard.claim(update_id, first_user.id).value == "CLAIMED"
        source_service = SourceTaskService(session_factory)
        source_service.begin_ai_search(first, chat_id=first_user.id)
        task = source_service.submit_ai_search_intent(
            first,
            update_id=update_id,
            message_id=111,
            chat_id=first_user.id,
            intent="publication integration",
        )
        assert task is not None

        relative_path = "content/publication-test.mp4"
        media_file = tmp_path / relative_path
        media_file.parent.mkdir(parents=True, exist_ok=True)
        media_file.write_bytes(b"video")

        repository = PublicationRepository()
        with session_factory() as session, tenant_transaction(session, first.context.tenant_id):
            artifact_id = _seed_ready_variant(
                session,
                tenant_id=first.context.tenant_id.value,
                source_task_id=task.id,
                suffix="one",
                storage_path=relative_path,
            )
            account = repository.upsert_account(
                session,
                tenant_id=first.context.tenant_id.value,
                platform="x",
                external_account_id="x-account-1",
                display_name="Primary X",
                credential_ref="env:VIMI_DEST_X_TEST_TOKEN",
            )
            assert account.state.value == "ACTIVE"
            preview = repository.prepare_preview(
                session,
                artifact_id=artifact_id,
                destination="x",
            )
            assert preview.state is PublicationPreviewState.AWAITING_APPROVAL
            assert preview.publication_id is not None
            publication_id = UUID(preview.publication_id)

        workflow_input = PublicationService(session_factory).approve(first, publication_id)
        assert workflow_input is not None

        first_attempt = uuid4()
        with session_factory() as session, tenant_transaction(session, first.context.tenant_id):
            claim = repository.claim_dispatch(
                session,
                publication_id=publication_id,
                attempt_token=first_attempt,
            )
            assert claim.state is PublicationState.DISPATCHING
            assert claim.owns_attempt is True
            reservation = session.execute(
                text(
                    """
                    SELECT state, quantity
                    FROM usage_reservation
                    WHERE operation_key = :operation_key
                    """
                ),
                {"operation_key": workflow_input.operation_key},
            ).one()
            assert reservation.state == "RESERVED"
            assert reservation.quantity == 1

        monkeypatch.setenv("VIMI_DEST_X_TEST_TOKEN", "secret-token")
        adapter = NoCallXAdapter()
        activities = PublicationActivities(
            session_factory,
            media_root=tmp_path,
            x_adapter=adapter,
        )
        result = await activities.publish_destination(workflow_input)

        assert result.state is PublicationState.UNKNOWN
        assert result.failure_code == "PUBLICATION_ATTEMPT_AMBIGUOUS"
        assert adapter.calls == 0

        with session_factory() as session, tenant_transaction(session, first.context.tenant_id):
            operation = repository.get_by_id(session, publication_id)
            assert operation is not None
            assert operation.state is PublicationState.UNKNOWN
            reservation = session.execute(
                text(
                    """
                    SELECT state
                    FROM usage_reservation
                    WHERE operation_key = :operation_key
                    """
                ),
                {"operation_key": workflow_input.operation_key},
            ).scalar_one()
            assert reservation == "RESERVED"

        with session_factory() as session, tenant_transaction(session, second.context.tenant_id):
            invisible = session.execute(
                text("SELECT id FROM publication_operation WHERE id = :publication_id"),
                {"publication_id": str(publication_id)},
            ).scalar_one_or_none()
            assert invisible is None
    finally:
        engine.dispose()
