import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.domain.media import (
    CuratorDecision,
    MediaAsset,
    MediaPreparation,
    MediaPreparationResult,
    MediaPreparationState,
    MediaPreparationWorkflowInput,
)
from vimi_social.media.classifier import BasicContentClassifier
from vimi_social.media.curator import CandidateCurator
from vimi_social.media.probe import MediaProbe
from vimi_social.media.repository import MediaPreparationRepository
from vimi_social.media.secure_ingest.addressing import DestinationPolicy, SystemHostResolver
from vimi_social.media.secure_ingest.errors import MediaIngestError
from vimi_social.media.secure_ingest.fetcher import SecureMediaFetcher
from vimi_social.media.secure_ingest.models import FetchLimits
from vimi_social.media.secure_ingest.transport import PinnedAiohttpTransport
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.usage.repository import UsageRepository


class MediaPreparationActivities:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        media_root: Path,
        max_bytes: int,
        repository: MediaPreparationRepository | None = None,
        source_repository: SourceTaskRepository | None = None,
        usage_repository: UsageRepository | None = None,
        curator: CandidateCurator | None = None,
        fetcher: SecureMediaFetcher | None = None,
        probe: MediaProbe | None = None,
        classifier: BasicContentClassifier | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._media_root = media_root.resolve()
        self._repository = repository or MediaPreparationRepository()
        self._source_repository = source_repository or SourceTaskRepository()
        self._usage_repository = usage_repository or UsageRepository()
        self._curator = curator or CandidateCurator()
        self._fetcher = fetcher or SecureMediaFetcher(
            DestinationPolicy(SystemHostResolver()),
            PinnedAiohttpTransport(),
            limits=FetchLimits(max_bytes=max_bytes),
        )
        self._probe = probe or MediaProbe()
        self._classifier = classifier or BasicContentClassifier()

    @activity.defn(name="prepare_candidate_media")
    async def prepare_candidate_media(
        self,
        workflow_input: MediaPreparationWorkflowInput,
    ) -> MediaPreparationResult:
        preparation = self._authorized_preparation(workflow_input)
        preparation_tenant = TenantId(preparation.tenant_id)

        with self._session_factory() as session, tenant_transaction(session, preparation_tenant):
            existing_asset = self._repository.get_asset(session, preparation.id)
            if existing_asset is not None:
                return _result_from_asset(existing_asset)
            current = self._repository.get_by_id(session, preparation.id)
            if current is None:
                raise RuntimeError("media preparation disappeared from tenant context")
            if current.state in {MediaPreparationState.FAILED_SAFE, MediaPreparationState.BLOCKED}:
                return MediaPreparationResult(
                    preparation_id=str(current.id),
                    state=current.state,
                    failure_code=current.failure_code,
                )
            candidate = self._repository.load_candidate(session, preparation.id)
            if candidate is None:
                raise RuntimeError("candidate disappeared from media preparation")
            assessment = self._curator.assess(candidate, current.rights_basis)
            if assessment.decision is not CuratorDecision.ACQUISITION_ALLOWED:
                state = self._repository.fail_safe(
                    session,
                    preparation_id=current.id,
                    failure_code=(
                        "RIGHTS_REVIEW_REQUIRED"
                        if assessment.decision is CuratorDecision.RIGHTS_REVIEW_REQUIRED
                        else "MEDIA_REFERENCE_UNAVAILABLE"
                    ),
                )
                if state is MediaPreparationState.FAILED_SAFE:
                    self._usage_repository.release(session, OperationKey(current.operation_key))
                return MediaPreparationResult(
                    preparation_id=str(current.id),
                    state=state,
                    failure_code=(
                        "RIGHTS_REVIEW_REQUIRED"
                        if assessment.decision is CuratorDecision.RIGHTS_REVIEW_REQUIRED
                        else "MEDIA_REFERENCE_UNAVAILABLE"
                    ),
                )
            acquisition_url = assessment.acquisition_url
            if acquisition_url is None:
                raise RuntimeError("Curator allowed acquisition without a media URL")

            state = self._repository.claim_acquisition(session, current.id)
            if state is MediaPreparationState.READY:
                asset = self._repository.get_asset(session, current.id)
                if asset is None:
                    raise RuntimeError("ready media preparation has no asset")
                return _result_from_asset(asset)
            if state in {MediaPreparationState.FAILED_SAFE, MediaPreparationState.BLOCKED}:
                refreshed = self._repository.get_by_id(session, current.id)
                return MediaPreparationResult(
                    preparation_id=str(current.id),
                    state=state,
                    failure_code=refreshed.failure_code if refreshed is not None else None,
                )
            self._usage_repository.commit(session, OperationKey(current.operation_key))

        content_dir = self._media_root / "content"
        scratch_dir = self._media_root / "scratch" / str(preparation.id)
        try:
            fetched = await self._fetcher.fetch(acquisition_url, content_dir)
            probe = await self._probe.probe(fetched.path, scratch_dir=scratch_dir)
            classification = self._classifier.classify(candidate)
        except MediaIngestError:
            return self._mark_failed(preparation, "MEDIA_INGEST_OR_PROBE_FAILED")
        except OSError:
            return self._mark_failed(preparation, "MEDIA_STORAGE_FAILED")
        finally:
            await asyncio.to_thread(shutil.rmtree, scratch_dir, True)

        try:
            storage_path = str(fetched.path.relative_to(self._media_root))
        except ValueError:
            return self._mark_failed(preparation, "MEDIA_STORAGE_PATH_INVALID")

        with self._session_factory() as session, tenant_transaction(session, preparation_tenant):
            current = self._repository.get_by_id(session, preparation.id)
            if current is None:
                raise RuntimeError("media preparation disappeared before asset persistence")
            if current.state is MediaPreparationState.READY:
                existing = self._repository.get_asset(session, preparation.id)
                if existing is None:
                    raise RuntimeError("ready media preparation has no asset")
                return _result_from_asset(existing)
            if current.state in {MediaPreparationState.FAILED_SAFE, MediaPreparationState.BLOCKED}:
                return MediaPreparationResult(
                    preparation_id=str(current.id),
                    state=current.state,
                    failure_code=current.failure_code,
                )
            asset = self._repository.persist_asset(
                session,
                preparation=current,
                fetch=fetched,
                storage_path=storage_path,
                probe=probe,
                classification=classification,
            )
        return _result_from_asset(asset)

    def _authorized_preparation(
        self,
        workflow_input: MediaPreparationWorkflowInput,
    ) -> MediaPreparation:
        source_operation_key = OperationKey(workflow_input.source_task_operation_key)
        try:
            source_execution_token = UUID(workflow_input.source_task_execution_token)
            preparation_id = UUID(workflow_input.preparation_id)
        except ValueError:
            raise RuntimeError("invalid media preparation authority input") from None

        with self._session_factory() as session, session.begin():
            tenant_id = self._source_repository.resolve_tenant(
                session,
                operation_key=source_operation_key,
                execution_token=source_execution_token,
            )

        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            preparation = self._repository.get_by_id(session, preparation_id)
            if preparation is None:
                raise RuntimeError("media preparation authority was not found")
            if preparation.operation_key != workflow_input.operation_key:
                raise RuntimeError("media preparation operation authority mismatch")
            if preparation.source_task_operation_key != workflow_input.source_task_operation_key:
                raise RuntimeError("media preparation source authority mismatch")
            if preparation.source_task_execution_token != source_execution_token:
                raise RuntimeError("media preparation source token mismatch")
            return preparation

    def _mark_failed(
        self,
        preparation: MediaPreparation,
        failure_code: str,
    ) -> MediaPreparationResult:
        with self._session_factory() as session, tenant_transaction(
            session,
            TenantId(preparation.tenant_id),
        ):
            state = self._repository.fail_safe(
                session,
                preparation_id=preparation.id,
                failure_code=failure_code,
            )
            current = self._repository.get_by_id(session, preparation.id)
            return MediaPreparationResult(
                preparation_id=str(preparation.id),
                state=state,
                failure_code=current.failure_code if current is not None else failure_code,
            )


def _result_from_asset(asset: MediaAsset) -> MediaPreparationResult:
    return MediaPreparationResult(
        preparation_id=str(asset.preparation_id),
        state=MediaPreparationState.READY,
        asset_id=str(asset.id),
        sha256=asset.sha256,
        size_bytes=asset.size_bytes,
        duration_ms=asset.probe.duration_ms,
        width=asset.probe.width,
        height=asset.probe.height,
        adult_classification=asset.classification.adult,
        explicitness_score=asset.classification.explicitness_score,
        signals=asset.classification.signals,
    )
