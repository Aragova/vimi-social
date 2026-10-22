import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.analysis import (
    PolicyDecision,
    RankedScene,
    RenderRecipe,
    RenderStrategy,
    SceneAnalysisState,
    SceneBoundary,
    SceneClassificationBasis,
    VariantPlan,
)
from vimi_social.domain.media import BaseAdultClassification, MediaPreparationWorkflowInput
from vimi_social.media.analysis_activities import MediaSceneAnalysisActivities
from vimi_social.media.analysis_repository import MediaAnalysisRepository
from vimi_social.media.repository import MediaPreparationRepository
from vimi_social.media.scenes import SceneDetector
from vimi_social.source.service import SourceTaskService
from vimi_social.telegram.identity import TelegramIdentityResolver
from vimi_social.telegram.models import TelegramUser


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


class NoCallSceneDetector(SceneDetector):
    def __init__(self) -> None:
        self.calls = 0

    async def detect(
        self,
        path: Path,
        *,
        duration_ms: int | None,
        scratch_dir: Path,
    ) -> tuple[SceneBoundary, ...]:
        del path, duration_ms, scratch_dir
        self.calls += 1
        raise AssertionError("retry must not start ffmpeg scene detection")


def _seed_ready_asset(
    session: Session,
    *,
    tenant_id: UUID,
    source_task_id: UUID,
    candidate_id: UUID,
    suffix: str,
) -> UUID:
    preparation_id = uuid4()
    asset_id = uuid4()
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
                'Scene integration', 'training clip', '{}', '{}'::jsonb,
                'UNKNOWN', NULL,
                'PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED',
                'DISCOVERED_MEDIA_REFERENCE_AVAILABLE', '{}'::jsonb
            )
            """
        ),
        {
            "candidate_id": str(candidate_id),
            "tenant_id": str(tenant_id),
            "source_task_id": str(source_task_id),
            "source_id": f"scene-{suffix}",
            "source_url": f"https://x.com/i/web/status/scene-{suffix}",
        },
    )
    session.execute(
        text(
            """
            INSERT INTO media_preparation (
                id, tenant_id, candidate_id, operation_key, rights_basis, state
            ) VALUES (
                :preparation_id, :tenant_id, :candidate_id, :operation_key,
                'USER_CONFIRMED', 'READY'
            )
            """
        ),
        {
            "preparation_id": str(preparation_id),
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
                :asset_id, :tenant_id, :candidate_id, :preparation_id, :sha256,
                :storage_path, 12345, 'mp4', 'video/mp4', :final_url,
                20000, 1080, 1920, 'h264', 'aac', 'mp4', 30.0, true,
                'NO_ADULT_SIGNAL_DETECTED', NULL, 'metadata-text-v1',
                ARRAY['metadata_text_only_no_adult_signal']
            )
            """
        ),
        {
            "asset_id": str(asset_id),
            "tenant_id": str(tenant_id),
            "candidate_id": str(candidate_id),
            "preparation_id": str(preparation_id),
            "sha256": suffix[0] * 64,
            "storage_path": f"content/{suffix}.mp4",
            "final_url": f"https://video.example/{suffix}.mp4",
        },
    )
    return preparation_id


