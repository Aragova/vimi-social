import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.analysis import MediaAnalysisResult, SceneAnalysisState
from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.domain.media import (
    MediaAsset,
    MediaPreparationState,
    MediaPreparationWorkflowInput,
)
from vimi_social.media.analysis_repository import (
    MediaAnalysisOwnershipLost,
    MediaAnalysisRepository,
)
from vimi_social.media.policy import DestinationProfileRegistry, PlatformPreflight
from vimi_social.media.repository import MediaPreparationRepository
from vimi_social.media.scenes import SceneDetector, SceneRanker
from vimi_social.media.secure_ingest.errors import MediaIngestError
from vimi_social.media.variant_planner import VariantPlanner
from vimi_social.media.visual_classifier import VisualSceneClassifier
from vimi_social.source.repository import SourceTaskRepository


class MediaSceneAnalysisActivities:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        media_root: Path,
        destination: str = "x",
        repository: MediaAnalysisRepository | None = None,
        media_repository: MediaPreparationRepository | None = None,
        source_repository: SourceTaskRepository | None = None,
        detector: SceneDetector | None = None,
        ranker: SceneRanker | None = None,
        visual_classifier: VisualSceneClassifier | None = None,
        profiles: DestinationProfileRegistry | None = None,
        preflight: PlatformPreflight | None = None,
        planner: VariantPlanner | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._media_root = media_root.resolve()
        self._destination = destination
        self._repository = repository or MediaAnalysisRepository()
        self._media_repository = media_repository or MediaPreparationRepository()
        self._source_repository = source_repository or SourceTaskRepository()
        self._detector = detector or SceneDetector()
        self._ranker = ranker or SceneRanker()
        self._visual_classifier = visual_classifier
        self._profiles = profiles or DestinationProfileRegistry()
        self._preflight = preflight or PlatformPreflight()
        self._planner = planner or VariantPlanner()

    @activity.defn(name="analyze_prepared_media")
    async def analyze_prepared_media(
        self,
        workflow_input: MediaPreparationWorkflowInput,
        asset_id: str,
    ) -> MediaAnalysisResult:
        asset = self._authorized_asset(workflow_input, asset_id)
        tenant_id = TenantId(asset.tenant_id)
        attempt_token = uuid4()

        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            analysis = self._repository.ensure_analysis(session, asset)
            claim = self._repository.claim_analysis(session, analysis.id, attempt_token)
            if claim.state is SceneAnalysisState.READY:
                return self._repository.build_result(session, analysis.id)
            if claim.state is SceneAnalysisState.FAILED_SAFE:
                return self._repository.build_result(session, analysis.id)
            if claim.state is not SceneAnalysisState.ANALYZING:
                raise RuntimeError("media analysis is not eligible for execution")
            if not claim.owns_attempt:
                observed = claim.attempt_token
                if observed is None:
                    raise RuntimeError("analyzing media has no attempt token")
                self._repository.fail_ambiguous(
                    session,
                    analysis_id=analysis.id,
                    observed_attempt_token=observed,
                )
                return self._repository.build_result(session, analysis.id)

        scratch_dir = (
            self._media_root / "scratch" / "analysis" / str(analysis.id) / str(attempt_token)
        )
        try:
            media_path = self._resolve_media_path(asset.storage_path)
            scenes = await self._detector.detect(
                media_path,
                duration_ms=asset.probe.duration_ms,
                scratch_dir=scratch_dir,
            )
            if asset.probe.duration_ms is None:
                raise RuntimeError("prepared media is missing duration after MediaProbe")
            ranked = self._ranker.rank(
                scenes,
                asset_duration_ms=asset.probe.duration_ms,
                classification=asset.classification,
            )
            if self._visual_classifier is not None:
                ranked = self._visual_classifier.classify(
                    media_path,
                    ranked,
                    scratch_dir=scratch_dir,
                )
                ranked = await ranked
            profile = self._profiles.require(self._destination)
            preflight = self._preflight.evaluate(asset, profile, ranked)
            plan = self._planner.plan(asset, ranked, preflight)
        except MediaIngestError:
            return self._mark_failed(
                tenant_id,
                analysis.id,
                attempt_token,
                "SCENE_OR_VISUAL_ANALYSIS_FAILED",
            )
        except OSError:
            return self._mark_failed(
                tenant_id,
                analysis.id,
                attempt_token,
                "SCENE_ANALYSIS_STORAGE_FAILED",
            )
        except (KeyError, ValueError):
            return self._mark_failed(
                tenant_id,
                analysis.id,
                attempt_token,
                "VARIANT_PLANNING_FAILED_SAFE",
            )
        finally:
            await asyncio.to_thread(shutil.rmtree, scratch_dir, True)

        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            try:
                self._repository.persist_success(
                    session,
                    analysis=analysis,
                    attempt_token=attempt_token,
                    detector_version=self._detector.version,
                    ranker_version=self._ranker.version,
                    scenes=ranked,
                    plan=plan,
                )
            except MediaAnalysisOwnershipLost:
                return self._repository.build_result(session, analysis.id)
            return self._repository.build_result(session, analysis.id)

    def _authorized_asset(
        self,
        workflow_input: MediaPreparationWorkflowInput,
        asset_id: str,
    ) -> MediaAsset:
        source_operation_key = OperationKey(workflow_input.source_task_operation_key)
        try:
            source_execution_token = UUID(workflow_input.source_task_execution_token)
            preparation_id = UUID(workflow_input.preparation_id)
            expected_asset_id = UUID(asset_id)
        except ValueError:
            raise RuntimeError("invalid media analysis authority input") from None

        with self._session_factory() as session, session.begin():
            tenant_id = self._source_repository.resolve_tenant(
                session,
                operation_key=source_operation_key,
                execution_token=source_execution_token,
            )

        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            preparation = self._media_repository.get_by_id(session, preparation_id)
            if preparation is None:
                raise RuntimeError("media analysis preparation authority was not found")
            if preparation.operation_key != workflow_input.operation_key:
                raise RuntimeError("media analysis preparation operation authority mismatch")
            if preparation.source_task_operation_key != workflow_input.source_task_operation_key:
                raise RuntimeError("media analysis source authority mismatch")
            if preparation.source_task_execution_token != source_execution_token:
                raise RuntimeError("media analysis source token mismatch")
            if preparation.state is not MediaPreparationState.READY:
                raise RuntimeError("media analysis requires a READY preparation")
            asset = self._media_repository.get_asset(session, preparation.id)
            if asset is None or asset.id != expected_asset_id:
                raise RuntimeError("media analysis asset authority mismatch")
            return asset

    def _resolve_media_path(self, storage_path: str) -> Path:
        candidate = (self._media_root / storage_path).resolve()
        if not candidate.is_relative_to(self._media_root):
            raise OSError("media asset path escapes configured media root")
        if not candidate.is_file():
            raise OSError("prepared media asset is not available on the media worker")
        return candidate

    def _mark_failed(
        self,
        tenant_id: TenantId,
        analysis_id: UUID,
        attempt_token: UUID,
        failure_code: str,
    ) -> MediaAnalysisResult:
        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            self._repository.fail_safe(
                session,
                analysis_id=analysis_id,
                attempt_token=attempt_token,
                failure_code=failure_code,
            )
            return self._repository.build_result(session, analysis_id)
