import asyncio
import math
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.analysis import RenderStrategy
from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.domain.media import MediaPreparationWorkflowInput
from vimi_social.domain.publication import RenderResult, VariantArtifact, VariantArtifactState
from vimi_social.media.render_repository import RenderOwnershipLost, VariantRenderRepository
from vimi_social.media.renderer import VariantRenderer
from vimi_social.media.secure_ingest.errors import MediaIngestError
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.usage.models import ReservationRequest
from vimi_social.usage.repository import CapacityExceeded, UsageRepository


class VariantRenderActivities:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        media_root: Path,
        max_bytes: int,
        destination: str = "x",
        repository: VariantRenderRepository | None = None,
        source_repository: SourceTaskRepository | None = None,
        usage_repository: UsageRepository | None = None,
        renderer: VariantRenderer | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._media_root = media_root.resolve()
        self._destination = destination
        self._repository = repository or VariantRenderRepository()
        self._source_repository = source_repository or SourceTaskRepository()
        self._usage_repository = usage_repository or UsageRepository()
        self._renderer = renderer or VariantRenderer(max_bytes=max_bytes)

    @activity.defn(name="render_variant")
    async def render_variant(
        self,
        workflow_input: MediaPreparationWorkflowInput,
        analysis_id: str,
    ) -> RenderResult:
        tenant_id, parsed_analysis_id = self._resolve_authority(workflow_input, analysis_id)
        attempt_token = uuid4()

        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            render_input = self._repository.load_input(
                session,
                analysis_id=parsed_analysis_id,
                destination=self._destination,
            )
            if render_input is None:
                return RenderResult(
                    state=VariantArtifactState.FAILED_SAFE,
                    failure_code="RENDER_PLAN_NOT_AVAILABLE",
                )
            artifact = self._repository.ensure_artifact(session, render_input)
            if artifact.state is VariantArtifactState.READY:
                return _result_from_artifact(artifact)
            if artifact.state is VariantArtifactState.FAILED_SAFE:
                return _result_from_artifact(artifact)

            claim = self._repository.claim_render(session, artifact.id, attempt_token)
            if claim.state is VariantArtifactState.READY:
                current = self._repository.get_by_id(session, artifact.id)
                if current is None:
                    raise RuntimeError("ready variant artifact disappeared")
                return _result_from_artifact(current)
            if claim.state is VariantArtifactState.FAILED_SAFE:
                current = self._repository.get_by_id(session, artifact.id)
                if current is None:
                    raise RuntimeError("failed variant artifact disappeared")
                return _result_from_artifact(current)
            if claim.state is not VariantArtifactState.RENDERING:
                raise RuntimeError("variant artifact is not eligible for rendering")
            if not claim.owns_attempt:
                observed = claim.attempt_token
                if observed is None:
                    raise RuntimeError("rendering artifact has no attempt token")
                self._repository.fail_ambiguous(
                    session,
                    artifact_id=artifact.id,
                    observed_attempt_token=observed,
                )
                current = self._repository.get_by_id(session, artifact.id)
                if current is None:
                    raise RuntimeError("ambiguous variant artifact disappeared")
                return _result_from_artifact(current)

            if render_input.strategy is RenderStrategy.PASSTHROUGH:
                ready = self._repository.persist_passthrough(
                    session,
                    artifact_id=artifact.id,
                    attempt_token=attempt_token,
                    render_input=render_input,
                )
                return _result_from_artifact(ready)

            quantity = max(1, math.ceil(render_input.expected_duration_ms / 60_000))
            try:
                self._usage_repository.reserve(
                    session,
                    ReservationRequest(
                        tenant_id=tenant_id,
                        operation_key=OperationKey(artifact.operation_key),
                        metric="rendered_video_minute",
                        quantity=quantity,
                    ),
                )
            except CapacityExceeded:
                self._repository.fail_safe(
                    session,
                    artifact_id=artifact.id,
                    attempt_token=attempt_token,
                    failure_code="RENDER_QUOTA_EXCEEDED",
                )
                current = self._repository.get_by_id(session, artifact.id)
                if current is None:
                    raise RuntimeError("quota-failed variant artifact disappeared")
                return _result_from_artifact(current)
            self._usage_repository.commit(session, OperationKey(artifact.operation_key))

        scratch_dir = self._media_root / "scratch" / "render" / str(artifact.id) / str(attempt_token)
        try:
            media_path = self._resolve_media_path(render_input.asset_storage_path)
            rendered = await self._renderer.render(
                media_path,
                render_input,
                scratch_dir=scratch_dir,
                durable_dir=self._media_root / "content",
            )
            storage_path = str(rendered.path.relative_to(self._media_root))
        except (MediaIngestError, OSError, ValueError):
            return self._mark_failed(
                tenant_id,
                artifact.id,
                attempt_token,
                "VARIANT_RENDER_FAILED_SAFE",
            )
        finally:
            await asyncio.to_thread(shutil.rmtree, scratch_dir, True)

        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            try:
                ready = self._repository.persist_ready(
                    session,
                    artifact_id=artifact.id,
                    attempt_token=attempt_token,
                    sha256=rendered.sha256,
                    storage_path=storage_path,
                    size_bytes=rendered.size_bytes,
                    duration_ms=rendered.duration_ms,
                )
            except RenderOwnershipLost:
                current = self._repository.get_by_id(session, artifact.id)
                if current is None:
                    raise RuntimeError("variant artifact disappeared after ownership loss")
                return _result_from_artifact(current)
            return _result_from_artifact(ready)

    def _resolve_authority(
        self,
        workflow_input: MediaPreparationWorkflowInput,
        analysis_id: str,
    ) -> tuple[TenantId, UUID]:
        try:
            execution_token = UUID(workflow_input.source_task_execution_token)
            parsed_analysis_id = UUID(analysis_id)
        except ValueError:
            raise RuntimeError("invalid render authority input") from None
        with self._session_factory() as session, session.begin():
            tenant_id = self._source_repository.resolve_tenant(
                session,
                operation_key=OperationKey(workflow_input.source_task_operation_key),
                execution_token=execution_token,
            )
        return tenant_id, parsed_analysis_id

    def _resolve_media_path(self, storage_path: str) -> Path:
        candidate = (self._media_root / storage_path).resolve()
        if not candidate.is_relative_to(self._media_root):
            raise OSError("variant source path escapes configured media root")
        if not candidate.is_file():
            raise OSError("variant source media is unavailable")
        return candidate

    def _mark_failed(
        self,
        tenant_id: TenantId,
        artifact_id: UUID,
        attempt_token: UUID,
        failure_code: str,
    ) -> RenderResult:
        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            self._repository.fail_safe(
                session,
                artifact_id=artifact_id,
                attempt_token=attempt_token,
                failure_code=failure_code,
            )
            current = self._repository.get_by_id(session, artifact_id)
            if current is None:
                raise RuntimeError("failed variant artifact disappeared")
            return _result_from_artifact(current)


def _result_from_artifact(artifact: VariantArtifact) -> RenderResult:
    return RenderResult(
        state=artifact.state,
        artifact_id=str(artifact.id),
        failure_code=artifact.failure_code,
        sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
        duration_ms=artifact.duration_ms,
    )
