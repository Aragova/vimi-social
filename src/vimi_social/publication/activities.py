from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.domain.media import MediaPreparationWorkflowInput
from vimi_social.domain.publication import (
    ProviderMutationKind,
    PublicationPreviewResult,
    PublicationPreviewState,
    PublicationResult,
    PublicationState,
    PublicationWorkflowInput,
    ReconciliationKind,
    RenderResult,
    VariantArtifactState,
)
from vimi_social.publication.repository import PublicationRepository
from vimi_social.publication.x_adapter import (
    DestinationCredentialError,
    EnvironmentCredentialResolver,
    XDestinationAdapter,
)
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.usage.repository import UsageRepository


@dataclass(frozen=True, slots=True)
class DispatchContext:
    tenant_id: TenantId
    publication_id: UUID
    artifact_path: Path
    credential_ref: str
    platform: str
    caption: str


class PublicationActivities:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        media_root: Path,
        repository: PublicationRepository | None = None,
        source_repository: SourceTaskRepository | None = None,
        usage_repository: UsageRepository | None = None,
        credential_resolver: EnvironmentCredentialResolver | None = None,
        x_adapter: XDestinationAdapter | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._media_root = media_root.resolve()
        self._repository = repository or PublicationRepository()
        self._source_repository = source_repository or SourceTaskRepository()
        self._usage_repository = usage_repository or UsageRepository()
        self._credential_resolver = credential_resolver or EnvironmentCredentialResolver()
        self._x_adapter = x_adapter or XDestinationAdapter()

    @activity.defn(name="prepare_publication_preview")
    def prepare_publication_preview(
        self,
        workflow_input: MediaPreparationWorkflowInput,
        render_result: RenderResult,
    ) -> PublicationPreviewResult:
        if (
            render_result.state is not VariantArtifactState.READY
            or render_result.artifact_id is None
        ):
            return PublicationPreviewResult(
                state=PublicationPreviewState.RENDER_FAILED,
                artifact_id=render_result.artifact_id,
                reason_code=render_result.failure_code or "VARIANT_RENDER_NOT_READY",
            )
        try:
            artifact_id = UUID(render_result.artifact_id)
        except ValueError:
            return PublicationPreviewResult(
                state=PublicationPreviewState.RENDER_FAILED,
                reason_code="VARIANT_ARTIFACT_ID_INVALID",
            )
        tenant_id = self._resolve_source_tenant(
            workflow_input.source_task_operation_key,
            workflow_input.source_task_execution_token,
        )
        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            if not self._artifact_matches_workflow(session, artifact_id, workflow_input):
                raise RuntimeError("publication preview artifact authority mismatch")
            return self._repository.prepare_preview(
                session,
                artifact_id=artifact_id,
                destination="x",
            )

    @activity.defn(name="publish_destination")
    async def publish_destination(
        self,
        workflow_input: PublicationWorkflowInput,
    ) -> PublicationResult:
        context = self._authorized_dispatch_context(workflow_input)
        try:
            access_token = self._credential_resolver.resolve(context.credential_ref)
        except DestinationCredentialError:
            return self._fail_before_mutation(
                context,
                workflow_input.operation_key,
                "DESTINATION_CREDENTIAL_UNAVAILABLE",
            )
        if context.platform != "x":
            return self._fail_before_mutation(
                context,
                workflow_input.operation_key,
                "DESTINATION_ADAPTER_NOT_CONFIGURED",
            )
        if not context.artifact_path.is_file():
            return self._fail_before_mutation(
                context,
                workflow_input.operation_key,
                "VARIANT_ARTIFACT_FILE_UNAVAILABLE",
            )

        attempt_token = uuid4()
        with self._session_factory() as session, tenant_transaction(session, context.tenant_id):
            claim = self._repository.claim_dispatch(
                session,
                publication_id=context.publication_id,
                attempt_token=attempt_token,
            )
            if claim.state is PublicationState.CONFIRMED:
                operation = self._repository.get_by_id(session, context.publication_id)
                if operation is None:
                    raise RuntimeError("confirmed publication disappeared")
                return _result(operation)
            if claim.state in {
                PublicationState.UNKNOWN,
                PublicationState.FAILED_SAFE,
                PublicationState.FAILED_PERMANENT,
                PublicationState.BLOCKED,
            }:
                operation = self._repository.get_by_id(session, context.publication_id)
                if operation is None:
                    raise RuntimeError("publication disappeared while joining terminal state")
                return _result(operation)
            if claim.state is not PublicationState.DISPATCHING:
                raise RuntimeError("publication is not eligible for dispatch")
            if not claim.owns_attempt:
                observed = claim.attempt_token
                if observed is None:
                    raise RuntimeError("dispatching publication has no attempt token")
                self._repository.fail_ambiguous_retry(
                    session,
                    publication_id=context.publication_id,
                    observed_attempt_token=observed,
                )
                operation = self._repository.get_by_id(session, context.publication_id)
                if operation is None:
                    raise RuntimeError("ambiguous publication disappeared")
                return _result(operation)

        async def checkpoint_media(remote_media_id: str) -> bool:
            with self._session_factory() as checkpoint_session, tenant_transaction(
                checkpoint_session,
                context.tenant_id,
            ):
                return self._repository.checkpoint_media(
                    checkpoint_session,
                    publication_id=context.publication_id,
                    attempt_token=attempt_token,
                    remote_media_id=remote_media_id,
                )

        outcome = await self._x_adapter.publish_video(
            access_token=access_token,
            video_path=context.artifact_path,
            caption=context.caption,
            checkpoint_media=checkpoint_media,
        )
        state = _state_for_mutation(outcome.kind)
        with self._session_factory() as session, tenant_transaction(session, context.tenant_id):
            result = self._repository.finish_mutation(
                session,
                publication_id=context.publication_id,
                attempt_token=attempt_token,
                state=state,
                remote_media_id=outcome.remote_media_id,
                remote_post_id=outcome.remote_post_id,
                failure_code=outcome.failure_code,
            )
            operation_key = OperationKey(workflow_input.operation_key)
            if result.state in {PublicationState.CONFIRMED, PublicationState.PROVIDER_ACCEPTED}:
                self._usage_repository.commit(session, operation_key)
            elif result.state in {
                PublicationState.FAILED_SAFE,
                PublicationState.FAILED_PERMANENT,
                PublicationState.BLOCKED,
            }:
                self._usage_repository.release(session, operation_key)
            return result

    @activity.defn(name="reconcile_destination_publication")
    async def reconcile_destination_publication(
        self,
        workflow_input: PublicationWorkflowInput,
    ) -> PublicationResult:
        context = self._authorized_dispatch_context(workflow_input, allow_unknown=True)
        try:
            access_token = self._credential_resolver.resolve(context.credential_ref)
        except DestinationCredentialError:
            return self._current_result(context.tenant_id, context.publication_id)
        with self._session_factory() as session, tenant_transaction(session, context.tenant_id):
            operation = self._repository.get_by_id(session, context.publication_id)
            if operation is None:
                raise RuntimeError("publication disappeared before reconciliation")
            if operation.state is not PublicationState.UNKNOWN:
                return _result(operation)
            remote_post_id = operation.remote_post_id

        reconciliation = await self._x_adapter.reconcile(
            access_token=access_token,
            remote_post_id=remote_post_id,
        )
        with self._session_factory() as session, tenant_transaction(session, context.tenant_id):
            result = self._repository.apply_reconciliation(
                session,
                publication_id=context.publication_id,
                result=reconciliation,
            )
            operation_key = OperationKey(workflow_input.operation_key)
            if reconciliation.kind is ReconciliationKind.CONFIRMED:
                self._usage_repository.commit(session, operation_key)
            elif reconciliation.kind is ReconciliationKind.PROVED_ABSENT:
                self._usage_repository.release(session, operation_key)
            return result

    def _fail_before_mutation(
        self,
        context: DispatchContext,
        operation_key: str,
        failure_code: str,
    ) -> PublicationResult:
        attempt_token = uuid4()
        with self._session_factory() as session, tenant_transaction(session, context.tenant_id):
            claim = self._repository.claim_dispatch(
                session,
                publication_id=context.publication_id,
                attempt_token=attempt_token,
            )
            if claim.state is PublicationState.READY and not claim.owns_attempt:
                raise RuntimeError("publication failed to claim safe failure transition")
            if claim.state is PublicationState.DISPATCHING and claim.owns_attempt:
                result = self._repository.finish_mutation(
                    session,
                    publication_id=context.publication_id,
                    attempt_token=attempt_token,
                    state=PublicationState.FAILED_SAFE,
                    failure_code=failure_code,
                )
                self._usage_repository.release(session, OperationKey(operation_key))
                return result
            operation = self._repository.get_by_id(session, context.publication_id)
            if operation is None:
                raise RuntimeError("publication disappeared during safe failure")
            return _result(operation)

    def _authorized_dispatch_context(
        self,
        workflow_input: PublicationWorkflowInput,
        *,
        allow_unknown: bool = False,
    ) -> DispatchContext:
        tenant_id = self._resolve_source_tenant(
            workflow_input.source_task_operation_key,
            workflow_input.source_task_execution_token,
        )
        try:
            publication_id = UUID(workflow_input.publication_id)
        except ValueError:
            raise RuntimeError("invalid publication workflow identifier") from None
        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            operation = self._repository.get_by_id(session, publication_id)
            if operation is None or operation.operation_key != workflow_input.operation_key:
                raise RuntimeError("publication operation authority mismatch")
            if not self._publication_matches_source(session, publication_id, workflow_input):
                raise RuntimeError("publication source authority mismatch")
            row = session.execute(
                text(
                    """
                    SELECT account.platform, account.credential_ref,
                           artifact.storage_path, publication.caption
                    FROM publication_operation AS publication
                    JOIN destination_account AS account
                      ON account.id = publication.destination_account_id
                     AND account.tenant_id = publication.tenant_id
                    JOIN variant_artifact AS artifact
                      ON artifact.id = publication.artifact_id
                     AND artifact.tenant_id = publication.tenant_id
                    WHERE publication.id = :publication_id
                      AND account.state = 'ACTIVE'
                      AND artifact.state = 'READY'
                    """
                ),
                {"publication_id": str(publication_id)},
            ).one_or_none()
            if row is None:
                raise RuntimeError("publication destination or artifact is unavailable")
            if not allow_unknown and operation.state not in {
                PublicationState.READY,
                PublicationState.DISPATCHING,
                PublicationState.CONFIRMED,
                PublicationState.UNKNOWN,
                PublicationState.FAILED_SAFE,
                PublicationState.FAILED_PERMANENT,
            }:
                raise RuntimeError("publication is not approved for dispatch")
            path = self._resolve_media_path(str(row.storage_path))
            return DispatchContext(
                tenant_id=tenant_id,
                publication_id=publication_id,
                artifact_path=path,
                credential_ref=str(row.credential_ref),
                platform=str(row.platform),
                caption=str(row.caption),
            )

    def _resolve_source_tenant(self, operation_key: str, execution_token: str) -> TenantId:
        try:
            token = UUID(execution_token)
        except ValueError:
            raise RuntimeError("invalid source execution token") from None
        with self._session_factory() as session, session.begin():
            return self._source_repository.resolve_tenant(
                session,
                operation_key=OperationKey(operation_key),
                execution_token=token,
            )

    def _artifact_matches_workflow(
        self,
        session: Session,
        artifact_id: UUID,
        workflow_input: MediaPreparationWorkflowInput,
    ) -> bool:
        return (
            session.execute(
                text(
                    """
                    SELECT 1
                    FROM variant_artifact AS artifact
                    JOIN variant_plan AS plan ON plan.id = artifact.plan_id
                    JOIN media_analysis AS analysis ON analysis.id = plan.analysis_id
                    JOIN media_preparation AS preparation
                      ON preparation.id = analysis.preparation_id
                    JOIN source_task_candidate AS candidate
                      ON candidate.id = preparation.candidate_id
                    JOIN source_task AS task ON task.id = candidate.source_task_id
                    WHERE artifact.id = :artifact_id
                      AND preparation.id = :preparation_id
                      AND preparation.operation_key = :preparation_operation_key
                      AND task.operation_key = :source_operation_key
                      AND task.execution_token = :source_execution_token
                    """
                ),
                {
                    "artifact_id": str(artifact_id),
                    "preparation_id": workflow_input.preparation_id,
                    "preparation_operation_key": workflow_input.operation_key,
                    "source_operation_key": workflow_input.source_task_operation_key,
                    "source_execution_token": workflow_input.source_task_execution_token,
                },
            ).scalar_one_or_none()
            is not None
        )

    def _publication_matches_source(
        self,
        session: Session,
        publication_id: UUID,
        workflow_input: PublicationWorkflowInput,
    ) -> bool:
        return (
            session.execute(
                text(
                    """
                    SELECT 1
                    FROM publication_operation AS publication
                    JOIN variant_artifact AS artifact ON artifact.id = publication.artifact_id
                    JOIN variant_plan AS plan ON plan.id = artifact.plan_id
                    JOIN media_analysis AS analysis ON analysis.id = plan.analysis_id
                    JOIN media_asset AS asset ON asset.id = analysis.asset_id
                    JOIN source_task_candidate AS candidate ON candidate.id = asset.candidate_id
                    JOIN source_task AS task ON task.id = candidate.source_task_id
                    WHERE publication.id = :publication_id
                      AND task.operation_key = :source_operation_key
                      AND task.execution_token = :source_execution_token
                    """
                ),
                {
                    "publication_id": str(publication_id),
                    "source_operation_key": workflow_input.source_task_operation_key,
                    "source_execution_token": workflow_input.source_task_execution_token,
                },
            ).scalar_one_or_none()
            is not None
        )

    def _resolve_media_path(self, storage_path: str) -> Path:
        path = (self._media_root / storage_path).resolve()
        if not path.is_relative_to(self._media_root):
            raise RuntimeError("publication artifact path escapes media root")
        return path

    def _current_result(self, tenant_id: TenantId, publication_id: UUID) -> PublicationResult:
        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            operation = self._repository.get_by_id(session, publication_id)
            if operation is None:
                raise RuntimeError("publication operation was not found")
            return _result(operation)

    async def aclose(self) -> None:
        await self._x_adapter.aclose()


def _state_for_mutation(kind: ProviderMutationKind) -> PublicationState:
    mapping = {
        ProviderMutationKind.CONFIRMED: PublicationState.CONFIRMED,
        ProviderMutationKind.PROVIDER_ACCEPTED: PublicationState.PROVIDER_ACCEPTED,
        ProviderMutationKind.FAILED_SAFE: PublicationState.FAILED_SAFE,
        ProviderMutationKind.FAILED_PERMANENT: PublicationState.FAILED_PERMANENT,
        ProviderMutationKind.UNKNOWN: PublicationState.UNKNOWN,
    }
    return mapping[kind]


def _result(operation: object) -> PublicationResult:
    from vimi_social.domain.publication import PublicationOperation

    if not isinstance(operation, PublicationOperation):
        raise TypeError("expected PublicationOperation")
    return PublicationResult(
        state=operation.state,
        publication_id=str(operation.id),
        remote_post_id=operation.remote_post_id,
        failure_code=operation.failure_code,
    )