@pytest.mark.asyncio
async def test_scene_analysis_persistence_attempt_fence_and_tenant_isolation(
    tmp_path: Path,
) -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](bind=engine, expire_on_commit=False, autoflush=False)
    first_user = TelegramUser(
        id=940000001,
        first_name="SceneOne",
        username="scene_one",
        language_code="en",
    )
    second_user = TelegramUser(
        id=940000002,
        first_name="SceneTwo",
        username="scene_two",
        language_code="en",
    )

    try:
        resolver = TelegramIdentityResolver(session_factory)
        first = resolver.resolve(first_user)
        second = resolver.resolve(second_user)
        source_service = SourceTaskService(session_factory)
        source_service.begin_ai_search(first, chat_id=first_user.id)
        task = source_service.submit_ai_search_intent(
            first,
            update_id=840000001,
            message_id=101,
            chat_id=first_user.id,
            intent="scene analysis integration",
        )
        assert task is not None

        success_candidate = UUID("21111111-2222-3333-4444-555555555555")
        fence_candidate = UUID("31111111-2222-3333-4444-555555555555")
        with session_factory() as session, tenant_transaction(session, first.context.tenant_id):
            success_preparation = _seed_ready_asset(
                session,
                tenant_id=first.context.tenant_id.value,
                source_task_id=task.id,
                candidate_id=success_candidate,
                suffix="aaaaaaaa",
            )
            fence_preparation = _seed_ready_asset(
                session,
                tenant_id=first.context.tenant_id.value,
                source_task_id=task.id,
                candidate_id=fence_candidate,
                suffix="bbbbbbbb",
            )

        analysis_repository = MediaAnalysisRepository()
        media_repository = MediaPreparationRepository()
        with session_factory() as session, tenant_transaction(session, first.context.tenant_id):
            success_asset = media_repository.get_asset(session, success_preparation)
            assert success_asset is not None
            analysis = analysis_repository.ensure_analysis(session, success_asset)
            attempt = uuid4()
            claim = analysis_repository.claim_analysis(session, analysis.id, attempt)
            assert claim.state is SceneAnalysisState.ANALYZING
            assert claim.owns_attempt is True

            scenes = (
                RankedScene(
                    ordinal=0,
                    start_ms=0,
                    end_ms=8000,
                    rank_score=0.8,
                    adult_classification=BaseAdultClassification.NO_ADULT_SIGNAL_DETECTED,
                    explicitness_score=None,
                    classification_basis=SceneClassificationBasis.ASSET_LEVEL_INHERITED,
                    signals=("scene_classification_inherits_asset_baseline",),
                ),
                RankedScene(
                    ordinal=1,
                    start_ms=8000,
                    end_ms=20000,
                    rank_score=0.9,
                    adult_classification=BaseAdultClassification.NO_ADULT_SIGNAL_DETECTED,
                    explicitness_score=None,
                    classification_basis=SceneClassificationBasis.ASSET_LEVEL_INHERITED,
                    signals=("scene_classification_inherits_asset_baseline",),
                ),
            )
            plan = VariantPlan(
                destination="x",
                decision=PolicyDecision.MANUAL_REVIEW_REQUIRED,
                capability_version="x-organic-video-v1",
                policy_version="x-adult-2024-05-reviewed-2026-10-22",
                planner_version="variant-planner-v1",
                requires_sensitive_label=False,
                reason_codes=("VISUAL_CLASSIFICATION_EVIDENCE_REQUIRED",),
                recipe=RenderRecipe(
                    strategy=RenderStrategy.PASSTHROUGH,
                    expected_duration_ms=20000,
                    segments=(),
                ),
            )
            analysis_repository.persist_success(
                session,
                analysis=analysis,
                attempt_token=attempt,
                detector_version="ffmpeg-scene-v1",
                ranker_version="deterministic-duration-position-v1",
                scenes=scenes,
                plan=plan,
            )
            result = analysis_repository.build_result(session, analysis.id)
            assert result.state is SceneAnalysisState.READY
            assert result.scene_count == 2
            assert result.top_scene_start_ms == 8000
            assert result.policy_decision is PolicyDecision.MANUAL_REVIEW_REQUIRED
            assert result.render_strategy is RenderStrategy.PASSTHROUGH

            fence_asset = media_repository.get_asset(session, fence_preparation)
            assert fence_asset is not None
            fenced = analysis_repository.ensure_analysis(session, fence_asset)
            first_attempt = uuid4()
            assert analysis_repository.claim_analysis(
                session, fenced.id, first_attempt
            ).owns_attempt is True

        detector = NoCallSceneDetector()
        activities = MediaSceneAnalysisActivities(
            session_factory,
            media_root=tmp_path,
            detector=detector,
        )
        workflow_input = MediaPreparationWorkflowInput(
            preparation_id=str(fence_preparation),
            operation_key=f"media-prep:{fence_candidate}",
            source_task_operation_key=task.operation_key.value,
            source_task_execution_token=str(task.execution_token),
        )
        retry_result = await activities.analyze_prepared_media(
            workflow_input,
            str(fence_asset.id),
        )

        assert retry_result.state is SceneAnalysisState.FAILED_SAFE
        assert retry_result.failure_code == "ANALYSIS_ATTEMPT_AMBIGUOUS"
        assert detector.calls == 0

        with session_factory() as session, tenant_transaction(session, second.context.tenant_id):
            invisible = session.execute(
                text("SELECT id FROM media_analysis WHERE id = :analysis_id"),
                {"analysis_id": str(analysis.id)},
            ).scalar_one_or_none()
            assert invisible is None
    finally:
        engine.dispose()
